"""Cross-building usage reuse from verified original or saved configurations. Preview only; save via existing components."""
import copy
import json
import math
import re
from foundation import digest,now
from building_configuration import baseline,validate_content,CHANNELS
from usage_schedules import source_snapshot,actual_pair,validate_load,gain_defaults
from model_adapter import VerifiedReader
from room_configuration import differences,context_notes

from component_library import Library

SOURCE='drawing26_global_frozen'

ORIGIN_PREFIX='跨建筑复用/v2 '
BASES={'source_units':'保留源单位','room_totals':'保留来源每间实际值','area_density':'按来源面积密度换算'}


def browser_numbers(value):
    """Keep new rules' integer values stable through JSON/browser undo round trips."""
    if isinstance(value,float) and value.is_integer():return int(value)
    if isinstance(value,list):return [browser_numbers(v) for v in value]
    if isinstance(value,dict):
        if 'sha256' in value and 'content' in value:return value  # Preserve signed daily profiles.
        return {k:browser_numbers(v) for k,v in value.items()}
    return value


def same_pair(a,b):
    return all(math.isclose(a[d][h],b[d][h],rel_tol=1e-12,abs_tol=1e-9) for d in ('weekday','weekend') for h in range(24))


class Sources:
    def __init__(self,catalog,root):
        self.catalog=catalog
        self.root=root
        self.reader=VerifiedReader(catalog)
        self.names={bid:s['building']['name'] for bid,s in catalog.get('ordinary_buildings',{}).items()}
        frozen=catalog.get('global_bundle',{}).get('building_source',{}).get('building')
        if frozen:
            self.names[frozen['id']]=frozen['name']
        self.versions={s['sha256']:s for s in Library(root).all('usage')}
        self.cache={}

    def menu(self,target):
        if target not in self.names:raise ValueError('目标建筑未登记可读取的房间配置。')
        return [dict(id=bid,name=name,versions=[dict(id='baseline',name='原始配置')]+[
            dict(id=s['sha256'],name=f"{s['name']} · v{s['revision']}")
            for s in self.versions.values() if s['content']['building_id']==bid])
            for bid,name in self.names.items() if bid!=target]

    def load(self,bid,version='baseline'):
        key=(bid,version)
        if key in self.cache:return self.cache[key]
        if bid not in self.names:raise ValueError('来源建筑未登记。')
        if version=='baseline':
            content,model,_=baseline(self.catalog,self.reader,building_id=bid)
            meta=source_snapshot(self.root) if bid==SOURCE else dict(rooms=self.catalog['ordinary_buildings'][bid]['usage_sources'])
            name='原始配置'
        else:
            snap=self.versions.get(version)
            if not snap or snap['content']['building_id']!=bid:raise ValueError('所选配置版本与来源建筑不符。')
            base,model,meta,_,_=self.load(bid)
            content=validate_content(snap['content'],base)
            name=f"{snap['name']} · v{snap['revision']}"
        original_by_id={r['id']:r for r in base['rooms']} if version!='baseline' else {}
        rooms=[]
        for room in content['rooms']:
            detail=meta['rooms'].get(room['id'],{})
            channels={}
            for channel,load in room['loads'].items():
                actual=actual_pair(load,room['area_m2'])
                rule=load if load.get('kind')=='scaled' else None
                if rule is None and (version=='baseline' or load==original_by_id[room['id']]['loads'][channel]):
                    candidate=detail.get('channels',{}).get(channel,{}).get('rule') or {}
                    if candidate.get('kind')=='scaled':
                        validate_load(candidate,channel,room['area_m2'])
                        if same_pair(actual,actual_pair(candidate,room['area_m2'])):rule=candidate
                channels[channel]=dict(actual=actual,rule=rule,source_units_verified=rule is not None,
                                       peak=max(actual['weekday']+actual['weekend']))
            rooms.append(dict(id=room['id'],zone=room['zone'],area_m2=room['area_m2'],conditioned=room['conditioned'],
                              use=detail.get('use') or '用途未标注',channels=channels))
        proof=dict(building_id=bid,building_name=self.names[bid],version=version,version_name=name,
                   baseline_sha256=content['baseline_sha256'],metadata_sha256=digest(meta))
        self.cache[key]=(content,model,meta,rooms,proof)
        return self.cache[key]

    def target(self,bid):
        base,model,_,rooms,_=self.load(bid)
        return base,model,[{k:v for k,v in r.items() if k!='channels'} for r in rooms]

    def select(self,target,source,version):
        menu=self.menu(target)
        if source is None:
            source=next((s['id'] for s in menu if s['id']==SOURCE),menu[0]['id'] if menu else None)
        if source==target:raise ValueError('请选择另一栋已登记建筑。')
        return self.load(source,version) if source is not None else None


