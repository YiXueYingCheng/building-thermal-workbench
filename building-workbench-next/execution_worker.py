"""Exclusive worker; every child belongs to our kill-on-close Windows job."""
import argparse
import ctypes
from ctypes import wintypes as w
import msvcrt
import os
from pathlib import Path
import subprocess
import time
import traceback
from collections import defaultdict
from foundation import ROOT,owned,sha,now,write_json,read_json
import output_storage
from execution_queue import Queue
from execution_inputs import load_review,execution_revision
from execution_results import verify
import resources
from resource_history import ResourceHistory, startup_wait_seconds

class ProcessGroup:
    def __init__(self):
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
        k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.CloseHandle.argtypes=[w.HANDLE]
        class BASIC(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):_fields_=[(n,ctypes.c_ulonglong) for n in ('ro','wo','oo','rb','wb','ob')]
        class EXT(ctypes.Structure):_fields_=[('basic',BASIC),('io',IO),('process_mem',ctypes.c_size_t),('job_mem',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.k=k;self.handle=k.CreateJobObjectW(None,None);info=EXT();info.basic.flags=0x2000
        if not self.handle or not k.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise OSError('不能建立计算进程保护组。')
    def add(self,proc):
        if not self.k.AssignProcessToJobObject(self.handle,w.HANDLE(int(proc._handle))):
            proc.terminate();proc.wait();raise OSError('新计算进程未能加入保护组，已停止。')
    def close(self):
        if getattr(self,'handle',None):self.k.CloseHandle(self.handle);self.handle=None

def engine_pids():
    """Toolhelp snapshot fails closed. No process command line or unrelated data read."""
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    class ENTRY(ctypes.Structure):
        _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('name',w.WCHAR*260)]
    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(ENTRY)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes;k.CloseHandle.argtypes=[w.HANDLE]
    h=k.CreateToolhelp32Snapshot(2,0)
    if h==ctypes.c_void_p(-1).value:raise OSError('无法核查当前计算进程。')
    try:
        e=ENTRY();e.size=ctypes.sizeof(e)
        if not k.Process32FirstW(h,ctypes.byref(e)):raise OSError('无法读取计算进程列表。')
        result=[]
        while True:
            if e.name.lower()=='energyplus.exe':result.append(e.pid)
            if not k.Process32NextW(h,ctypes.byref(e)):
                if ctypes.get_last_error()!=18:raise OSError('计算进程列表读取中断。')
                break
        return result
    finally:k.CloseHandle(h)

def memory_history(q):
    history=defaultdict(list);seen=set()
    with q.db() as c:rows=[dict(r) for r in c.execute("SELECT batch,result,result_sha256 FROM jobs WHERE status IN ('passed','review','reused') AND result IS NOT NULL")]
    for row in rows:
        try:
            path=output_storage.checked_path(row['result'],q.root)
            if (row['batch'],str(path)) in seen or sha(path)!=row['result_sha256']:continue
            r=read_json(path);value=r.get('peak_gib',0)
            if value>0:history[(row['batch'],r['mode'])].append(value);seen.add((row['batch'],str(path)))
        except (OSError,ValueError,KeyError,TypeError):continue
    return history

def publish_status(root, payload):
    """Status is observational: an I/O failure must not close the owned process group."""
    try:
        write_json(Path(root)/'data/execution/worker.json',payload,root)
        return True
    except OSError as error:
        print(f'运行状态暂未写入，保留正在计算的进程，下轮重试：{error}',flush=True)
        return False

def fail_attempt(q,job,phase,error):
    """The queue is local even if an output disk disappears. Never lose terminal state
    because writing an error next to the unavailable result also fails.
    """
    q.finish(job,'failed',error=str(error))
    try:
        write_json(q.folder/'attempt-errors'/(job['attempt']+'.json'),
            dict(attempt=job['attempt'],batch=job['batch'],phase=phase,error=str(error),
                 traceback=traceback.format_exc(),finished=now()),q.root)
    except OSError as log_error:
        print('算例已记录失败，但诊断文件暂未写入：'+str(log_error),flush=True)


def complete_attempt(q,r,rc):
    job=r['job'];root=q.root
    try:
        r['log'].close();elapsed=time.monotonic()-r['started']
        # Resolve again before every completion write: never write to a replaced disk.
        folder=output_storage.attempt_folder(root,job['attempt'])
        if folder!=r['folder']:raise ValueError('原执行位置发生变化。')
        output_storage.write_run(folder/'execution.json',dict(returncode=rc,pid=r['proc'].pid,
            elapsed_seconds=elapsed,peak_gib=r['peak'],resources=r['policy'],
            resource_estimate=r['resource_estimate'],finished=now()),root)
        load_review(root,job['plan']['id'],job['checksum'])
        if sha(folder/'model.epJSON')!=job['case']['model_sha256']:raise ValueError('实际运行输入变化。')
        result=verify(folder,job['case'],rc,elapsed)
        result.update(identity=job['identity'],attempt=job['attempt'],peak_gib=r['peak'],
                      execution_revision=execution_revision(job['plan']['code_hashes'],root))
        path=folder/'result.json';output_storage.write_run(path,result,root)
        q.finish(job,result['status'],str(path))
    except Exception as error:
        fail_attempt(q,job,'completion',error)


def run(root,idle_exit=False):
    q=Queue(root);lock=(q.folder/'worker.lock').open('a+b');lock.seek(0)
    if lock.read(1)==b'':lock.write(b'0');lock.flush()
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:lock.close();return
    active={};group=ProcessGroup();last_status=0;history_status=[0.]
    def history_progress(completed,total):
        if time.monotonic()-history_status[0]<2:return
        policy=q.policy()
        try:machine=resources.snapshot(root)
        except OSError:machine=None
        reason=f'正在核对内存历史 {completed}/{total}，完成后继续调度。' if not active else f'当前算例继续运行，正在更新内存历史 {completed}/{total}。'
        publish_status(root,dict(pid=os.getpid(),root=str(root),heartbeat=now(),active=len(active),resources=policy,machine=machine,foreign_engine_pids=[],reason=reason,phase='memory_history',budget=None))
        history_status[0]=time.monotonic()
    try:
        q.recover()
        history=ResourceHistory(root,progress=history_progress)
        while True:
            for key,r in list(active.items()):
                r['memory']=resources.process_memory(r['proc']._handle);r['peak']=max(r['peak'],r['memory']['peak_gib'],r['memory']['peak_commit_gib'])
                r['memory']['reserved_gib']=max(r['resource_estimate']['reserved_gib'],history.history.estimate(r['resource_estimate']['key'])['reserved_gib'],r['peak']*1.25+.05)
                rc=r['proc'].poll()
                if rc is None:continue
                complete_attempt(q,r,rc)
                del active[key]
                try:history.refresh()
                except Exception as error:print('内存历史暂未更新，保留已读取的预算：'+str(error),flush=True)
            policy=q.policy();machine=None;reason=None;foreign=[];budget=None;estimate=.75
            try:
                machine=resources.snapshot(root);foreign=sorted(set(engine_pids())-{r['proc'].pid for r in active.values()})
                candidate=q.next_pending()
                if candidate:
                    resource_estimate=history.estimate(candidate);estimate=resource_estimate['reserved_gib']
                    budget=resources.dispatch_budget(policy,machine,[r['memory'] for r in active.values()],estimate)
                    budget.update(completed_samples=resource_estimate['configuration_samples'],family_samples=resource_estimate['family_samples'],basis=resource_estimate['basis'],observed_family_peak_gib=resource_estimate['observed_family_peak_gib'])
                    disk_budget=output_storage.dispatch_capacity(root,candidate['batch'],policy,list(active.values()))
                    budget['storage']=disk_budget
                    if budget['reason'] is None and disk_budget['reason']:budget.update(reason=disk_budget['reason'],allowed=False)
                    settling=startup_wait_seconds([dict(started_seconds=r['started'],unseen_configuration=r['resource_estimate']['unseen_configuration']) for r in active.values()],time.monotonic())
                    budget['startup_wait_seconds']=settling
                    reason='检测到其他 EnergyPlus 计算，等待其完成' if foreign else budget['reason']
                    if reason is None and settling>0:reason=f'等待新配置启动稳定：约 {settling:.0f} 秒后重新核对内存'
                    if reason is not None:budget.update(allowed=False,reason=reason)
                elif active:reason='当前算例继续运行，没有可派发的排队项'
                else:
                    with q.db() as c:waiting=c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('pending','interrupted')").fetchone()[0]
                    reason='队列已暂停，等待继续' if waiting else '当前没有排队中的计算任务'
                if candidate and reason is None:
                    job=q.claim(expected=candidate)
                    if job:
                        # Keep engine paths below legacy Windows MAX_PATH, including outputs.
                        try:
                            folder=output_storage.attempt_folder(root,job['attempt'],probe=True)
                            folder.mkdir(parents=True,exist_ok=False)
                            if len(str(folder))+35>=260:raise ValueError('工作区路径过长，请将工作区放在更短的目录后运行。')
                            plan=load_review(root,job['plan']['id'],job['checksum']);cached=q.cached(job['identity'])
                            if history.context(job['batch'],job['idx'])['key']!=resource_estimate['key']:raise ValueError('派发前内存分类输入变化，请重新核对。')
                            if cached:q.finish(job,'reused',cached)
                            else:
                                c=job['case'];source=owned(q.folder/'reviews'/plan['id']/c['model_file'],root)
                                (folder/'model.epJSON').write_bytes(source.read_bytes());(folder/'run').mkdir()
                                log=(folder/'engine.log').open('ab')
                                try:
                                    flags=subprocess.CREATE_NO_WINDOW | (subprocess.BELOW_NORMAL_PRIORITY_CLASS if policy['priority']=='below_normal' else subprocess.NORMAL_PRIORITY_CLASS)
                                    proc=subprocess.Popen([plan['engine'],'-w',c['weather'],'-d','run','model.epJSON'],cwd=folder,
                                        stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=flags,env=dict(os.environ,OMP_NUM_THREADS='1'))
                                    group.add(proc)
                                except Exception:log.close();raise
                                active[job['attempt']]=dict(proc=proc,log=log,folder=folder,job=job,started=time.monotonic(),memory={'working_gib':0,'commit_gib':0,'reserved_gib':estimate},peak=0,policy=policy,resource_estimate=resource_estimate)
                                q.set_pid(job,proc.pid);output_storage.write_run(folder/'launch.json',dict(pid=proc.pid,started=now(),batch=job['batch'],case=c,resources=policy,resource_estimate=resource_estimate,execution_revision=execution_revision(plan['code_hashes'],root)),root)
                        except Exception as error:
                            run=active.pop(job['attempt'],None)
                            if run:
                                run['proc'].terminate();run['proc'].wait(timeout=30);run['log'].close()
                            fail_attempt(q,job,'launch',error)
            except Exception as error:reason='暂停派发：'+str(error);print(traceback.format_exc(),flush=True)
            if time.monotonic()-last_status>2:
                publish_status(root,dict(pid=os.getpid(),root=str(root),heartbeat=now(),active=len(active),resources=policy,machine=machine,foreign_engine_pids=foreign,reason=reason,per_job_reserved_gib=estimate,budget=budget));last_status=time.monotonic()
            if idle_exit and not active and not any(b['counts']['pending'] and b['mode']=='run' for b in q.state()['batches']):break
            time.sleep(1)
    finally:
        group.close()
        for r in active.values():
            r['proc'].wait(timeout=30);r['log'].close()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--idle-exit',action='store_true');args=parser.parse_args()
    run(args.root.resolve(),args.idle_exit)
