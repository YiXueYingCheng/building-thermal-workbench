"""Explicit first cross-building usage reuse. Preview only; save via existing components."""
import copy
import math
import re
from foundation import digest,now
from building_configuration import baseline,validate_content,CHANNELS
from usage_schedules import source_snapshot,actual_pair,validate_load,gain_defaults
from model_adapter import VerifiedReader
from room_configuration import differences,context_notes

SOURCE='drawing26_global_frozen'
TARGET='building2_5f_verified'
BASES={'source_units':'保留源单位','room_totals':'保留来源每间实际值','area_density':'按来源面积密度换算'}


def browser_numbers(value):
    """Keep new rules' integer values stable through JSON/browser undo round trips."""
    if isinstance(value,float) and value.is_integer():return int(value)
    if isinstance(value,list):return [browser_numbers(v) for v in value]
    if isinstance(value,dict):return {k:browser_numbers(v) for k,v in value.items()}
    return value


def check_target(target):
    if target!=TARGET:raise ValueError('首轮跨建筑复用仅开放 Drawing26 原配置到已核实五层建筑；其他来源组合需先核对。')


def same_pair(a,b):
    return all(math.isclose(a[d][h],b[d][h],rel_tol=1e-12,abs_tol=1e-9) for d in ('weekday','weekend') for h in range(24))


def inventories(catalog,root):
    reader=VerifiedReader(catalog);source,_,_=baseline(catalog,reader,building_id=SOURCE)
    target,model,_=baseline(catalog,reader,building_id=TARGET)
    metadata=source_snapshot(root);labels=catalog['ordinary_buildings'][TARGET]['usage_sources'];rooms=[]
    for room in source['rooms']:
        detail=metadata['rooms'].get(room['id'],{});channels={}
        for channel in CHANNELS:
            actual=actual_pair(room['loads'][channel],room['area_m2']);rule=detail.get('channels',{}).get(channel,{}).get('rule');verified=False
            if rule:
                try:
                    validate_load(rule,channel,room['area_m2']);verified=rule.get('kind')=='scaled' and same_pair(actual,actual_pair(rule,room['area_m2']))
                except (ValueError,KeyError,TypeError):pass
            channels[channel]=dict(actual=actual,rule=copy.deepcopy(rule) if verified else None,source_units_verified=verified,
                                   peak=max(actual['weekday']+actual['weekend']))
        rooms.append(dict(id=room['id'],zone=room['zone'],area_m2=room['area_m2'],conditioned=room['conditioned'],use=detail.get('use') or '用途未标注',channels=channels))
    targets=[dict(id=r['id'],zone=r['zone'],area_m2=r['area_m2'],conditioned=r['conditioned'],use=labels.get(r['id'],{}).get('use') or '用途未标注') for r in target['rooms']]
    proof=dict(building_id=SOURCE,baseline_sha256=source['baseline_sha256'],metadata_sha256=digest(metadata))
    reader.unchanged()
    return source,target,model,rooms,targets,proof


def options(catalog,root,target):
    check_target(target);source,base,model,rooms,targets,proof=inventories(catalog,root)
    uses=[]
    for use in sorted({r['use'] for r in targets}):
        candidates=[r['id'] for r in rooms if r['use']==use and use!='用途未标注']
        uses.append(dict(use=use,targets=[r['id'] for r in targets if r['use']==use],candidates=candidates,requires_selection=True))
    return dict(source_name='Drawing26 原冻结配置',target_name=catalog['ordinary_buildings'][TARGET]['building']['name'],
                source=proof,rooms=rooms,targets=targets,type_candidates=uses,bases=BASES,
                note='用途名称仅用于筛选候选。来源房间、目标房间和通道均需明确选择；本入口不搬移温控、得热参数或材料应用。')


