"""Explicit, same-content locations for new reads; frozen execution stays strict."""
import copy
import os
from pathlib import Path
import re
import threading
import uuid
from foundation import digest, now, read_json, sha, write_json
from source_recovery import candidate_identity

LOCK = threading.Lock()


def key(ref):
    from inspection_io import resolve_path
    return digest(dict(path=resolve_path(ref['path']), sha256=ref.get('expected_sha256') or ref.get('sha256')))


def listing(root):
    rows = []
    identities = set()
    for p in (Path(root) / 'data/source-locations').glob('location_*.json'):
        box = read_json(p); row = box['data']
        if digest(row) != box['sha256'] or row['id'] != p.stem or key(row['target']) != row['key']:
            raise ValueError('来源位置登记校验不一致，请保留记录核查。')
        identity = (row['key'], row['revision'])
        if identity in identities:raise ValueError('来源位置版本重复，请核查登记。')
        identities.add(identity); rows.append(row)
    return sorted(rows, key=lambda r: (r['key'], r['revision']))


def latest(rows):
    result = {}
    for row in rows:
        if row['key'] not in result or row['revision'] > result[row['key']]['revision']:result[row['key']] = row
    return result


def attach(catalog, root):
    from history_locations import locations
    catalog.pop('_migrated_workspace',None)
    if locations(root):
        catalog['_migrated_workspace']=str(Path(root).resolve())
    catalog.pop('_import_copies', None)
    origins = locations(root).get('import_roots', {})
    if origins:
        base = Path(root)/'data/building-imports'
        copies = {}
        for origin, ident in origins.items():
            if not re.fullmatch(r'import_[a-zA-Z0-9_-]+', ident) or Path(origin).name != ident:
                raise ValueError('导入建筑位置登记无效。')
            copies[origin] = str(base/ident)
        catalog['_import_copies'] = copies
    catalog.pop('_source_locations', None)
    active = {k: r for k, r in latest(listing(root)).items() if r['action'] == 'register'}
    if active:catalog['_source_locations'] = active
    return catalog


def resolve(ref, catalog):
    from foundation import owned
    catalog = catalog or {}
    ident = key(ref)
    row = catalog.get('_source_locations', {}).get(ident)
    checksum = ref.get('expected_sha256') or ref.get('sha256')
    if not row:
        path = Path(ref['path'])
        for origin, local in catalog.get('_import_copies', {}).items():
            if path.is_relative_to(origin):
                copied = owned(Path(local)/path.relative_to(origin), local)
                row = dict(key=ident, kind='verified_import_copy', candidate=dict(path=str(copied), sha256=checksum))
                break
    migrated=catalog.get('_migrated_workspace')
    if migrated:
        from history_locations import locations, workspace_path, input_path
        actual = row['candidate']['path'] if row else ref['path']
        if row and row['candidate']['sha256'] != checksum:
            raise ValueError('来源位置与原内容身份不一致。')
        table = locations(migrated)
        original_key = ident if actual == ref['path'] else key(dict(path=actual,sha256=checksum))
        local = (input_path(migrated,actual,checksum) if original_key in table.get('reference_keys',{})
                 else workspace_path(migrated,actual))
        if local != Path(actual):
            row={**(row or dict(key=ident,kind='verified_workspace_copy')), 'candidate':dict(path=str(local),sha256=checksum)}
    if not row:return copy.deepcopy(ref), None
    if row['candidate']['sha256'] != checksum:raise ValueError('来源位置与原内容身份不一致。')
    return {**ref, 'path': row['candidate']['path'], 'sha256': checksum, 'expected_sha256': checksum}, row


def reference(record, catalog, target):
    from source_updates import references
    if not isinstance(target, str) or not Path(target).is_absolute():raise ValueError('请选择本方案已登记的来源引用。')
    path = str(Path(target).resolve())
    rows = [r for r in references(record, catalog) if r['path'] == path]
    hashes = {r['expected_sha256'] for r in rows}
    if not rows or len(hashes) != 1 or not re.fullmatch('[0-9a-f]{64}', next(iter(hashes)) or ''):
        raise ValueError('来源缺少唯一的原内容身份，不能重定位。')
    if any('计算引擎' in r['roles'] for r in rows):raise ValueError('计算引擎不通过来源位置登记迁移。')
    return rows[0]


