"""Offline, manifest-scoped v0.72.2 update and non-destructive backup recovery.

Standard library only. Never imports a workspace's application code, runs a
simulation, installs dependencies or accesses GitHub. Recovery retains the
current installation/results beside their original paths before restoring.
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, re, shutil, socket, sqlite3, stat
import subprocess, sys, time, uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from contextlib import closing,contextmanager
from urllib.request import urlopen

PACKAGE = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', '.git', '__pycache__'}
DATA_PARTS = {'data','runs','assets','verification','backups'}
TOP = {'.github','building-workbench-next','dependencies','docs','examples','resources','scripts','LICENSES','验收结果'}
ACTIVE = {'running','pending','queued','starting'}

class UpgradeError(ValueError): pass
def fail(message): raise UpgradeError(message)
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def dump(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8');os.replace(tmp,path)
def stamp():return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]

@contextmanager
def exclusive(target):
    target=safe_path(target);path=safe_path(target.with_name(target.name+'.upgrade.lock'))
    with path.open('a+b') as f:
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:fail('已有升级或恢复操作正在处理这个平台，请等它完成。')
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)

def safe_path(path):
    p=Path(path).absolute()
    if '..' in p.parts:fail('路径不能包含上级目录标记。')
    for x in [p,*p.parents]:
        try:info=x.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            fail('不处理链接或重定向文件夹：'+str(x))
    p=p.resolve()
    if p==Path(p.anchor):fail('请选择具体的平台或结果文件夹，不能选择整个磁盘。')
    return p

def child(root,name):
    rel=PurePosixPath(name)
    if not name or '\\' in name or rel.is_absolute() or PureWindowsPath(name).drive or any(x in ('..','.') for x in rel.parts) or ':' in name:
        fail('文件清单含无效路径：'+name)
    p=safe_path(root/Path(*rel.parts))
    if p==root or not p.is_relative_to(root):fail('文件超出指定目录：'+name)
    return p

def scan(root):
    root=safe_path(root)
    if not root.is_dir():fail('文件夹不存在或不能访问：'+str(root))
    files={}
    for folder,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[n for n in dirs if n not in EXCLUDED]
        for n in dirs:safe_path(Path(folder)/n)
        for n in names:
            if n.endswith(('.pyc','.pyo')):continue
            p=safe_path(Path(folder)/n)
            if not p.is_file():fail('不是普通文件：'+str(p))
            files[p.relative_to(root).as_posix()]=dict(sha256=sha(p),bytes=p.stat().st_size)
    return files

def manifest(root,verify=True):
    root=safe_path(root);rows={};seen=set()
    for line in child(root,'MANIFEST.sha256').read_text('utf-8-sig').splitlines():
        if not line.strip():continue
        m=re.fullmatch(r'([a-fA-F0-9]{64}) [ *](.+)',line)
        if not m:fail('包内文件清单格式不正确。')
        h,n=m.groups();p=child(root,n)
        if n.casefold() in seen or n=='MANIFEST.sha256':fail('包内清单存在重复或自引用项。')
        seen.add(n.casefold())
        if verify and (not p.is_file() or sha(p)!=h.lower()):fail('新包校验不通过：'+n)
        rows[n]=h.lower()
    if not rows:fail('包内文件清单为空。')
    return rows

def kept(name):
    p=PurePosixPath(name).parts
    return any(x in EXCLUDED for x in p) or (p[0]=='building-workbench-next' and len(p)>1 and (p[1] in DATA_PARTS or p[1]=='config.json')) or name=='UPGRADE_RECEIPT.json'

def external_roots(target):
    file=target/'building-workbench-next/data/output-storage.json';out=[]
    if file.exists():
        for row in read(file).get('roots',[]):
            raw=Path(row['path'])
            if not raw.is_absolute():fail('外置结果登记必须是完整路径：'+str(raw))
            p=safe_path(raw)
            if not p.is_dir():fail('请先接通已登记的结果位置：'+str(p))
            if p.is_relative_to(target):continue
            if target.is_relative_to(p):fail('结果位置包含整个平台目录，需先核对保存位置。')
            if p not in out:out.append(p)
    # Nested external registrations are backed up once under their outer root.
    return [p for p in out if not any(p!=q and p.is_relative_to(q) for q in out)]

def health(target):
    app=target/'building-workbench-next'
    try:cfg=read(app/'config.json')
    except (OSError,ValueError):return None  # Recovery also works after a damaged config.
    port=cfg.get('port',8776)
    if type(port) is not int or not 1<=port<=65535:fail('旧平台端口配置无效。')
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as r:return json.load(r)
    except (OSError,ValueError):return None

def queue_idle(target):
    db=target/'building-workbench-next/data/execution/queue.sqlite'
    if db.exists():
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='jobs'").fetchone():
                rows=conn.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status').fetchall()
                busy=[(s,n) for s,n in rows if s in ACTIVE and n]
                if busy:fail('还有等待或运行中的计算，请回平台完成或正常停止后再升级：'+str(busy))

def processes(target):
    if os.name!='nt':return []
    env=dict(os.environ,WB_UPGRADE_APP=str(target/'building-workbench-next'))
    script="""$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.Name -match '^python(w)?(.exe)?$' -and $_.CommandLine.IndexOf($env:WB_UPGRADE_APP,[StringComparison]::OrdinalIgnoreCase) -ge 0 } | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"""
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,text=True,encoding='utf8',errors='replace',creationflags=0x08000000)
    if p.returncode:fail('无法核对旧平台的后台进程；请在普通 Windows 用户会话中运行升级助手。')
    value=json.loads(p.stdout or '[]');return value if isinstance(value,list) else [value]

def stopped(target):
    queue_idle(target)
    if health(target) or processes(target):fail('旧平台仍在运行。请先使用升级助手的“停止旧平台”操作，或关闭该平台进程。')

def stop(target):
    target=safe_path(target);queue_idle(target);app=target/'building-workbench-next';h=health(target);ps=processes(target)
    if h and Path(h.get('root','')).resolve()!=app:fail('端口属于另一个平台，拒绝停止。')
    if any('server.py' not in row['CommandLine'] for row in ps):fail('该工作区仍有计算或准备进程，请等它们完成；不会强行结束。')
    if h and h.get('pid') not in {r['ProcessId'] for r in ps}:fail('服务身份核对失败，未停止任何进程。')
    for row in ps:
        env=dict(os.environ,WB_UPGRADE_APP=str(app),WB_UPGRADE_PID=str(int(row['ProcessId'])))
        script="""$ErrorActionPreference='Stop'; $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$env:WB_UPGRADE_PID); if ($p) { if (-not $p.CommandLine -or $p.CommandLine.IndexOf($env:WB_UPGRADE_APP,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or $p.CommandLine -notmatch 'server.py') { throw 'Process identity changed' }; Stop-Process -Id $p.ProcessId -ErrorAction Stop }"""
        p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,creationflags=0x08000000)
        if p.returncode:fail('停止服务未完成，请检查该工作区状态。')
    for _ in range(30):
        if not health(target):break
        time.sleep(.1)
    stopped(target)
    return dict(stopped=True,target=str(target))

def plan(source,target):
    source=safe_path(source);target=safe_path(target)
    if source==target or source.is_relative_to(target) or target.is_relative_to(source):fail('新包必须解压在旧平台之外的独立文件夹。')
    incoming=manifest(source);old=manifest(target,False)
    oldversion=(target/'building-workbench-next/VERSION').read_text('utf8').strip()
    if oldversion.removeprefix('v')!='0.72.2':fail('本工具本次只支持 v0.72.2 原路径升级；检测到 '+oldversion)
    if not (target/'building-workbench-next/config.json').is_file():fail('请选择含旧配置的完整平台包根目录。')
    if sha(source/'requirements-lock.txt')!=sha(target/'requirements-lock.txt'):fail('锁定依赖已变化，本版工具不自动升级 Python 环境。')
    writes=[];conflicts=[]
    for n,h in incoming.items():
        parts=PurePosixPath(n).parts
        if kept(n):
            if n!='building-workbench-next/config.json':fail('发行清单意外包含研究资料：'+n)
            continue
        if len(parts)>1 and parts[0] not in TOP:fail('发行清单包含不受支持的目录：'+n)
        destination=child(target,n)
        if destination.exists() and not destination.is_file():fail('目标同名位置不是文件：'+n)
        actual=sha(destination) if destination.exists() else None
        if actual==h:continue
        if actual is not None and (n not in old or actual!=old[n]):conflicts.append(n)
        writes.append(dict(path=n,before=actual,after=h))
    if conflicts:fail('发现自行修改或同名新增文件，未覆盖。请先另存这些修改，再恢复原发行文件：\n'+'\n'.join(conflicts[:20]))
    writes.append(dict(path='MANIFEST.sha256',before=sha(target/'MANIFEST.sha256'),after=sha(source/'MANIFEST.sha256')))
    return dict(schema=1,source=str(source),target=str(target),old_version=oldversion,new_version=(source/'building-workbench-next/VERSION').read_text('utf8').strip(),
        source_manifest_sha256=sha(source/'MANIFEST.sha256'),writes=writes,external_roots=[str(p) for p in external_roots(target)],
        preserved=['旧 config.json','data / runs / assets 及所有未列入更新的文件','已有 .venv','外置结果位置与内容'],
        note='只更新列出的发行文件；不会删除旧文件、自动改造物性或重算。')

def room_for(path,needed):
    while not path.exists():path=path.parent
    if shutil.disk_usage(path).free<needed+32*1024*1024:fail('备份或恢复位置可用空间不足，尚未更新平台。')

def verify_copy(root,files):
    for n,v in files.items():
        p=child(root,n)
        if not p.is_file() or sha(p)!=v['sha256']:fail('备份/恢复校验不通过：'+str(p))

def copy_files(source,dest,files):
    for n in files:
        a=child(source,n);b=child(dest,n);b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a,b)
    verify_copy(dest,files)

def backup(target,folder):
    target=safe_path(target);folder=safe_path(folder);stopped(target)
    roots=[target,*external_roots(target)]
    if any(folder==r or folder.is_relative_to(r) or r.is_relative_to(folder) for r in roots):fail('备份位置必须位于平台和结果文件夹之外。')
    if folder.exists():fail('备份文件夹已存在，请使用新的空路径。')
    sets=[]
    for i,r in enumerate(roots):
        print('核对备份内容：'+str(r),flush=True);files=scan(r)
        sets.append(dict(original=str(r),folder='workspace' if i==0 else 'external-'+str(i),files=files))
    room_for(folder,sum(v['bytes'] for s in sets for v in s['files'].values()))
    folder.mkdir(parents=True)
    metadata=dict(schema=1,state='copying',created=stamp(),target=str(target),sets=sets,
        excluded=['.venv','.git','__pycache__','*.pyc','*.pyo'],note='包含平台文件及已登记的外置结果；外部原始建筑、气象、引擎不复制且不会改动。')
    dump(folder/'BACKUP.json',metadata)
    for item in sets:
        dest=folder/item['folder'];dest.mkdir();copy_files(Path(item['original']),dest,item['files'])
        if scan(Path(item['original']))!=item['files']:fail('备份期间原目录发生变化，请保持平台关闭后重新备份。')
    metadata['state']='verified';dump(folder/'BACKUP.json',metadata)
    return metadata

def apply(source,target,folder):
    with exclusive(target):return _apply(source,target,folder)

def _apply(source,target,folder):
    p=plan(source,target);source=Path(p['source']);target=Path(p['target']);stopped(target)
    folder=safe_path(folder)
    if source==folder or source.is_relative_to(folder) or folder.is_relative_to(source):fail('备份不能放在新发行包目录中。')
    info=backup(target,folder)
    # Recheck both the approved file plan and full backup after the copy.
    if plan(source,target)!=p:fail('升级计划已变化，未开始覆盖；备份已保留。')
    stopped(target)
    receipt=dict(schema=1,state='updating',backup=str(folder),plan=p,updated=[])
    dump(folder/'UPGRADE.json',receipt)
    try:
        for row in p['writes']:
            n=row['path'];dest=child(target,n)
            actual=sha(dest) if dest.exists() else None
            if actual!=row['before']:fail('文件在更新期间发生变化：'+n)
            src=child(source,n)
            if sha(src)!=row['after']:fail('新包文件在更新期间发生变化：'+n)
            dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.upgrade-'+uuid.uuid4().hex)
            shutil.copy2(src,temp)
            if sha(temp)!=row['after']:fail('复制校验失败：'+n)
            os.replace(temp,dest);receipt['updated'].append(n);dump(folder/'UPGRADE.json',receipt)
        replaced={r['path'] for r in p['writes']}
        for item in info['sets']:
            unchanged={n:v for n,v in item['files'].items() if item['folder']!='workspace' or n not in replaced}
            verify_copy(Path(item['original']),unchanged)
        for row in p['writes']:
            if sha(child(target,row['path']))!=row['after']:fail('更新后程序校验失败：'+row['path'])
        receipt['state']='complete';dump(folder/'UPGRADE.json',receipt);dump(target/'UPGRADE_RECEIPT.json',receipt)
    except Exception as error:
        receipt['state']='incomplete';receipt['error']=str(error);dump(folder/'UPGRADE.json',receipt)
        raise UpgradeError('更新未完成，请勿启动平台。完整备份和已写入清单在 '+str(folder)+'；请用“从备份恢复”保留现场后还原。') from error
    return receipt

def load_backup(folder):
    folder=safe_path(folder);info=read(child(folder,'BACKUP.json'))
    if info.get('schema')!=1 or info.get('state')!='verified':fail('备份未完成校验，不能恢复。')
    target=safe_path(info['target']);expected=[target,*external_roots_from_info(info)]
    if len(info['sets'])!=len(expected):fail('备份位置记录无效。')
    for i,item in enumerate(info['sets']):
        original=safe_path(item['original']);sub='workspace' if i==0 else 'external-'+str(i)
        if original!=expected[i] or item['folder']!=sub:fail('备份路径记录不一致。')
        if original==folder or original.is_relative_to(folder) or folder.is_relative_to(original):fail('备份与恢复位置不能互相包含。')
        if any(original!=q and (original.is_relative_to(q) or q.is_relative_to(original)) for q in expected):fail('恢复位置之间不能重叠。')
        verify_copy(child(folder,sub),item['files'])
    return folder,info

def external_roots_from_info(info):
    # The restore operation additionally binds these to the saved settings.
    return [Path(s['original']) for s in info['sets'][1:]]

def restore(folder):
    folder,info=load_backup(folder)
    with exclusive(info['target']):return _restore(folder)

def _restore(folder):
    folder,info=load_backup(folder);target=Path(info['target']);stopped(target)
    # Bind recovery paths to the actual saved output-storage settings too.
    settings=folder/'workspace/building-workbench-next/data/output-storage.json'
    declared=[safe_path(r['path']) for r in read(settings).get('roots',[])] if settings.exists() else []
    for item in info['sets'][1:]:
        if safe_path(item['original']) not in declared:fail('恢复的外置位置不属于备份时的保存位置登记。')
    suffix='-before-restore-'+stamp();moves=[];required={}
    for item in info['sets']:
        original=safe_path(item['original']);aside=safe_path(original.with_name(original.name+suffix))
        if aside.exists():fail('现场保留目录已存在。')
        if original.exists():scan(original)  # no links; confirms readable current state
        volume=Path(original.anchor)
        required[volume]=required.get(volume,0)+sum(v['bytes'] for v in item['files'].values())
        moves.append(dict(original=str(original),preserved=str(aside),backup_folder=item['folder'],moved=False,restored=False))
    for volume,amount in required.items():room_for(volume,amount)
    receipt=dict(state='restoring',backup=str(folder),locations=moves)
    receipt_path=folder/('RESTORE-'+stamp()+'.json');dump(receipt_path,receipt)
    try:
        for item,move in zip(info['sets'],moves,strict=True):
            original=safe_path(move['original']);aside=safe_path(move['preserved'])
            # These are the exact validated installation or registered output
            # roots above. Rename preserves everything; never recursive delete.
            if original.exists():original.rename(aside);move['moved']=True;dump(receipt_path,receipt)
            original.mkdir();copy_files(folder/item['folder'],original,item['files'])
            if item['folder']=='workspace':
                for name in ('.venv','.git'):
                    existing=safe_path(aside/name);dest=safe_path(original/name)
                    if existing.exists():
                        if dest.exists() or dest.parent!=target:fail('运行环境恢复路径冲突。')
                        existing.rename(dest)
            move['restored']=True;dump(receipt_path,receipt)
        receipt['state']='complete';dump(receipt_path,receipt)
    except Exception as error:
        receipt['state']='incomplete';receipt['error']=str(error);dump(receipt_path,receipt)
        raise UpgradeError('恢复中断；旧备份、升级后现场及恢复清单均保留。请不要启动或手工覆盖，查看 '+str(receipt_path)) from error
    return receipt

def prompt_path(text):return safe_path(input(text).strip().strip('"'))
def wizard():
    print('建筑热环境工作台 · 升级与恢复助手\n只支持 v0.72.2 原路径升级；不会自动计算或上传。')
    mode=input('输入 1 升级旧平台；输入 2 从备份恢复：').strip()
    if mode=='1':
        target=prompt_path('旧平台包根目录（含 Start Workbench.cmd）：')
        p=plan(PACKAGE,target)
        print(json.dumps({k:v for k,v in p.items() if k!='writes'},ensure_ascii=False,indent=2))
        print('将更新 '+str(len(p['writes']))+' 个文件，先完整备份平台资料和已登记外置结果。')
        folder=target.with_name(target.name+'-upgrade-backups')/stamp()
        entered=input('备份保存到 '+str(folder)+'；如需修改请输入完整路径，直接回车使用此位置：').strip().strip('"')
        if entered:folder=safe_path(entered)
        print('请保存编辑，等计算、核对和导出完成，关闭其他访问此平台的页面。')
        if input('确认后输入“升级”（其他输入退出）：').strip()!='升级':return
        stop(target);result=apply(PACKAGE,target,folder)
        print('升级完成。备份：'+str(folder)+'\n请在原目录双击 Start Workbench.cmd，按升级说明核对方案与结果。')
    elif mode=='2':
        folder=prompt_path('备份目录（含 BACKUP.json）：');folder,info=load_backup(folder)
        print('将恢复到原位置：'+info['target']+'\n升级后的平台和结果会先另存为 before-restore 文件夹；不会丢弃新增研究资料。')
        for item in info['sets'][1:]:print('外置结果也恢复到：'+item['original'])
        print('恢复后显示备份时的资料；后来新增的记录保存在现场副本里，不会自动合并到旧数据库。')
        if input('保存编辑，等待计算、核对和导出结束后，输入“恢复”（其他输入退出）：').strip()!='恢复':return
        stop(Path(info['target']));result=restore(folder)
        print('恢复完成。请从原位置启动；升级后现场位置：')
        for row in result['locations']:print(row['preserved'])
    else:print('已退出，未更改平台。')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['wizard','plan','stop','apply','restore'])
    parser.add_argument('--target',type=Path);parser.add_argument('--source',type=Path,default=PACKAGE);parser.add_argument('--backup',type=Path)
    parser.add_argument('--yes',action='store_true',help='明确执行已检查的升级/停止/恢复；交互用户建议使用 wizard')
    args=parser.parse_args()
    try:
        if args.action=='wizard':wizard();return 0
        if args.action in ('apply','stop','restore') and not args.yes:fail('需要 --yes 才执行；也可双击 Upgrade Workbench.cmd 使用逐步向导。')
        if args.action in ('plan','apply','stop') and args.target is None:fail('请提供旧平台 --target 路径。')
        if args.action in ('apply','restore') and args.backup is None:fail('请提供 --backup 路径。')
        if args.action=='plan':result=plan(args.source,args.target)
        elif args.action=='stop':result=stop(args.target)
        elif args.action=='apply':result=apply(args.source,args.target,args.backup)
        else:result=restore(args.backup)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,sqlite3.Error) as error:
        print('未完成：'+str(error),file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