def converted(origin,channel,basis,area,proof):
    entry=origin['channels'][channel];rule=copy.deepcopy(entry['rule'])
    if basis=='source_units' and rule is None:raise ValueError('来源单位说明未能与原配置核对；请改选每间实际值或面积密度，不能猜测原单位。')
    if rule is None:
        scale=area/origin['area_m2'] if basis=='area_density' else 1
        return {d:[x*scale for x in entry['actual'][d]] for d in ('weekday','weekend')}
    per_area=rule['unit'].endswith('/m2')
    if basis=='room_totals' and per_area:
        rule['minimum']*=origin['area_m2'];rule['maximum']*=origin['area_m2'];rule['unit']=rule['unit'].removesuffix('/m2')
    elif basis=='area_density' and not per_area:
        rule['minimum']/=origin['area_m2'];rule['maximum']/=origin['area_m2'];rule['unit']+='/m2'
    rule['basis']=f"跨建筑复用起点：Drawing26 {origin['zone']} / {origin['id']}；{BASES[basis]}；来源配置 {proof['baseline_sha256']}；单位作息来源 {proof['metadata_sha256']}。"
    validate_load(rule,channel,area)
    return rule


def coverage(content,base,rooms,targets,proof):
    """Describe current values, not a count of clicks or a claim that every room must change."""
    origin_by_id={r['id']:r for r in rooms};labels={r['id']:r for r in targets};rows=[]
    totals=dict(rooms=len(content['rooms']),full=0,partial=0,none=0,reused_items=0,edited_reuse_items=0,unverified_items=0,other_edits=0)
    pattern=r'跨建筑复用起点：Drawing26 (\S+) / (\S+)；([^；]+)；来源配置 ([a-f0-9]{64})；单位作息来源 ([a-f0-9]{64})。'
    for room,original in zip(content['rooms'],base['rooms']):
        cells={}
        for channel in CHANNELS:
            rule=room['loads'][channel];before=original['loads'][channel]
            cell=dict(state='original' if rule==before else 'edited',origin=None,
                      actual_changed=not same_pair(actual_pair(rule,room['area_m2']),actual_pair(before,room['area_m2'])))
            match=re.fullmatch(pattern,rule.get('basis',''))
            if match:
                zone,ident,label,baseline_hash,metadata_hash=match.groups();basis=next((k for k,v in BASES.items() if v==label),None)
                cell['origin']=dict(id=ident,zone=zone,basis=basis,label=label,baseline_sha256=baseline_hash,metadata_sha256=metadata_hash)
                source=origin_by_id.get(ident);cell['state']='unverified'
                if source and source['zone']==zone and basis and baseline_hash==proof['baseline_sha256'] and metadata_hash==proof['metadata_sha256']:
                    try:expected=converted(source,channel,basis,room['area_m2'],proof)
                    except ValueError:pass
                    else:cell['state']='reused' if rule==expected else 'reuse_edited'
            if cell['state']=='reused':totals['reused_items']+=1
            elif cell['state']=='reuse_edited':totals['edited_reuse_items']+=1
            elif cell['state']=='unverified':totals['unverified_items']+=1
            elif cell['state']=='edited':totals['other_edits']+=1
            cells[channel]=cell
        known=sum(c['origin'] is not None for c in cells.values());category='full' if known==3 else 'partial' if known else 'none';totals[category]+=1
        rows.append(dict(**labels[room['id']],channels=cells,category=category))
    return dict(totals=totals,rooms=rows)


def overview(body,catalog,root,saved_record):
    allowed={'id','revision','content','selected_profile','configuration_name','overrides','mode'}
    if not isinstance(body,dict) or set(body)-allowed:raise ValueError('全楼复用核对请求含未支持字段。')
    content=body.get('content',{})
    if not isinstance(content,dict):raise ValueError('目标配置格式不正确。')
    check_target(content.get('building_id'))
    source,base,model,rooms,targets,proof=inventories(catalog,root);validate_content(content,base)
    if saved_record['factors']['building']['id']!=TARGET:raise ValueError('方案与目标建筑不一致。')
    from component_library import verify
    selected=body.get('selected_profile');saved=saved_record['factors']['building'].get('usage_profile')
    for ref in (selected,saved):
        if ref:validate_content(verify(ref,'usage')['content'],base)
    adopted=selected['content'] if selected else base
    name=selected['name'] if selected else saved_record['factors']['building']['name']+' 房间使用'
    status='draft' if content!=adopted or body.get('configuration_name',name)!=name else 'configuration' if selected!=saved else 'saved'
    result=coverage(content,base,rooms,targets,proof)
    result.update(save_state=status,scheme=dict(id=saved_record['id'],revision=saved_record['revision']),source=proof,
                  differences=differences(base,content,base,gain_defaults(model)))
    result['notes']=context_notes(result['differences'],content,body.get('overrides',{}),body.get('mode','controlled'))
    result['note']='按当前配置记录核对，不把仅预览的选择计入。无复用记录的房间可以继续使用原配置，不要求全部复用。'
    result['sha256']=digest(result);result['checked_at']=now();return result


