"""Read-only index for one saved version; does not validate or accept results."""
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from foundation import ROOT, read_json, loads, digest, sha, owned, now

STATUSES=('pending','running','passed','reused','review','failed','interrupted','cancelled')

def build(record,catalog,store,root=ROOT):
    root=Path(root).resolve();checksum=digest(record);inputs=[];batches=[];comparisons=[];issues=[];other=set()
    def same(item):return item.get('record_id')==record['id'] and item.get('revision')==record['revision']
    def note_other(item):
        if item.get('record_id')==record['id'] and item.get('revision')!=record['revision']:
            other.add(item.get('revision'))
    for path in sorted((root/'data/model-inputs').glob('inputs_*/manifest.json')):
        try:
            folder=owned(path.parent,root/'data/model-inputs')
            frozen=read_json(folder/'record.json')
            if not isinstance(frozen,dict):raise ValueError('方案快照格式无效')
            identity=dict(record_id=frozen.get('id'),revision=frozen.get('revision'))
            note_other(identity)
            # This is a navigation index. Inspect only this saved version's
            # large manifests; unrelated models are verified when opened.
            if not same(identity):continue
            m=read_json(path)
            if not isinstance(m,dict):raise ValueError('输入清单格式无效')
            note_other(m)
            if not same(m):raise ValueError('输入清单与方案快照的归属不一致')
            if not re.fullmatch(r'inputs_[a-f0-9]{32}',folder.name) or m['id']!=folder.name:raise ValueError('输入包编号不一致')
            if m['identity']['record']!=checksum or frozen!=record:raise ValueError('输入包与保存版本不一致')
            if type(m['case_count']) is not int or m['case_count']!=len(m['cases']):raise ValueError('输入清单数量不一致')
            inputs.append({k:m[k] for k in ('id','created','case_count','generated_bytes')})
        except (OSError,ValueError,KeyError,TypeError) as error:
            issues.append(f'输入清单 {path.parent.name} 暂未纳入：{error}')
    queue=root/'data/execution/queue.sqlite'
    if queue.exists():
        # A single read transaction, without acquiring the worker's write lock.
        with closing(sqlite3.connect(queue.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN')
            rows=[dict(r) for r in db.execute('SELECT id,review,plan,checksum,mode,created FROM batches ORDER BY created DESC,rowid DESC')]
            counts={}
            for row in db.execute('SELECT batch,status,COUNT(*) n FROM jobs GROUP BY batch,status'):
                counts.setdefault(row['batch'],{})[row['status']]=row['n']
        for b in rows:
            try:
                p=loads(b['plan'])
                if not isinstance(p,dict):raise ValueError('批次清单格式无效')
                note_other(p)
                if not same(p):continue
                if not re.fullmatch(r'batch_[a-f0-9]{32}',b['id']):raise ValueError('批次编号不一致')
                folder=owned(root/'data/execution/reviews'/b['review'],root/'data/execution/reviews')
                if p['record_sha256']!=checksum or read_json(folder/'record.json')!=record:raise ValueError('批次与保存版本不一致')
                if sha(folder/'plan.json')!=b['checksum'] or read_json(folder/'plan.json')!=p:raise ValueError('批次清单核对不一致')
                c=counts.get(b['id'],{})
                if set(c)-set(STATUSES) or sum(c.values())!=p['case_count']:raise ValueError('批次状态数量不一致')
                batches.append(dict(id=b['id'],created=b['created'],mode=b['mode'],case_count=p['case_count'],
                    bundle_id=p['bundle_id'],output_contract=p.get('output_contract','monthly_period_v1'),counts={s:c.get(s,0) for s in STATUSES}))
            except (OSError,ValueError,KeyError,TypeError) as error:
                issues.append(f'批次 {b["id"]} 暂未纳入：{error}')
    for c in store.comparisons():
        sides=[side for side in ('left','right') if c[side]==dict(id=record['id'],revision=record['revision'])]
        if not sides:continue
        try:
            names={side:store.get(c[side]['id'],c[side]['revision'])['name'] for side in ('left','right')}
            comparisons.append(dict(**c,names=names,roles=sides))
        except (ValueError,KeyError) as error:issues.append(f'比较关系 {c["name"]} 暂未纳入：{error}')
    history={h['revision']:h for h in store.history(record['id'])}
    historical=record['id'] in ('global_w00','global_fixed') and record==catalog['records'][record['id']]
    return dict(record_id=record['id'],revision=record['revision'],record_sha256=checksum,created=now(),
        inputs=sorted(inputs,key=lambda x:x['created'],reverse=True),batches=batches,comparisons=comparisons,issues=issues,
        other_versions=[h for rev,h in history.items() if rev in other],historical=historical)
