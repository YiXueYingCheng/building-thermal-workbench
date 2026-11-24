"""Read-only source audit and explicit weather adoption preview."""
import copy
from pathlib import Path
from foundation import now,sha
from contracts import recipe_digest
import weather_import

def references(record,catalog):
    refs=[]
    def add(ref,role):
        if isinstance(ref,dict) and ref.get('path'):refs.append({**ref,'role':role})
    for r in record['provenance'].get('source_refs',[]):add(r,'建筑来源')
    adapter=record['provenance']['adapter'];sites=record['factors']['scope']['site_ids']
    if adapter=='ordinary_building_v1':
        s=catalog['ordinary_buildings'][record['factors']['building']['id']]
        for r in s['source_refs']:add(r,'建筑来源')
        for r in s['models'].values():add(r,'建筑模型')
        for r in s['dependencies']:add(r,'使用配置')
    elif adapter=='global_frozen_v011':
        case='FIXED_COOL_LOW7' if record['factors']['materials']['definitions'] else 'W00'
        for site in sites:
            j=weather_import.job(catalog,site,case);add(j['model'],'建筑模型')
            for r in j['dependencies']:add(r,'使用配置')
        from building_configuration import has_configuration
        if has_configuration(record):
            j=next(j for k,j in catalog['global_bundle']['jobs'].items() if k.endswith('|W00'))
            add(j['model'],'建筑配置基准')
            for r in j['dependencies']:add(r,'建筑配置基准')
    else:
        b=catalog.get('dynamic_registry',{}).get('records',{}).get(record['provenance'].get('origin_id',record['id']),{})
        add(b.get('weather'),'气象')
        for r in b.get('sources',[]):add(r,'日历来源')
        for info in b.get('modes',{}).values():
            add(info.get('model'),'建筑模型')
            for r in info.get('dependencies',[]):add(r,'使用配置')
    for ident in sites:add(catalog['sites'][ident].get('weather'),'气象')
    for path,h in record['numerics'].get('engine_files',{}).items():add(dict(path=path,sha256=h),'计算引擎')
    unique={}
    for r in refs:
        key=(str(Path(r['path']).resolve()),r.get('expected_sha256') or r.get('sha256'))
        if key not in unique:unique[key]=dict(path=key[0],expected_sha256=key[1],roles=[])
        if r['role'] not in unique[key]['roles']:unique[key]['roles'].append(r['role'])
    return list(unique.values())

def audit(record,catalog,root=None):
    rows=references(record,catalog)
    external=[]
    for ident in record['factors']['scope']['site_ids']:
        site=catalog['sites'][ident];ref=site.get('source_file')
        if ref and site.get('storage_mode') != 'reference':external.append(dict(path=ref['path'],expected_sha256=ref['sha256'],roles=['导入时原文件'],name=site['name']))
    from source_locations import resolve,listing,key
    for r in rows:
        actual,location=resolve(r,catalog)
        if location:r.update(actual_path=actual['path'],relocation=location)
    for r in rows+external:
        p=Path(r.get('actual_path',r['path']));r['actual_sha256']=None
        try:
            a=p.stat();r['actual_sha256']=sha(p);b=p.stat()
            r['status']='changed_during_read' if (a.st_size,a.st_mtime_ns)!=(b.st_size,b.st_mtime_ns) else 'matches' if r['actual_sha256']==r['expected_sha256'] else 'mismatch'
        except FileNotFoundError:r['status']='missing'
        except OSError:r['status']='unreadable'
    updates=[dict(old_id=i,new_id=s['id'],name=s['name']) for i in record['factors']['scope']['site_ids'] for s in catalog['sites'].values() if s.get('supersedes')==i]
    from source_recovery import history
    return dict(checked_at=now(),record=dict(id=record['id'],revision=record['revision']),files=rows,external_files=external,
        recoveries=history(root,{r['path'] for r in rows}) if root is not None else [],
        location_history=[r for r in listing(root) if r['key'] in {key(f) for f in rows}] if root is not None else [],
        passed=all(r['status']=='matches' for r in rows),updates=updates,
        note='核对当前读取位置的文件内容身份，原引用路径保留用于追溯。存在新登记气象时可预览选入；缺失引用可核对原副本后恢复；已有文件的内容变化需走来源更新，不自动重绑定。')

def preview(record,old_id,new_id,catalog):
    if old_id not in record['factors']['scope']['site_ids']:raise ValueError('原地点不在当前方案内。')
    site=catalog['sites'].get(new_id)
    if not site or not site.get('eligible') or not site.get('weather'):raise ValueError('请选择可用的新气象来源。')
    if new_id==old_id:raise ValueError('请选择不同的来源。')
    if new_id in record['factors']['scope']['site_ids']:raise ValueError('新地点已在当前范围内，替换会产生重复，请先整理选择。')
    if site.get('supersedes')!=old_id:raise ValueError('新气象没有声明为此来源的更新，请通过气象导入明确登记关系。')
    from weather_quality import read_snapshot
    from source_locations import resolve
    actual,_=resolve(site['weather'],catalog)
    identity,raw=read_snapshot(actual['path'],site['weather']['sha256'])
    if raw is None:raise ValueError('新气象文件未通过身份核对：'+identity['status'])
    if record['factors']['condition'].get('reference_runs') or any(c.get('mode')=='calendar' for c in record['factors']['condition'].get('controls',[])):
        raise ValueError('本方案绑定参考计算或光学切换日历，换气象前须重新建立对应参考，不能沿用旧日历。')
    out=copy.deepcopy(record);out['factors']['scope']['site_ids']=[new_id if i==old_id else i for i in out['factors']['scope']['site_ids']]
    from model_adapter import capability
    cap=capability(out,catalog)
    if not cap['supported']:raise ValueError('当前组合尚不能采用此来源：'+'；'.join(cap['reasons']))
    return dict(scope=out['factors']['scope'],before=catalog['sites'][old_id],after=site,
        recipe_before=recipe_digest(record),recipe_after=recipe_digest(out),generation=cap,
        note='只替换当前编辑中的这一地点。保存后形成新方案版本；原版本、已排队输入和完成结果继续绑定原气象，不批量传播。')