def preview(body,catalog,root):
    allowed={'content','source_room','targets','groups','bases','overrides','mode'}
    if not isinstance(body,dict) or set(body)-allowed:raise ValueError('跨建筑复用请求含未支持字段。')
    content=body.get('content',{})
    if not isinstance(content,dict):raise ValueError('目标配置格式不正确。')
    check_target(content.get('building_id'))
    source,base,model,rooms,target_rows,proof=inventories(catalog,root);validate_content(content,base)
    origin=next((r for r in rooms if r['id']==body.get('source_room')),None)
    if not origin:raise ValueError('请明确选择 Drawing26 来源房间。')
    targets=body.get('targets');groups=body.get('groups');bases=body.get('bases')
    valid_targets={r['id'] for r in base['rooms']}
    if not isinstance(targets,list) or not targets or any(not isinstance(x,str) for x in targets) or len(set(targets))!=len(targets) or set(targets)-valid_targets:raise ValueError('请选择不重复的目标建筑房间。')
    if not isinstance(groups,list) or not groups or any(not isinstance(x,str) for x in groups) or len(set(groups))!=len(groups) or set(groups)-set(CHANNELS):raise ValueError('本轮只复用明确选中的人员、照明或设备及两天作息。')
    if not isinstance(bases,dict) or set(bases)!=set(groups) or any(not isinstance(v,str) or v not in BASES for v in bases.values()):raise ValueError('请为每个选中通道明确复用单位方式。')
    result=copy.deepcopy(content);patches=[]
    for i,room in enumerate(result['rooms']):
        if room['id'] not in targets:continue
        for channel in groups:
            old=copy.deepcopy(room['loads'][channel]);new=browser_numbers(converted(origin,channel,bases[channel],room['area_m2'],proof))
            if old!=new:
                room['loads'][channel]=new;patches.append(dict(room=i,path=['loads',channel],before_present=True,before=old,after=copy.deepcopy(new)))
    if result!=content:result['schema_version']=2
    validate_content(result,base);diff=differences(content,result,base,gain_defaults(model))
    notes=context_notes(diff,result,body.get('overrides',{}),body.get('mode','controlled'))
    mismatches=[r['zone'] for r in target_rows if r['id'] in targets and r['use']!=origin['use']]
    if mismatches:notes.append('以下目标与来源用途标注不同，请核对所选房间：'+'、'.join(mismatches))
    notes.append('目标建筑的几何、面积、空调归属、温控/可用时段、得热参数及未选通道保持；作息按原工作日/周末年历展开。')
    out=dict(content=result,differences=diff,notes=notes,source=proof,source_room=origin,targets=targets,groups=groups,bases=bases,
             undo=dict(before_sha256=digest(content),after_sha256=digest(result),schema_before=content['schema_version'],patches=patches))
    before=coverage(content,base,rooms,target_rows,proof);after=coverage(result,base,rooms,target_rows,proof)
    out['coverage_before']=before['totals'];out['coverage_after']=after['totals']
    out['overlaps']=[dict(room=r['id'],zone=r['zone'],channel=k,previous=c['origin']) for r in before['rooms'] if r['id'] in targets for k,c in r['channels'].items() if k in groups and c['origin']]
    out['review_sha256']=digest(out);out['checked_at']=now()
    return out
