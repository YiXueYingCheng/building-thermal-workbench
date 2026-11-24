"""Freeze executable plans; output selection changes no physical or control fields."""
import copy
from pathlib import Path
import re
import uuid
import os
import output_resolution
from schedule_sharing import share_files
from foundation import ROOT, read_json, write_json, sha, digest, owned, now
from model_adapter import VerifiedReader

OUTPUT_CONTRACT = 'monthly_period_v1'
DAILY_CONTRACT = 'daily_sensible_reference_v1'
CODE_FILES = ('execution_inputs.py','execution_results.py','execution_queue.py','execution_worker.py','resources.py','cpu_budget.py','worker_runtime.py','daily_reference.py','resource_history.py','output_storage.py','output_resolution.py','wb_warmup.py','site_recalculation.py','schedule_sharing.py','history_locations.py')

OBSERVER = {'WB Daily Warmup': {'run_during_warmup_days':'Yes',
            'python_module_name':'wb_warmup','plugin_class_name':'DailyRoomTemperatures'}}

def add_warmup_observer(model, engine):
    periods = model.get('RunPeriod', {})
    install = Path(engine).parent
    if (len(periods) != 1 or not model.get('Zone') or
            any(key.startswith('PythonPlugin:') for key in model) or
            not (install/'pyenergyplus/plugin.py').is_file() or not (install/'python_lib').is_dir()):
        return None
    building = next(iter(model['Building'].values()))
    model['PythonPlugin:Instance'] = copy.deepcopy(OBSERVER)
    return dict(environment=next(iter(periods)), tolerance=building.get('temperature_convergence_tolerance_value', 0.4),
                minimum_days=building.get('minimum_number_of_warmup_days', 6))

def stage_observer(folder, codes):
    import shutil
    source = ROOT/'wb_warmup.py'
    target = folder/source.name
    shutil.copyfile(source, target)
    if sha(target) != codes[str(source)]:
        raise ValueError('预热记录程序与冻结版本不一致，请重新准备。')

def code_hashes():
    return {str(ROOT/n):sha(ROOT/n) for n in CODE_FILES}

def execution_revision(frozen,root,*,historical=False):
    actual=code_hashes()
    if frozen==actual:return dict(kind='frozen',code_hashes=actual)
    # A frozen parent may be inspected at a new location. Only exact named
    # file sets from the running program or an explicit upgrade are accepted.
    def names(values):
        by_name={Path(name).name:checksum for name,checksum in values.items()}
        if len(by_name)!=len(values):raise ValueError('冻结执行程序包含重复文件名。')
        return by_name
    if historical:
        if names(frozen)==names(actual):return dict(kind='relocated_frozen',code_hashes=actual)
    contract_path=ROOT.parent/'EXECUTOR_COMPATIBILITY.json'
    edges=[]
    historical_baselines={}
    if contract_path.is_file():
        contract=read_json(contract_path)
        for key in ('history_location_update','schedule_sharing_update','scheduling_update'):
            item=contract.get(key)
            if item:edges.append((item['from'],item['to'],item['id']))
        if historical and contract.get('schema')==2:
            historical_baselines=contract.get('historical_baselines',{})
            item=contract.get('integrated_history_read')
            if item:edges.append((item['from'],item['to'],item['id']))
    path=Path(root)/'data/execution/runtime-compatibility.json'
    if path.is_file():
        for row in read_json(path).get('upgrades',[]):
            if not row.get('historical_only') or historical:
                edges.append((names(row['from_code_hashes']),names(row['to_code_hashes']),row['id']))
    local_names=all(Path(p).parent==ROOT for p in frozen)
    if historical or local_names:
        known=[names(actual)]
        for current in known:
            if historical_baselines and current==contract['to_code_hashes']:
                for version, checksums in historical_baselines.items():
                    if checksums and names(frozen)==checksums:
                        return dict(kind='audited_historical_result_read',id=version,code_hashes=actual)
            for before,after,ident in edges:
                if after!=current or not before:continue
                if names(frozen)==before:return dict(kind='audited_scheduling_update',id=ident,code_hashes=actual)
                if before not in known:known.append(before)
    raise ValueError('计算程序已更新，请重新准备计算。')

