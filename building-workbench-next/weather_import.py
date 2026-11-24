"""Register screened EPWs by content, in workspace storage or at a user-selected path."""
from pathlib import Path
import copy
import os
import stat
import shutil
import threading
from foundation import ROOT, owned, read_json, write_json, digest, now
import weather_quality

LOCK = threading.RLock()
KIND = 'imported_epw_v1'

def scan_folder(path, recursive=False):
    """List bounded local candidates; inspecting/registering remains explicit per file."""
    if not isinstance(path,str) or not path.strip() or not Path(path).is_absolute():
        raise ValueError('请选择气象文件夹的完整路径。')
    if not isinstance(recursive,bool):raise ValueError('是否包含子文件夹应为勾选值。')
    base=Path(path).resolve(strict=True)
    if not base.is_dir():raise ValueError('所选路径不是文件夹。')
    files=[];notes=[];todo=[base];visited=0;entries_seen=0;limited=False
    while todo:
        folder=todo.pop();visited+=1
        if visited>1000:limited=True;break
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    entries_seen+=1
                    if entries_seen>20000:limited=True;break
                    # Never follow links, junctions or other reparse points into unrelated trees.
                    info=entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
                        notes.append('跳过链接或重解析项：'+str(Path(entry.path).relative_to(base)))
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:todo.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower()=='.epw':
                        if len(files)>=500:limited=True;break
                        files.append(dict(path=entry.path,name=entry.name,relative=str(Path(entry.path).relative_to(base)),bytes=info.st_size))
        except OSError:
            notes.append('无法读取文件夹：'+str(folder.relative_to(base) or '.'))
        if limited:break
    files.sort(key=lambda r:r['relative'].casefold())
    if limited:notes.append('单次最多列出 500 份 EPW、遍历 1000 个文件夹或 20000 个文件项；请分文件夹继续导入。')
    return dict(path=str(base),recursive=recursive,files=files,notes=notes,limited=limited)

def register_folder_item(root,path,expected_sha256,metadata,catalog):
    """Skip verified identical content, including another item registered concurrently."""
    if not isinstance(metadata,dict) or metadata.get('reviewed') is not True:
        raise ValueError('请先核对所选地点与质量说明。')
    mode = storage_mode(metadata)
    with LOCK:
        checked,_=inspect(path)
        if checked['sha256']!=expected_sha256:raise ValueError('检查后的气象文件已改变，请重新检查再登记。')
        if not checked['can_register']:raise ValueError('逐时气象存在需修复项，不能登记。')
        from source_locations import resolve
        for row in listing(root):
            site = row['site']
            weather = site['weather']
            if weather['sha256'] != expected_sha256 or storage_mode(site) != mode:
                continue
            actual, _ = resolve(weather, catalog)
            if mode == 'reference' and Path(actual['path']) != Path(checked['path']):
                continue
            if weather_quality.read_snapshot(actual['path'], expected_sha256)[0]['status'] == 'matches':
                return dict(reused=True, existing_id=site['id'], name=site['name'])
        # Folder imports add locations, never change a previous source or assign a climate class.
        return register(root,path,expected_sha256,dict(reviewed=True,name=metadata.get('name',''),storage_mode=mode,note='由用户选定文件夹导入；已核对地点与逐时质量说明，气候分类暂未指定。'),catalog)

def storage_mode(metadata):
    mode = metadata.get('storage_mode', 'copy')
    if mode not in ('copy', 'reference'):
        raise ValueError('请选择保存工作区副本或仅引用原文件。')
    return mode

