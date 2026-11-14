"""Lightweight set progress across group, member and bound-source submissions.

This is a navigation projection, never an acceptance or result-pairing decision.
Only compact queue fields are read; immutable bindings are cached separately from
live job status. Opening results retains the full scientific verification.
"""
from pathlib import Path
from contextlib import closing
from collections import Counter
import sqlite3
from foundation import digest,now
from research_sets import ref,recipe
from navigation_cache import cached,live_queue,queue_identity

def projection(sets,snapshot,headers):
    records=sets.records(snapshot);allowed={};issues=[]
    for role,record in records.items():
        current=ref(record);allowed.setdefault((current['id'],current['revision'],current['sha256']),[]).append((role,None,'member',None))
        current_recipe=recipe(record)
        for candidate in snapshot['members'][role].get('results',[]):
            if candidate['recipe']!=current_recipe:continue
            try:
                source=sets.store.get(candidate['source']['id'],candidate['source']['revision'])
                if ref(source)!=candidate['source'] or recipe(source)!=current_recipe:continue
                r=candidate['source'];allowed.setdefault((r['id'],r['revision'],r['sha256']),[]).append((role,candidate['batch_id'],'source',candidate['plan_sha256']))
            except (ValueError,KeyError,OSError) as exc:issues.append('来源版本暂未纳入进度：'+str(exc))
    path=sets.root/'data/execution/queue.sqlite';rows=[]
    if not path.exists():return dict(cases=rows,issues=issues)
    expected={b['id']:b['checksum'] for b in headers}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        # SQLite extracts metadata without materializing full 34/72-site plans in Python.
        meta=db.execute("""SELECT id,checksum,json_extract(plan,'$.record_id') record_id,
          json_extract(plan,'$.revision') revision,json_extract(plan,'$.record_sha256') record_sha256 FROM batches""").fetchall()
        for b in meta:
            if expected.get(b['id'])!=b['checksum']:continue
            matches=allowed.get((b['record_id'],b['revision'],b['record_sha256']),[])
            matches=[m for m in matches if m[1] is None or m[1]==b['id'] and m[3]==b['checksum']]
            if not matches:continue
            cases=db.execute("""SELECT CAST(j.key AS INTEGER) idx,json_extract(j.value,'$.site_id') site_id
              FROM batches b,json_each(b.plan,'$.cases') j WHERE b.id=?""",(b['id'],)).fetchall()
            for role,_,origin,_ in matches:
                for c in cases:
                    if c['site_id'] in records[role]['factors']['scope']['site_ids']:
                        rows.append(dict(role=role,site_id=c['site_id'],batch_id=b['id'],index=c['idx'],origin=origin))
    unique={}
    for r in rows:
        k=(r['role'],r['batch_id'],r['index'])
        if k not in unique or r['origin']=='member':unique[k]=r
    return dict(cases=list(unique.values()),issues=issues)

def build(sets,ident,revision,preparations):
    root=sets.root;snapshot=sets.get(ident,revision);headers,jobs,storage=live_queue(root)
    value=cached(root,['research-progress-v1',ident,snapshot['revision']],
        [snapshot['sha256'],queue_identity(headers,storage)],
        lambda:[Path(__file__),root/'research_sets.py',root/'record_store.py',root/'data/drafts.sqlite',root/'data/drafts.sqlite-wal'],
        lambda:projection(sets,snapshot,headers))
    batch={b['id']:b for b in headers};live={(j['batch'],j['idx']):j for j in jobs}
    prepared_batches={c.get('batch_id') for p in preparations for c in p['cases'] if c.get('batch_id')}
    cases=[];issues=list(value['issues'])
    for r in value['cases']:
        j=live.get((r['batch_id'],r['index']));b=batch.get(r['batch_id'])
        if not j or not b:issues.append('批次状态有更新，请刷新进度。');continue
        cases.append(dict(r,status=j['status'],error=j['error'],paused=b['mode']=='pause',created=b['created'],origin='group' if r['batch_id'] in prepared_batches else r['origin']))
    prepared=set()
    for p in preparations:
        for c in p['cases']:
            if c.get('batch_id'):continue
            if c.get('lifecycle',{}).get('kind') in ('submitted','finished'):continue
            k=(c['role'],c['site_id'],c.get('review_id'))
            if k in prepared:continue
            prepared.add(k);cases.append(dict(role=c['role'],site_id=c['site_id'],batch_id=None,index=0,status='unknown' if c.get('lifecycle',{}).get('kind') in ('unknown','partial') else 'prepared',origin='group',created=p['created'],paused=p.get('state')=='paused',error=c.get('error')))
    counts=Counter(c['status'] for c in cases)
    return dict(id=ident,revision=snapshot['revision'],read_at=now(),cases=cases,counts=dict(counts),
        case_count=len(cases),submitted=sum(bool(c['batch_id']) for c in cases),preparations=preparations,issues=list(dict.fromkeys(issues)),
        note='包含本组批量安排、成员方案单独提交及已绑定来源的批次。状态取自队列；结果配对仍需读取并核对。')