def portable_reference(root,path,checksum,suffix):
    """Only Unicode/long external paths need small content-addressed local copies."""
    path=Path(path).resolve()
    if str(path).isascii() and len(str(path))<230:return str(path)
    asset_root=Path(root)/'assets'
    if not str(asset_root).isascii() or len(str(asset_root))>180:
        from foundation import config
        import tempfile
        configured=config(root).get('reference_cache_root')
        candidates=[Path(configured)] if configured else [Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())/'BuildingThermalWorkbench'/'references',Path(tempfile.gettempdir())/'BTWB-references']
        asset_root=None
        for base in candidates:
            if not base.is_absolute() or not str(base).isascii() or len(str(base))>150:continue
            candidate=base/('workspace_'+digest(str(Path(root).resolve()))[:16])
            try:
                candidate.mkdir(parents=True,exist_ok=True)
                marker=candidate/'workspace.json';identity=dict(workspace=str(Path(root).resolve()),kind='hashed_reference_copies_v1')
                if marker.exists() and read_json(marker)!=identity:raise ValueError('计算引用缓存归属不符，请保留核查。')
                if not marker.exists():write_json(marker,identity,candidate)
                asset_root=candidate;break
            except OSError:continue
        if asset_root is None:
            raise ValueError('工作区可以使用中文路径，但气象与作息需要可写的短英文引用目录。请在 config.json 的 reference_cache_root 中设置独立的英文文件夹，例如 D:/BTWB-references；无需移动已有工作区或结果。')
    target=owned(asset_root/(checksum[:24]+suffix),asset_root);target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        data=path.read_bytes()
        import hashlib
        if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError('复制期间来源内容变化。')
        temporary=target.with_name('.'+uuid.uuid4().hex)
        with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:temporary.rename(target)
        except FileExistsError:temporary.unlink()
    if sha(target)!=checksum:raise ValueError('已有便携引用内容不符，请保留并核查。')
    if not str(target).isascii() or len(str(target))>=230:raise ValueError('计算运行目录需要较短的英文路径。')
    return str(target)

def compact_model(original):
    model=copy.deepcopy(original)
    # Retain all requested variable identities, but only summary frequencies.
    requests={}
    for row in original.get('Output:Variable',{}).values():
        key=(row.get('key_value','*'),row['variable_name'],row.get('schedule_name'))
        requests[key]=row
    for name in ('Zone Mean Air Temperature','Zone Operative Temperature'):
        requests[('*',name,None)]={'key_value':'*','variable_name':name}
    if model.get('ZoneHVAC:IdealLoadsAirSystem'):
        for name in ('Zone Ideal Loads Zone Sensible Heating Energy','Zone Ideal Loads Zone Sensible Cooling Energy'):
            requests[('*',name,None)]={'key_value':'*','variable_name':name}
    rows={}
    for row in requests.values():
        for freq in ('Monthly','RunPeriod'):
            rows['NX_Output_'+str(len(rows)+1)]={**row,'reporting_frequency':freq}
    model['Output:Variable']=rows
    for kind in ('Output:Meter','Output:Meter:MeterFileOnly','Output:Meter:Cumulative','Output:Meter:Cumulative:MeterFileOnly'):
        if kind in model:
            model[kind]={n:{**v,'reporting_frequency':'RunPeriod'} for n,v in model[kind].items()}
    model['Output:SQLite']={'NX_SQLite':{'option_type':'SimpleAndTabular'}}
    # These are output controls only, never EMS/control calling points.
    model.pop('Output:JSON',None)
    model['OutputControl:Files']={'NX_Files':{'output_csv':'No','output_mtr':'No','output_eso':'No','output_sqlite':'Yes'}}
    return model

