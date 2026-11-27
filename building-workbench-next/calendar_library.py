"""Pinned W00-derived calendars, explicit versions and draft-only adoption.

The existing China34 rule is reused for legacy and accepted queue daily inputs.
Ordinary buildings expose preview/versioning only until orientation is adapted.
"""
import copy
from pathlib import Path
from threading import RLock
from foundation import ROOT,digest,now
from contracts import normalize
from component_library import Library,verify,payload_hash
from model_adapter import VerifiedReader
from reference_readiness import baseline
import calendar_preview as cp
import legacy_daily as ld

KIND='workspace_daily_calendar_v1'
LOCK=RLock()

def stable_numbers(value):
    # Browser JSON writes 23.0 as 23. Pin calendar payloads in that same form.
    if isinstance(value,dict):return {k:stable_numbers(v) for k,v in value.items()}
    if isinstance(value,list):return [stable_numbers(v) for v in value]
    if type(value) is float and value.is_integer():return int(value)
    return value

def references(record):
    return [r for r in record['factors']['condition'].get('reference_runs',[]) if r.get('kind')==KIND]

def active_references(record):
    ids={c.get('reference_id') for c in record['factors']['condition'].get('controls',[]) if c.get('mode')=='calendar'}
    return [r for r in references(record) if r['id'] in ids]

def check_active(record,catalog):
    for ref in active_references(record):
        bound(record,catalog,ref)
        from surface_materials import enabled as physical_surface
        if ref['snapshot']['content']['schema_version']==2 and record['provenance']['adapter']=='ordinary_building_v1' and not physical_surface(record):
            from ordinary_orientation import validate_binding
            validate_binding(record,catalog)

def definition(record,catalog):
    """Effective W00 inputs; name, materials, resource budget and aggregation do not drive the rule."""
    r=baseline(normalize(record))
    if r['provenance']['adapter']=='ordinary_building_v1':
        from ordinary_building import source,resolve
        s=source(catalog,r['factors']['building']['id']);_,effective=resolve(r,catalog,s['usage'])
        building=copy.deepcopy(r['factors']['building']);building.pop('usage_profile',None)
        return stable_numbers(dict(building=building,usage=effective,numerics=r['numerics'],adapter=r['provenance']['adapter'],
            source_snapshot=s['snapshot_id'],source_model=s['models']['controlled']))
    if r['provenance']['adapter']!='global_frozen_v011':raise ValueError('当前建筑来源尚未接通逐日日历参考。')
    from building_configuration import baseline as usage_baseline,resolve
    base,_,_=usage_baseline(catalog);shim,effective=resolve(r,catalog,base)
    return stable_numbers(dict(building=shim['factors']['building'],usage=effective,numerics=r['numerics'],
                original_constructions=r['factors']['materials'].get('legacy_construction_overrides',{}),
                adapter=r['provenance']['adapter']))

def snapshot_reference(snapshot):
    return dict(id=snapshot['id'],kind=KIND,snapshot=copy.deepcopy(snapshot))

def basis_differences(saved,current):
    labels={'building':'建筑与构造','usage':'房间作息与温控','adapter':'建筑来源',
            'source_snapshot':'建筑来源版本','source_model':'原墙模型','original_constructions':'原墙构造'}
    differences=[]
    for key in sorted(set(saved)|set(current)):
        if key in saved and key in current and saved[key]==current[key]:continue
        if key=='numerics':
            old,new=saved.get(key,{}),current.get(key,{})
            for field in sorted(set(old)|set(new)):
                if field in old and field in new and old[field]==new[field]:continue
                if field=='step_minutes':
                    differences.append(f'原墙参考步长：日历 {old.get(field)} min，当前 {new.get(field)} min')
                else:differences.append('数值设置 · '+field)
        else:differences.append(labels.get(key,key))
    return differences

