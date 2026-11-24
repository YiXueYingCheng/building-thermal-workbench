"""Research-question collections of immutable plan versions. Calculations remain separate."""
import re
from collections import Counter

from comparison_results import choice_index, choices
from execution_queue import Queue
from foundation import canonical, digest, loads, now
import pair_archives
from pair_evidence import archive_alternative, building_key, needs_pair_archive, pin, read
from planner import compare
from research_sets import require
import coverage_results
import version_notes

ANY_BUILDING='*'


def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS theme_versions (group_id TEXT, revision INTEGER, payload TEXT NOT NULL, PRIMARY KEY(group_id,revision))')


def latest(db, ident):
    row=db.execute('SELECT payload FROM theme_versions WHERE group_id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
    return loads(row[0]) if row else dict(members=[],reference=None,revision=0)


def append_version(db, ident, old, members, reference):
    if old['members']==members and old['reference']==reference:
        return old
    snap=dict(revision=old['revision']+1,members=members,reference=reference,created=now())
    db.execute('INSERT INTO theme_versions VALUES(?,?,?)',(ident,snap['revision'],canonical(snap)))
    return snap


def enroll_members(db, ident, refs):
    if not db.execute('SELECT 1 FROM reading_groups WHERE id=? AND building=?',(ident,ANY_BUILDING)).fetchone():
        return
    old=latest(db,ident)
    members=list(old['members'])
    for ref in refs:
        if ref not in members:
            members.append(ref)
    append_version(db,ident,old,members,old['reference'])


def valid_pin(store, ref):
    require(isinstance(ref,dict) and set(ref)=={'id','revision'} and isinstance(ref['id'],str)
            and (type(ref['revision']) is int or isinstance(ref['revision'],str)),'请选择一个已保存版本。')
    require(pin(store.study_record(ref))==ref,'方案版本已变化。')
    return ref


def key(p):
    return p['id'],p['revision']


def status_label(counts):
    good=sum(counts.get(k,0) for k in ('passed','reused'))
    if good and good==sum(counts.values()):return '已核验'
    if good:return '部分已核验'
    if counts.get('failed'):return '核查未通过'
    if counts.get('review'):return '待复核'
    if counts:return '未核验'
    return '尚无结果'


def design_facts(record):
    """Describe the saved input, including whether a calendar is actually bound."""
    from comparison_reading import installation
    from calendar_library import active_references
    f=record['factors']
    materials=f['materials']
    context=digest([building_key(record),f['building'],f['scope'],f['condition']['operation'],record['numerics']])
    facts=dict(context=context,material_key=digest(materials),optical='',thermal='',optical_key='',thermal_key='')
    app=installation(record)
    if not app:
        names=[d['name'] for d in materials['definitions']]
        facts['summary']='、'.join(names) if names else '未铺研究材料层'
        return facts
    optical,thermal=app['optical'],app['thermal']
    references=active_references(record)
    if optical['mode']=='fixed':
        facts['optical']='固定 '+optical['face_id']
    elif optical['mode']=='calendar':
        facts['optical']='光学日历待绑定'
        if len(references)==1 and references[0].get('snapshot',{}).get('sha256'):
            rule=references[0]['snapshot']['content'].get('rule') or {}
            facts['optical']='季节光学切换' if {'dominant_share','persistence_days','window_days'}<=rule.keys() else '按日历光学切换'
    if thermal['mode']=='feedback':
        facts['thermal']='按反馈调节热阻'
    elif thermal['mode']=='fixed' and app['state']:
        facts['thermal']='固定'+app['state']
    facts.update(summary=' · '.join(filter(None,[facts['optical'],facts['thermal']])) or app['material'],
                 material=app['material'],optical_key=digest([optical,references]),thermal_key=digest(thermal))
    return facts


def options(reader):
    store=reader.store
    catalog,root=store.catalog,store.root
    index=choice_index(root)
    notes={(n['record_id'],n['revision']):n['note'] for n in version_notes.listing(store)}
    with Queue(root).db() as db:
        counts={}
        for batch,status,n in db.execute('SELECT batch,status,count(*) FROM jobs GROUP BY batch,status'):
            counts.setdefault(batch,Counter())[status]=n
    def summarize(r,historical_bound=None):
        rec_counts=Counter()
        sources=[]
        for s in choices(r,catalog,root,index,historical_bound=historical_bound):
            sid=s['id']
            if sid.startswith('observed_'):
                try: tally=Counter(v['status'] for v in coverage_results.observed(r,sid,root)['cases'].values())
                except (OSError,ValueError,KeyError):tally=Counter(failed=1)
            elif sid=='historical':
                tally=Counter(v['review_status'].startswith('accepted') and 'passed' or 'review'
                              for v in catalog['global_bundle']['jobs'].values() if v['case']==r['provenance']['case'])
            else:tally=counts.get(sid,{})
            rec_counts.update(tally)
            sources.append(dict(**s,status=status_label(tally)))
        f=r['factors']
        return dict(ref=pin(r),name=r['name'],building=f['building']['name'],building_id=f['building']['id'],
                    design=design_facts(r),building_key=building_key(r),step=r['numerics']['step_minutes'],period=f['scope']['period'],
                    places=[catalog['sites'].get(s,{}).get('name',s) for s in f['scope']['site_ids']],
                    mode=f['condition']['operation']['mode'],note=notes.get((r['id'],str(r['revision'])),''),sources=sources,
                    status=status_label(rec_counts),archived=r.get('archived',False))
    rows=[summarize(r) for r in catalog['records'].values()]
    with store.connect() as db:
        rows.extend(summarize(loads(r[0])) for r in db.execute('SELECT payload FROM versions ORDER BY created DESC,revision DESC'))
    comparisons=store.comparisons()
    known={key(row['ref']) for row in rows}
    for rel in comparisons:
        for side in ('left','right'):
            member=key(rel[side])
            if member not in known:
                record,bound=store.comparison_input(rel,side)
                known.add(member)
                rows.append(summarize(record,bound))
    return dict(versions=rows,comparisons=[{k:r[k] for k in ('id','name','left','right','metric')} for r in comparisons])


def save_members(reader, body):
    ident=body.get('group','')
    require(re.fullmatch('reading_[0-9a-f]{32}',ident) is not None,'对比集编号无效。')
    name=body.get('name')
    require(isinstance(name,str) and 0<len(name.strip())<=100,'请用 1 至 100 字填写研究问题。')
    name=name.strip()
    refs=body.get('members')
    require(isinstance(refs,list) and len(refs)>=2,'至少选择两个方案版本。')
    members=[valid_pin(reader.store,p) for p in refs]
    require(len({key(p) for p in members})==len(members),'有重复的成员版本。')
    reference=body.get('reference')
    require(reference is None or reference in members,'共同参考须为本次选中的成员。')
    ids=body.get('comparisons',[])
    require(isinstance(ids,list) and all(isinstance(s,str) for s in ids),'所选对照无效。')
    rels={r['id']:r for r in reader.store.comparisons()}
    checks=[]
    index=choice_index(reader.store.root) if ids else None
    for i in dict.fromkeys(ids):
        rel=rels.get(i)
        require(rel and all(rel[k] in members for k in ('left','right')),'加入已有对照时须保留该对照的两个版本。')
        checks.append(reader.prepare(rel,{},ANY_BUILDING,index))
    with reader.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT name,building FROM reading_groups WHERE id=?',(ident,)).fetchone()
        if row:
            require(row['building']==ANY_BUILDING and row['name']==name,'请选择通用对比集。')
        else:
            require(body.get('expected_revision')==0,'对比集已变化。')
            require(not db.execute('SELECT 1 FROM reading_groups WHERE building=? AND name=?',(ANY_BUILDING,name)).fetchone(),'已有同名研究问题，请打开该集或调整名称。')
            db.execute('INSERT INTO reading_groups VALUES(?,?,?)',(ident,name,ANY_BUILDING))
        for p in members:valid_pin(reader.store,p)
        old=latest(db,ident)
        require(body.get('expected_revision')==old['revision'] or (members==old['members'] and reference==old['reference']),
                '成员已由另一窗口修改，请重新打开核对。')
        snap=append_version(db,ident,old,members,reference)
        for sig,data in checks:
            reader.save_link(db,ident,sig,data)
    return dict(group=ident,revision=snap['revision'])


def compare_members(reader,body,retain):
    group=reader.group(body['group'])
    require(group['building']==ANY_BUILDING,'请选择通用对比集。')
    with reader.store.connect() as db:snap=latest(db,group['id'])
    left,right=body['left'],body['right']
    require(snap['revision']==body['revision'] and left!=right and all(p in snap['members'] for p in (left,right)),
            '请选择当前集内两个不同的成员版本。')
    a,b=[reader.store.study_record(p) for p in (left,right)]
    require(building_key(a)==building_key(b),'两栋建筑可同时收录。定量比较请选择同一栋建筑的两项。')
    metric=body.get('metric','total')
    rels=[r for r in reader.store.comparisons() if r['left']==left and r['right']==right and r['metric']==metric]
    rel=next((r for r in rels if r['id']==body.get('comparison')),None) if body.get('comparison') else (rels[0] if len(rels)==1 else None)
    require(not body.get('comparison') or rel,'对照方向或保存版本不匹配。')
    require(len(rels)<2 or rel is not None,'当前方向有多条已有对照，请选择一条。')
    if rel is None:
        ident='comparison_'+digest(['topic-pair',left,right,metric])[:32]
        rel=next((r for r in rels if r['id']==ident),dict(id=ident,name=(a['name']+' → '+b['name'])[:100],
                                                        left=left,right=right,metric=metric))
    request=dict(metric=metric,left_source=body.get('left_source'),right_source=body.get('right_source'))
    if rel in rels:request['comparison']=rel['id']
    data=read(a,b,request,reader.store.catalog,reader.store.root,store=reader.store)
    data.update(name=rel['name'],comparison=rel['id'],building=a['factors']['building']['name'],building_key=building_key(a))
    audit=compare(a,b)
    token=digest([group['id'],snap['revision'],data,audit])
    if not retain:
        preview=dict(data=data,audit=audit,token=token)
        if needs_pair_archive(data):
            notices=[]
            exports=pair_archives.for_members(reader,(a,b),notices)
            alternative=archive_alternative(reader,a,b,request,exports,notices)
            if alternative and alternative['sites']:
                preview['archive_candidate']=dict(data=alternative,relation=request.get('comparison'))
            if notices:preview['notices']=notices
        return preview
    require(token==body.get('token'),'输入或结果已变化，请重新核对。')
    require(not any(s['ambiguous'] for s in data['sides']),'请选择明确的结果批次后收录。')
    sig=digest([left,right,metric,data['mode'],[s['source'] for s in data['sides']]])
    with reader.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        require(latest(db,group['id'])['revision']==snap['revision'],'成员已更新，请重新核对。')
        # A new direction is local until the user explicitly saves the checked relation.
        if not db.execute('SELECT 1 FROM comparisons WHERE id=?',(rel['id'],)).fetchone():
            db.execute('INSERT INTO comparisons VALUES(?,?,?)',(rel['id'],canonical(dict(rel,created=now())),now()))
        reader.store._pin_members(db,rel)
        added=reader.save_link(db,group['id'],sig,data)
        if data['sites']:
            # Replace unresolved placeholders for this same direction and compatible source selection.
            for row in db.execute('SELECT signature,payload FROM visible_reading_links WHERE group_id=? AND signature<>?',(group['id'],sig)).fetchall():
                prior=loads(row['payload'])
                if (prior['comparison']==rel['id'] and prior['mode']==data['mode'] and not prior['sites']
                        and any(s['source'] is None for s in prior['sides'])
                        and all(not old['source'] or old['source']==new['source'] for old,new in zip(prior['sides'],data['sides']))):
                    db.execute('INSERT OR IGNORE INTO reading_hidden VALUES(?,?,?)',(group['id'],row['signature'],digest(['resolved',sig,row['signature']])))
    return dict(group=group['id'],entry=sig,added=added)