def inspect(path):
    if not isinstance(path,str) or not path.strip() or len(path)>32768:raise ValueError('请选择本机 EPW 文件。')
    p=Path(path)
    if not p.is_absolute() or p.suffix.lower()!='.epw':raise ValueError('需要 EPW 文件的完整路径。')
    p=p.resolve(strict=True)
    if not p.is_file():raise ValueError('所选路径不是文件。')
    # read_snapshot binds the inspected bytes and detects a concurrent writer.
    identity,raw=weather_quality.read_snapshot(p,None)
    if identity['status']!='mismatch':raise ValueError('未能稳定读取 EPW：'+identity['status'])
    identity,raw=weather_quality.read_snapshot(p,identity['actual_sha256'])
    if raw is None:raise ValueError('检查期间文件改变，请重新检查。')
    q=weather_quality.inspect(raw)
    return dict(path=str(p),sha256=q['sha256'],bytes=len(raw),quality=q,can_register=q['status']!='issues',checked_at=now()),raw

def listing(root=ROOT):
    rows=[]
    for p in sorted((Path(root)/'data/weather-registry').glob('weather_*.json')):
        row=read_json(p)
        if digest(row['data'])!=row['sha256'] or p.stem!=row['data']['id']:raise ValueError('气象登记内容校验失败。')
        rows.append(row['data'])
    return rows

def inventory(root, catalog, verify_id=None):
    """Opening the library checks file metadata only. Hash an entry on explicit request."""
    from source_locations import resolve
    entries = []
    for row in listing(root):
        if verify_id is not None and row['id'] != verify_id:
            continue
        site = row['site']
        weather = site['weather']
        actual, _ = resolve(weather, catalog)
        path = Path(actual['path'])
        if verify_id is not None:
            status = weather_quality.read_snapshot(path, weather['sha256'])[0]['status']
        else:
            try:
                info = path.stat()
                status = ('unreadable' if not stat.S_ISREG(info.st_mode) else
                          'mismatch' if info.st_size != weather['bytes'] else 'present')
            except FileNotFoundError:
                status = 'missing'
            except OSError:
                status = 'unreadable'
        entries.append(dict(id=row['id'], name=site['name'], climate=site.get('climate'),
                            country=site.get('country'), station=row['quality']['header'].get('station'),
                            created=row['created'], storage_mode=storage_mode(site), path=str(path),
                            source_path=row['source_path'], sha256=weather['sha256'],
                            bytes=weather['bytes'], status=status))
    if verify_id is not None and not entries:
        raise ValueError('找不到这项气象登记，请刷新气象管理。')
    return sorted(entries, key=lambda row: (row['created'], row['id']), reverse=True)

def merge(catalog,root=ROOT):
    for row in listing(root):
        site=row['site'];old=catalog['sites'].get(site['id'])
        if old is not None and old!=site:raise ValueError('气象地点编号冲突。')
        catalog['sites'][site['id']]=copy.deepcopy(site)
    return catalog

