"""Derive a fixed-face feedback experiment and a pinned comparison atomically."""
import copy

from contracts import record_digest
from foundation import canonical, digest, loads, now
from inspection_io import reading
from model_adapter import capability
from research_sets import compatible, recipe, ref, require
from solid_eca import enabled


def propose(sets, group, records):
    fixed = records['fixed']
    donor = records.get('feedback')
    require(donor and enabled(fixed) and enabled(donor), '需要包含实体 ECA 热阻反馈成员的四工况对比集。')
    audit = compatible(records)
    require(audit['consistent'], '；'.join(audit['issues']))
    condition = fixed['factors']['condition']
    require(condition['operation']['mode'] == 'controlled', '本实验需要温控冷热需求工况。')
    controls = {c['channel']: c for c in condition['controls']}
    thermal, orientation = controls['thermal'], controls['orientation']
    require(thermal['state_id'] == 'R' and orientation['face_id'] == 'A' and not condition['reference_runs'],
            '参照须为固定蓬松态、固定 A。')
    feedback, = [c for c in donor['factors']['condition']['controls'] if c['channel'] == 'thermal']
    require(feedback['mode'] == 'feedback' and thermal['application_id'] == feedback['application_id']
            and set(thermal['target_ids']) == set(feedback['target_ids']), '反馈材料或作用墙面与参照不一致。')
    factors = copy.deepcopy(fixed['factors'])
    index = condition['controls'].index(thermal)
    factors['condition']['controls'][index] = copy.deepcopy(feedback)
    name = group['name'][:75] + ' · 固定 A＋热阻调节'
    target = sets.store.update_payload(fixed, dict(name=name, factors=factors))
    restored = copy.deepcopy(target)
    restored['factors']['condition']['controls'][index] = thermal
    require(recipe(restored) == recipe(fixed) and recipe(target) != recipe(fixed), '无法将输入差异限定为热阻控制。')
    supported = capability(target, sets.catalog)
    require(supported['supported'], '；'.join(supported.get('reasons', [])) or '当前模型尚未接通此工况。')
    return target, feedback


def reference_results(sets, group, fixed, sites):
    # Keep a single pinned reference version for the standard two-plan comparison.
    rows = sets._results(group['id'], group['revision'], only_roles={'fixed'})['members']['fixed']
    coverage = {}
    owners = {}
    for batch in rows:
        if not batch['usable']:
            continue
        source = batch['source']
        key = (source['id'], source['revision'])
        owners[key] = dict(id=key[0], revision=key[1])
        coverage.setdefault(key, set()).update(r['site_id'] for r in batch['results']
            if r['accepted'] and r['mode'] == 'controlled' and r['site_id'] in sites)
    own = (fixed['id'], fixed['revision'])
    if not coverage:
        return dict(id=own[0], revision=own[1]), set(), [b['reason'] for b in rows if b.get('reason')]
    key = max(coverage, key=lambda k: (len(coverage[k]), k == own, k))
    return owners[key], coverage[key], [b['reason'] for b in rows if b.get('reason')]


def handle(sets, ident, action, body):
    require(type(body.get('revision')) is int, '请选择明确的对比集版本。')
    group = sets.get(ident, body['revision'])
    require(group['sha256'] == body.get('set_sha256'), '对比集版本已变化，请重新打开实验。')
    identity = digest(['fixed-face-feedback-v1', group['sha256']])[:32]
    target_id = 'draft_' + identity
    pair_id = 'comparison_' + identity
    with sets.store.connect() as db:
        row = db.execute('SELECT payload FROM comparisons WHERE id=?', (pair_id,)).fetchone()
    if row:
        return dict(saved=True, comparison=loads(row[0]), target_id=target_id)
    with reading():
        records = sets.records(group)
        fixed = records['fixed']
        target, control = propose(sets, group, records)
        sites = fixed['factors']['scope']['site_ids']
        left, accepted, reasons = reference_results(sets, group, fixed, sites)
    planned = [dict(id=s, name=sets.catalog['sites'][s]['name'], reference_available=s in accepted)
               for s in sites]
    p = dict(saved=False, group_revision=group['revision'], name=target['name'], left=left,
             fixed_revision=fixed['revision'], donor_revision=records['feedback']['revision'],
             target_sha256=recipe(target), source_sha256=group['sha256'], policy=control['policy'],
             update_minutes=control['update']['minutes'], walls=len(control['target_ids']),
             step_minutes=fixed['numerics']['step_minutes'], sites=planned, reasons=reasons)
    token = digest(p)
    if action == 'preview':
        return dict(**p, preview_sha256=token)
    require(action == 'save' and token == body.get('preview_sha256'), '来源或可用结果已变化，请重新预览。')
    at = now()
    target.update(id=target_id, revision=1, status='draft', archived=False, saved_at=at)
    target['provenance'].update(origin_id=fixed['provenance'].get('origin_id', fixed['id']),
                                parent_id=fixed['id'], parent_revision=fixed['revision'])
    target['record_sha256'] = record_digest(target)
    pair = dict(id=pair_id, name=group['name'][:70]+' · 固定 A 时的热阻调节贡献',
                left=left, right=dict(id=target_id,revision=1), metric='total', created=at,
                experiment=dict(source_set=ident, revision=group['revision'], sha256=group['sha256'],
                                fixed=ref(fixed), feedback=ref(records['feedback']), recipe=p['target_sha256']))
    with sets.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT payload FROM comparisons WHERE id=?', (pair_id,)).fetchone()
        if existing:
            return dict(saved=True, comparison=loads(existing[0]), target_id=target_id)
        pinned = sets.get(ident, group['revision'], db)
        require(pinned['sha256'] == group['sha256'], '对比集来源已变化。')
        sets.records(pinned)
        require(recipe(sets.store.get(left['id'], left['revision'])) == recipe(fixed), '参照输入已变化。')
        db.execute('INSERT INTO versions VALUES (?,?,?,?)', (target_id,1,canonical(target),at))
        db.execute('INSERT INTO events(at,action,record_id,revision) VALUES (?,?,?,?)', (at,'create',target_id,1))
        db.execute('INSERT INTO comparisons VALUES (?,?,?)', (pair_id,canonical(pair),at))
        sets.store._pin_members(db,pair)
    return dict(saved=True, comparison=pair, target_id=target_id)
