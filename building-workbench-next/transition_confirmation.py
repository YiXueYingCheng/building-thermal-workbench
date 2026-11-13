"""Explicit preview choices, stored only inside a saved calendar snapshot.

Explicit two-season exceptions retain two original switch dates and their source
binding. Callers must first derive the original rule from verified daily data.
"""
import copy,re
from foundation import digest
from calendar_preview import PARAMETERS,FACE

CHOICE='keep_all_rule_switches_v1'
TWO_CHOICE='retain_two_rule_switches_v1'

def require(ok,message):
    if not ok:raise ValueError(message)

def selections(values):
    require(isinstance(values,list),'季节确认选择格式无效。');out={}
    for value in values:
        require(isinstance(value,dict),'季节确认须绑定具体地点与本次预览。')
        keys={'site_id','choice','binding_sha256'}|({'retained_dates'} if value.get('choice')==TWO_CHOICE else set())
        require(set(value)==keys,'季节确认须绑定具体地点与本次预览。')
        require(isinstance(value['site_id'],str) and value['site_id'] and value['site_id'] not in out,'季节确认地点为空或重复。')
        require(value['choice'] in (CHOICE,TWO_CHOICE) and bool(re.fullmatch('[a-f0-9]{64}',str(value['binding_sha256']))),'季节选择或来源绑定无效。')
        if value['choice']==TWO_CHOICE:
            dates=value['retained_dates']
            require(isinstance(dates,list) and len(dates)==2 and all(isinstance(v,str) and re.fullmatch(r'\d{2}-\d{2}',v) for v in dates) and dates==sorted(set(dates)),'两季特例须明确两个不同且按顺序排列的原切换日期。')
        out[value['site_id']]=copy.deepcopy(value)
    return out

def describe(basis,preview,entry):
    if not preview['transition_review_needed']:
        return dict(required=False,supported=False,confirmed=False)
    days=preview['days'];switches=preview['switches'];faces=[d['face'] for d in days]
    require(len(days)==365 and all(type(v) is int and v in (0,1) for v in faces),'季节确认需要完整有效的 365 天日历。')
    require(faces==entry['calendar'] and digest(faces)==preview['calendar_sha256']==entry['calendar_sha256'],'季节预览与绑定日历不同。')
    require(switches==entry['switches'],'切换日期与绑定内容不同。')
    actual=[i+1 for i in range(365) if faces[i]!=faces[i-1]]
    require(actual==[s['day_of_year'] for s in switches],'切换清单与逐日朝向不一致。')
    supported=preview['annual_override'] is None and len(switches)>=4 and len(switches)%2==0
    if not supported:return dict(required=True,supported=False,confirmed=False,reason='当前不是已稳定重现的多季节切换，请保留待讨论状态。')
    require(entry['source_kind']=='accepted_queue_daily_v1','季节确认只适用于已接受的队列逐日参考。')
    hashes=[entry[k] for k in ('data_sha256','weather_sha256','physical_sha256')]+[entry['result']['sha256'],entry['daily']['sha256'],entry['rule_source']['sha256']]
    require(all(isinstance(h,str) and re.fullmatch('[a-f0-9]{64}',h) for h in hashes),'季节确认的参考依据不完整。')
    from calendar_library import stable_numbers
    identity=dict(basis_sha256=digest(stable_numbers(basis)),source_kind=entry['source_kind'],site_id=entry['site_id'],
        source_id=entry['source_id'],result=entry['result'],daily=entry['daily'],data_sha256=entry['data_sha256'],
        weather_sha256=entry['weather_sha256'],physical_sha256=entry['physical_sha256'],rule=PARAMETERS,
        rule_source=entry['rule_source'],evidence_sha256=digest(entry['evidence']),calendar_sha256=entry['calendar_sha256'],switches=switches)
    return dict(required=True,supported=True,confirmed=False,choice=CHOICE,binding_sha256=digest(stable_numbers(identity)),
        switch_count=len(switches),calendar_sha256=entry['calendar_sha256'])

def review_entry(basis,preview,entry,choices):
    """Return a copied accepted entry, or None while a research choice is pending."""
    status=describe(basis,preview,entry);selected=choices.get(entry['site_id'])
    if not status['required']:
        require(selected is None,'该地点日历已改变，请清除旧季节选择并重新预览。')
        return copy.deepcopy(entry),status
    if not selected:return None,status
    require(status['supported'],'本次季节尚不支持直接确认，请保留待讨论状态。')
    require(selected['site_id']==entry['site_id'] and selected['binding_sha256']==status['binding_sha256'],'参考、条件或日历已变化，请重新查看切换日期。')
    out=copy.deepcopy(entry)
    if selected['choice']==TWO_CHOICE:
        retained=[s for s in preview['switches'] if s['date'] in selected['retained_dates']]
        require([s['date'] for s in retained]==selected['retained_dates'] and len({s['to'] for s in retained})==2,'特例只能保留原规则中各一次转 A、转 B 的日期。')
        require(all(s['to'] in ('cooling','heating') for s in retained),'原切换朝向无效。')
        faces=[];face=int(retained[-1]['to']=='cooling');switch_by_day={s['day_of_year']:int(s['to']=='cooling') for s in retained}
        for day in range(1,366):
            face=switch_by_day.get(day,face);faces.append(face)
        out.update(calendar=faces,calendar_sha256=digest(faces),switches=copy.deepcopy(retained))
        proof=dict(choice=TWO_CHOICE,binding_sha256=status['binding_sha256'],switch_count=2,calendar_sha256=digest(faces),
            original_calendar_sha256=entry['calendar_sha256'],original_switch_count=len(preview['switches']),retained_dates=copy.deepcopy(selected['retained_dates']))
        out['transition_confirmation']=proof
        status.update(proof,confirmed=True)
        return out,status
    require(selected==dict(site_id=entry['site_id'],choice=CHOICE,binding_sha256=status['binding_sha256']),'季节选择格式不一致。')
    out['transition_confirmation']={k:status[k] for k in ('choice','binding_sha256','switch_count','calendar_sha256')}
    status['confirmed']=True
    return out,status