def options(catalog,root,target,source=None,version='baseline'):
    db=Sources(catalog,root)
    _,_,targets=db.target(target)
    selected=db.select(target,source,version) if source!='' else None
    rooms,proof=selected[3:] if selected else ([],None)
    db.reader.unchanged()
    uses=[]
    for use in sorted({r['use'] for r in targets}):
        candidates=[r['id'] for r in rooms if r['use']==use and use!='用途未标注']
        uses.append(dict(use=use,targets=[r['id'] for r in targets if r['use']==use],candidates=candidates,requires_selection=True))
    return dict(source_name=proof['building_name'] if proof else '',target_name=db.names[target],sources=db.menu(target),
                source=proof,rooms=rooms,targets=targets,type_candidates=uses,bases=BASES,
                note='用途名称仅用于筛选候选。来源房间、目标房间和通道均需明确选择；本入口不搬移温控、得热参数或材料应用。')


def converted(origin,channel,basis,area,proof,legacy=False):
    entry=origin['channels'][channel];rule=copy.deepcopy(entry['rule'])
    if basis=='source_units' and rule is None:raise ValueError('来源单位说明未能与原配置核对；请改选每间实际值或面积密度，不能猜测原单位。')
    if basis=='area_density' and origin['area_m2']<=0:raise ValueError('来源房间面积必须大于零，才能换算为面积密度。')
    if rule is None:
        peak=entry['peak']
        rule=dict(kind='scaled',unit='people' if channel=='people' else 'W',minimum=0,maximum=peak)
        for day in ('weekday','weekend'):
            rule[day]=[x/peak if peak else 0 for x in entry['actual'][day]]
    per_area=rule['unit'].endswith('/m2')
    if basis=='room_totals' and per_area:
        rule['minimum']*=origin['area_m2'];rule['maximum']*=origin['area_m2'];rule['unit']=rule['unit'].removesuffix('/m2')
    elif basis=='area_density' and not per_area:
        rule['minimum']/=origin['area_m2'];rule['maximum']/=origin['area_m2'];rule['unit']+='/m2'
    if legacy:
        rule['basis']=f"跨建筑复用起点：Drawing26 {origin['zone']} / {origin['id']}；{BASES[basis]}；来源配置 {proof['baseline_sha256']}；单位作息来源 {proof['metadata_sha256']}。"
    else:
        identity=[proof['building_id'],proof['version'],origin['id'],basis,proof['baseline_sha256'],proof['metadata_sha256']]
        rule['basis']=ORIGIN_PREFIX+json.dumps(identity,ensure_ascii=False,separators=(',',':'))
    validate_load(rule,channel,area)
    return rule


