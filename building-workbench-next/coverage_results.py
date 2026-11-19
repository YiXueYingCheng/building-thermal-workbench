"""Read pinned local observations and describe coverage changes in matched load results."""
from pathlib import Path
import re

from foundation import digest, read_json
from drawing_wall_scope import available, rows


def registry(root):
    path = Path(root) / 'data/coverage-results/index.json'
    return read_json(path) if path.is_file() else {'sources': {}, 'comparisons': []}


def sources(record, root):
    return registry(root)['sources'].get(digest(record), [])


def observed(record, ident, root):
    if not re.fullmatch(r'observed_[a-f0-9]{64}', ident):
        raise ValueError('实算快照标识无效。')
    data = read_json(Path(root) / 'data/coverage-results' / (ident + '.json'))
    if digest(data) != ident.removeprefix('observed_') or data['record_sha256'] != digest(record):
        raise ValueError('实算快照或绑定的方案版本已变化。')
    return dict(data, id=ident)


def switches(left, right):
    if not left or not right or left['minutes'] != right['minutes'] or left['step'] != right['step']:
        return None
    a, b = (dict(row['events']) for row in (left, right))
    last = 0
    different = same = 0
    lstate, rstate = left['initial'], right['initial']
    unmatched = []
    for minute in sorted(a.keys() | b.keys()):
        if lstate != rstate:
            different += minute - last
        if minute in a and minute in b and a[minute] == b[minute]:
            same += 1
        else:
            unmatched.append(dict(minute=minute, left=a.get(minute), right=b.get(minute)))
        last = minute
        lstate, rstate = a.get(minute, lstate), b.get(minute, rstate)
    if lstate != rstate:
        different += left['minutes'] - last
    return dict(left=len(a), right=len(b), coincident=same, different_minutes=different,
                step=left['step'], unmatched=unmatched)


def layout(record):
    f = record['factors']
    application = f['materials']['applications'][0]
    covered = set(application['target_ids'])
    controls = f['condition']['controls']
    feedback = {w for c in controls if c['mode'] == 'feedback' for w in c['target_ids']}
    by_wall = {w: {c['channel']: {k:v for k,v in c.items() if k != 'target_ids'}
                   for c in controls if w in c['target_ids']} for w in covered}
    return covered, feedback, by_wall


def annotate(result, records, sources_used, catalog):
    a, b = records
    if (result['metric'] == 'temperature' or
            not all(r.get('provenance',{}).get('adapter') in ('global_frozen_v011','ordinary_building_v1') and available(r) for r in records)):
        return
    left, lf, lc = layout(a)
    right, rf, rc = layout(b)
    if left == right or a['factors']['building'] != b['factors']['building']:
        return
    if not any(site['status'] == 'paired' for site in result['sites']):
        return
    # Ground the area's denominator in the saved model. Older sources may only retain the catalog.
    scopes = result.get('wall_scopes', {})
    walls = next((s['rows'] for pair in scopes.values() for s in pair.values() if s.get('rows')), None)
    if not walls:
        try:
            walls = rows(a, catalog)
        except (OSError, ValueError, KeyError):
            return
    if not (left | right) <= {wall['id'] for wall in walls}:
        return
    added = [w for w in walls if w['id'] in right-left]
    removed = [w for w in walls if w['id'] in left-right]
    shared = left & right
    def common_inputs(record):
        f = record['factors']
        m = f['materials']
        app = m['applications'][0]
        return (record['provenance']['adapter'],record['provenance'].get('snapshot_id'),
                {k:v for k,v in m.items() if k != 'applications'}, {k:v for k,v in app.items() if k != 'target_ids'},
                {k:v for k,v in f['condition'].items() if k not in ('controls','reference_runs')},
                record['numerics'])
    same_inputs = common_inputs(a) == common_inputs(b)
    def calendars(record):
        refs = record['factors']['condition']['reference_runs']
        return {s['site_id']:s['calendar'] for ref in refs for s in ref.get('snapshot',{}).get('content',{}).get('sites',[])}
    calendars_a, calendars_b = map(calendars, records)
    scope = dict(left_count=len(left), right_count=len(right),added=added,removed=removed,
                 added_m2=round(sum(w['net_m2'] for w in added),6),
                 removed_m2=round(sum(w['net_m2'] for w in removed),6),
                 feedback_same=lf==rf, left_feedback=len(lf), right_feedback=len(rf),
                 common_controls_same=all(lc[w]==rc[w] for w in shared))
    result['wall_coverage'] = scope
    for site in result['sites']:
        if site['status'] != 'paired':
            continue
        sid = site['site_id']
        calendar_used = any(c['mode']=='calendar' for r in records for c in r['factors']['condition']['controls'])
        same = bool(calendars_a.get(sid)) and calendars_a.get(sid)==calendars_b.get(sid) if calendar_used else None
        site['coverage_calendar_same'] = same
        if (result['annual'] and added and not removed and scope['added_m2'] > 0 and
                same_inputs and same is not False and scope['feedback_same'] and scope['common_controls_same'] and
                site['pairing_basis']=='严格配对'):
            site['savings_per_added_m2'] = {m:site[m+'_saved_kWh']/scope['added_m2'] for m in ('heating','cooling','total')}
        site['feedback_timing'] = switches(*(s['cases'][sid].get('feedback_trace') for s in sources_used))
