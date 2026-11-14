"""Bounded input preparation: one model at a time, separate verified case audits.

This changes packaging, not model compilation, output selection or the executor.
Completed checkpoints are only reused after all source and artifact hashes pass.
"""
from pathlib import Path
import gc,json,os,shutil,time,uuid,sqlite3
from contextvars import ContextVar
from foundation import ROOT,owned,read_json,write_json,digest,sha,now
from model_adapter import VerifiedReader,BUILD_LOCK,compile_case,uses_dynamic_adapter,ADAPTER
from contracts import normalize,recipe_digest

FORMAT='case_audits_v2'
EVENTS=ContextVar('input_preparation_progress',default=None)

def emit(**value):
    if EVENTS.get():EVENTS.get()(**value)

def resource_gate(root,progress,index,total):
    from resources import snapshot
    policy=dict(reserve_gib=1.,disk_reserve_gib=5.)
    db=Path(root)/'data/execution/queue.sqlite'
    if db.exists():
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
            row=c.execute("SELECT value FROM settings WHERE key='resources'").fetchone()
            if row:policy.update(json.loads(row[0]))
    while True:
        machine=snapshot(root)
        if machine['disk_free_gib']<policy['disk_reserve_gib']+.15:raise ValueError('磁盘余量不足以保留工作区设置并写入下一算例；完成项保留，可续接。')
        if min(machine['available_gib'],machine['commit_available_gib'])>=policy['reserve_gib']+.35:return
        progress(stage='等待内存余量，已完成项保留',completed=index,total=total)
        time.sleep(2)
SUMMARY=('adapter','site_id','city','mode','period','step_minutes','source_model','weather',
         'dependencies','source_model_digest','generated_model_digest','exact_input_match',
         'untouched_fields_match','execution_enabled','numerical_equivalence')

def compact_write(path,value,root):
    path=owned(path,root);path.parent.mkdir(parents=True,exist_ok=True)
    temp=owned(path.with_name('.'+path.name+'.'+uuid.uuid4().hex),root)
    with temp.open('w',encoding='utf-8',newline='') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        stream.flush();os.fsync(stream.fileno())
    if temp.stat().st_size>32*1024**2:raise ValueError('单算例文件超过 32 MiB，需要进一步拆分详情；已完成算例保留。')
    os.replace(temp,path)

def read_audit(folder,row):
    ref=row.get('audit')
    if not ref:return row
    path=owned(Path(folder)/ref['file'],folder)
    if ref.get('kind')!='case_audit_v1' or sha(path)!=ref['sha256']:raise ValueError('算例详情校验不符，请保留输入包并核查。')
    report=read_json(path)
    if any(report.get(k)!=row[k] for k in SUMMARY if k in row):raise ValueError('算例摘要与详情不一致。')
    if len(report.get('differences',[]))!=row['difference_count']:raise ValueError('算例差异数量不一致。')
    return report

def verify_case(folder,row):
    p=owned(Path(folder)/row['model_file'],folder)
    if sha(p)!=row['model_sha256']:raise ValueError('已完成模型内容变化，请保留并核查：'+p.name)
    read_audit(folder,row)

def code_identity():
    import model_adapter
    names=('construction_library.py','material_types.py','surface_materials.py','model_adapter.py','dynamic_adapter.py','calendar_library.py','calendar_preview.py',
        'weather_import.py','source_locations.py','building_configuration.py','component_library.py',
        'usage_schedules.py','ordinary_building.py','ordinary_envelope.py','ordinary_materials.py',
        'ordinary_orientation.py','queue_calendar.py','transition_confirmation.py','workspace_setup.py')
    base=Path(model_adapter.__file__).parent
    return {n:sha(base/n) for n in names}|{'input_pipeline.py':sha(__file__)}

def build_bundle(record,catalog,root=ROOT,site_ids=None,progress=None):
    with BUILD_LOCK:return _build(record,catalog,Path(root).resolve(),site_ids,progress or (lambda **kw:None))