def verify_reference(ref):
    if not isinstance(ref,dict) or set(ref)!={'id','kind','snapshot'} or ref['kind']!=KIND:
        raise ValueError('工作区日历引用不完整。')
    s=verify(ref['snapshot'],'calendar');c=s['content']
    pair=(c.get('schema_version'),c.get('acceptance'))
    if ref['id']!=s['id'] or pair not in ((1,'explicit_legacy_evidence_v1'),(2,'accepted_queue_daily_v1')) or c.get('rule')!=cp.PARAMETERS:
        raise ValueError('日历版本、规则或采用依据不一致。')
    sites=c.get('sites',[])
    if not sites or len({r['site_id'] for r in sites})!=len(sites):raise ValueError('日历地点为空或重复。')
    for row in sites:
        if c['schema_version']==2 and (row.get('source_kind')!='accepted_queue_daily_v1' or not row.get('batch_id') or type(row.get('index')) is not int or not row.get('result') or not row.get('evidence')):
            raise ValueError('队列逐日日历缺少绑定的结果和接受依据。')
        values=row.get('calendar')
        if not isinstance(values,list) or len(values)!=365 or any(type(v) is not int or v not in (0,1) for v in values) or digest(values)!=row.get('calendar_sha256'):
            raise ValueError('逐日日历内容与校验不一致。')
        if c['schema_version']==2:
            from transition_confirmation import validate_saved_entry
            validate_saved_entry(row)
    return s

def bound(record,catalog,ref):
    s=verify_reference(ref);c=s['content']
    current_basis=definition(record,catalog)
    if c['basis']!=current_basis:
        raise ValueError('日历参考条件不同：'+'；'.join(basis_differences(c['basis'],current_basis) or ['参考版本结构'])+'。')
    rows={x['site_id']:x for x in c['sites']}
    for sid in record['factors']['scope']['site_ids']:
        if sid not in rows:raise ValueError('新增地点没有此版本的日历，请重新核对范围。')
        site=catalog['sites'][sid]
        if not site.get('eligible') or (site.get('weather') or {}).get('sha256')!=rows[sid]['weather_sha256']:
            raise ValueError('地点气象已变化，日历需重新核对。')
    return rows

def status(record,catalog):
    rows=[]
    for ref in references(record):
        s=ref.get('snapshot',{});item=dict(id=ref.get('id'),name=s.get('name'),revision=s.get('revision'),valid=False,sites=0,active=ref in active_references(record))
        try:
            values=bound(record,catalog,ref);item.update(valid=True,sites=len(values),note='采用条件一致；生成输入时再核对来源文件及实际模型。')
        except (ValueError,KeyError,TypeError,OSError) as exc:item['note']=str(exc)
        rows.append(item)
    return rows

def derive(source,checked,catalog,reader):
    if source['kind']!='china34':raise ValueError('该旧逐日来源的规则登记尚未接通。')
    for ref in checked['evidence']:reader.check(ref)
    batch=reader.json(source['anchor']);rule,rule_ref=cp.registered_rule(batch,reader)
    path=reader.check(dict(path=source['daily_path'],sha256=source['daily_sha256']));daily=ld.csv_rows(path)
    result=cp.calculate([x['heating_kWh'] for x in daily],[x['cooling_kWh'] for x in daily],rule)
    saved=next(x for x in batch['cities'] if x['region_id']==source['region_id'])
    faces=[x['face'] for x in result['days']]
    if faces!=saved['daily_cooling_face'] or [{k:s[k] for k in ('day_of_year','date','at','to')} for s in result['switches']]!=saved['switches']:
        raise ValueError('新重现与已登记日历不一致。')
    if result['transition_review_needed']:raise ValueError('出现多段或不确定季节，需要单独讨论，未自动合并。')
    return result,dict(source_id=source['id'],daily=dict(path=source['daily_path'],sha256=source['daily_sha256']),
        weather_sha256=source['weather_sha256'],physical_sha256=checked['physical_sha256'],rule_source=rule_ref,
        anchor=source['anchor'],evidence=checked['evidence'],warnings=checked['warnings'],calendar=faces,calendar_sha256=digest(faces),
        switches=saved['switches'])

def engine_matches(record,source,reader):
    engine=record['numerics'].get('engine_files',{})
    executables=[h for p,h in engine.items() if Path(p).name.lower()=='energyplus.exe']
    if executables!=[source['engine']['sha256']]:raise ValueError('当前求解程序与旧逐日参考不同，需重新准备参考。')
    for p,h in engine.items():reader.check(dict(path=p,sha256=h))

