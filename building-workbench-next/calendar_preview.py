"""Explain an existing seasonal rule from pinned daily demand. Preview only."""
import ast
import copy
import math
from pathlib import Path
from foundation import ROOT, digest, now
from model_adapter import VerifiedReader, compile_case
from reference_readiness import baseline
import legacy_daily

PARAMETERS=dict(window_days=15,dominant_share=.55,persistence_days=7,minor_annual_share=.02)
FACE={0:'供暖面',1:'制冷面',-1:'无主导需求'}


def registered_rule(batch,reader):
    refs=[r for r in batch['protected_code'] if Path(r['path']).name=='janus_seasons.py']
    if len(refs)!=1:raise ValueError('未找到唯一的已冻结日历规则来源。')
    path=reader.check(refs[0]);tree=ast.parse(path.read_text('utf-8-sig'))
    values=[n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RULE' for t in n.targets)]
    if len(values)!=1 or not isinstance(values[0],ast.Call) or not isinstance(values[0].func,ast.Name) or values[0].func.id!='dict' or values[0].args:
        raise ValueError('已登记规则格式未识别。')
    rule={k.arg:ast.literal_eval(k.value) for k in values[0].keywords}
    if any(rule.get(k)!=v for k,v in PARAMETERS.items()):raise ValueError('旧规则参数发生变化，不能默认为本预览规则。')
    return rule,refs[0]


def replay(signals,initial,persistence):
    state=initial;pending=-1;count=0;history=[];trace=[]
    for i in range(365*3):
        signal=signals[i%365]
        count=count+1 if signal==pending and signal!=-1 else int(signal!=-1)
        pending=signal
        previous=state
        if count>=persistence:state=signal
        history.append(state)
        if i>=730:trace.append(dict(signal=signal,consecutive_days=count,previous_face=previous,face=state,changed=previous!=state))
    if history[-365:]!=history[-730:-365]:raise ValueError('重复参考年尚未得到稳定日历。')
    return trace


def calculate(heat,cool,rule=None):
    rule=copy.deepcopy(rule or PARAMETERS)
    if any(rule.get(k)!=v for k,v in PARAMETERS.items()):raise ValueError('本轮仅预览已登记的统一规则。')
    if len(heat)!=365 or len(cool)!=365:raise ValueError('需要完整 365 天的参考需求。')
    heat=[legacy_daily.finite_nonnegative(v) for v in heat];cool=[legacy_daily.finite_nonnegative(v) for v in cool]
    total_h=math.fsum(heat);total_c=math.fsum(cool);total=total_h+total_c
    if total<=0:raise ValueError('全年没有冷热需求，需要另行判断朝向。')
    annual_h=total_h/total;annual_c=total_c/total
    override=1 if annual_h<rule['minor_annual_share'] else 0 if annual_c<rule['minor_annual_share'] else None
    n=rule['window_days'];h=[sum(heat[(d-i)%365] for i in range(1,n+1)) for d in range(365)];c=[sum(cool[(d-i)%365] for i in range(1,n+1)) for d in range(365)]
    signals=[1 if a+b>0 and b>rule['dominant_share']*(a+b) else 0 if a+b>0 and a>rule['dominant_share']*(a+b) else -1 for a,b in zip(h,c)]
    if override is None:
        a=replay(signals,0,rule['persistence_days']);b=replay(signals,1,rule['persistence_days'])
        if [r['face'] for r in a]!=[r['face'] for r in b]:raise ValueError('日历仍依赖任意起始朝向，需要单独判断。')
        trace=a
    else:trace=[dict(signal=s,consecutive_days=None,previous_face=override,face=override,changed=False) for s in signals]
    days=[]
    for i,(d,t) in enumerate(zip(legacy_daily.DATES,trace)):
        q=h[i]+c[i];day=dict(day_of_year=i+1,date=d.strftime('%m-%d'),heating_kWh=heat[i],cooling_kWh=cool[i],
            prior_heating_kWh=h[i],prior_cooling_kWh=c[i],cooling_share=c[i]/q if q>0 else None,
            window_start=legacy_daily.DATES[(i-n)%365].strftime('%m-%d'),window_end=legacy_daily.DATES[(i-1)%365].strftime('%m-%d'),
            window_crosses_year=i<n,annual_override=override is not None,**t)
        day['face_label']=FACE[t['face']];day['signal_label']=FACE[t['signal']]
        if override is not None:day['reason']='全年次要需求占比低于 2%，按已有规则保持全年'+FACE[override]+'。'
        elif t['signal']==-1:day['reason']='前 15 日没有需求或双方占比均未严格超过 55%；保持朝向，连续计数清零。'
        elif t['changed']:day['reason']='前 15 日以'+FACE[t['signal']]+'对应需求为主，连续满足 7 天；当天 00:00 切换。'
        elif t['signal']!=t['face']:day['reason']='出现相反需求信号，但连续天数尚不足 7 天，保持原朝向。'
        else:day['reason']='主导需求与当前朝向一致，继续保持。'
        days.append(day)
    switches=[dict(day_of_year=d['day_of_year'],date=d['date'],at='00:00',to='cooling' if d['face'] else 'heating',
        face_label=d['face_label'],window_start=d['window_start'],window_end=d['window_end'],
        window_crosses_year=d['window_crosses_year'],prior_heating_kWh=d['prior_heating_kWh'],prior_cooling_kWh=d['prior_cooling_kWh'],
        cooling_share=d['cooling_share'],consecutive_days=d['consecutive_days'],reason=d['reason']) for i,d in enumerate(days) if d['face']!=days[i-1]['face']]
    faces=[d['face'] for d in days]
    return dict(days=days,switches=switches,calendar_sha256=digest(faces),
        totals=dict(heating_kWh=total_h,cooling_kWh=total_c,heating_share=annual_h,cooling_share=annual_c,
            heating_face_days=365-sum(faces),cooling_face_days=sum(faces)),annual_override=override,
        transition_review_needed=len(switches)!=(0 if override is not None else 2))


def build_example(catalog,root=ROOT):
    sources,issues=legacy_daily.discover(catalog,root)
    found=[s for s in sources if s['id']=='china34_110000']
    if len(found)!=1:raise ValueError('北京旧 W00 示例来源不唯一或不可读取。'+'；'.join(issues))
    source=found[0];reader=VerifiedReader(catalog);checked=legacy_daily.inspect(source,catalog,reader)
    if not checked['daily_checks_passed']:raise ValueError('示例逐日资料核对未通过：'+'；'.join(checked['issues']))
    batch=reader.json(source['anchor']);rule,rule_ref=registered_rule(batch,reader)
    daily_path=reader.check(dict(path=source['daily_path'],sha256=source['daily_sha256']))
    rows=legacy_daily.csv_rows(daily_path);result=calculate([r['heating_kWh'] for r in rows],[r['cooling_kWh'] for r in rows],rule)
    saved=next(c for c in batch['cities'] if c['region_id']==source['region_id'])
    if [d['face'] for d in result['days']]!=saved['daily_cooling_face']:
        raise ValueError('本次重现与已登记日历不同，需先核查规则执行。')
    expected=[{k:s[k] for k in ('day_of_year','date','at','to')} for s in result['switches']]
    if expected!=saved['switches']:raise ValueError('本次切换日期与登记日历不一致。')
    candidates=[sid for sid,s in catalog['sites'].items() if s.get('eligible') and s.get('source_kind')=='imported_epw_v1' and (s.get('weather') or {}).get('sha256')==source['weather_sha256']]
    if not candidates:raise ValueError('示例缺少已登记的同内容气象。')
    reference=baseline(catalog['records']['global_w00']);reference['numerics']['step_minutes']=5;reference['factors']['scope']['site_ids']=[candidates[0]]
    model,report=compile_case(reference,candidates[0],catalog,reader,'controlled');reader.check(report['weather'])
    if digest(legacy_daily.model_value(model,root,reader))!=checked['physical_sha256']:raise ValueError('示例与当前原构造模型不匹配。')
    reader.unchanged()
    return dict(example_id='beijing_w00',name='北京 · Drawing26 原构造',checked_at=now(),status='preview_only',
        bound_to_current_scheme=False,can_adopt=False,new_simulation=False,rule=rule,
        rule_explanation='前 15 个完整日中，某类冷热需求占比严格超过 55%，连续满足 7 次，于当日 00:00 改为对应朝向；中性或零需求保持朝向并重置计数。这里连续满足的是占比判断，并非连续 7 天都有该类负荷。全年某类需求占比低于 2% 时，全年采用另一类对应朝向。',
        year_boundary='参考年首尾循环衔接，重放至两种起始朝向得到同一日历；这不是追加建筑预热或计算新气象年。',
        note='此处朝向表示材料翻面，温控运行仍由工况决定。这是已有规则的独立日期预览，未绑定当前方案，也未作材料节能最优化。',
        source=dict(id=source['id'],daily_path=source['daily_path'],daily_sha256=source['daily_sha256'],weather_sha256=source['weather_sha256'],
            physical_sha256=checked['physical_sha256'],rule_source=rule_ref,anchor=source['anchor'],warnings=checked['warnings'],
            model_match=True,registered_calendar_match=True,evidence=checked['evidence']),**result)
