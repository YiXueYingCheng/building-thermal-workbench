"""Register the authorized Drawing26 scaffold using the existing fixed-state adapter."""
import copy
from pathlib import Path
import shutil
from foundation import ROOT, read_json, write_json, sha, digest, now, owned
from workspace_setup import setup_lock, initialize, registration, register_engine

REGISTRY = 'data/examples/drawing26.json'

def merge(catalog, root):
    path=Path(root)/REGISTRY
    if not path.exists():
        return catalog
    saved=read_json(path);data=saved['data']
    if saved['sha256']!=digest(data) or data['kind']!='drawing26_public_example_v1':
        raise ValueError('Drawing26 示例登记校验失败。')
    if catalog.get('catalog_kind')!='standalone_v1' or set(catalog['records'])&set(data['records']):
        raise ValueError('示例与已有来源冲突，未覆盖。')
    if catalog['global_bundle'].get('jobs'):
        raise ValueError('已有模型模板，未覆盖。')
    catalog['records'].update(copy.deepcopy(data['records']))
    catalog['global_bundle']=copy.deepcopy(data['global_bundle'])
    catalog['example_bundle']=copy.deepcopy(data)
    return catalog

def ref(path):
    return dict(path=str(path.resolve()),sha256=sha(path),bytes=path.stat().st_size,status='verified')

def register(root=ROOT,weather_path=None,engine_path=None):
    from manage import current
    from contracts import validate
    from weather_import import inspect,register as register_weather
    root=Path(root).resolve();initialize(root)
    checked,_=inspect(str(Path(weather_path).resolve()))
    expected=read_json(Path(__file__).resolve().parents[1]/'examples/weather/sources.json')
    weather_spec=next(r for r in expected['weather'] if r['id']=='china34_430000')
    if checked['sha256']!=weather_spec['epw_sha256']:
        raise ValueError('该示例要求来源清单中的长沙 EPW；其他地点可在登记后另存方案配置。')
    existing=root/REGISTRY
    if existing.exists():
        catalog=current(root)
        data=catalog['example_bundle']
        if data['weather_sha256']!=checked['sha256']:
            raise ValueError('已登记示例的气象不同，未覆盖。')
        from verification import verify_catalog
        result=verify_catalog(catalog)
        if not result['passed']:raise ValueError('已有示例来源校验未通过。')
        return dict(reused=True,site_id=data['site_id'],records=list(data['records']))
    if engine_path:
        register_engine(root,engine_path)
    engine=registration(root)
    if not engine:raise ValueError('请先登记计算引擎，或使用 --engine 指定安装位置。')
    catalog=current(root)
    if catalog.get('catalog_kind')!='standalone_v1' or any(k in catalog['records'] for k in ('global_w00','global_fixed')):
        raise ValueError('请在独立新工作区登记示例，不覆盖已有旧平台来源。')
    package=Path(__file__).resolve().parents[1]/'examples/drawing26/template'
    manifest=read_json(package/'manifest.json');fingerprint=digest(manifest)
    source_db=package.parent/'Drawing26.accdb'
    if sha(source_db)!=manifest['authorized_building_sha256']:
        raise ValueError('示例数据库与登记来源不一致。')
    for name,checksum in manifest['files'].items():
        path=owned(package/name,package)
        if sha(path)!=checksum:raise ValueError('示例模板文件已变化：'+name)
    weather=register_weather(root,checked['path'],checked['sha256'],dict(name='长沙 · 公开示例',reviewed=True,
        note='CSWD 典型年；分钟字段 0 按原兼容解释保留；来源 '+weather_spec['source_url']),catalog)
    site=weather['registration']['site'];site_id=site['id']
    with setup_lock(root):
        if existing.exists():raise ValueError('另一个示例登记已完成，请重新运行以读取结果。')
        frozen=owned(root/'data/examples'/('drawing26_'+fingerprint[:16]),root)
        source_refs=[ref(source_db)]
        for name,checksum in manifest['files'].items():
            dest=owned(frozen/'template'/name,frozen)
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():shutil.copy2(package/name,dest)
            if sha(dest)!=checksum:raise ValueError('已有示例副本内容不同，已保留。')
            source_refs.append(ref(dest))
        records=read_json(frozen/'template'/manifest['records']);jobs={}
        for case,name in manifest['models'].items():
            model=read_json(frozen/'template'/name);dependencies={}
            for schedule in model.get('Schedule:File',{}).values():
                relative=schedule['file_name']
                if relative not in manifest['files']:raise ValueError('作息不在示例来源清单中。')
                dest=owned(frozen/'template'/relative,frozen)
                schedule['file_name']=str(dest);dependencies[str(dest)]=ref(dest)
            model_path=frozen/'models'/name
            if model_path.exists() and read_json(model_path)!=model:raise ValueError('已有示例模型不同，已保留。')
            write_json(model_path,model,root)
            jobs[site_id+'|'+case]=dict(id='example_'+case,site_id=site_id,case=case,model=ref(model_path),
                weather=site['weather'],dependencies=list(dependencies.values()),review_status='template_only',
                weather_adaptation=dict(template_site='verified_Drawing26_scaffold',target_site=site_id))
        for record in records.values():
            record['factors']['building']['model_snapshot']=copy.deepcopy(jobs[site_id+'|W00']['model'])
            record['factors']['scope']['site_ids']=[site_id]
            record['numerics'].update(engine=Path(engine['executable']).name,engine_files=copy.deepcopy(engine['engine_files']))
            record['provenance'].update(snapshot_id='drawing26_example_'+fingerprint[:16],source_refs=source_refs,
                catalog_sha256=fingerprint,source_path=str(frozen),imported_recipe_sha256='')
            from contracts import recipe_digest
            record['provenance']['imported_recipe_sha256']=recipe_digest(record)
            record['revision']='source_'+digest(record)[:16]
            errors=validate(record,{site_id:site})
            if errors:raise ValueError('；'.join(errors))
        bundle=dict(jobs=jobs,classes=[],summary=dict(accepted_cases=0,accepted_sites=0),historical=None,
            protocol=manifest['protocol'],source_refs=source_refs,catalog_sha256=fingerprint,
            source=ref(frozen/'template'/manifest['records']))
        data=dict(kind=manifest['id'],created=now(),site_id=site_id,weather_sha256=checked['sha256'],records=records,global_bundle=bundle)
        write_json(existing,dict(data=data,sha256=digest(data)),root)
    return dict(reused=False,site_id=site_id,records=list(records))

