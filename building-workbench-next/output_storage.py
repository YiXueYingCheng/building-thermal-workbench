"""Result destinations are operational records, separate from physical inputs."""
from pathlib import Path
from contextlib import contextmanager,closing
import ctypes,hashlib,json,math,msvcrt,os,re,shutil,sqlite3,uuid
from foundation import ROOT,now,read_json,write_json,owned,canonical,loads,digest

def volume(path):
    root = Path(path).anchor
    if os.name != 'nt':
        usage = shutil.disk_usage(root)
        return dict(root=root, serial=str(os.stat(root).st_dev), filesystem='local', drive_type='本地卷', free_gib=usage.free/2**30)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetVolumeInformationW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32]
    k.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    serial = ctypes.c_uint32();maximum = ctypes.c_uint32();flags = ctypes.c_uint32()
    label = ctypes.create_unicode_buffer(261);fs = ctypes.create_unicode_buffer(261)
    if not k.GetVolumeInformationW(root, label, len(label), ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags), fs, len(fs)):
        raise OSError('保存位置所在磁盘离线或无法读取。')
    drive = k.GetDriveTypeW(root)
    if drive not in (2, 3):
        raise ValueError('当前仅支持本机磁盘或外置磁盘，不支持网络盘。')
    if fs.value.upper() not in ('NTFS', 'EXFAT', 'REFS'):
        raise ValueError('请使用NTFS、exFAT或ReFS；FAT32等格式无法可靠保存大型结果文件。')
    return dict(root=root, serial=f'{serial.value:08x}', filesystem=fs.value, label=label.value,
                drive_type='可移动卷' if drive == 2 else '本地卷（也可能是外置盘）', free_gib=shutil.disk_usage(root).free/2**30)

def identity(info):
    return {key: info[key] for key in ['root', 'serial', 'filesystem']}

def reserved_roots():
    """OS/application folders are never workbench output locations."""
    if os.name!='nt':return []
    system_drive=os.environ.get('SystemDrive','C:')
    defaults=[Path(system_drive+'/')/name for name in ('Windows','Program Files','Program Files (x86)','ProgramData')]
    configured=[Path(os.environ[key]) for key in ('SystemRoot','WINDIR','ProgramFiles','ProgramFiles(x86)','ProgramW6432','ProgramData') if os.environ.get(key)]
    return [p.resolve() for p in defaults+configured]

