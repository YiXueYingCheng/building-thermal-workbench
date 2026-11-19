"""Isolated, versioned research sets on the existing records and result pipeline.

Members are owned records. One SQLite transaction publishes member revisions and
the set revision together. Source records, libraries, runs and queue are read only.
"""
import copy
import re
import uuid
from pathlib import Path
from foundation import ROOT,canonical,loads,digest,now
from record_store import Store,Conflict
from contracts import calculation_recipe,record_digest,differences
from calendar_library import stable_numbers

ROLES=('baseline','fixed','flip')
ALL_ROLES=(*ROLES,'feedback')
LABELS=dict(baseline='W00 · 原构造',fixed='固定 ECA',flip='ECA 表面光学切换',feedback='表面光学切换＋热阻调节')
COMMON=dict(building='建筑、基材与房间使用',operation='温控与运行作息',scope='地点与时段',numerics='步长与数值设置')

def require(ok,message):
    if not ok:raise ValueError(message)

def recipe(record):return digest(stable_numbers(calculation_recipe(record)))

def same_record(a,b):
    # JSON through the browser turns 1.0 into 1; this is not a saved input change.
    return record_digest(stable_numbers(a))==record_digest(stable_numbers(b))

def material_basis(record,include_thermal=True):
    """Compare installed material and active thermal state; the flip B face may differ."""
    m=record['factors']['materials'];controls=record['factors']['condition']['controls'];rows=[]
    for a in m['applications']:
        d=next(x for x in m['definitions'] if x['id']==a['material_id'])
        thermal=[c for c in controls if c['application_id']==a['id'] and c['channel']=='thermal']
        rows.append(dict(application=a,model=d['model'],states=d['states'],optics_A={k:v for k,v in d['optics'].items() if k.startswith('A_')},thermal=thermal if include_thermal else []))
    return stable_numbers(rows)

def common(record):
    f=record['factors']
    return stable_numbers(dict(building=f['building'],operation=f['condition']['operation'],scope=f['scope'],numerics=record['numerics']))

def compatible(records):
    base=common(records['baseline']);rows=[]
    for key,label in COMMON.items():
        values=[common(r)[key] for r in records.values()]
        if key=='numerics':
            values=[{k:v for k,v in n.items() if k!='step_minutes'} for n in values]
            label='引擎与数值设置（实际步长逐地点配对）'
        rows.append(dict(key=key,label=label,equal=all(v==values[0] for v in values)))
    issues=[]
    b=records['baseline'];m=b['factors']['materials']
    if m.get('applications') or m.get('legacy_construction_overrides') or b['factors']['condition']['controls']:issues.append('W00 需保留原构造，不含研究材料应用或材料控制。')
    for role in (k for k in records if k!='baseline'):
        r=records[role];c=r['factors']['condition']['controls']
        if not r['factors']['materials']['applications']:issues.append(LABELS[role]+'尚无研究材料应用。')
        thermal=[x for x in c if x['channel']=='thermal']
        if role=='feedback':
            if not any(x['mode']=='feedback' for x in thermal) or any(x['mode'] not in ('fixed','feedback') for x in thermal):issues.append(LABELS[role]+'需要明确的反馈作用范围，其余墙面保持固定。')
        elif not thermal or any(x['mode']!='fixed' for x in thermal):issues.append(LABELS[role]+'的热学控制与成员角色不一致。')
        face=[x for x in c if x['channel']=='orientation']
        if not face or any(x['mode']!=('fixed' if role=='fixed' else 'calendar') for x in face):issues.append(LABELS[role]+'的表面光学控制与角色不一致。')
    p=[r['provenance'] for r in records.values()]
    if len({(r['adapter'],r['snapshot_id']) for r in p})!=1:issues.append('组内成员的建筑来源不同，需要先核对。')
    rows.append(dict(key='research_basis',label='两项 ECA 的热学参数、A 组光学参数与应用范围',equal=material_basis(records['fixed'])==material_basis(records['flip'])))
    if 'feedback' in records:
        rows.append(dict(key='feedback_basis',label='仅表面光学切换与反馈的材料参数、A/B 光学参数及应用范围',equal=material_basis(records['flip'],False)==material_basis(records['feedback'],False) and records['flip']['factors']['materials']['definitions']==records['feedback']['factors']['materials']['definitions']))
        def thermal_targets(record):
            targets={}
            for c in record['factors']['condition']['controls']:
                if c['channel']!='thermal':continue
                for wall in c['target_ids']:
                    key=(c['application_id'],wall)
                    require(key not in targets,'同一墙面存在重复热学控制。')
                    targets[key]={k:v for k,v in c.items() if k not in ('id','target_ids')}
            return targets
        flip_targets=thermal_targets(records['flip']);feedback_targets=thermal_targets(records['feedback'])
        rows.append(dict(key='feedback_unaffected',label='未参与反馈的墙面保持原固定状态',equal=set(flip_targets)==set(feedback_targets) and all(c['mode']=='feedback' or c==flip_targets.get(k) for k,c in feedback_targets.items())))
    if 'feedback' in records:
        from calendar_library import active_references
        def calendar_content(r):
            refs=active_references(r)
            return [v['snapshot']['content'] for v in refs]
        rows.append(dict(key='control_calendar',label='仅表面光学切换与反馈使用同一逐日日历',equal=calendar_content(records['flip'])==calendar_content(records['feedback'])))
    issues += [r['label']+'不一致' for r in rows if not r['equal']]
    return dict(consistent=not issues,rows=rows,issues=issues)