def preview(root, record, catalog, target, candidate='', action='register'):
    if action not in ('register', 'revoke'):raise ValueError('来源位置操作无效。')
    ref = reference(record, catalog, target); current = latest(listing(root)).get(key(ref))
    revision = current['revision'] if current else 0
    original_status = 'missing'
    if os.path.lexists(ref['path']):
        try:
            p = Path(ref['path']); a = p.stat(); actual = sha(p); b = p.stat()
            original_status = 'matches' if actual == ref['expected_sha256'] and (a.st_size,a.st_mtime_ns,a.st_ino)==(b.st_size,b.st_mtime_ns,b.st_ino) else 'mismatch'
        except OSError:original_status = 'unreadable'
    source = None
    if action == 'register':
        if original_status in ('mismatch','unreadable'):raise ValueError('原路径已有内容变化或不可读文件，请先核对；不能用位置登记掩盖来源异常。')
        source = candidate_identity(candidate)
        if source['path'] == ref['path']:raise ValueError('新位置应与原引用路径不同。')
        if source['sha256'] != ref['expected_sha256']:raise ValueError('新位置文件与原引用内容不一致，不能重定位。')
        if current and current['action']=='register' and current['candidate']==source:raise ValueError('此位置已登记，无需重复采用。')
    elif not current or current['action'] != 'register':raise ValueError('当前没有可撤销的位置登记。')
    plan = dict(record_sha256=digest(record), record=dict(id=record['id'],revision=record['revision']),
                target=ref, key=key(ref), prior_revision=revision, candidate=source, action=action, original_status=original_status)
    return dict(**plan, plan_sha256=digest(plan), checked_at=now(), current={k:current[k] for k in ('id','revision','action','candidate')} if current else None,
                note='登记适用于本工作区引用同一路径和内容身份的来源，供后续读取及生成输入使用。旧方案不改写，已有输入包和计算批次仍固定原路径；需要重新生成并核对计算清单。' if action=='register' else
                '撤销后，后续读取及生成输入恢复使用原路径；原路径缺失时将无法读取。已生成输入仍固定生成时的路径，副本文件不删除。')


def commit(root, record, catalog, target, candidate, action, expected_plan):
    if (Path(root)/'.recovery-copy.json').exists():raise ValueError('隔离恢复工作区仅供核对，不登记来源位置。')
    with LOCK:
        plan = preview(root,record,catalog,target,candidate,action)
        if plan['plan_sha256'] != expected_plan:raise ValueError('来源、方案或登记版本已变化，请重新预览。')
        row = dict(id='location_'+uuid.uuid4().hex,key=plan['key'],revision=plan['prior_revision']+1,
                   created=now(),action=action,target=plan['target'],candidate=plan['candidate'],plan=plan)
        write_json(Path(root)/'data/source-locations'/(row['id']+'.json'),dict(data=row,sha256=digest(row)),root)
        return row


def prepare_case(model, report, reader):
    """Only filenames change here, after the physical adapters have checked their changes."""
    before = copy.deepcopy(model); rewrites = []
    refs = {str(Path(d['path']).resolve()):d for d in report.get('dependencies',[])}
    for name, schedule in model.get('Schedule:File',{}).items():
        original = str(Path(schedule['file_name']).resolve()); ref = refs.get(original)
        if ref is None:raise ValueError('重定位时发现未登记作息引用：'+original)
        actual = str(reader.check(ref))
        if actual != str(Path(ref['path'])):
            schedule['file_name'] = actual
            rewrites.append(dict(path=['Schedule:File',name,'file_name'],before=before['Schedule:File'][name]['file_name'],after=actual))
    weather, location = resolve(report['weather'], reader.catalog)
    if location:
        reader.check(report['weather']); report['weather_origin'] = copy.deepcopy(report['weather']); report['weather'] = weather
    if rewrites:
        from model_adapter import changes
        if changes(before,model) != rewrites:
            # Dict iteration differs from the canonical difference order, so compare by digest sets.
            if {digest(x) for x in changes(before,model)} != {digest(x) for x in rewrites}:raise ValueError('位置改写超出文件名字段。')
        report['differences'] = report.get('differences',[]) + rewrites
        report['generated_model_digest'] = digest(model);report['exact_input_match'] = False
    if rewrites or location:report['source_location_changes'] = dict(schedule_files=rewrites, weather=location)
    return model, report