def with_reference(record,snapshot):
    from surface_materials import enabled as physical_surface
    if snapshot['content'].get('schema_version')==2 and record['provenance']['adapter']=='ordinary_building_v1' and not physical_surface(record):
        from ordinary_orientation import EXECUTION_VERIFIED
        if not EXECUTION_VERIFIED:raise ValueError('五层表面光学切换短期实跑尚未完成。')
    r=copy.deepcopy(record);controls=r['factors']['condition']['controls']
    if not r['factors']['materials']['applications'] or not any(c['channel']=='orientation' for c in controls):
        raise ValueError('可先保存日历版本；启用光学切换需先配置材料应用及两组表面光学参数。')
    for c in controls:
        if c['channel']=='orientation':
            c.update(mode='calendar',reference_id=snapshot['id'])
            if any(d.get('model')=='layer_stack_v1' for d in r['factors']['materials']['definitions']):
                c.update(face_basis='exposed_layer',face_id='A')
    r['factors']['condition']['reference_runs']=[snapshot_reference(snapshot)]
    return r

def temporary_snapshot(content):
    s=dict(kind='calendar',id='component_'+'0'*32,revision=1,name='逐日光学切换预览',created='preview',content=content)
    s['sha256']=payload_hash(s);return s

def prepare(record,catalog,root=ROOT,transition_confirmations=None):
    from inspection_io import reading
    with reading():return _prepare(record,catalog,root,transition_confirmations)

def _prepare(record,catalog,root=ROOT,transition_confirmations=None):
    record=normalize(record);out=dict(record_sha256=digest(record),checked_at=now(),rows=[],issues=[],can_save=False,can_apply=False,
        bound=status(record,catalog),versions=[],application_issues=[],phase='blocked',
        scope_sites=[dict(site_id=sid,city=catalog['sites'][sid]['name']) for sid in record['factors']['scope']['site_ids']])
    try:basis=definition(record,catalog)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        out['issues'].append(str(exc))
        return out
    sites=set(record['factors']['scope']['site_ids'])
    out['reference_differences']=[]
    for version in Library(root).all('calendar'):
        prior=version['content']
        shared=[s for s in prior['sites'] if s['site_id'] in sites]
        if not shared:continue
        differences=basis_differences(prior['basis'],basis)
        for s in shared:
            weather=catalog['sites'][s['site_id']].get('weather') or {}
            if s.get('weather_sha256')!=weather.get('sha256'):differences.append(s['city']+' · 气象文件版本')
        if differences:out['reference_differences'].append(dict(name=version['name'],revision=version['revision'],differences=differences))
    if record['provenance']['adapter']=='ordinary_building_v1' or (catalog.get('example_controls') and record['provenance']['adapter']=='global_frozen_v011'):
        from queue_calendar import prepare as queue_prepare
        return queue_prepare(record,catalog,root,out,basis,transition_confirmations)
    if transition_confirmations:raise ValueError('本次季节确认只接通已接受的队列逐日参考。')
    annual=copy.deepcopy(record);annual['factors']['scope']['period']=[1,1,12,31]
    inspected=ld.build(annual,catalog,root);sources,issues=ld.discover(catalog,root);out['issues'].extend(inspected['issues']+issues)
    out['phase']='inspected'
    sources={s['id']:s for s in sources};reader=VerifiedReader(catalog);entries=[]
    for position,row in enumerate(inspected['rows']):
        from inspection_io import progress
        progress('推导光学切换日历',position,len(inspected['rows']),row['city'])
        item=dict(site_id=row['site_id'],city=row['city'],ready=False,issues=[],preview=None);out['rows'].append(item)
        eligible=[s for s in row['sources'] if s['daily_checks_passed'] and s['input_match'] and s['kind']=='china34']
        if len(eligible)!=1:
            item['issues']=[row.get('issue') or ('找到多个匹配来源，需明确采用哪个。' if len(eligible)>1 else '没有完整且输入匹配的已接通逐日来源。')]
            item['issues']+=list(dict.fromkeys(s.get('compatibility','') for s in row['sources'] if s.get('compatibility')))
            continue
        checked=eligible[0]
        try:
            engine_matches(record,sources[checked['id']],reader)
            result,entry=derive(sources[checked['id']],checked,catalog,reader);entry.update(site_id=row['site_id'],city=row['city']);entries.append(entry)
            result.update(name=row['city'],source=dict(warnings=entry['warnings']),rule=cp.PARAMETERS)
            item.update(ready=True,preview=result)
        except (ValueError,KeyError,TypeError,OSError) as exc:item['issues'].append(str(exc))
    reader.unchanged()
    if not out['rows'] or len(entries)!=len(out['rows']) or out['issues']:return out
    content=stable_numbers(dict(schema_version=1,basis=basis,rule=cp.PARAMETERS,sites=sorted(entries,key=lambda x:x['site_id']),acceptance='explicit_legacy_evidence_v1'))
    out.update(can_save=True,content_sha256=digest(content),content=content)
    for s in Library(root).all('calendar'):
        if s['content']==content:out['versions'].append({k:s[k] for k in ('id','revision','name','created','sha256')})
    try:
        candidate=with_reference(record,temporary_snapshot(content))
        from model_adapter import capability
        cap=capability(candidate,catalog);out['can_apply']=cap['supported'];out['application_issues']=cap['reasons']
    except (ValueError,KeyError,TypeError,OSError) as exc:out['application_issues']=[str(exc)]
    return out

