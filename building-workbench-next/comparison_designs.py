"""User-defined contrast drafts. Each cell can point to an immutable version or stay open."""
import re

from foundation import canonical, digest, loads, now
from research_sets import require
from theme_groups import valid_pin


def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS comparison_designs (id TEXT, revision INTEGER, payload TEXT NOT NULL, PRIMARY KEY(id,revision))')


def drafts(store):
    with store.connect() as db:
        ensure(db)
        rows=db.execute('SELECT payload FROM comparison_designs AS d WHERE revision=(SELECT MAX(revision) FROM comparison_designs WHERE id=d.id) ORDER BY rowid DESC')
        return [loads(row[0]) for row in rows]


def label(value, limit):
    require(isinstance(value,str) and 0<len(value.strip())<=limit,'请填写研究问题、因素名称及每个取值。')
    return value.strip()


def save(store, body):
    ident=body.get('id')
    require(isinstance(ident,str) and re.fullmatch(r'design_[0-9a-f]{32}',ident),'对照设计编号无效。')
    title=label(body.get('name'),100)
    base=valid_pin(store,body.get('base'))
    axes=body.get('axes')
    require(isinstance(axes,list) and len(axes) in (1,2),'请选择一个或两个研究因素。')
    normalized=[]
    for axis in axes:
        require(isinstance(axis,dict),'因素格式无效。')
        values=axis.get('values')
        require(isinstance(values,list) and len(values)==2,'每个因素需要两种取值。')
        values=[label(v,64) for v in values]
        require(values[0]!=values[1],'同一因素的两种取值须能区分。')
        normalized.append(dict(name=label(axis.get('name'),64),values=values))
    require(len({a['name'] for a in normalized})==len(axes),'两条研究轴须有不同的名称。')
    cells=body.get('cells')
    require(isinstance(cells,list) and len(cells)==2**len(axes),'工况格数与因素不符。')
    cells=[None if ref is None else valid_pin(store,ref) for ref in cells]
    used=[(p['id'],p['revision']) for p in cells if p]
    require(len(set(used))==len(used),'同一版本不能同时代表两种预期设置。')
    content=dict(id=ident,name=title,base=base,axes=normalized,cells=cells)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        ensure(db)
        row=db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
        old=loads(row[0]) if row else None
        if old and all(content[k]==old[k] for k in content):
            return old
        rev=old['revision'] if old else 0
        require(type(body.get('expected_revision')) is int and body['expected_revision']==rev,'这份设计已在另一窗口更新，请重新打开后核对。')
        saved=dict(content,revision=rev+1,updated=now())
        if old and old.get('cell_origins'):
            saved['cell_origins']={str(i):entry for i,ref in enumerate(cells)
                                   for entry in old['cell_origins'].values() if ref==entry['bound']}
        db.execute('INSERT INTO comparison_designs VALUES(?,?,?)',(ident,rev+1,canonical(saved)))
        return saved


def coverage(reader, body):
    """Inspect known results at each requested location without creating a plan or estimating run time."""
    from collections import Counter
    import comparison_results as results
    import pair_archives
    from pair_evidence import source
    from research_sets import recipe
    store=reader.store
    with store.connect() as db:
        ensure(db)
        row=db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',(body.get('id'),)).fetchone()
    require(row is not None,'请先保存设计。')
    design=loads(row[0]);require(body.get('revision')==design['revision'],'设计版本已变化，请重新打开核对。')
    cells=body.get('selected')
    require(isinstance(cells,list) and 0<len(cells)<=len(design['cells']) and all(type(i) is int and 0<=i<len(design['cells']) for i in cells),'请选择要核对的工况。')
    records={i:store.get(**dict(ident=p['id'],revision=p['revision'])) for i in dict.fromkeys(cells) if (p:=design['cells'][i])}
    index=results.choice_index(store.root,{r['id'] for r in records.values()}) if records else None
    notices=[]
    archives=pair_archives.for_members(reader,list(records.values()),notices,min_matches=1) if records else []
    items=[];missing=set();counts=Counter()
    for i in dict.fromkeys(cells):
        if i not in records:
            items.append(dict(cell=i,status='待选或待派生',sites=[]));continue
        record=records[i];scope=record['factors']['scope'];options=results.choices(record,store.catalog,store.root,index)
        mode=record['factors']['condition']['operation']['mode']
        if mode not in ('controlled','natural','both'):
            items.append(dict(cell=i,status='请先核对运行模式',sites=[]));continue
        rows=[];key=pair_archives.record_key(record)
        for current in (('controlled','natural') if mode=='both' else (mode,)):
            evidence=[];unclear=False
            for option in options:
                if current not in option['modes']:continue
                data,note=source(record,options,option['id'],current,store.catalog,store.root)
                if note:unclear=True
                if data:evidence.append(data['cases'])
            evidence.extend(archive['cases'][key] for archive in archives if key in archive['cases'])
            for site in scope['site_ids']:
                hits=[e[site] for e in evidence if site in e and e[site].get('mode')==current]
                accepted={h.get('evidence',{}).get('result_sha256') or digest(h) for h in hits if h.get('status') in ('passed','reused')}
                states={h.get('status') for h in hits}
                if not store.catalog['sites'].get(site,{}).get('eligible',True):state='地点待核对'
                elif len(accepted)>1:state='多份结果待选'
                elif accepted:state='已有核验结果'
                elif 'running' in states:state='计算中'
                elif 'pending' in states:state='已排队'
                elif 'review' in states:state='待复核'
                elif unclear or notices:state='来源待核对'
                elif states:state='已有任务需处理'
                else:
                    state='已有方案，缺结果';missing.add((recipe(record),site,current))
                counts[state]+=1
                row=dict(city=store.catalog['sites'].get(site,{}).get('name',site),mode=current,status=state)
                if state=='已有核验结果' and current=='controlled':
                    hit=next(h for h in hits if h.get('status') in ('passed','reused'))
                    if hit.get('loads'):
                        row['loads']={k:results.finite(hit['loads'][k]) for k in ('heating_kWh','cooling_kWh','total_kWh')}
                rows.append(row)
        items.append(dict(cell=i,status='',sites=rows))
    return dict(items=items,counts=dict(counts),missing_cases=len(missing),notices=notices)