def ref(record):return dict(id=record['id'],revision=record['revision'],sha256=digest(record))

def short(record):
    f=record['factors']
    return dict(id=record['id'],revision=record['revision'],name=record['name'],building=f['building']['name'],
        sites=len(f['scope']['site_ids']),period=f['scope']['period'],step_minutes=record['numerics']['step_minutes'])

class Sets:
    def __init__(self,catalog,root=ROOT):self.root=Path(root).resolve();self.catalog=catalog;self.store=Store(catalog,root)

    def get(self,ident,revision=None,db=None):
        require(bool(re.fullmatch(r'set_[a-f0-9]{32}',str(ident))),'对比集编号无效。')
        if db is None:
            with self.store.connect() as c:return self.get(ident,revision,c)
        row=db.execute('SELECT payload FROM research_sets WHERE id=? '+('AND revision=?' if revision is not None else 'ORDER BY revision DESC LIMIT 1'),(ident,revision) if revision is not None else (ident,)).fetchone()
        require(row is not None,'未找到该对比集版本。');value=loads(row[0]);h=value.pop('sha256')
        require(digest(value)==h,'对比集记录校验失败。');value['sha256']=h;return value

    def records(self,value):
        records={}
        for role,m in value['members'].items():
            r=self.store.get(m['record']['id'],m['record']['revision']);require(digest(r)==m['record']['sha256'],'成员快照已变化。');records[role]=r
        return records

    def all(self):
        with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM research_sets GROUP BY id ORDER BY MAX(created) DESC')]
        return [self.describe(i,summary_only=True) for i in ids]

    def describe(self,ident,revision=None,summary_only=False):
        s=self.get(ident,revision);r=self.records(s);out=dict(id=s['id'],revision=s['revision'],name=s['name'],notes=s['notes'],created=s['created'],sha256=s['sha256'],audit=compatible(r),
            members={k:dict(**short(r[k]),source=v['source'],source_summary=short(self.store.get(v['source']['id'],v['source']['revision'])),result_candidates=len(v.get('results',[]))) for k,v in s['members'].items()})
        if summary_only:return out
        from solid_eca import enabled
        out['fixed_feedback_experiment']=('feedback' in r and enabled(r['fixed']) and enabled(r['feedback']) and out['audit']['consistent'])
        with self.store.connect() as db:out['history']=[dict(revision=row[0],created=row[1],name=loads(row[2])['name']) for row in db.execute('SELECT revision,created,payload FROM research_sets WHERE id=? ORDER BY revision DESC',(ident,))]
        out['latest_revision']=out['history'][0]['revision'];out['calendars']=[]
        from calendar_library import status
        for role in (k for k in ('flip','feedback') if k in r):
            for row in status(r[role],self.catalog):out['calendars'].append(dict(role=role,**row))
        out['common']=common(r['baseline']);return out

    def create_preview(self,name,sources):
        require(isinstance(name,str) and 1<=len(name.strip())<=100,'请填写对比集名称。')
        require(isinstance(sources,dict) and set(sources) in (set(ROLES),set(ALL_ROLES)),'请明确选择三个或四个成员的保存版本。')
        records={}
        for role,v in sources.items():
            require(isinstance(v,dict) and set(v)=={'id','revision'} and type(v['revision']) is int,'来源需指定明确保存版本。')
            records[role]=self.store.get(v['id'],v['revision'])
        audit=compatible(records);require(audit['consistent'],'；'.join(audit['issues']))
        payload=dict(name=name.strip(),sources={k:ref(r) for k,r in records.items()})
        return dict(**payload,preview_sha256=digest(payload),audit=audit,members={k:short(r) for k,r in records.items()},new_simulations=0)

    def _bind_results(self,source):
        # Source candidates remain explicit references, not copied or renamed runs.
        from comparison_results import batch_rows
        rows=[]
        if not (self.root/'data/execution/queue.sqlite').exists():return rows
        source_ref=ref(source);source_recipe=recipe(source)
        for b in batch_rows(self.root):
            p=loads(b['plan'])
            if p.get('site_recalculation'):continue
            if (p['record_id'],p['revision'],p['record_sha256'])==(source['id'],source['revision'],source_ref['sha256']):
                rows.append(dict(batch_id=b['id'],source=source_ref,recipe=source_recipe,plan_sha256=b['checksum']))
        return rows

    def create(self,name,sources,expected):
        p=self.create_preview(name,sources);require(p['preview_sha256']==expected,'来源或预览已变化，请重新核对。')
        source_records={k:self.store.get(v['id'],v['revision']) for k,v in sources.items()}
        result_refs={k:self._bind_results(r) for k,r in source_records.items()}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for source in source_records.values():self.store.get(source['id'],source['revision'])
            # A double click creates only one set. Explicit copies can use a new name.
            for row in db.execute('SELECT payload FROM research_sets WHERE revision=1'):
                old=loads(row[0])
                if old.get('creation_sha256')==expected:return dict(id=old['id'],revision=self.get(old['id'],db=db)['revision'],reused=True)
            at=now();ident='set_'+uuid.uuid4().hex;members={}
            for role,source in source_records.items():
                r=copy.deepcopy(source);r.update(id='draft_'+uuid.uuid4().hex,revision=1,status='draft',archived=False,saved_at=at,name=(p['name']+' · '+LABELS[role])[:100])
                r['provenance'].update(origin_id=source['provenance'].get('origin_id',source['id']),parent_id=source['id'],parent_revision=source['revision'])
                r['record_sha256']=record_digest(r)
                db.execute('INSERT INTO versions VALUES(?,?,?,?)',(r['id'],1,canonical(r),at))
                db.execute('INSERT INTO research_set_members VALUES(?,?,?)',(r['id'],ident,role))
                members[role]=dict(record=ref(r),source=ref(source),results=result_refs[role])
            s=dict(schema_version=1,id=ident,revision=1,name=p['name'],notes='',created=at,members=members,creation_sha256=expected,change=dict(kind='create',label='从指定版本建立独立成员'))
            self._publish(db,s)
        return dict(id=ident,revision=1,reused=False)

    def _publish(self,db,value):
        value['sha256']=digest(value)
        db.execute('INSERT INTO research_sets VALUES(?,?,?,?)',(value['id'],value['revision'],canonical(value),value['created']))
        db.execute('INSERT INTO events(at,action,record_id,revision) VALUES(?,?,?,?)',(value['created'],'research_set_'+value['change']['kind'],value['id'],value['revision']))

    def _proposal(self,s,request):
        require(isinstance(request,dict) and not set(request)-{'role','changes','shared','name','notes'},'对比集修改参数无效。')
        old=self.records(s);new=copy.deepcopy(old);role=request.get('role');shared=request.get('shared',[])
        require(isinstance(shared,list) and len(set(shared))==len(shared) and set(shared)<=set(COMMON),'共同条件选择无效。')
        if role is not None:
            require(role in old,'成员角色无效。');new[role]=self.store.update_payload(old[role],request.get('changes',{}))
            require(new[role]['factors']['building']['id']==old[role]['factors']['building']['id'],'本轮对比集保持建筑身份；跨建筑研究请另外创建。')
            for key in shared:
                for other in old:
                    if key=='operation':new[other]['factors']['condition']['operation']=copy.deepcopy(new[role]['factors']['condition']['operation'])
                    elif key=='numerics':new[other]['numerics']=copy.deepcopy(new[role]['numerics'])
                    else:new[other]['factors'][key]=copy.deepcopy(new[role]['factors'][key])
        else:require(not shared and not request.get('changes'),'成员修改需指定角色。')
        for k,r in new.items():new[k]=self.store.update_payload(old[k],{x:r[x] for x in ('name','factors','numerics','execution')})
        name=request.get('name',s['name']);notes=request.get('notes',s['notes'])
        require(isinstance(name,str) and 1<=len(name.strip())<=100 and isinstance(notes,str) and len(notes)<=2000,'名称或备注格式无效。')
        return old,new,name.strip(),notes

    def preview(self,ident,revision,request):
        s=self.get(ident);require(type(revision) is int,'请提供对比集保存版本。')
        if s['revision']!=revision:raise Conflict('对比集已更新，请保留当前编辑并重新核对。')
        old,new,name,notes=self._proposal(s,request)
        payload=dict(set_sha256=s['sha256'],request=request)
        from calendar_library import status
        rows=[]
        from research_change_summary import describe as change_summary
        for role in old:
            changed=not same_record(old[role],new[role]);same_recipe=recipe(old[role])==recipe(new[role])
            rows.append(dict(role=role,label=LABELS[role],changed=changed,from_revision=old[role]['revision'],to_revision=old[role]['revision']+int(changed),
                factors=differences(old[role],new[role]),same_recipe=same_recipe,result_note='研究输入保持；已有结果候选可继续核对' if same_recipe else '研究输入变化；原结果保留，不作为修改后的新结果',
                calendars=status(new[role],self.catalog),calendar_changes=change_summary(old[role],new[role],self.catalog),before=short(old[role]),after=short(new[role])))
        return dict(id=ident,revision=revision,preview_sha256=digest(payload),members=rows,audit=compatible(new),name=name,notes=notes,
            changed=any(r['changed'] for r in rows) or name!=s['name'] or notes!=s['notes'],source_records_changed=0,new_simulations=0)

    def save(self,ident,revision,request,expected):
        p=self.preview(ident,revision,request);require(p['preview_sha256']==expected,'编辑或预览已变化，请重新预览。')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');s=self.get(ident,db=db)
            if s['revision']!=revision:raise Conflict('对比集已被其他操作更新，本次未写入。')
            if not p['changed']:return dict(id=ident,revision=revision,reused=True)
            old,new,name,notes=self._proposal(s,request);at=now();members=copy.deepcopy(s['members'])
            for role,r in new.items():
                if same_record(old[role],r):continue
                r.update(revision=old[role]['revision']+1,saved_at=at);r['record_sha256']=record_digest(r)
                db.execute('INSERT INTO versions VALUES(?,?,?,?)',(r['id'],r['revision'],canonical(r),at));members[role]['record']=ref(r)
            v=dict(schema_version=1,id=ident,revision=revision+1,name=name,notes=notes,created=at,members=members,
                creation_sha256=s['creation_sha256'],change=dict(kind='save',role=request.get('role'),shared=request.get('shared',[]),parent_revision=revision))
            self._publish(db,v)
        return dict(id=ident,revision=v['revision'],reused=False)

    def results(self,ident,revision=None,*,include_monthly=False):
        from inspection_io import reading
        with reading():return self._results(ident,revision,include_monthly=include_monthly)

    def _results(self,ident,revision=None,*,include_monthly=False,only_roles=None):
        s=self.get(ident,revision);records=self.records(s);out=dict(id=ident,revision=s['revision'],set_sha256=s['sha256'],name=s['name'],members={},audit=compatible(records),scope=records['baseline']['factors']['scope'],records={role:ref(r) for role,r in records.items()})
        from batch_results import build
        from execution_queue import Queue
        with Queue(self.root).db() as db:
            completed={r['batch']:r['accepted'] for r in db.execute("SELECT batch,SUM(status IN ('passed','reused')) AS accepted FROM jobs GROUP BY batch")}
        sources={}
        monthly={}
        for role,m in s['members'].items():
            if only_roles is not None and role not in only_roles:continue
            current_recipe=recipe(records[role])
            candidates=copy.deepcopy(m.get('results',[]))+self._bind_results(records[role]);rows=[];seen=set()
            for candidate in candidates:
                if candidate['batch_id'] in seen:continue
                seen.add(candidate['batch_id']);row=dict(batch_id=candidate['batch_id'],usable=False,reason='',reused_source=candidate['source']['id']!=records[role]['id'])
                rows.append(row)
                try:
                    require(current_recipe==candidate['recipe'],'研究输入已改变，此批仅属于旧配置。')
                    key=(candidate['source']['id'],candidate['source']['revision'])
                    if key not in sources:
                        source=self.store.get(*key);sources[key]=(source,ref(source),recipe(source))
                    source,source_ref,source_recipe=sources[key];require(source_ref==candidate['source'],'来源方案快照变化。')
                    require(source_recipe==candidate['recipe'],'来源输入标识不一致。')
                    # Queue state is sufficient to say there are no accepted results.
                    # Only completed candidates warrant reading and hashing model artifacts.
                    if candidate['batch_id'] in completed and not completed[candidate['batch_id']]:
                        row.update(waiting=True,results=[],source=dict(name=source['name'],**candidate['source']));continue
                    d=build(candidate['batch_id'],self.catalog,self.root)
                    require((d['record_id'],d['revision'])==(source['id'],source['revision']),'结果批次未绑定所选来源版本。')
                    require(d['plan_sha256']==candidate['plan_sha256'] and d['record_sha256']==candidate['source']['sha256'],'结果冻结输入与绑定来源不一致。')
                    if include_monthly:
                        monthly[d['id']]={r['index']:r['monthly'] for r in d['results']
                                          if r['accepted'] and r['mode']=='controlled' and r.get('monthly')}
                    row.update(usable=d['counts']['accepted']>0,counts=d['counts'],results=[{k:r.get(k) for k in ('index','site_id','city','accepted','acceptance','status','status_label','loads','days','period','mode','step_minutes','weather_sha256','evidence','pending_warnings','data_retention')} for r in d['results']],source=dict(name=source['name'],**candidate['source']))
                except (ValueError,KeyError,OSError) as e:row['reason']=str(e)
            out['members'][role]=rows
        out['dataset_sha256']=digest(out);out['checked_at']=now()
        # Monthly rows come from the same verified result bytes as the totals.
        # This optional view does not change the existing export identity.
        if include_monthly:out['monthly_by_batch']=monthly
        return out