def create_comparison(root=ROOT):
    root=Path(root).resolve()
    with setup_lock(root):
        return _create_comparison(root)

def _create_comparison(root):
    from manage import current
    from record_store import Store
    root=Path(root).resolve();catalog=current(root);store=Store(catalog,root)
    receipt=root/'data/examples/fixed-comparison.json'
    if receipt.exists():
        saved=read_json(receipt)
        for row in saved['records'].values():store.get(row['id'],row['revision'])
        return {**saved,'reused':True}
    base=store.get('global_fixed');rows={}
    for state,label in [('R','蓬松'),('C','压缩')]:
        factors=copy.deepcopy(base['factors'])
        factors['condition']['controls'][0]['state_id']=state
        row=store.create(base['id'],base['revision'],dict(name='Drawing26 示例 · '+label+' · 长沙两日',factors=factors))
        rows[state]=dict(id=row['id'],revision=row['revision'])
    comparison=store.add_comparison('Drawing26 · ECA 两态热阻对照',rows['R'],rows['C'],'total')
    saved=dict(records=rows,comparison_id=comparison['id'],period=[1,1,1,2],step_minutes=5,mode='controlled',
        compared_walls=7,other_walls='7 walls remain R',orientation='A',new_simulations=0)
    write_json(receipt,saved,root)
    return {**saved,'reused':False}
