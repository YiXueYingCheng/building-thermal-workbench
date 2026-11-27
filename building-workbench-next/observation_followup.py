"""Prepare an output-only replay of one frozen case and revisit its recorded switch."""
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile

from execution_inputs import code_hashes, load_review, public, stage_observer
from execution_results import COOL, HEAT
from foundation import digest, now, owned, read_json, sha, write_json
from history_locations import engine_location, input_path
from result_timeline import require, source
from spectral_response import frozen_model, registered_input, step_series, zone_ideal_systems
from wall_observations import METRICS
import wall_switches


def probes(model, wall, zone, mode):
    systems=zone_ideal_systems(model,zone) if mode!='natural' else []
    return {'inward':([wall],METRICS['inward'][0],'W/m2','Avg'),
            'air':([zone],METRICS['air'][0],'C','Avg'),
            'heating':(systems,HEAT,'J','Sum'),'cooling':(systems,COOL,'J','Sum')}


def verify_series(db,env,fields,specs,period,step):
    start=dt.date(2025,*period[:2])
    dates=[start+dt.timedelta(days=i) for i in range((dt.date(2025,*period[2:])-start).days+1)]
    for field in fields:
        keys,name,unit,kind=specs[field]
        require(keys,'该房间没有相应测点。')
        for key in keys:
            if 'Zone Timestep' not in wall_switches.outputs(db,key,name,unit,kind):
                return False
            values=step_series(db,env,dates,step,key,name,unit)
            if unit=='J':
                require(min(values)>=0,'房间负荷含有无效负值。')
    return True


def compatible(root,original,case,other,c):
    if (original['record_sha256']!=other['record_sha256'] or
            any(case.get(k)!=c.get(k) for k in ('site_id','mode','period','step_minutes','physical_digest')) or
            not case.get('physical_digest') and case['identity']!=c['identity'] or
            case['dependencies'][case['weather']]!=c['dependencies'][c['weather']]):
        return False
    if case['dependencies']!=c['dependencies']:
        def inputs(item):
            return {input_path(root,p,h):h for p,h in item['dependencies'].items()}
        if inputs(case)!=inputs(c):
            return False
    if original['engine_files']==other['engine_files']:
        return True
    def installation(plan):
        base=Path(plan['engine']).parent
        return {Path(p).relative_to(base):h for p,h in plan['engine_files'].items()}
    return installation(original)==installation(other)


def candidates(root,plan,case):
    path=Path(root)/'data/execution/queue.sqlite'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute("""SELECT j.batch,j.idx,j.result_sha256,b.plan FROM jobs j JOIN batches b ON b.id=j.batch
            WHERE j.status IN ('passed','reused') AND json_extract(b.plan,'$.record_sha256')=?
            ORDER BY j.updated DESC""",(plan['record_sha256'],)).fetchall()
    for batch,index,checksum,data in rows:
        other=json.loads(data)
        if compatible(root,plan,case,other,other['cases'][index]):
            yield dict(batch=batch,index=index,sha256=checksum)


def add_outputs(model,fields,specs):
    table=model.setdefault('Output:Variable',{})
    present={(v.get('key_value','*').casefold(),v['variable_name'].casefold(),v.get('reporting_frequency','Hourly').casefold()) for v in table.values()}
    for field in fields:
        keys,name,_,_=specs[field]
        for key in keys:
            for frequency in ('Timestep','Monthly'):
                pair=(name.casefold(),frequency.casefold())
                if (key.casefold(),*pair) in present or ('*',*pair) in present:
                    continue
                label='WB Probe '+digest([key,*pair])[:16]
                require(label not in table,'冻结模型中输出名称冲突。')
                table[label]=dict(key_value=key,variable_name=name,reporting_frequency=frequency)
                present.add((key.casefold(),*pair))