def register(root,path,expected_sha256,metadata,catalog):
    with LOCK:
        checked,raw=inspect(path)
        if checked['sha256']!=expected_sha256:raise ValueError('检查后的气象文件已改变，请重新检查再登记。')
        if not checked['can_register']:raise ValueError('逐时气象存在需修复项，不能登记为可选输入。')
        if not isinstance(metadata,dict) or metadata.get('reviewed') is not True:raise ValueError('请确认已核对地点与本次数据说明。')
        def text(key,maximum,required=False):
            value=metadata.get(key,'')
            if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):raise ValueError('请填写有效的 '+key+'。')
            return value.strip()
        h=checked['quality']['header'];name=text('name',100,True);note=text('note',1000)
        climate=text('climate',3);basis=text('climate_basis',500)
        if climate and (climate not in {r['climate'] for r in catalog['global_bundle']['classes']} or not basis):raise ValueError('指定气候类型时，请选择已有类型并填写分类依据；也可暂不分类。')
        parent=text('supersedes',120)
        if parent and not catalog['sites'].get(parent,{}).get('weather'):raise ValueError('要更新的原气象来源不存在。')
        if parent and catalog['sites'][parent]['weather']['sha256']==expected_sha256:raise ValueError('新旧气象内容完全相同，无需作为来源更新；如需独立登记，请选择新增地点。')
        spec=dict(sha256=expected_sha256,name=name,note=note,climate=climate or None,climate_basis=basis,supersedes=parent or None)
        mode = storage_mode(metadata)
        if mode == 'reference':
            dest = Path(checked['path'])
            spec.update(storage_mode=mode, reference_path=os.path.normcase(str(dest)))
        else:
            dest = owned(Path(root)/'data/weather-files'/expected_sha256/'weather.epw',root)
        ident='weather_'+digest(spec)[:32]
        registry=owned(Path(root)/'data/weather-registry'/(ident+'.json'),root)
        if registry.exists():
            result=next(r for r in listing(root) if r['id']==ident)
            if weather_quality.read_snapshot(dest,expected_sha256)[0]['status']!='matches':
                raise ValueError('已登记的气象文件缺失或发生变化，请在气象管理中核对。')
            return dict(registration=result,reused=True)
        if mode == 'copy' and not dest.exists():
            if shutil.disk_usage(root).free < len(raw)+50*1024*1024:raise ValueError('可用磁盘不足以保存气象副本和登记记录。')
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as stream:
                try:
                    stream.write(raw)
                except OSError:
                    stream.close()
                    dest.unlink(missing_ok=True)
                    raise
        if weather_quality.read_snapshot(dest,expected_sha256)[0]['status']!='matches':
            raise ValueError('气象文件与检查时的内容不一致，未登记。请核对读取位置。')
        weather=dict(path=str(dest),sha256=expected_sha256,expected_sha256=expected_sha256,bytes=len(raw),status='verified')
        site=dict(id=ident,name=name,climate=climate or None,country=h['country'],eligible=True,
            site_kind='导入气象站点',source_kind=KIND,latitude=float(h['latitude']),longitude=float(h['longitude']),timezone=float(h['timezone']),elevation=float(h['elevation']),
            source_file=dict(path=checked['path'],sha256=expected_sha256),
            weather=weather,review_note=note or '用户确认主要逐时检查说明；区域代表性及太阳时序未自动判定。',
            climate_basis=basis,classification_status='user_declared' if climate else 'unclassified',supersedes=parent or None)
        if mode == 'reference':
            site['storage_mode'] = mode
        row=dict(id=ident,created=now(),spec=spec,site=site,source_path=checked['path'],quality=checked['quality'])
        write_json(registry,dict(data=row,sha256=digest(row)),root)
        return dict(registration=row,reused=False)

def job(catalog,site_id,case):
    """Use a verified building scaffold; imported weather never inherits old results."""
    exact=catalog['global_bundle']['jobs'].get(site_id+'|'+case)
    if exact:return exact
    site=catalog['sites'][site_id]
    if site.get('source_kind')!=KIND or not site.get('eligible'):raise ValueError('地点没有可用的模型来源。')
    anchor=next((j['site_id'] for j in catalog['global_bundle']['jobs'].values() if j['case']==case),None)
    if anchor is None:raise ValueError('当前气象没有对应的建筑输入来源。')
    source=catalog['global_bundle']['jobs'][anchor+'|'+case]
    return {**source,'site_id':site_id,'weather':site['weather'],'weather_adaptation':dict(template_site=anchor,target_site=site_id)}

def apply_location(model,site,location):
    if any(k.startswith('Site:GroundTemperature') for k in model):raise ValueError('建筑含固定地温输入，需先适配地温，不能直接换气象。')
    if not model.get('Foundation:Kiva'):raise ValueError('换气象目前仅支持已核对的 Kiva 接地建筑。')
    if len(model.get('Site:Location',{}))!=1:raise ValueError('建筑地点输入不唯一。')
    before=copy.deepcopy(model['Site:Location'])
    # Keep the object name stable; only the four physical location fields change.
    key=next(iter(model['Site:Location']));model['Site:Location'][key]=dict(location)
    return dict(before=before,after=copy.deepcopy(model['Site:Location']),target_site=site['id'],
        ground='Kiva 使用所选全年气象；基础几何、土壤和原室内初始化参数保持，无固定月地温。',
        schedules='保留本方案作息及其起始星期，不按气象年份、地点或节假日自动改变。')
