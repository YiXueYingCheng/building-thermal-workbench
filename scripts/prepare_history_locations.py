"""Pack verified frozen references before detaching a copied workspace.

python scripts/prepare_history_locations.py --source <original app> --target <copied app> [--weather-library <EPW directory>]
The target must already contain the corresponding catalog, frozen plans and runs.
"""
import argparse
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'building-workbench-next'))
from foundation import digest, owned, read_json, sha, write_json
from history_locations import input_path, locations
from workspace_setup import setup_lock
from source_locations import key, latest, listing


def verified_import_roots(target):
    """An import keeps its original identity even when its model directory moves."""
    roots = {}
    overrides = latest(listing(target))
    for descriptor in sorted((target/'data/imported-buildings').glob('import_*.json')):
        box = read_json(descriptor)
        if box['sha256'] != digest(box['data']):
            raise ValueError('导入建筑登记校验失败：'+descriptor.name)
        for building in box['data'].values():
            model = Path(building['models']['controlled']['path'])
            origin = next((p for p in model.parents if p.name == descriptor.stem
                           and p.parent.name == 'building-imports' and p.parent.parent.name == 'data'), None)
            if not origin:
                continue
            local = owned(target/'data/building-imports'/descriptor.stem, target)
            if origin == local:
                continue
            refs = [*building['models'].values(), *building['dependencies'], *building['source_refs'],
                    building['building']['model_snapshot'], building['building']['input_snapshot'], building['weather']]
            for ref in refs:
                path = Path(ref['path'])
                if not path.is_relative_to(origin):
                    continue
                copy = owned(local/path.relative_to(origin), local)
                if not copy.is_file():
                    override = overrides.get(key(ref))
                    if override and override['action'] == 'register':
                        copy = Path(override['candidate']['path'])
                if sha(copy) != (ref.get('expected_sha256') or ref['sha256']):
                    raise ValueError('导入资料与原登记不一致：'+str(copy))
            roots[str(origin)] = descriptor.stem
    return roots


def references(source):
    pointer=read_json(source/'data/current.json')
    catalog=read_json(owned(source/pointer['catalog'],source))
    if digest(catalog)!=pointer['sha256']:raise ValueError('目录校验失败。')
    group=catalog.get('global_bundle',{})
    if group.get('historical'):
        yield group['historical']['source']
        for job in group['jobs'].values():
            yield from (job['model'],job['weather'],job['result'],*job['dependencies'])
    db_path=source/'data/execution/queue.sqlite'
    if db_path.is_file():
        from contextlib import closing
        with closing(sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)) as db:
            for raw,checksum in db.execute('select plan,checksum from batches'):
                plan=json.loads(raw)
                folder=owned(source/'data/execution/reviews'/plan['id'],source)
                if sha(folder/'plan.json')!=checksum or read_json(folder/'plan.json')!=plan:raise ValueError('批次输入校验失败。')
                for case in plan['cases']:
                    for path,h in case['dependencies'].items():
                        yield dict(path=path,sha256=h)


def prepare(source,target,weather_library=None):
    source,target=Path(source).resolve(strict=True),Path(target).resolve(strict=True)
    if not (target/'data/current.json').is_file():raise ValueError('请先复制工作区目录和计算记录。')
    base=owned(target/'data/history-locations',target)
    with setup_lock(target):
        previous=locations(target); inputs=dict(previous.get('inputs',{}))
        origins=list(dict.fromkeys([*previous.get('origins',[]),*locations(source).get('origins',[]),str(source)]))
        refs={(r['path'],r.get('expected_sha256') or r['sha256']) for r in references(source)}
        for name,h in sorted(refs):
            import re
            if not re.fullmatch('[a-f0-9]{64}',h):raise ValueError('来源哈希无效。')
            original=Path(name)
            if original.is_relative_to(source):
                relative=original.relative_to(source)
                copy=owned(target/relative,target)
                if not copy.is_file() or sha(copy)!=h:raise ValueError('工作区副本缺失或内容不同：'+str(relative))
                continue
            if h in inputs:
                entry=inputs[h];file=Path(entry['path']) if entry['kind']=='shared_epw' else owned(target/entry['path'],base)
                if sha(file)!=h:raise ValueError('历史资料包内容已变化：'+str(file))
                continue
            src=input_path(source,original,h)
            if weather_library and original.suffix.lower()=='.epw':
                epw=Path(weather_library).resolve()/'research'/h[:2]/(h+'.epw')
                if epw.is_file() and sha(epw)==h:
                    inputs[h]=dict(kind='shared_epw',path=str(epw));continue
            dest=owned(base/'files'/h[:2]/(h+original.suffix),base)
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():
                with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
                    temp=Path(f.name)
                try:
                    shutil.copyfile(src,temp)
                    if sha(temp)!=h:raise ValueError('来源内容与登记不一致：'+str(src))
                    os.replace(temp,dest)
                finally:temp.unlink(missing_ok=True)
            if sha(dest)!=h:raise ValueError('历史资料包校验失败：'+str(dest))
            inputs[h]=dict(kind='local',path=str(dest.relative_to(target)))
        data=dict(schema=1,origins=origins,inputs=inputs,import_roots=verified_import_roots(target))
        write_json(base/'index.json',dict(data=data,sha256=digest(data)),target)
        return dict(origins=origins,references=len(refs),files=len(inputs),shared_weather=sum(r['kind']=='shared_epw' for r in inputs.values()))


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source',type=Path,required=True);cli.add_argument('--target',type=Path,required=True)
    cli.add_argument('--weather-library',type=Path)
    args=cli.parse_args()
    print(json.dumps(prepare(args.source,args.target,args.weather_library),ensure_ascii=False))