def _build(record,catalog,root,site_ids,progress):
    from source_locations import prepare_case
    sites=record['factors']['scope']['site_ids']
    if site_ids is not None and (not isinstance(site_ids,list) or not site_ids or len(set(site_ids))!=len(site_ids) or not set(site_ids)<=set(sites)):
        raise ValueError('本批地点必须是保存范围内的非重复子集。')
    selected=sites if site_ids is None else [s for s in sites if s in site_ids]
    modes=['controlled','natural'] if record['factors']['condition']['operation']['mode']=='both' else [None]
    requested=[(s,m) for s in selected for m in modes];total=len(requested)
    codes=code_identity();identity=dict(recipe=recipe_digest(normalize(record)),record=digest(record),
        adapter_sha256=digest(codes),format=FORMAT,catalog_sha256=digest(catalog),selected_site_ids=selected)
    ident='inputs_'+digest(identity)[:32];final=owned(root/'data/model-inputs'/ident,root)
    work=owned(final.parent/('.building_'+ident),root)
    from workspace_setup import engine_files
    engine=engine_files(record,catalog);sources={}
    def checked(refs):
        reader=VerifiedReader(catalog)
        for ref in refs:reader.check(ref)
        reader.unchanged();return reader
    if final.exists():
        saved=read_json(final/'manifest.json')
        if saved['identity']!=identity or saved['case_count']!=total or read_json(final/'record.json')!=record:raise ValueError('已有输入包绑定内容不一致。')
        progress(stage='复核已有输入与来源',completed=0,total=total)
        reader=checked(saved['verified_sources'])
        for i,row in enumerate(saved['cases']):
            verify_case(final,row);progress(stage='复核已有输入',completed=i+1,total=total,city=row['city'])
        reader.unchanged();return dict(saved,reused=True)
    rows=[];durations=[]
    work.mkdir(parents=True,exist_ok=True)
    checkpoint=work/'checkpoint.json'
    if checkpoint.exists():
        saved=read_json(checkpoint)
        if saved['identity']!=identity:raise ValueError('未完成输入的身份不一致，请保留并核查。')
        progress(stage='复核可续接算例',completed=0,total=total)
        checked(saved['sources']);sources={x['path']:x for x in saved['sources']}
        rows=saved['cases'];durations=saved['case_seconds']
        if len(rows)>total:raise ValueError('已完成算例数量异常。')
        for i,row in enumerate(rows):
            sid,mode=requested[i]
            if row['site_id']!=sid or (mode is not None and row['mode']!=mode):raise ValueError('未完成清单顺序与请求不一致。')
            verify_case(work,row)
    resumed=len(rows)
    for index in range(resumed,total):
        resource_gate(root,progress,index,total)
        site,mode=requested[index];start=time.monotonic()
        progress(stage='生成与核对单地点模型',completed=index,total=total,city=catalog['sites'][site]['name'],case_seconds=durations,resumed=resumed)
        reader=VerifiedReader(catalog)
        for p,h in engine.items():reader.check(dict(path=p,sha256=h))
        model,report=prepare_case(*compile_case(record,site,catalog,reader,operation_mode=mode),reader)
        progress(stage='保存模型与独立详情',completed=index,total=total,city=report['city'],case_seconds=durations,resumed=resumed)
        if shutil.disk_usage(root).free<512*1024**2:raise ValueError('可用空间不足 512 MiB，已完成输入保留；释放空间后可续接。')
        name=f'{index+1:03d}.epJSON';audit=f'audit-{index+1:03d}.json'
        compact_write(work/name,model,root);compact_write(work/audit,report,root)
        reader.unchanged()
        for p,ref in ((r['path'],r) for r in reader.checked.values()):
            if p in sources and sources[p]['sha256']!=ref['sha256']:raise ValueError('批内来源内容变化，未发布输入包。')
            sources[p]=ref
        # Dependencies stay in each complete audit and once in verified_sources.
        # Repeating the common source list in every summary grows with city count.
        row={k:report[k] for k in SUMMARY if k in report and k!='dependencies'}
        row.update(model_file=name,model_sha256=sha(work/name),difference_count=len(report.get('differences',[])),
            audit=dict(kind='case_audit_v1',file=audit,sha256=sha(work/audit)))
        rows.append(row);durations.append(round(time.monotonic()-start,3))
        del model,report,reader;gc.collect()
        compact_write(checkpoint,dict(identity=identity,cases=rows,sources=list(sources.values()),case_seconds=durations),root)
        progress(stage='单地点输入已保存',completed=index+1,total=total,city=row['city'],case_seconds=durations,resumed=resumed)
    progress(stage='复核全部来源并发布清单',completed=total,total=total,case_seconds=durations,resumed=resumed)
    checked(sources.values())
    if codes!=code_identity():raise ValueError('生成期间程序变化，未发布输入包；已完成算例保留。')
    manifest=dict(id=ident,format=FORMAT,created=now(),adapter='ordinary_building_v1' if record['provenance']['adapter']=='ordinary_building_v1' else ('drawing26_state_v1' if uses_dynamic_adapter(record) else ADAPTER),
        identity=identity,record_id=record['id'],revision=record['revision'],record_name=record['name'],recipe_sha256=identity['recipe'],
        cases=rows,case_count=total,exact_matches=sum(r['exact_input_match'] for r in rows),verified_sources=list(sources.values()),
        source_checks=len(sources),engine_files=engine,execution_enabled=False,new_simulations=0,
        generated_bytes=sum(p.stat().st_size for p in work.glob('*.epJSON')),case_seconds=durations,resumed_cases=resumed)
    if selected!=sites:manifest.update(selected_site_ids=selected,scope_site_count=len(sites),partial_scope=True)
    compact_write(work/'record.json',record,root);compact_write(work/'manifest.json',manifest,root)
    owned(work,root);owned(final,root);work.rename(final)
    return manifest