def coverage(content,base,targets,db):
    """Describe current values, not a count of clicks or a claim that every room must change."""
    labels={r['id']:r for r in targets};rows=[]
    totals=dict(rooms=len(content['rooms']),full=0,partial=0,none=0,reused_items=0,edited_reuse_items=0,unverified_items=0,other_edits=0)
    pattern=r'跨建筑复用起点：Drawing26 (.+?) / (\S+)；([^；]+)；来源配置 ([a-f0-9]{64})；单位作息来源 ([a-f0-9]{64})。'
    for room,original in zip(content['rooms'],base['rooms']):
        cells={}
        for channel in CHANNELS:
            rule=room['loads'][channel];before=original['loads'][channel]
            cell=dict(state='original' if rule==before else 'edited',origin=None,
                      actual_changed=not same_pair(actual_pair(rule,room['area_m2']),actual_pair(before,room['area_m2'])))
            match=re.fullmatch(pattern,rule.get('basis',''))
            detail=rule.get('basis','')
            if match or detail.startswith(ORIGIN_PREFIX):
                cell['state']='unverified'
                try:
                    if match:
                        zone,ident,label,baseline_hash,metadata_hash=match.groups()
                        bid,version=SOURCE,'baseline'
                        basis=next(k for k,v in BASES.items() if v==label)
                    else:
                        bid,version,ident,basis,baseline_hash,metadata_hash=json.loads(detail[len(ORIGIN_PREFIX):])
                        zone=ident
                    cell['origin']=dict(id=ident,zone=zone,label=BASES[basis],basis=basis,building_id=bid,
                                        building_name=db.names.get(bid,bid),version=version,
                                        baseline_sha256=baseline_hash,metadata_sha256=metadata_hash)
                    _,_,_,origins,proof=db.load(bid,version)
                    origin=next(r for r in origins if r['id']==ident)
                    if (not match or zone==origin['zone']) and baseline_hash==proof['baseline_sha256'] and metadata_hash==proof['metadata_sha256']:
                        expected=converted(origin,channel,basis,room['area_m2'],proof,legacy=bool(match))
                        cell['state']='reused' if rule==expected else 'reuse_edited'
                        cell['origin'].update(zone=origin['zone'],version_name=proof['version_name'])
                except (ValueError,KeyError,StopIteration,TypeError,OSError):
                    pass
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
    db=Sources(catalog,root);target=content.get('building_id')
    base,model,targets=db.target(target);validate_content(content,base)
    if saved_record['factors']['building']['id']!=target:raise ValueError('方案与目标建筑不一致。')
    from component_library import verify
    selected=body.get('selected_profile');saved=saved_record['factors']['building'].get('usage_profile')
    for ref in (selected,saved):
        if ref:validate_content(verify(ref,'usage')['content'],base)
    adopted=selected['content'] if selected else base
    name=selected['name'] if selected else saved_record['factors']['building']['name']+' 房间使用'
    status='draft' if content!=adopted or body.get('configuration_name',name)!=name else 'configuration' if selected!=saved else 'saved'
    result=coverage(content,base,targets,db)
    result.update(save_state=status,scheme=dict(id=saved_record['id'],revision=saved_record['revision']),
                  differences=differences(base,content,base,gain_defaults(model)))
    result['notes']=context_notes(result['differences'],content,body.get('overrides',{}),body.get('mode','controlled'))
    result['note']='按当前配置记录核对，不把仅预览的选择计入。无复用记录的房间可以继续使用原配置，不要求全部复用。'
    db.reader.unchanged()
    result['sha256']=digest(result);result['checked_at']=now();return result


def preview(body,catalog,root):
    allowed={'content','source_building','source_version','source_room','targets','groups','bases','overrides','mode'}
    if not isinstance(body,dict) or set(body)-allowed:raise ValueError('跨建筑复用请求含未支持字段。')
    content=body.get('content',{})
    if not isinstance(content,dict):raise ValueError('目标配置格式不正确。')
    db=Sources(catalog,root);target=content.get('building_id')
    base,model,target_rows=db.target(target);validate_content(content,base)
    selected=db.select(target,body.get('source_building'),body.get('source_version','baseline'))
    if not selected:raise ValueError('请先登记另一栋带有房间配置的建筑。')
    rooms,proof=selected[3:]
    origin=next((r for r in rooms if r['id']==body.get('source_room')),None)
    if not origin:raise ValueError('请明确选择来源房间。')
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
    before=coverage(content,base,target_rows,db);after=coverage(result,base,target_rows,db)
    out['coverage_before']=before['totals'];out['coverage_after']=after['totals']
    out['overlaps']=[dict(room=r['id'],zone=r['zone'],channel=k,previous=c['origin']) for r in before['rooms'] if r['id'] in targets for k,c in r['channels'].items() if k in groups and c['origin']]
    db.reader.unchanged()
    out['review_sha256']=digest(out);out['checked_at']=now()
    return out