def safe_path(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('请填写完整的结果文件夹路径。')
    raw = raw.strip().strip('"')
    path = Path(raw)
    if not path.is_absolute() or raw.startswith(('\\\\', '//')) or path == Path(path.anchor) or '..' in path.parts:
        raise ValueError('请选用本机磁盘下的专用文件夹，不能使用盘符根目录、网络路径或相对路径。')
    resolved=path.resolve()
    reserved=reserved_roots()+[Path(path.anchor)/name for name in ('$RECYCLE.BIN','System Volume Information')]
    if any(resolved==root or resolved.is_relative_to(root) for root in reserved):
        raise ValueError('不能将结果保存在系统、程序安装或磁盘保留目录中，请选择自己的专用文件夹。')
    for part in path.parts[1:]:
        if any(ch in part for ch in '<>:"|?*') or any(ord(ch) < 32 for ch in part) or part.endswith((' ', '.')):
            raise ValueError('文件夹名称含有不支持的字符。')
    for parent in [path, *path.parents]:
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('结果位置暂不支持符号链接、目录联接或其他重定向文件夹。')
    return resolved

def writable(folder):
    """Only create and remove our unique, tiny probe file."""
    path = Path(folder)/('.write-check-'+uuid.uuid4().hex+'.tmp')
    payload = uuid.uuid4().bytes
    try:
        with path.open('xb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        if path.read_bytes() != payload:
            raise OSError('写入回读不一致。')
    finally:
        if path.is_file():
            try:path.unlink()
            except OSError as error:
                import warnings
                warnings.warn('结果目录写入回读检查已结束，但检查临时文件未能清理：'+str(path)+'；'+str(error),RuntimeWarning)

MARKER='.building-workbench-next-output.json'

@contextmanager
def locked(root):
    path=owned(Path(root)/'data/output-storage.lock',root);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as f:
        if f.seek(0,2)==0:f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise ValueError('保存位置正在更新，请稍后重试。')
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def config(root=ROOT):
    p=Path(root)/'data/output-storage.json'
    return read_json(p) if p.exists() else dict(schema=1,default='local',roots=[])

def local(root=ROOT):
    return dict(id='local',label='工作区结果目录',path=str(Path(root).resolve()/'runs'),marker=None,volume=None)

def entries(root=ROOT):return [local(root),*config(root)['roots']]

def entry(ident=None,root=ROOT):
    ident=ident or config(root)['default']
    row=next((r for r in entries(root) if r['id']==ident),None)
    if row is None:raise ValueError('保存位置未登记，请重新选择。')
    return row

def inspect(item,root=ROOT,probe=False):
    path=safe_path(item['path']);info=volume(path)
    from inspection_io import current
    reads=current()
    if reads:reads.watch_value('output-volume:'+str(path.anchor),lambda:identity(volume(path)),identity(info))
    if item.get('volume') and identity(info)!=item['volume']:raise ValueError('磁盘身份与登记不同，请接回原磁盘；不会改存其他位置。')
    if item['id']=='local' and not path.exists():
        if probe:path.mkdir(parents=True,exist_ok=True)
        else:return dict(item,online=True,current_volume=info,free_gib=info['free_gib'],error=None,directory_pending=True)
    if not path.is_dir():raise ValueError('保存文件夹不可用，请检查连接；不会自动改存其他位置。')
    if item.get('marker'):
        if item['marker'].get('workspace')!=hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest():raise ValueError('此保存位置属于另一工作区，不能直接写入或重新绑定。')
        p=path/MARKER
        if not p.is_file() or read_json(p)!=item['marker']:raise ValueError('保存目录标识不匹配，请检查原磁盘及文件夹。')
    if probe:writable(path)
    return dict(item,online=True,current_volume=info,free_gib=info['free_gib'],error=None)

def status(root=ROOT):
    rows=[]
    for item in entries(root):
        try:rows.append(inspect(item,root))
        except (OSError,ValueError) as e:rows.append(dict(item,online=False,free_gib=None,error=str(e)))
    return dict(default=config(root)['default'],items=rows,workspace_path=str(Path(root).resolve()),workspace_free_gib=volume(root)['free_gib'])

def register(raw,label,root=ROOT):
    if (Path(root)/'.recovery-copy.json').exists():raise ValueError('恢复副本不能登记新的计算位置。')
    if not isinstance(label,str) or not 1<=len(label.strip())<=60:raise ValueError('请输入 1 至 60 字的位置名称。')
    path=safe_path(raw);workspace=Path(root).resolve()
    if path==workspace or path.is_relative_to(workspace) or workspace.is_relative_to(path):raise ValueError('工作区已有默认结果目录；新增位置请选择工作区之外的独立文件夹。')
    if len(str(path))+1+32+35>=260:raise ValueError('保存路径过长，请选择较短的文件夹，给算例和结果文件留出空间。')
    with locked(root):
        info=volume(path)
        for known in entries(root):
            kp=Path(known['path']).resolve()
            if path==kp:return inspect(known,root,True)
            if path.is_relative_to(kp) or kp.is_relative_to(path):raise ValueError('保存位置不能互相包含，请选独立文件夹。')
        if path.exists() and (not path.is_dir() or any(path.iterdir())):raise ValueError('请选空文件夹或新文件夹，避免混入旧平台结果及归档。')
        path.mkdir(parents=True,exist_ok=True);writable(path)
        marker=dict(schema=1,id=uuid.uuid4().hex,workspace=hashlib.sha256(str(workspace).encode()).hexdigest())
        with (path/MARKER).open('x',encoding='utf8') as f:json.dump(marker,f);f.flush();os.fsync(f.fileno())
        item=dict(id='storage_'+uuid.uuid4().hex[:16],label=label.strip(),path=str(path),marker=marker,volume=identity(info),created=now())
        cfg=config(root);cfg['roots'].append(item);write_json(workspace/'data/output-storage.json',cfg,workspace)
        return inspect(item,root)

def capture(ident=None,root=ROOT,probe=False):
    r=inspect(entry(ident,root),root,probe)
    return dict(id=r['id'],label=r['label'],path=r['path'],marker=r.get('marker'),volume=identity(r['current_volume']))

def verify(snapshot,root=ROOT,probe=False):
    if not isinstance(snapshot,dict):raise ValueError('缺少保存位置快照，请重新核对预算。')
    item=entry(snapshot.get('id'),root)
    if item['path']!=snapshot.get('path') or item.get('marker')!=snapshot.get('marker'):raise ValueError('保存位置登记改变，请重新核对。')
    if not isinstance(snapshot.get('volume'),dict):raise ValueError('保存位置缺少磁盘身份。')
    return inspect(dict(item,volume=snapshot['volume']),root,probe)

def select(ident,root=ROOT):
    if (Path(root)/'.recovery-copy.json').exists():raise ValueError('恢复副本不能更改后续计算位置。')
    with locked(root):
        snap=capture(ident,root,True);cfg=config(root);cfg['default']=ident;write_json(Path(root)/'data/output-storage.json',cfg,root)
    return snap

def capacity(snapshot,target_extra_bytes,workspace_extra_bytes,reserve_gib,root=ROOT):
    r=verify(snapshot,root);workspace=volume(root);same=identity(workspace)==identity(r['current_volume'])
    for number in (target_extra_bytes,workspace_extra_bytes,reserve_gib):
        if type(number) not in (int,float) or not math.isfinite(number) or number<0:raise ValueError('磁盘预算数值无效。')
    reserve=reserve_gib*2**30
    target_required=reserve+target_extra_bytes+(workspace_extra_bytes if same else 0)
    workspace_required=target_required if same else reserve+workspace_extra_bytes
    return dict(destination=snapshot,same_volume=same,workspace_path=str(Path(root).resolve()),
        target_free_bytes=int(r['current_volume']['free_gib']*2**30),workspace_free_bytes=int(workspace['free_gib']*2**30),
        target_required_bytes=target_required,workspace_required_bytes=workspace_required,
        target_extra_bytes=target_extra_bytes,workspace_extra_bytes=workspace_extra_bytes,reserve_bytes=reserve,
        fits=r['current_volume']['free_gib']*2**30>=target_required and workspace['free_gib']*2**30>=workspace_required)

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS batch_storage(batch TEXT PRIMARY KEY,snapshot TEXT NOT NULL,sha256 TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS attempt_storage(attempt TEXT PRIMARY KEY,batch TEXT NOT NULL,snapshot TEXT NOT NULL,sha256 TEXT NOT NULL)')

def _read_row(root,table,column,value):
    path=Path(root)/'data/execution/queue.sqlite'
    if not path.exists():return None
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if not db.execute("select 1 from sqlite_master where type='table' and name=?",(table,)).fetchone():return None
        return db.execute('SELECT snapshot,sha256 FROM '+table+' WHERE '+column+'=?',(value,)).fetchone()

def _row(root,table,column,value):
    row=_read_row(root,table,column,value)
    from inspection_io import current
    reads=current()
    if reads:reads.watch_value('output-binding:'+str(root)+':'+table+':'+str(value),lambda:_read_row(root,table,column,value),row)
    return row

def decode(row):
    data=loads(row[0])
    if digest(data)!=row[1]:raise ValueError('任务保存位置记录发生变化，请核查。')
    return data

def batch_destination(root,batch):
    row=_row(root,'batch_storage','batch',batch)
    # Existing batches always retain their historical workspace destination.
    return decode(row) if row else capture('local',root)

def attempt_folder(root,attempt,probe=False):
    if not re.fullmatch('attempt_[a-f0-9]{32}',str(attempt)):raise ValueError('计算尝试编号无效。')
    row=_row(root,'attempt_storage','attempt',attempt)
    if not row:return owned(Path(root)/'runs'/attempt[8:],root)
    snapshot=decode(row);verify(snapshot,root,probe)
    return owned(safe_path(str(Path(snapshot['path'])/attempt[8:])),snapshot['path'])

def checked_path(path,root=ROOT):
    """Workspace files or paths tied to a registered, pinned external attempt."""
    raw=Path(path);p=raw.resolve();workspace=Path(root).resolve()
    if p.is_relative_to(workspace):return owned(p,workspace)
    safe_path(str(raw))
    for item in entries(root):
        base=Path(item['path']).resolve()
        if not p.is_relative_to(base):continue
        rel=p.relative_to(base)
        if len(rel.parts)<2 or not re.fullmatch('[a-f0-9]{32}',rel.parts[0]):raise ValueError('文件不在已登记算例目录内。')
        folder=attempt_folder(root,'attempt_'+rel.parts[0])
        if folder.parent!=base:raise ValueError('结果位置与原执行登记不一致。')
        return owned(p,folder)
    raise ValueError('结果文件不属于工作区或已登记的计算位置。')

def result_folder(result,root=ROOT):
    folder=attempt_folder(root,result['attempt'])
    models=[checked_path(p,root) for p in result['artifacts'] if Path(p).name=='model.epJSON']
    if len(models)!=1 or models[0].parent!=folder:raise ValueError('结果模型与原执行位置不一致。')
    return folder

def write_run(path,value,root=ROOT):
    path=checked_path(path,root)
    write_json(path,value,path.parent)

def dispatch_capacity(root,batch,policy,running):
    snapshot=batch_destination(root,batch);verify(snapshot,root)
    active=sum(identity(volume(r['folder']))==snapshot['volume'] for r in running)
    out=capacity(snapshot,(active+1)*.1*2**30,(len(running)+1)*.02*2**30,policy['disk_reserve_gib'],root)
    out['reason']=None if out['fits'] else '等待磁盘：结果位置或工作区的剩余空间低于保留线及启动留量'
    return out

def bind_attempt(db,batch,attempt,root):
    row=db.execute('SELECT snapshot,sha256 FROM batch_storage WHERE batch=?',(batch,)).fetchone()
    snapshot=decode(row) if row else capture('local',root)
    db.execute('INSERT INTO attempt_storage VALUES(?,?,?,?)',(attempt,batch,canonical(snapshot),digest(snapshot)))
    return snapshot

def planning(root,snapshot,cases,reserve_gib):
    # Preserve the existing 160 MiB/case planning allowance, now separated by
    # destination. This is a coarse preparation allowance, not a measured peak.
    out=capacity(snapshot,cases*80*1024**2,cases*80*1024**2,reserve_gib,root)
    out.update(available_bytes=out['target_free_bytes'],planning_allowance_bytes=cases*160*1024**2,
        note='暂按每项工作区 80 MiB、结果位置 80 MiB 留量；同盘合计 160 MiB/项，不是峰值保证。实际派发继续检查两处空间。')
    return out