def validate_output(record, output_contract):
    if output_contract not in (OUTPUT_CONTRACT,DAILY_CONTRACT):output_resolution.validate(record,output_contract)
    if output_contract==DAILY_CONTRACT:
        from daily_reference import require_baseline
        require_baseline(record)


def bundle(root,ident,expected=None,output_contract=OUTPUT_CONTRACT,*,observe_warmup=True,share_schedules=True):
    root=Path(root).resolve()
    if not re.fullmatch(r'inputs_[a-f0-9]{32}',str(ident)):raise ValueError('输入包编号不正确。')
    folder=owned(root/'data/model-inputs'/ident,root)
    manifest=read_json(folder/'manifest.json')
    if manifest['id']!=ident or (expected and sha(folder/'manifest.json')!=expected):raise ValueError('输入包清单变化，请重新准备计算。')
    record=read_json(folder/'record.json')
    if digest(record)!=manifest['identity']['record']:raise ValueError('绑定的方案快照变化。')
    validate_output(record,output_contract)
    reader=VerifiedReader()
    for ref in manifest['verified_sources']:reader.check(ref)
    engine_files=manifest.get('engine_files') or record['numerics'].get('engine_files')
    if not engine_files:raise ValueError('旧输入包未绑定执行引擎，请重新生成输入。')
    for path,checksum in engine_files.items():reader.check(dict(path=path,sha256=checksum))
    engines=[p for p in engine_files if Path(p).name.lower()=='energyplus.exe']
    if len(engines)!=1:raise ValueError('未能确定唯一的已登记计算引擎。')
    cases=[]
    for row in manifest['cases']:
        model=reader.json(dict(path=str(owned(folder/row['model_file'],folder)),sha256=row['model_sha256']))
        if output_contract==DAILY_CONTRACT:
            from daily_reference import prepare_model
            prepared=prepare_model(model)
        elif output_contract in output_resolution.CONTRACTS:prepared=output_resolution.prepare(model,output_contract)
        else:prepared=compact_model(model)
        # Verify every external schedule is already registered, never implicit cwd search.
        refs={str(Path(r['path']).resolve()):r['sha256'] for r in manifest['verified_sources']}
        weather=row['weather']['path'] if isinstance(row['weather'],dict) else row['weather']
        required={str(Path(weather).resolve()):None}
        for v in prepared.get('Schedule:File',{}).values():required[str(Path(v['file_name']).resolve())]=None
        for p in required:
            if p not in refs:raise ValueError('模型引用尚未登记的外部文件：'+p)
            required[p]=refs[p]
        sharing=share_files(prepared,required) if share_schedules else None
        for v in prepared.get('Schedule:File',{}).values():
            p=str(Path(v['file_name']).resolve());alias=portable_reference(root,p,required[p],'.txt')
            v['file_name']=alias;required[alias]=required[p]
        original_weather=str(Path(weather).resolve());weather=portable_reference(root,original_weather,required[original_weather],'.epw');required[weather]=required[original_weather]
        mode=row.get('mode') or record['factors']['condition']['operation']['mode']
        observer=add_warmup_observer(prepared,engines[0]) if observe_warmup else None
        physical={k:v for k,v in prepared.items() if not k.startswith('Output')}
        if output_contract==DAILY_CONTRACT and (mode!='controlled' or row['period']!=[1,1,12,31]):raise ValueError('逐日参考算例必须为全年温控。')
        identity=dict(model=digest(prepared),dependencies=required,engine_files=engine_files,output_contract=output_contract)
        if sharing:identity['schedule_sharing']=sharing
        cases.append(dict(site_id=row['site_id'],city=row['city'],mode=mode,period=row['period'],step_minutes=row['step_minutes'],
            weather=weather,dependencies=required,model=prepared,physical_digest=digest(physical),identity=digest(identity)))
        if observer:cases[-1]['warmup_observer']=observer
        if sharing:cases[-1]['schedule_sharing']=sharing
        if output_contract!=OUTPUT_CONTRACT:cases[-1]['output_contract']=output_contract
    reader.unchanged()
    return manifest,record,engines[0],engine_files,cases

