"""Read-only discovery of pinned results; never pair, accept, or total observations."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from foundation import ROOT, digest, loads, now, owned, read_json, sha
from presentation import STATUSES, batch_status


def material_labels(record):
    f=record['factors'];m=f.get('materials',{});apps=m.get('applications',[])
    if not apps:return ['未加研究材料层']
    definitions={d['id']:d for d in m.get('definitions',[])};labels=[]
    for app in apps:
        d=definitions.get(app['material_id'],{});states={s['id']:s.get('name',s['id']) for s in d.get('states',[])}
        parts=[d.get('name',app['material_id']),{'exterior':'外侧','interior':'内侧','between':'层间'}.get(app.get('position'),app.get('position','位置见配置'))]
        for control in f['condition'].get('controls',[]):
            if control.get('application_id')!=app['id']:continue
            mode=control.get('mode');channel=control.get('channel')
            if channel=='thermal':label='固定'+states.get(control.get('state_id'),control.get('state_id','')) if mode=='fixed' else {'feedback':'热学反馈调节','calendar':'热学按日历'}.get(mode,'热学设置见配置')
            elif channel=='orientation':label='固定 '+str(control.get('face_id','')) if mode=='fixed' else {'calendar':'按日历切换表面光学参数','feedback':'光学参数按反馈切换'}.get(mode,'光学选择见工况')
            else:continue
            parts.append(label+(f" × {len(control['target_ids'])}" if 'target_ids' in control else ''))
        labels.append(' · '.join(parts))
    return labels


def record_label(record, catalog):
    from research_input_notes import describe
    f = record['factors']
    return dict(id=record['id'], revision=record['revision'], name=record['name'],
                building_id=f['building']['id'], building=f['building']['name'], research_input_note=describe(record,catalog),
                period=f['scope']['period'], step_minutes=record['numerics']['step_minutes'],material_summary=material_labels(record),
                site_count=len(f['scope']['site_ids']), site_names=[catalog.get('sites', {}).get(k, {}).get('name', k) for k in f['scope']['site_ids']], mode=f['condition']['operation']['mode'])


def build(catalog, store, root=ROOT):
    root = Path(root).resolve()
    batches, comparisons, issues, versions = [], [], [], {}
    fingerprints, labels = {}, {}

    def saved(ident, revision):
        key = (ident, revision)
        if key not in versions:
            versions[key] = store.get(ident, revision)
        return versions[key]

    def fingerprint(record):
        key = (record['id'], record['revision'])
        if key not in fingerprints: fingerprints[key] = digest(record)
        return fingerprints[key]

    def label(record):
        key = (record['id'], record['revision'])
        if key not in labels: labels[key] = record_label(record, catalog)
        return labels[key]

    rows, counts, adopted_steps = [], {}, {}
    queue = root / 'data/execution/queue.sqlite'
    if queue.exists():
        with closing(sqlite3.connect(queue.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            rows = [dict(r) for r in db.execute('SELECT id,review,plan,checksum,mode,created FROM batches ORDER BY created DESC,rowid DESC')]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='site_recalculations'").fetchone():
                for link in db.execute('SELECT parent,idx,step FROM site_recalculations WHERE adopted IS NOT NULL'):
                    adopted_steps.setdefault(link['parent'],{})[link['idx']]=link['step']
            for row in db.execute('SELECT batch,status,COUNT(*) n FROM jobs GROUP BY batch,status'):
                counts.setdefault(row['batch'], {})[row['status']] = row['n']
    for b in rows:
        try:
            if not re.fullmatch(r'batch_[a-f0-9]{32}', b['id']):
                raise ValueError('批次编号无效')
            p = loads(b['plan'])
            if not re.fullmatch(r'review_[a-f0-9]{32}', b['review']) or p['id'] != b['review']:
                raise ValueError('清单编号不一致')
            folder = owned(root / 'data/execution/reviews' / b['review'], root / 'data/execution/reviews')
            r = saved(p['record_id'], p['revision'])
            if p['record_sha256'] != fingerprint(r) or read_json(folder / 'record.json') != r:
                raise ValueError('批次与保存版本不一致')
            if sha(folder / 'plan.json') != b['checksum'] or read_json(folder / 'plan.json') != p:
                raise ValueError('批次清单内容不一致')
            c = counts.get(b['id'], {})
            if type(p['case_count']) is not int or len(p['cases']) != p['case_count'] or set(c) - set(STATUSES) or sum(c.values()) != p['case_count']:
                raise ValueError('算例与状态数量不一致')
            site_ids=list(dict.fromkeys(x['site_id'] for x in p['cases']))
            effective=adopted_steps.get(b['id'],{})
            steps=[effective.get(i,x.get('step_minutes',r['numerics']['step_minutes'])) for i,x in enumerate(p['cases'])]
            from site_recalculation import step_label
            batches.append(dict(kind='batch', id=b['id'], name=p.get('record_name') or r['name'], record=label(r),
                                actual_steps=sorted(set(steps)),step_label=step_label(steps),adopted_count=len(effective),
                                created=b['created'], queue_mode=b['mode'], case_count=p['case_count'],
                                site_count=len({x['site_id'] for x in p['cases']}),
                                site_names=[catalog.get('sites',{}).get(k,{}).get('name',k) for k in site_ids],
                                modes=sorted({x['mode'] for x in p['cases']}), counts={s:c.get(s, 0) for s in STATUSES},
                                status=batch_status(dict(c,failed=c.get('failed',0)-len(effective),passed=c.get('passed',0)+len(effective)), p['case_count'], b['mode'])))
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append(dict(kind='batch', id=b['id'], message=str(error)))
    for comparison in store.comparisons():
        try:
            sides = {}
            for side in ('left', 'right'):
                r,historical = store.comparison_input(comparison,side)
                side_batches = [b['id'] for b in batches if (b['record']['id'], b['record']['revision']) == (r['id'], r['revision'])]
                sides[side] = dict(**label(r), batch_ids=side_batches, historical=historical)
            comparisons.append(dict(**comparison, kind='comparison', sides=sides))
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append(dict(kind='comparison', id=comparison.get('id', ''), message=str(error)))
    historical = []
    if all(k in catalog['records'] for k in ('global_w00', 'global_fixed')):
        historical.append(dict(kind='historical', id='legacy-global', name='原平台正式全球历史结果',
                               sides={s:record_label(catalog['records'][k], catalog) for s,k in (('left','global_w00'),('right','global_fixed'))}))
    return dict(checked_at=now(), batches=batches, comparisons=sorted(comparisons, key=lambda c:(c['created'],c['id']), reverse=True),
                historical=historical, issues=issues,
                note='索引核对保存版本、批次清单与队列登记状态；打开结果时继续核验结果文件。已保存比较不等于已完成配对，选择双方来源后再读取。')
