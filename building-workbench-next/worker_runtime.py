"""Observed worker liveness and bounded startup diagnostics; never removes locks."""
import ctypes
from ctypes import wintypes as w
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from foundation import ROOT,now,read_json,write_json

_launch_lock=threading.Lock()

def process_info(pid):
    if type(pid) is not int or pid<=0:return dict(alive=False,created=None)
    if os.name!='nt':
        try:os.kill(pid,0);return dict(alive=True,created=None)
        except ProcessLookupError:return dict(alive=False,created=None)
        except PermissionError:return dict(alive=None,created=None)
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
    k.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
    k.CloseHandle.argtypes=[w.HANDLE]
    h=k.OpenProcess(0x1000,False,pid)
    if not h:return dict(alive=False if ctypes.get_last_error()==87 else None,created=None)
    try:
        code=w.DWORD()
        if not k.GetExitCodeProcess(h,ctypes.byref(code)):return dict(alive=None,created=None)
        times=[w.FILETIME() for _ in range(4)]
        created=None
        if k.GetProcessTimes(h,*(ctypes.byref(t) for t in times)):created=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
        return dict(alive=code.value==259,created=created)
    finally:k.CloseHandle(h)

def _read(path):
    try:return read_json(path) if path.exists() else None
    except (OSError,ValueError):return None

def log_tail(path,offset=0):
    try:
        with path.open('rb') as f:
            f.seek(0,2);end=f.tell();f.seek(max(offset,end-8192));return f.read().decode('utf8',errors='replace')[-6000:]
    except OSError as error:return '无法读取后台日志：'+str(error)

def status(root):
    root=Path(root).resolve();folder=root/'data/execution';raw=_read(folder/'worker.json')
    startup=_read(folder/'worker-start.json')
    if not raw and not startup:return None
    raw=raw or {};pid=raw.get('pid');info=process_info(pid)
    identity=raw.get('process_created')
    if identity and info['created'] and identity!=info['created']:info['alive']=False
    try:
        age=(datetime.now().astimezone()-datetime.fromisoformat(raw['heartbeat'])).total_seconds()
        fresh=0<=age<15 and Path(raw.get('root','')).resolve()==root
    except (KeyError,TypeError,ValueError):age=None;fresh=False
    ready=info['alive'] is True and fresh and raw.get('ready',True)
    starting=False
    if not ready and info['alive'] is False and startup and startup.get('state') in ('starting','failed'):
        launch=process_info(startup.get('pid'))
        if startup.get('process_created') and launch['created'] and startup['process_created']!=launch['created']:launch['alive']=False
        if launch['alive'] is not False:
            # A slow import may precede the first worker heartbeat. Do not launch again.
            raw=dict(raw,pid=startup.get('pid'));info=launch;starting=True
    out=dict(raw,alive=info['alive'],stale=not fresh,online=bool(ready),heartbeat_age_seconds=age,
             diagnostic=None,startup=startup)
    if not ready:
        if starting:out['diagnostic']='后台启动进程尚未退出，但未收到就绪心跳；请稍后刷新或查看日志，不会重复启动。'
        elif startup and startup.get('state')=='failed':out['diagnostic']=startup.get('error')
        elif info['alive'] is False:out['diagnostic']='计算后台未运行；上次状态仅为历史记录。'
        elif info['alive'] is None:out['diagnostic']='无法确认计算后台进程权限或身份，请查看诊断。'
        elif not fresh:out['diagnostic']='计算后台仍有进程，但心跳已过期；请检查后台日志，不会强行结束进程。'
        else:out['diagnostic']='计算后台正在初始化，尚未完成恢复检查。'
        out['log_tail']=log_tail(folder/'worker.log')
    return out

def ensure(root=ROOT,timeout=6):
    root=Path(root).resolve();folder=root/'data/execution';folder.mkdir(parents=True,exist_ok=True)
    with _launch_lock:
        existing=status(root)
        if existing and existing['online']:return dict(ready=True,reused=True,worker=existing)
        if existing and existing.get('alive') is not False and existing.get('pid'):
            return dict(ready=False,error=existing['diagnostic'],worker=existing)
        ident=uuid.uuid4().hex;logpath=folder/'worker.log';offset=logpath.stat().st_size if logpath.exists() else 0
        attempt=dict(id=ident,created=now(),state='starting',root=str(root))
        def save():
            try:write_json(folder/'worker-start.json',attempt,root)
            except OSError:pass  # The HTTP response still carries the failure.
        save();proc=None
        try:
            with logpath.open('ab') as log:
                log.write(('\n--- 后台启动 '+ident+' '+now()+' ---\n').encode('utf8'));log.flush()
                proc=subprocess.Popen([sys.executable,'-B','-X','utf8',str(ROOT/'execution_worker.py'),'--root',str(root)],cwd=ROOT,
                    stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            attempt.update(pid=proc.pid,process_created=process_info(proc.pid)['created']);save();deadline=time.monotonic()+timeout
            while True:
                observed=status(root)
                if observed and observed['online']:
                    attempt.update(state='ready',launcher_pid=proc.pid,pid=observed['pid']);save()
                    return dict(ready=True,reused=False,worker=observed)
                rc=proc.poll()
                if rc is not None:raise RuntimeError(f'计算后台启动失败（退出码 {rc}）。')
                if time.monotonic()>=deadline:raise RuntimeError('计算后台未在等待时间内完成启动检查；进程若仍在初始化，请稍后刷新，不会反复启动。')
                time.sleep(.1)
        except (OSError,RuntimeError) as error:
            detail=log_tail(logpath,offset)
            attempt.update(state='failed',error=str(error)+(('\n'+detail) if detail else ''),finished=now());save()
            return dict(ready=False,error=attempt['error'],worker=status(root))