def prepare(root,ident,output_contract=OUTPUT_CONTRACT):
    root=Path(root).resolve();manifest,record,engine,engine_files,cases=bundle(root,ident,output_contract=output_contract)
    token='review_'+uuid.uuid4().hex;folder=owned(root/'data/execution/reviews'/token,root)
    codes=code_hashes()
    for index,c in enumerate(cases):
        model=c.pop('model');name=f'{index:03d}.epJSON';write_json(folder/name,model,root)
        c.update(index=index,model_file=name,model_sha256=sha(folder/name))
        c['identity']=digest(dict(inputs=c['identity'],executor=codes))
    if any(c.get('warmup_observer') for c in cases):stage_observer(folder,codes)
    plan=dict(id=token,created=now(),bundle_id=ident,bundle_sha256=sha(root/'data/model-inputs'/ident/'manifest.json'),
        record_name=record['name'],record_id=record['id'],revision=record['revision'],record_sha256=digest(record),
        engine=engine,engine_files=engine_files,cases=cases,case_count=len(cases),code_hashes=codes,
        output_contract=output_contract,conditioned_area_m2=record['factors']['building'].get('conditioned_area_m2'))
    write_json(folder/'record.json',record,root);write_json(folder/'plan.json',plan,root)
    return public(plan,root)

def public(plan,root):
    return {k:plan[k] for k in ('id','created','bundle_id','record_name','record_id','revision','case_count','output_contract')} | dict(
        cases=[{k:c[k] for k in ('index','site_id','city','mode','period','step_minutes')} |
               (dict(schedule_counts=dict(original=c['schedule_sharing']['original_count'],
                                          retained=c['schedule_sharing']['retained_count'])) if c.get('schedule_sharing') else {})
               for c in plan['cases']],
        output_detail=output_resolution.description(plan['output_contract'],plan['cases'][0]['period'],plan['cases'][0]['step_minutes']) if plan['cases'] else None,
        plan_sha256=sha(Path(root)/'data/execution/reviews'/plan['id']/'plan.json'))

def load_review(root,ident,checksum,*,historical=False,only_index=None):
    if not re.fullmatch(r'review_[a-f0-9]{32}',str(ident)):raise ValueError('计算预览编号不正确。')
    folder=owned(Path(root)/'data/execution/reviews'/ident,root)
    if sha(folder/'plan.json')!=checksum:raise ValueError('待提交的计算清单变化，请重新预览。')
    plan=read_json(folder/'plan.json')
    execution_revision(plan['code_hashes'],root,historical=historical)
    record=read_json(folder/'record.json')
    if digest(record)!=plan['record_sha256']:raise ValueError('方案快照变化。')
    validate_output(record,plan['output_contract'])
    followup = plan.get('site_recalculation')
    if followup and not historical:
        from site_recalculation import validate_step
        if len(plan['cases']) != 1 or plan['cases'][0]['step_minutes'] != followup['step']:
            raise ValueError('单地点补算清单与登记的步长不符。')
        validate_step(record, followup['original_step'], followup['step'], followup.get('purpose','recovery'))
    reader=VerifiedReader(history_root=root if historical else None)
    reader.check(dict(path=str(Path(root)/'data/model-inputs'/plan['bundle_id']/'manifest.json'),sha256=plan['bundle_sha256']))
    files = plan['engine_files']
    if historical:
        from history_locations import engine_location
        _, files = engine_location(root,plan)
    for p,h in files.items():reader.check(dict(path=p,sha256=h))
    cases=plan['cases'] if only_index is None else [plan['cases'][only_index]]
    for c in cases:
        if c.get('output_contract',OUTPUT_CONTRACT)!=plan['output_contract']:raise ValueError('算例与清单的输出类型不一致。')
        reader.check(dict(path=str(owned(folder/c['model_file'],folder)),sha256=c['model_sha256']))
        for p,h in c['dependencies'].items():reader.check(dict(path=p,sha256=h))
    reader.unchanged()
    return plan
