"""Explicit result review: bounded evidence checks, then separate adoption.

No building simulations. Unknown warnings stay pending; raw results are immutable.
Methods cover the corrected five-storey sensible-load cases: the exact Beijing
event, or full-year weather-function evidence whose events match the current log.
"""
import ast
import copy
import csv
import datetime as dt
import json
import io
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import sys
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from foundation import ROOT, read_json, write_json, sha, digest, now, owned
import output_storage
from execution_inputs import load_review
from execution_results import verify_artifacts

WARNING='Temperature out of range [-100. to 200.] (PsyPsatFnTemp)'
METHOD='corrected_five_storey_exact_event_replay'
WEATHER_METHOD='corrected_five_storey_full_weather_function_replay'

def require(ok,message):
    if not ok:raise ValueError(message)

def folder(root,ident):
    require(bool(re.fullmatch(r'review_[a-f0-9]{32}',str(ident))),'复核编号无效。')
    return owned(Path(root)/'verification/result-reviews'/ident,root)

def target(root,batch,index):
    require(bool(re.fullmatch(r'batch_[a-f0-9]{32}',str(batch))) and type(index) is int and index>=0,'算例编号无效。')
    with closing(sqlite3.connect((Path(root)/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        b=db.execute('select * from batches where id=?',(batch,)).fetchone()
        j=db.execute('select * from jobs where batch=? and idx=?',(batch,index)).fetchone()
        require(b is not None and j is not None,'未找到该计算结果。')
        b,j=dict(b),dict(j)
    require(j['status'] in ('review','passed','reused') and j['result'],'该算例尚无可复核的完成结果。')
    path=output_storage.checked_path(j['result'],root);require(sha(path)==j['result_sha256'],'结果文件发生变化，需先核查。')
    raw=read_json(path);require(raw['identity']==j['identity'],'结果身份不一致。')
    return b,j,raw

def binding(job):
    return {k:job[k] for k in ('batch','idx','attempt','identity','result','result_sha256')}

def status(root,ident):
    p=folder(root,ident);job=read_json(p/'job.json')
    out={k:v for k,v in job.items() if k not in ('binding','owner')}
    if (p/'report.json').exists():
        out['report']=read_json(p/'report.json');out['report_sha256']=sha(p/'report.json')
    if (p/'acceptance.json').exists():out['acceptance']=read_json(p/'acceptance.json')
    return out

def latest(root,batch,index):
    from warmup_review import failed_view
    failed=failed_view(root,batch,index)
    if failed is not None:return failed
    _,j,raw=target(root,batch,index);matches=[]
    for p in (Path(root)/'verification/result-reviews').glob('review_*/job.json'):
        v=read_json(p)
        if v['batch']==batch and v['index']==index and (v['binding']==binding(j) or j['status']=='passed' and (p.parent/'acceptance.json').exists() and read_json(p.parent/'acceptance.json').get('result_sha256')==j['result_sha256']):matches.append(v)
    if matches:return status(root,max(matches,key=lambda v:v['created'])['id'])
    if raw.get('scientific_review'):
        from review_evidence import reviewed
        prior=reviewed(raw,root)
        return dict(id=None,batch=batch,index=index,state='ready',acceptance=dict(status='accepted_with_notes'),
            report=dict(title='此前已登记复核结论',explanation=prior['method'],scope=prior['display_scope'],checks=[],
                next_step='原警告与依据可在结果的来源与核查中查看，也可导出本批数据包。',limits=[prior['note']]))
    return None

def export_review(root,ident):
    p=folder(root,ident);job=read_json(p/'job.json');bound=job['binding']
    raw_path=output_storage.checked_path(bound['result'],root)
    require(sha(raw_path)==bound['result_sha256'],'原结果变化，暂不导出。')
    raw=read_json(raw_path);verify_artifacts(raw)
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('说明.txt','复核资料，不是计算输入包。未接受的报告不能作为有效结果。\n原日志和数值保持；来源路径及校验值见 JSON。\n批次：'+job['batch']+'\n算例序号：'+str(job['index']+1))
        z.writestr('算例标识.json',json.dumps(bound,ensure_ascii=False,indent=2))
        for name in ('report.json','outcome.json','acceptance.json'):
            if (p/name).exists():z.write(p/name,name)
        z.write(raw_path,'original-result.json')
        for path in raw['artifacts']:
            if Path(path).name in ('model.epJSON','eplusout.err','eplusout.end','daily-loads.csv'):
                z.write(output_storage.checked_path(path,root),'original/'+Path(path).name)
    return data.getvalue()

def check_orientation_outputs(sql,calendar):
    """Match saved daily faces to actual EMS monthly/yearly (and daily if present) outputs."""
    require(len(calendar)==365 and all(type(v) is int and v in (0,1) for v in calendar),'翻面日历不完整。')
    with closing(sqlite3.connect(Path(sql).as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute("select d.ReportingFrequency,t.Month,t.Day,r.Value from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex) where d.Name='NX_FiveStorey_Flip_FaceOutput'")]
    monthly=[r for r in rows if r['ReportingFrequency']=='Monthly'];annual=[r for r in rows if r['ReportingFrequency']=='Run Period'];daily=[r for r in rows if r['ReportingFrequency']=='Daily']
    require(len(monthly)==12 and {r['Month'] for r in monthly}==set(range(1,13)) and len(annual)==1,'翻面执行输出缺少完整月度或全年记录。')
    expected={m:[] for m in range(1,13)}
    for i,v in enumerate(calendar):expected[(dt.date(2025,1,1)+dt.timedelta(days=i)).month].append(v)
    for row in monthly:
        values=expected[row['Month']];require(abs(row['Value']-sum(values)/len(values))<1e-10,'实际翻面月份与保存日历不符。')
    require(abs(annual[0]['Value']-sum(calendar)/365)<1e-10,'实际全年翻面占比与保存日历不符。')
    if daily:
        require(len(daily)==365 and len({(r['Month'],r['Day']) for r in daily})==365,'逐日翻面执行记录不完整。')
        for row in daily:
            i=(dt.date(2025,row['Month'],row['Day'])-dt.date(2025,1,1)).days
            require(abs(row['Value']-calendar[i])<1e-10,'逐日翻面执行与保存日历不符。')
    require(len(rows)==13+len(daily),'出现未预期的翻面输出频率。')
    return dict(A_days=sum(calendar),B_days=365-sum(calendar),rows=rows,monthly_and_annual_match=True)

def analyse(root,ident):
    root=Path(root).resolve();p=folder(root,ident);job=read_json(p/'job.json');checks=[]
    def check(label,ok,detail=''):
        require(ok,label+'未通过。'+detail);checks.append(dict(label=label,passed=True,detail=detail))
    b,j,raw=target(root,job['batch'],job['index'])
    check('本次结果与待复核记录一致',j['status']=='review' and binding(j)==job['binding'])
    verify_artifacts(raw);check('原始输入、日志和结果文件完整',True)
    plan=load_review(root,b['review'],b['checksum']);case=plan['cases'][j['idx']]
    check('复核绑定本次算例',case['identity']==j['identity'])
    record=read_json(root/'data/execution/reviews'/b['review']/'record.json')
    run=output_storage.result_folder(raw,root);model=read_json(run/'model.epJSON')
    check('实际执行模型与冻结输入一致',sha(run/'model.epJSON')==case['model_sha256'])
    execution=read_json(run/'execution.json');err=(run/'run/eplusout.err').read_text(encoding='utf-8',errors='replace');end=(run/'run/eplusout.end').read_text(encoding='utf-8',errors='replace')
    check('计算正常结束且没有严重错误',execution['returncode']==0 and 'EnergyPlus Completed Successfully' in end and 'EnergyPlus Completed Successfully' in err and not re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',err))
    check('完整全年、5 min、温控显热需求',raw['days']==365 and raw['period']==[1,1,12,31] and raw['step_minutes']==5 and raw['mode']=='controlled')
    check('输出覆盖与汇总检查通过',raw['checks']['full_period'] and raw['checks']['monthly_reconciliation'])
    if raw.get('daily_reference'):
        from daily_reference import verify_sql
        daily=verify_sql(run/'run/eplusout.sql',model,5)
        check('每日、月度与全年逐系统闭合',daily==raw['daily_reference'],'365 天、50 个原空调系统；仅核对数据，不替代警告影响判断。')
    # This is intentionally not a name-only warning allowlist.
    check('警告属于已接通的核查范围',len(raw['pending_warnings'])==2 and set(raw['pending_warnings'])=={WARNING},'其他警告需要单独分析，不能直接采用本方法。')
    source=root/'verification/warning-review-20261105/psy_replay.py'
    prior_path=root/'verification/five-storey-annual-20261109/outcome.json';prior=read_json(prior_path)
    check('核查方法与历史函数证据完整',prior['passed'] and sha(source)==prior['translation_sha256'])
    names={'quantize','wet_iteration','boiling','sample','branch_roots','blocks'}
    nodes=[n for n in ast.parse(source.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name in names]
    ns=dict(math=math,struct=struct,dt=dt);exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
    warnings=[w for w in ns['blocks'](err) if 'PsyPsatFnTemp' in w[0]]
    expected=[w for w in prior['review_conclusions'][0]['warnings'] if 'PsyPsatFnTemp' in w[0]]
    weather=Path(case['weather']);engine=Path(plan['engine']).parent
    beijing=sha(weather)==prior['weather_sha256']
    weather_source=None;cache_source=None
    if not beijing:
        engine_source_refs=read_json(source.parent/'source/exact-commit-sources.json');weather_source=next(x for x in engine_source_refs if Path(x['path']).name=='WeatherManager.cc')
        check('天气插值与相对湿度处理源码匹配本次引擎',sha(weather_source['path'])==weather_source['sha256'],'保留引擎读取的相对湿度；原气象不截断、不修改。')
    if beijing:check('事件时刻、次数及试算值完全匹配',warnings==expected and len(warnings)==2,'1 月 2 日 19:04–19:05，发生 1 次；首次提示和末尾汇总为同一事件。')
    check('冻结气象与已验证引擎匹配',sha(weather)==case['dependencies'][str(weather)] and sha(engine/'energyplusapi.dll')==prior['engine_dll_sha256'])
    check('建筑与研究范围匹配',record['factors']['building']['id']=='building2_5f_verified' and len(model['Zone'])==75 and len(model['ZoneHVAC:IdealLoadsAirSystem'])==50)
    from manage import current
    from ordinary_materials import validate,targets
    catalog=current(root);src=catalog['ordinary_buildings']['building2_5f_verified'];spec=validate(record,src)
    require(spec is None or spec['state']=='R','目前仅覆盖原构造或固定蓬松 ECA。')
    ids=targets(src);check('覆盖已确认的 135 面外墙',len(ids)==135)
    for sid in ids:
        c=model['Construction'][model['BuildingSurface:Detailed'][sid]['construction_name']]
        keys=['outside_layer']+sorted((k for k in c if k.startswith('layer_')),key=lambda k:int(k[6:]))
        for i in (1 if spec else 0,-1):
            v=model['Material'][c[keys[i]]]
            require(v['solar_absorptance']==.55 and v['thermal_absorptance']==.85,'外墙基材两侧未满足已确认的 0.45／0.85 基准。')
    check('基材内外两侧均为已确认的光学基准',True,'反射率 0.45、发射率 0.85；ECA 自身参数保持方案定义。')
    # Read and verify the frozen bundle; this does not rebuild or change inputs.
    from execution_inputs import bundle
    _,_,_,_,cases=bundle(root,plan['bundle_id'],plan['bundle_sha256'],plan['output_contract'])
    check('运行输入与保存方案生成的输入一致',cases[j['idx']]['model']==model)
    orientation=None
    if 'NX_FiveStorey_Flip_Apply' in model.get('EnergyManagementSystem:Program',{}):
        from calendar_library import active_references,verify_reference
        calendar_refs=active_references(record);require(len(calendar_refs)==1,'翻面参考绑定不唯一。')
        snapshot=verify_reference(calendar_refs[0]);calendar=next(r['calendar'] for r in snapshot['content']['sites'] if r['site_id']==raw['site_id'])
        orientation=check_orientation_outputs(run/'run/eplusout.sql',calendar)
        check('实际翻面输出与保存日历一致',True,f"制冷面 {orientation['A_days']} 天，另一面 {orientation['B_days']} 天；12 个月及全年输出均核对。")
    check('当前研究用途不使用湿球驱动设备',not any(k.startswith(('EvaporativeCooler:','CoolingTower:')) for k in model)
          and all(v.get('use_weather_file_rain_indicators')=='No' for v in model['RunPeriod'].values())
          and all(v.get('dehumidification_control_type')=='None' and v.get('humidification_control_type')=='None' for v in model['ZoneHVAC:IdealLoadsAirSystem'].values())
          and {v['output_variable_or_output_meter_name'] for v in model.get('EnergyManagementSystem:Sensor',{}).values()}<={'Schedule Value','Zone Mean Air Temperature'})
    sys.path.insert(0,str(engine));from pyenergyplus.api import EnergyPlusAPI
    api=EnergyPlusAPI();s=api.state_manager.new_state();messages=[];event=None;weather_scan=None;log_match=None;event_count=1
    callback=lambda severity,msg:messages.append(dict(severity=severity,text=msg.decode(errors='replace')))
    try:
        api.functional.callback_error(s,callback);psy=api.functional.psychrometrics(s)
        with weather.open(encoding='utf-8-sig') as f:records=list(csv.reader(f))[8:]
        if beijing:
            stamp=dt.datetime(2001,1,2,19,5);(dry,rh,pressure),bracket=ns['sample'](records,stamp)
            humidity=psy.humidity_ratio_c(s,dry,rh/100,pressure);messages.clear()
            wet=psy.wet_bulb(s,dry,humidity,pressure);native=messages.copy()
            trace=ns['wet_iteration'](dry,humidity,pressure,lambda t:psy.saturation_pressure(s,t),keep=True)
            roots=ns['branch_roots'](ns['quantize'](dry),ns['quantize'](humidity),ns['quantize'](pressure),lambda t:psy.saturation_pressure(s,t))
            check('同引擎函数重放最终收敛',trace['converged'] and len(trace['extreme_guesses_C'])==1 and abs(trace['extreme_guesses_C'][0]+130.079124)<1e-6 and any('PsyPsatFnTemp' in x['text'] for x in native))
            check('有界求根独立核对一致',len(roots)==1 and abs(wet-roots[0]['wet_C'])<1e-7 and abs(wet-trace['wet_C'])<1e-7,f'最终湿球温度 {wet:.9f} °C；极端值为中间试算值。')
            event=dict(stamp=stamp.isoformat(),dry_C=dry,RH_pct=rh,pressure_Pa=pressure,humidity_ratio=humidity,native_wet_C=wet,native_messages=native,trace=trace,bounded_roots=roots,bounded_delta_C=wet-roots[0]['wet_C'],bracket=bracket)
        else:
            from weather_function_review import scan,validate
            weather_scan=scan(records,s,psy,ns);log_match=validate(weather_scan,warnings);event_count=log_match['event_count']
            if log_match['cache_equivalent_repeats']:
                cache_source=next(x for x in engine_source_refs if Path(x['path']).name=='Psychrometrics.cc')
                check('相同天气输入的缓存路径已核对',sha(cache_source['path'])==cache_source['sha256'],
                    f"{log_match['raw_exception_samples']} 处天气输入及量化缓存键完全相同，最终湿球值一致。准确引擎源码在完整缓存键相同时直接返回已求得的值；原日志记录 {event_count} 次警告。此处核对重复输入等价性，不声称重建完整建筑的缓存轨迹。")
            if weather_scan['RH_above_110_hours']:
                check('原气象湿度超范围提示已保留',True,f"原 EPW 有 {weather_scan['RH_above_110_hours']} 小时相对湿度超过 110%，最高 {weather_scan['max_RH_pct']:g}%。按本引擎读取原值，不修改气象；本核查解释数值函数事件，不证明气象观测准确性。")
            detail=f"105120 个五分钟样本；原日志 {event_count} 次越界，首次时刻及极值匹配，所有函数最终收敛。"
            detail+=f"{log_match['raw_exception_samples']} 处完全相同输入按同一缓存值核对。" if log_match['cache_equivalent_repeats'] else '总次数与逐次求解一致。'
            check('全年天气函数重放与原日志匹配',True,detail)
            check('所有越界事件独立有界求根一致',True,'各事件最终湿球温度与有界根误差均小于 1e-7 °C；极端值只出现在中间试算。')
    finally:api.state_manager.delete_state(s)
    # No report can be adopted if any input/result changes during analysis.
    _,fresh,_=target(root,j['batch'],j['idx']);verify_artifacts(raw)
    check('复核期间结果保持不变',binding(fresh)==binding(j))
    scope=f"{plan['record_name']} v{plan['revision']}，本次冻结输入与{case['city']}气象，135 面外墙基材内外两侧反射率 0.45／发射率 0.85；5 min、原预热、全年温控显热冷热需求"+('及逐日参考' if raw.get('daily_reference') else '')+'。仅接受本次已重放、最终收敛且与原日志匹配的湿球函数事件。'
    if weather_scan and weather_scan['RH_above_110_hours']:
        scope+=f"原气象另有 {weather_scan['RH_above_110_hours']} 小时相对湿度超过 110%（最高 {weather_scan['max_RH_pct']:g}%），作为来源提示保留；未修正气象，不据本次函数核查证明观测真实性。"
    if cache_source:
        scope+=f"逐点求解中的 {log_match['raw_exception_samples']} 处异常试算具有完全相同的天气输入及缓存键；原日志 {event_count} 次警告与缓存复用相符，最终值均收敛且独立根一致。未重建完整建筑缓存轨迹。"
    conclusion=dict(batch=j['batch'],index=j['idx'],identity=j['identity'],site_id=raw['site_id'],attempt=j['attempt'],original_result=j['result'],original_result_sha256=j['result_sha256'],decision='accepted_with_notes',evidence_kind=METHOD if beijing else WEATHER_METHOD,scientific_scope=scope)
    evidence=dict(created=now(),passed=True,review_conclusions=[conclusion],checks=checks,building_simulations=0,
        actual_orientation=orientation,exact_warning_blocks=warnings,event=event,weather_scan=weather_scan,log_match=log_match,
        method_source=dict(path=str(Path(__file__).resolve()),sha256=sha(__file__)),
        verified_sources=[dict(path=str(source),sha256=sha(source)),dict(path=str(prior_path),sha256=sha(prior_path)),dict(path=str(weather),sha256=sha(weather)),dict(path=str(engine/'energyplusapi.dll'),sha256=sha(engine/'energyplusapi.dll'))])
    if not beijing:
        method_file=Path(__file__).with_name('weather_function_review.py');evidence['verified_sources'].append(dict(path=str(method_file),sha256=sha(method_file)))
        evidence['verified_sources'].append(dict(path=weather_source['path'],sha256=weather_source['sha256']))
        if cache_source:evidence['verified_sources'].append(dict(path=cache_source['path'],sha256=cache_source['sha256']))
    write_json(p/'outcome.json',evidence,root)
    write_json(p/'report.json',dict(created=now(),recommendation='accept_with_notes',title='本次警告可附说明接受',
        explanation='极端温度出现在湿球函数求根的中间试算中，最终正常收敛；本次输入和结果已逐项绑定核对。',
        scope=scope,checks=checks,warning_events=event_count,raw_warning_records=len(raw['pending_warnings']),
        next_step='确认采用后，本结果列为附说明接受；逐日结果可继续用于匹配条件的翻面日历。',
        evidence_sha256=sha(p/'outcome.json'),limits=['不是重新运行全年模型或修改引擎。','结论仅适用于这一冻结结果，不会按警告名称自动放行其他结果。','原日志、数值及警告完整保留。']),root)

def accept(root,ident,expected):
    from execution_queue import Queue
    from review_evidence import reviewed
    root=Path(root).resolve();p=folder(root,ident);report=read_json(p/'report.json');job=read_json(p/'job.json')
    require(sha(p/'report.json')==expected,'复核报告已变化，请重新读取。')
    require(job['state']=='ready' and report['recommendation']=='accept_with_notes','目前没有可采用的复核结论。')
    evidence=read_json(p/'outcome.json');require(evidence['passed'] is True and sha(p/'outcome.json')==report['evidence_sha256'],'复核依据不完整。')
    for ref in evidence['verified_sources']:require(sha(ref['path'])==ref['sha256'],'复核引用资料发生变化，请重新检查。')
    b,j,raw=target(root,job['batch'],job['index'])
    if j['status']=='passed' and raw.get('scientific_review',{}).get('id')==ident:
        reviewed(raw,root)
        done=dict(created=raw['scientific_review']['reviewed_at'],batch=j['batch'],index=j['idx'],status='accepted_with_notes',result_sha256=j['result_sha256'],raw_preserved=True)
        if not (p/'acceptance.json').exists():write_json(p/'acceptance.json',done,root)
        return read_json(p/'acceptance.json')
    if (p/'acceptance.json').exists():
        done=read_json(p/'acceptance.json')
        require(j['status']=='passed' and j['result_sha256']==done['result_sha256'],'已采用的结果记录发生变化。')
        reviewed(raw,root);return done
    require(j['status']=='review' and binding(j)==job['binding'],'待复核结果已变化，请重新检查。')
    load_review(root,b['review'],b['checksum']);verify_artifacts(raw)
    c=evidence['review_conclusions'][0]
    require(len(evidence['review_conclusions'])==1 and c['identity']==j['identity'] and c['original_result_sha256']==j['result_sha256'] and c['batch']==j['batch'] and c['index']==j['idx'],'依据未绑定本次结果。')
    at=now();result=copy.deepcopy(raw)
    result.update(status='passed',pending_warnings=[],reviewed_warnings=raw['pending_warnings'],scientific_review=dict(id=ident,decision=c['decision'],reviewed_at=at,original_result=j['result'],original_result_sha256=j['result_sha256'],evidence=str(p/'outcome.json'),evidence_sha256=sha(p/'outcome.json'),scope=c['scientific_scope'],evidence_kind=c['evidence_kind']))
    result_path=owned(root/'data/execution/scientific-reviews'/ident/('result_'+digest(result)[:24]+'.json'),root)
    write_json(result_path,result,root);reviewed(result,root);verify_artifacts(result);h=sha(result_path)
    q=Queue(root)
    with q.db() as db:
        cur=db.execute("update jobs set status='passed',result=?,result_sha256=?,updated=? where batch=? and idx=? and attempt=? and identity=? and status='review' and result=? and result_sha256=?",(str(result_path),h,at,j['batch'],j['idx'],j['attempt'],j['identity'],j['result'],j['result_sha256']))
        require(cur.rowcount==1,'结果状态已变化，本次未重复采用。')
        db.execute('insert or replace into cache(identity,path,checksum) values(?,?,?)',(j['identity'],str(result_path),h))
        q.event(db,j['batch'],'scientific_review_accepted',dict(index=j['idx'],review_id=ident,evidence=str(p/'outcome.json')))
    done=dict(created=at,batch=j['batch'],index=j['idx'],status='accepted_with_notes',result_sha256=h,raw_preserved=True)
    write_json(p/'acceptance.json',done,root);return done

class Reviews:
    def __init__(self,root):
        self.root=Path(root).resolve();self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='result-review');self.owner=uuid.uuid4().hex;self.active=set()
    def get(self,ident):
        data=status(self.root,ident);p=folder(self.root,ident);j=read_json(p/'job.json')
        if j['state'] in ('queued','running') and j.get('owner')!=self.owner:
            data.update(state='interrupted',error='服务已重启，复核检查需要重新发起；计算结果保持。')
        return data
    def latest(self,batch,index):
        value=latest(self.root,batch,index);return self.get(value['id']) if value and value.get('id') else value
    def start(self,batch,index,force=False):
        with self.lock:
            from warmup_review import handle_start
            candidate=handle_start(self.root,batch,index)
            if candidate is not None:return candidate
            _,j,raw=target(self.root,batch,index);require(j['status']=='review','结果不处于待复核状态。')
            prior=self.latest(batch,index)
            if prior and (prior['state'] in ('queued','running') or not force and prior['state']=='ready'):return prior
            require(len(self.active)<3,'已有复核检查排队，请稍后再试。')
            ident='review_'+uuid.uuid4().hex;p=folder(self.root,ident)
            write_json(p/'job.json',dict(id=ident,batch=batch,index=index,created=now(),state='queued',owner=self.owner,binding=binding(j),message='等待检查复核依据；不会重新计算建筑。'),self.root)
            self.active.add(ident);self.pool.submit(self.run,ident);return self.get(ident)
    def run(self,ident):
        p=folder(self.root,ident);job=read_json(p/'job.json')
        try:
            job.update(state='running',message='正在核对输入、日志与数值事件…');write_json(p/'job.json',job,self.root)
            with (p/'inspection.log').open('ab') as log:
                proc=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--analyse',str(self.root),ident],cwd=p,stdout=log,stderr=log,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=240)
            require(proc.returncode==0 and (p/'report.json').exists(),'检查未能完成，请保留记录并重新检查。')
            job.update(state='ready',message='检查已完成，请查看结论。',finished=now())
        except Exception as exc:job.update(state='error',error=str(exc),finished=now())
        finally:
            write_json(p/'job.json',job,self.root)
            with self.lock:self.active.discard(ident)
    def close(self):self.pool.shutdown(wait=True,cancel_futures=False)

if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--analyse':raise SystemExit('Use --analyse ROOT ID')
    root=Path(sys.argv[2]).resolve();ident=sys.argv[3];p=folder(root,ident)
    try:analyse(root,ident)
    except Exception as exc:
        write_json(p/'report.json',dict(created=now(),recommendation='needs_analysis',title='仍需进一步分析',explanation=str(exc),checks=[],next_step='保留待复核状态，下载本次核查说明，结合原日志继续分析；不要直接重试或接受。',limits=['尚未形成可采用的科学结论。','没有启动新的建筑计算。']),root)