def verify_entry(basis,preview,entry):
    """Revalidate a saved confirmation against freshly regenerated original dates."""
    raw=copy.deepcopy(entry);proof=raw.pop('transition_confirmation',None)
    if proof and proof.get('choice')==TWO_CHOICE:
        raw.update(calendar=[d['face'] for d in preview['days']],calendar_sha256=preview['calendar_sha256'],switches=copy.deepcopy(preview['switches']))
        choice={k:proof[k] for k in ('choice','binding_sha256','retained_dates')};choice['site_id']=entry['site_id']
        expected,_=review_entry(basis,preview,raw,selections([choice]))
        require(expected==entry,'保存的地点特例与原规则、来源或采用日期不一致。');return
    require([d['face'] for d in preview['days']]==raw['calendar'],'日历与绑定的逐日结果不一致，请重新预览。')
    status=describe(basis,preview,raw)
    if not status['required']:
        require(proof is None,'日历已不再对应保存时的季节确认。');return
    require(status['supported'] and proof is not None,'多季节日历没有完整的明确确认依据。')
    expected={k:status[k] for k in ('choice','binding_sha256','switch_count','calendar_sha256')}
    require(proof==expected,'保存的季节确认与当前来源或日历不一致。')

def validate_saved_entry(entry):
    """Structural check before a saved calendar is offered as a bound version."""
    faces=entry['calendar'];count=sum(faces[i]!=faces[i-1] for i in range(365));proof=entry.get('transition_confirmation')
    if proof and proof.get('choice')==TWO_CHOICE:
        require(set(proof)=={'choice','binding_sha256','switch_count','calendar_sha256','original_calendar_sha256','original_switch_count','retained_dates'},'地点特例依据不完整。')
        require(count==proof['switch_count']==2 and proof['original_switch_count']>=4 and proof['calendar_sha256']==entry['calendar_sha256'],'地点特例与保存的朝向不一致。')
        require(all(bool(re.fullmatch('[a-f0-9]{64}',str(proof[k]))) for k in ('binding_sha256','original_calendar_sha256')),'地点特例来源绑定不完整。')
        require(proof['retained_dates']==[s['date'] for s in entry['switches']] and [s['day_of_year'] for s in entry['switches']]==[i+1 for i in range(365) if faces[i]!=faces[i-1]],'地点特例日期与逐日朝向不一致。')
        return
    if count<=2:
        require(proof is None,'保存的季节确认与切换次数不一致。');return
    require(isinstance(proof,dict) and set(proof)=={'choice','binding_sha256','switch_count','calendar_sha256'},'多季节日历缺少明确确认记录。')
    require(proof['choice']==CHOICE and proof['switch_count']==count and proof['calendar_sha256']==entry['calendar_sha256'], '季节确认与保存的日历不一致。')
    require(bool(re.fullmatch('[a-f0-9]{64}',str(proof['binding_sha256']))),'季节确认依据不完整。')

def saved_selections(record):
    """Reuse only explicit choices in this scheme's active immutable snapshot.

    History/library candidates are never consent. Each returned selection still
    has to match the newly derived source and dates in review_entry().
    """
    from calendar_library import active_references,verify_reference
    values=[];scope=set(record['factors']['scope']['site_ids'])
    for ref in active_references(record):
        try:snapshot=verify_reference(ref)
        except (ValueError,KeyError,TypeError):continue
        for entry in snapshot['content']['sites']:
            proof=entry.get('transition_confirmation')
            if entry['site_id'] in scope and proof:
                value=dict(site_id=entry['site_id'],choice=proof['choice'],binding_sha256=proof['binding_sha256'])
                if proof['choice']==TWO_CHOICE:value['retained_dates']=copy.deepcopy(proof['retained_dates'])
                values.append(value)
    return values

def applied_preview(preview,entry):
    proof=entry.get('transition_confirmation')
    if not proof or proof['choice']!=TWO_CHOICE:return preview
    out=copy.deepcopy(preview);out['rule_switches']=copy.deepcopy(preview['switches'])
    out['switches']=copy.deepcopy(entry['switches']);out['calendar_sha256']=entry['calendar_sha256']
    out['seasonal_exception']=copy.deepcopy(proof)
    faces=entry['calendar']
    for i,day in enumerate(out['days']):
        day['rule_face']=day['face'];day['rule_reason']=day.get('reason')
        day.update(face=faces[i],face_label=FACE[faces[i]],previous_face=faces[i-1],changed=faces[i]!=faces[i-1],reason='地点两季特例：采用已明确保留的切换日期；下方信号与连续次数保留原规则计算，不再决定本特例的朝向。')
    out['totals'].update(heating_face_days=365-sum(faces),cooling_face_days=sum(faces))
    return out
