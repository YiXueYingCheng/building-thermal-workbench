"""User-curated readings of saved comparisons, independent of calculation set members."""
import uuid
import theme_groups

from comparison_results import comparison, choices, choice_index
from foundation import canonical, digest, loads
from pair_evidence import building_key, read
from record_store import Store
from research_sets import Sets, require


def pair_key(rel):
    return (rel['left']['id'], rel['left']['revision'], rel['right']['id'], rel['right']['revision'], rel['metric'])


def connect_readings(section):
    """Connect complete observations with the same metric and middle evidence at every site."""
    starts = {}
    for row in section:
        row['next'] = []
        if row['excluded'] or not row['sites']:
            continue
        for side in ('left','right'):
            index = 0 if side == 'left' else 1
            row[side + '_key'] = (row['metric'], tuple(sorted((s['site'],s['keys'][index]) for s in row['sites'])))
        starts.setdefault(row['left_key'],[]).append(row)
    for row in section:
        for other in starts.get(row.get('right_key'),[]):
            if row is not other and row['sides'][0]['ref'] != other['sides'][1]['ref']:
                row['next'].append(other['id'])
    for row in section:
        row.pop('left_key',None)
        row.pop('right_key',None)


class Readings:
    def __init__(self,catalog,root):
        self.store = Store(catalog,root)
        self.sets = Sets(catalog,root)
        with self.store.connect() as db:
            theme_groups.ensure(db)
            db.execute('CREATE TABLE IF NOT EXISTS reading_groups (id TEXT PRIMARY KEY, name TEXT NOT NULL, building TEXT NOT NULL, UNIQUE(building,name))')
            db.execute('CREATE TABLE IF NOT EXISTS reading_links (group_id TEXT NOT NULL, signature TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(group_id,signature))')
            db.execute('CREATE TABLE IF NOT EXISTS reading_hidden (group_id TEXT NOT NULL, signature TEXT NOT NULL, token TEXT NOT NULL, PRIMARY KEY(group_id,signature))')
            db.execute('CREATE VIEW IF NOT EXISTS visible_reading_links AS SELECT l.group_id,l.signature,l.payload,l.rowid AS position FROM reading_links l '
                       'WHERE NOT EXISTS (SELECT 1 FROM reading_hidden h WHERE h.group_id=l.group_id AND h.signature=l.signature)')

    def records(self,rel):
        return [self.store.comparison_input(rel,k)[0] for k in ('left','right')]

    def calculation_group(self,ident,db):
        group=self.sets.get(ident,db=db)
        ref=group['members']['baseline']['record']
        record=self.store.get(ref['id'],ref['revision'])
        return dict(id=ident,name=group['name'],building=building_key(record),kind='calculation',
                    revision=group['revision'],member_count=len(group['members']))

    def groups(self,rel_id=None):
        building = None
        if rel_id:
            a,b = self.records(comparison(self.store,rel_id))
            building = building_key(a)
            if building!=building_key(b):building=theme_groups.ANY_BUILDING
        with self.store.connect() as db:
            entries = [dict(r,kind='reading') for r in db.execute('SELECT * FROM reading_groups ORDER BY name')]
            for row in db.execute('SELECT id FROM research_sets GROUP BY id'):
                entries.append(self.calculation_group(row[0],db))
            counts = dict(db.execute('SELECT group_id,COUNT(*) FROM visible_reading_links GROUP BY group_id'))
        return [dict(e,count=counts.get(e['id'],0)) for e in entries if building is None or e['building'] in (building,theme_groups.ANY_BUILDING)]

    def group(self,ident):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM reading_groups WHERE id=?',(ident,)).fetchone()
            if row:
                group=dict(row,kind='reading')
            else:
                require(db.execute('SELECT 1 FROM research_sets WHERE id=? LIMIT 1',(ident,)).fetchone(),'未找到阅读汇总。')
                group=self.calculation_group(ident,db)
            if group['building']==theme_groups.ANY_BUILDING:
                group['membership']=theme_groups.latest(db,ident)
                group['member_history']=[loads(row[0]) for row in db.execute('SELECT payload FROM theme_versions WHERE group_id=? ORDER BY revision DESC',(ident,))]
            group['count']=db.execute('SELECT COUNT(*) FROM visible_reading_links WHERE group_id=?',(ident,)).fetchone()[0]
        return group

    def prepare(self,rel,body,building,index=None):
        a,b = self.records(rel)
        same_building=building_key(a)==building_key(b)
        require(building==theme_groups.ANY_BUILDING or (same_building and building==building_key(a)),'请选择本建筑的对照。')
        data = read(a,b,dict(body,comparison=rel['id'],metric=rel['metric']),self.store.catalog,self.store.root,index=index,store=self.store)
        buildings=[r['factors']['building']['name'] for r in (a,b)]
        data.update(comparison=rel['id'],name=rel['name'],building=buildings[0] if same_building else ' / '.join(buildings),
                    building_key=building_key(a) if same_building else digest([building_key(a),building_key(b)]))
        sig = digest([rel['left'],rel['right'],rel['metric'],data['mode'],[s['source'] for s in data['sides']]])
        return sig,data

    def save_link(self,db,group,sig,data):
        require(db.execute('SELECT 1 FROM comparisons WHERE id=?',(data['comparison'],)).fetchone(),'比较关系已被移除。')
        key = (group,sig)
        added = db.execute('INSERT OR IGNORE INTO reading_links VALUES (?,?,?)',(*key,canonical(data))).rowcount
        restored = db.execute('DELETE FROM reading_hidden WHERE group_id=? AND signature=?',key).rowcount
        if restored:
            db.execute('UPDATE reading_links SET payload=? WHERE group_id=? AND signature=?',(canonical(data),*key))
        theme_groups.enroll_members(db,group,[s['ref'] for s in data['sides']])
        return bool(added or restored)

    def add(self,body):
        rel = comparison(self.store,body['comparison'])
        group_id = body.get('group') or ''
        if group_id:
            building = self.group(group_id)['building']
        else:
            name = body.get('name','')
            require(isinstance(name,str) and 0<len(name.strip())<=100,'请填写 1 至 100 字的汇总名称。')
            name = name.strip()
            building = theme_groups.ANY_BUILDING
        sig,data = self.prepare(rel,body,building)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not group_id:
                row=db.execute('SELECT id FROM reading_groups WHERE building=? AND name=?',(building,name)).fetchone()
                group_id=row[0] if row else 'reading_'+uuid.uuid4().hex
                if not row:db.execute('INSERT INTO reading_groups VALUES (?,?,?)',(group_id,name,building))
            added=self.save_link(db,group_id,sig,data)
        return dict(group=group_id,entry=sig,reused=not added)

    def options(self,ident):
        group=self.group(ident)
        with self.store.connect() as db:
            enrolled=set()
            for payload, in db.execute('SELECT payload FROM visible_reading_links WHERE group_id=?',(ident,)):
                row=loads(payload)
                enrolled.add(pair_key(dict(left=row['sides'][0]['ref'],right=row['sides'][1]['ref'],metric=row['metric'])))
        # Inspect each pinned record once. Result bodies are only needed for the selected comparisons.
        records, sources, options = {},{},[]
        saved=self.store.comparisons()
        index=choice_index(self.store.root,{rel[k]['id'] for rel in saved for k in ('left','right')})
        for rel in saved:
            pins=[(rel[s]['id'],rel[s]['revision']) for s in ('left','right')]
            for side,key in zip(('left','right'),pins):
                if key not in records:records[key]=self.store.comparison_input(rel,side)
            sides=[records[k][0] for k in pins]
            if group['building']!=theme_groups.ANY_BUILDING and any(building_key(r)!=group['building'] for r in sides):continue
            mode='natural' if rel['metric']=='temperature' and any(r['factors']['condition']['operation']['mode']=='natural' for r in sides) else 'controlled'
            for key in pins:
                if key not in sources:sources[key]=choices(records[key][0],self.store.catalog,self.store.root,index,historical_bound=records[key][1])
            counts=[sum(mode in x['modes'] for x in sources[k]) for k in pins]
            options.append(dict(id=rel['id'],name=rel['name'],metric=rel['metric'],sides=[dict(name=r['name'],revision=r['revision']) for r in sides],
                                counts=counts,enrolled=pair_key(rel) in enrolled))
        return dict(name=group['name'],options=options)

    def add_many(self,body):
        group=self.group(body['group'])
        ids=body.get('comparisons')
        require(isinstance(ids,list) and ids and all(isinstance(x,str) for x in ids),'请勾选要收录的比较。')
        available={r['id']:r for r in self.store.comparisons()}
        selected=list(dict.fromkeys(ids))
        require(all(i in available for i in selected),'有比较已被移除，请重新选择。')
        prepared=[]
        index=choice_index(self.store.root,{available[i][k]['id'] for i in selected for k in ('left','right')})
        for ident in selected:
            sig,data=self.prepare(available[ident],{},group['building'],index)
            require(not any(s.get('ambiguous') for s in data['sides']),data['name']+'有多份结果来源，请在结果页选定后加入。')
            prepared.append((sig,data))
        added=0
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for sig,data in prepared:
                added+=self.save_link(db,group['id'],sig,data)
        return dict(group=group['id'],entries=[sig for sig,_ in prepared],added=added,reused=len(prepared)-added)

    def refresh(self,body):
        """Fill coverage for the same pins; never replace previously verified evidence."""
        key = (body['group'],body['entry'])
        with self.store.connect() as db:
            saved=db.execute('SELECT payload FROM visible_reading_links WHERE group_id=? AND signature=?',key).fetchone()
        require(saved,'请重新打开汇总选择一条收录。')
        old=loads(saved[0])
        rel=comparison(self.store,old['comparison'])
        require(all(rel[s]==v['ref'] for s,v in zip(('left','right'),old['sides'])),'保存版本与原收录不一致。')
        request=dict(mode=old['mode'],left_source=old['sides'][0]['source'],right_source=old['sides'][1]['source'])
        sig,new=self.prepare(rel,request,self.group(key[0])['building'])
        require(not any(s['ambiguous'] for s in new['sides']),'有多份结果来源，请到结果页选择批次后收录。')
        current={s['site']:s['keys'] for s in new['sites']}
        def preserves(data):
            return all(current.get(s['site'])==s['keys'] for s in data['sites'])
        require(preserves(old),'已有地点的结果依据发生变化，原收录已保留。请从比较结果页核对来源。')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            original=db.execute('SELECT payload FROM visible_reading_links WHERE group_id=? AND signature=?',key).fetchone()
            require(original and original[0]==saved[0],'收录状态已变化，请重新打开汇总。')
            if sig!=key[1]:
                target=db.execute('SELECT payload FROM reading_links WHERE group_id=? AND signature=?',(key[0],sig)).fetchone()
                require(not target or preserves(loads(target[0])),'相同来源已有其他核验记录，请先核对两条收录。')
                # When the newly resolved sources are already present, keep one visible snapshot.
                db.execute('DELETE FROM reading_hidden WHERE group_id=? AND signature=?',(key[0],sig))
                db.execute('DELETE FROM reading_links WHERE group_id=? AND signature=?',key)
            db.execute('INSERT INTO reading_links(group_id,signature,payload) VALUES (?,?,?) '
                       'ON CONFLICT(group_id,signature) DO UPDATE SET payload=excluded.payload',(key[0],sig,canonical(new)))
        return dict(group=key[0],entry=sig,added=len(new['sites'])-len(old['sites']),paired=len(new['sites']),missing=len(new['excluded']))

    def visibility(self,body,restore):
        key=(body['group'],body['entry'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT 1 FROM reading_links WHERE group_id=? AND signature=?',key).fetchone(),'该汇总没有这条收录。')
            if restore:
                changed=db.execute('DELETE FROM reading_hidden WHERE group_id=? AND signature=? AND token=?',(*key,body['token'])).rowcount
                require(changed,'收录状态已更新，请重新打开汇总。')
                return dict(group=key[0])
            token=uuid.uuid4().hex
            db.execute('INSERT OR IGNORE INTO reading_hidden VALUES (?,?,?)',(*key,token))
            hidden=db.execute('SELECT token FROM reading_hidden WHERE group_id=? AND signature=?',key).fetchone()
            return dict(group=key[0],token=hidden[0])

    def detail(self,ident):
        group=self.group(ident)
        with self.store.connect() as db:
            links=[dict(loads(r[1]),id=r[0]) for r in db.execute('SELECT signature,payload FROM visible_reading_links WHERE group_id=? ORDER BY position',(ident,))]
        sections={}
        for row in links:
            sections.setdefault((row.get('building_key'),row['condition']),[]).append(row)
        for section in sections.values():
            connect_readings(section)
        return dict(group=group,sections=list(sections.values()))

    def months(self,body):
        with self.store.connect() as db:
            entry=db.execute('SELECT payload FROM visible_reading_links WHERE group_id=? AND signature=?',
                             (body['group'],body['entry'])).fetchone()
        require(entry,'这条对照已移出或不在当前集内。')
        saved=loads(entry[0])
        require(saved['mode']=='controlled' and saved['metric']!='temperature','请选择温控显热需求对照。')
        site=body['site']
        original=next((s for s in saved['sites'] if s['site']==site),None)
        require(original and len(original.get('keys',[]))==2,'该地点没有已收录的严格配对结果。')
        left,right=saved['sides']
        require(left.get('source') and right.get('source'),'收录记录缺少明确的结果来源。')
        rel=comparison(self.store,saved['comparison'])
        require([left['ref'],right['ref']]==[rel['left'],rel['right']],'已收录的双方版本与保存的比较不一致。')
        records=self.records(rel)
        request=dict(comparison=saved['comparison'],mode=saved['mode'],metric=saved['metric'],left_source=left['source'],right_source=right['source'])
        fresh=read(*records,request,self.store.catalog,self.store.root,store=self.store,monthly_observation=original)
        result=next((s for s in fresh['sites'] if s['site']==site),None)
        require(result and result.get('months'),next((s['reason'] for s in fresh['excluded'] if s['site']==site),'该地点的月度结果未通过核对。'))
        return dict(site=site,city=result['city'],keys=result['keys'],months=result['months'],evidence=result['month_evidence'],export=saved.get('export'))