def prepare(root,ident,output_contract='monthly_period_v1'):
    """Freeze one model at a time using the unchanged executor's primitives."""
    import execution_inputs as ex
    root=Path(root).resolve();folder=owned(root/'data/model-inputs'/ident,root)
    manifest=read_json(folder/'manifest.json')
    if manifest.get('format')!=FORMAT:return ex.prepare(root,ident,output_contract)
    record=read_json(folder/'record.json');manifest_hash=sha(folder/'manifest.json')
    if manifest['id']!=ident or digest(record)!=manifest['identity']['record']:raise ValueError('输入包绑定内容变化。')
    ex.validate_output(record,output_contract)
    reader=VerifiedReader();refs={r['path']:r['sha256'] for r in manifest['verified_sources']}
    for ref in manifest['verified_sources']:reader.check(ref)
    engine=manifest['engine_files'];engines=[p for p in engine if Path(p).name.lower()=='energyplus.exe']
    if len(engines)!=1:raise ValueError('执行引擎登记不唯一。')
    for p,h in engine.items():reader.check(dict(path=p,sha256=h))
    token='review_'+uuid.uuid4().hex;target=owned(root/'data/execution/reviews'/token,root)
    staging=owned(target.with_name('.preparing_'+token),root);codes=ex.code_hashes();cases=[]
    for index,row in enumerate(manifest['cases']):
        resource_gate(root,emit,index,len(manifest['cases']))
        emit(stage='逐地点准备预算清单',completed=index,total=len(manifest['cases']),city=row['city'])
        verify_case(folder,row)
        original=reader.json(dict(path=str(owned(folder/row['model_file'],folder)),sha256=row['model_sha256']))
        if output_contract==ex.DAILY_CONTRACT:
            from daily_reference import prepare_model
            model=prepare_model(original)
        else:model=ex.compact_model(original)
        del original
        weather=row['weather']['path'] if isinstance(row['weather'],dict) else row['weather']
        required={str(Path(weather).resolve()):None}
        for v in model.get('Schedule:File',{}).values():required[str(Path(v['file_name']).resolve())]=None
        for p in required:
            if p not in refs:raise ValueError('模型引用未登记：'+p)
            required[p]=refs[p]
        for v in model.get('Schedule:File',{}).values():
            p=str(Path(v['file_name']).resolve());alias=ex.portable_reference(root,p,required[p],'.txt');v['file_name']=alias;required[alias]=required[p]
        p=str(Path(weather).resolve());weather=ex.portable_reference(root,p,required[p],'.epw');required[weather]=required[p]
        mode=row.get('mode') or record['factors']['condition']['operation']['mode']
        if output_contract==ex.DAILY_CONTRACT and (mode!='controlled' or row['period']!=[1,1,12,31]):raise ValueError('逐日参考仅支持全年温控。')
        identity=digest(dict(model=digest(model),dependencies=required,engine_files=engine,output_contract=output_contract))
        name=f'{index:03d}.epJSON';compact_write(staging/name,model,root)
        case=dict(site_id=row['site_id'],city=row['city'],mode=mode,period=row['period'],step_minutes=row['step_minutes'],
            weather=weather,dependencies=required,physical_digest=digest({k:v for k,v in model.items() if not k.startswith('Output')}),
            identity=digest(dict(inputs=identity,executor=codes)),index=index,model_file=name,model_sha256=sha(staging/name))
        if output_contract==ex.DAILY_CONTRACT:case['output_contract']=output_contract
        cases.append(case);del model;gc.collect()
        emit(stage='算例清单已保存',completed=index+1,total=len(manifest['cases']),city=row['city'])
    reader.unchanged()
    if sha(folder/'manifest.json')!=manifest_hash or ex.code_hashes()!=codes:raise ValueError('准备期间输入或程序变化，未发布清单。')
    plan=dict(id=token,created=now(),bundle_id=ident,bundle_sha256=manifest_hash,record_name=record['name'],record_id=record['id'],revision=record['revision'],
        record_sha256=digest(record),engine=engines[0],engine_files=engine,cases=cases,case_count=len(cases),code_hashes=codes,
        output_contract=output_contract,conditioned_area_m2=record['factors']['building'].get('conditioned_area_m2'))
    compact_write(staging/'record.json',record,root);compact_write(staging/'plan.json',plan,root)
    owned(staging,root);owned(target,root);staging.rename(target)
    return ex.public(plan,root)