def prepare(root,body,detail,folder,record,original,case,fields,specs):
    load_review(root,original['id'],sha(folder/'plan.json'),historical=True,only_index=case['index'])
    model=frozen_model(folder,case)
    add_outputs(model,fields,specs)
    engine,files=engine_location(root,original)
    rebound={p:str(input_path(root,p,h)) for p,h in case['dependencies'].items()}
    for obj in model.get('Schedule:File',{}).values():
        require(obj['file_name'] in rebound,'冻结模型引用了未登记的作息。')
        obj['file_name']=rebound[obj['file_name']]
    codes=code_hashes()
    bookmark=dict(source=body['result'],wall=body['wall'],zone=detail['zone'],layer=body.get('layer'),
                  offset=detail['offset'],fields=fields,source_model_sha256=case['model_sha256'])
    identity=digest(dict(parent=case['identity'],model=digest(model),engine=files,executor=codes))
    token='review_'+digest([body['result'],body['wall'],fields,identity])[:32]
    dest=owned(root/'data/execution/reviews'/token,root)
    if not dest.exists():
        with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
            stage=Path(temp)/'ready'
            write_json(stage/'000.epJSON',model,root)
            child=dict(case,index=0,model_file='000.epJSON',model_sha256=sha(stage/'000.epJSON'),identity=identity,
                       weather=rebound[case['weather']],dependencies={rebound[p]:h for p,h in case['dependencies'].items()})
            plan=dict(original,id=token,created=now(),engine=engine,engine_files=files,cases=[child],case_count=1,
                      code_hashes=codes,observation_followup=bookmark)
            plan.pop('site_recalculation',None)
            write_json(stage/'record.json',record,root)
            write_json(stage/'plan.json',plan,root)
            if case.get('warmup_observer'):stage_observer(stage,codes)
            try:stage.rename(dest)
            except OSError:
                if not dest.exists():raise
    plan=load_review(root,token,sha(dest/'plan.json'))
    check=plan['observation_followup']
    require(plan['cases'][0]['identity']==identity and check['source']==bookmark['source'] and
            check['wall']==bookmark['wall'] and check['fields']==fields,'已有补录清单与本次选择不符。')
    p=public(plan,root)
    p['observation_followup']=dict(check,step=case['step_minutes'])
    with closing(sqlite3.connect((root/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        batch=db.execute('SELECT id FROM batches WHERE review=?',(token,)).fetchone()
    if batch:p['existing_batch']=dict(id=batch[0])
    return p


def resolve(root,body):
    action=body.get('action')
    require(action in ('check','prepare'),'请选择检查或准备补录。')
    detail=wall_switches.read(root,body)
    require('offset' in detail,'请选择一个已记录的切换时刻。')
    folder,case,record,plan,job,_,token=registered_input(root,body['result'])
    require(token==detail['source_token'] and job['status'] in ('passed','reused'),'请使用核验通过的来源批次。')
    fields=body.get('fields')
    allowed={r['field'] for r in detail['rows'] if r.get('requestable')}
    require(isinstance(fields,list) and fields and all(isinstance(k,str) and k in allowed for k in fields),
            '请选择这面墙及其所属房间可记录的观测量。')
    fields=sorted(set(fields))
    specs=probes(frozen_model(folder,case),detail['wall'],detail['zone'],case['mode'])
    days=(dt.date(2025,*case['period'][2:])-dt.date(2025,*case['period'][:2])).days+1
    remaining=set(fields)
    observed={}
    out=dict(wall=detail['wall'],zone=detail['zone'],city=case['city'],period=case['period'],step=case['step_minutes'],
             points=days*1440//case['step_minutes'],fields=fields,reused={},issues=[])
    for ref in candidates(root,plan,case):
        try:
            with source(root,ref['batch'],ref['index']) as (db,_,env,receipt):
                require(ref['sha256']==receipt['summary_sha256'],'候选结果版本已变化。')
                covered=[field for field in sorted(remaining) if verify_series(db,env,[field],specs,case['period'],case['step_minutes'])]
                if not covered:continue
                candidate_token=receipt['view_token']
            found=wall_switches.read(root,dict(body,result=ref,source_token=candidate_token))
            require(found['states']==detail['states'] and found['zone']==detail['zone'],'切换状态或房间归属与原记录不符。')
            rows={r['field']:r for r in found['rows'] if r.get('field') in covered and 'values' in r}
            require(len(rows)==len(covered),'已登记测点缺少切换前后读数。')
            observed.update(rows)
            out['reused'].update({field:ref for field in covered})
            remaining.difference_update(covered)
            if not remaining:
                detail['rows']=[observed.get(r.get('field'),r) for r in detail['rows']]
                out.update(detail=detail,missing=[])
                return out
        except (ValueError,KeyError,OSError) as error:
            out['issues'].append(dict(batch=ref['batch'],reason=str(error)))
    out['missing']=sorted(remaining)
    if action=='prepare':
        out['review']=prepare(root,body,detail,folder,record,plan,case,out['missing'],specs)
    return out
