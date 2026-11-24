"""Maintenance commands for the isolated transition workspace."""
import argparse
from pathlib import Path
import uuid
from foundation import ROOT, config, read_json, write_json, now, digest

def current(root=ROOT):
    root=Path(root)
    pointer=read_json(root/'data/current.json')
    path=(root/pointer['catalog']).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('目录引用超出本工作区。')
    value=read_json(path)
    if digest(value)!=pointer['sha256']:raise ValueError('新工作区目录校验不一致。')
    extra=root/'data/dynamic-sources.json'
    if extra.exists():
        supplemental=read_json(extra)
        if digest(supplemental['data'])!=supplemental['sha256']:raise ValueError('动态来源登记校验不一致。')
        value['dynamic_registry']=supplemental['data']
    for extra in [root/'data/ordinary-buildings.json',*sorted((root/'data/imported-buildings').glob('import_*.json'))]:
      if extra.exists():
        supplemental=read_json(extra)
        if digest(supplemental['data'])!=supplemental['sha256']:raise ValueError('普通建筑来源登记校验不一致。')
        if set(value.get('ordinary_buildings',{}))&set(supplemental['data']):raise ValueError('普通建筑编号重复。')
        value.setdefault('ordinary_buildings',{}).update(supplemental['data'])
        for source in supplemental['data'].values():
            r=source['record'];site=source['site']
            if r['id'] in value['records'] or site['id'] in value['sites']:raise ValueError('新建筑来源编号与已有目录冲突。')
            value['records'][r['id']]=r;value['sites'][site['id']]=site
    from workspace_setup import registration
    from example_setup import merge as merge_example
    value=merge_example(value,root)
    bundle=value.get('global_bundle',{})
    if bundle.get('jobs') and 'building_source' not in bundle:
        # Old catalogues kept these import-time fields in the reference recipe.
        # Isolate the building metadata before any editable records are loaded.
        frozen=root/'data/frozen-building-source.json'
        if frozen.is_file():
            descriptor=read_json(frozen)
            if descriptor['catalog_sha256']!=bundle['catalog_sha256'] or digest(descriptor['content'])!=descriptor['sha256']:
                raise ValueError('冻结建筑来源与当前导入目录不一致。')
            bundle['building_source']=descriptor['content']
        elif 'global_w00' in value['records']:
            from legacy_import import building_descriptor
            bundle['building_source']=building_descriptor(value['records']['global_w00'])
        else:
            raise ValueError('冻结建筑来源描述缺失，请从该建筑的已校验导入资料恢复。')
    from example_controls import merge as merge_controls
    value=merge_controls(value,root)
    runtime=registration(root)
    if runtime:value['workspace_runtime']=runtime
    from weather_import import merge
    from source_locations import attach
    return attach(merge(value,root),root)

def persist_building_source(root, catalog):
    bundle = catalog.get('global_bundle') or {}
    frozen = Path(root)/'data/frozen-building-source.json'
    if bundle.get('jobs') and not frozen.exists():
        content = bundle['building_source']
        write_json(frozen, dict(catalog_sha256=bundle['catalog_sha256'], content=content, sha256=digest(content)), root)

def import_sources(root=ROOT):
    from legacy_import import Importer
    root=Path(root)
    if (root/'data/current.json').exists():
        raise ValueError('已有来源快照。当前阶段不覆盖导入，请使用 verify 核对；多来源版本迁移将在后续开放。')
    reader=Importer(config(root));catalog=reader.run()
    protection=reader.sources.check_unchanged()
    if not protection['passed']:raise ValueError('读取过程中来源发生变化，请重新核对。')
    ident=now().replace(':','').replace('+','_')+'_'+uuid.uuid4().hex[:8]
    path=root/'data/imports'/ident/'catalog.json'
    write_json(path,catalog,root)
    write_json(path.parent/'protection.json',protection,root)
    write_json(root/'data/current.json',dict(catalog=str(path.relative_to(root)),sha256=digest(catalog)),root)
    summary=dict(created=catalog['created'],records=len(catalog['records']),active=sum(not x['archived'] for x in catalog['records'].values()),
        legacy_roundtrips=len(catalog['roundtrips']),issues=catalog['issues'],protected_sources=protection['checked'],
        global_cases=len(catalog['global_bundle']['jobs']),historical_sites=catalog['global_bundle']['summary']['accepted_sites'])
    write_json(root/'verification/import-summary.json',summary,root)
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['import','verify']);args=parser.parse_args()
    if args.command=='import':result=import_sources()
    else:
        from verification import verify_catalog
        result=verify_catalog(current())
        write_json(ROOT/'verification/acceptance.json',result)
    import json
    print(json.dumps(result,ensure_ascii=False,indent=2))