def save_or_apply(record,catalog,root,expected,accept,action,record_sha256,parent=None,transition_confirmations=None):
    if action not in ('save','apply') or accept is not True:raise ValueError('请明确接受本轮展示的参考来源、原警告和已有规则。')
    fresh=prepare(record,catalog,root,transition_confirmations=transition_confirmations) if transition_confirmations is not None else prepare(record,catalog,root)
    return _save_prepared(record,catalog,root,expected,accept,action,record_sha256,fresh,parent)

def _save_prepared(record,catalog,root,expected,accept,action,record_sha256,fresh,parent=None):
    # Internal boundary: callers must freshly prepare or fully revalidate a service-owned inspection.
    if action not in ('save','apply') or accept is not True:raise ValueError('请明确接受本轮展示的参考来源、原警告和已有规则。')
    if not fresh['can_save'] or fresh.get('content_sha256')!=expected or fresh['record_sha256']!=record_sha256:raise ValueError('方案、参考条件或来源已变化，请重新预览。')
    if action=='apply' and not fresh['can_apply']:raise ValueError('当前不能启用光学切换：'+'；'.join(fresh['application_issues']))
    content=fresh['content']
    with LOCK:
        library=Library(root)
        if parent is not None:
            if content['schema_version']!=2:raise ValueError('当前来源不支持独立选择父日历版本。')
            from queue_calendar import check_parent
            check_parent(content,parent,library)
        same=[s for s in library.all('calendar') if s['content']==content and (parent is None or (s['id'],s['revision'])==(parent['id'],parent['revision']))]
        if same:snapshot=same[0];reused=True
        else:
            refs=references(record)
            if parent is None and len(refs)==1 and content['schema_version']==1:
                previous=verify_reference(refs[0]);parent={k:previous[k] for k in ('id','revision')}
            name=('逐日光学切换 · '+record['factors']['building']['name']+' · '+str(len(content['sites']))+' 地点')[:100]
            snapshot=library.save('calendar',name,content,parent);reused=False
    result=dict(snapshot=snapshot,reused=reused,applied=action=='apply',new_simulations=0)
    if action=='apply':result['condition']=with_reference(record,snapshot)['factors']['condition']
    return result

def verify_for_site(record,catalog,site_id,reader):
    """Recheck registered evidence and actual baseline before any generated input uses it."""
    refs=active_references(record)
    if not refs:return
    queue_refs=[ref for ref in refs if ref['snapshot']['content']['schema_version']==2]
    if queue_refs:
        from queue_calendar import verify_for_site as verify_queue
        for ref in queue_refs:verify_queue(record,catalog,ref,site_id,reader)
        refs=[ref for ref in refs if ref not in queue_refs]
        if not refs:return
    sources,issues=ld.discover(catalog);sources={s['id']:s for s in sources}
    if issues:raise ValueError('；'.join(issues))
    for ref in refs:
        expected=bound(record,catalog,ref)[site_id];source=sources.get(expected['source_id'])
        if source is None:raise ValueError('日历参考来源已不在登记目录中。')
        engine_matches(record,source,reader)
        checked=ld.inspect(source,catalog,reader)
        if not checked['daily_checks_passed']:raise ValueError('日历逐日来源核对失败：'+'；'.join(checked['issues']))
        result,actual=derive(source,checked,catalog,reader)
        actual.update(site_id=site_id,city=expected['city'])
        if actual!=expected:raise ValueError('日历版本的来源、规则或选用的光学参数组已变化，请重新预览。')
        r=baseline(record);r['factors']['scope']['period']=[1,1,12,31]
        from model_adapter import compile_case
        model,report=compile_case(r,site_id,catalog,reader,'controlled');reader.check(report['weather'])
        if digest(ld.model_value(model,ROOT,reader))!=expected['physical_sha256']:raise ValueError('实际原构造模型与日历参考不同，请重新核对。')
