"""Resolve one saved design cell from immutable input versions, on demand."""
import copy
import re
from itertools import chain

from calendar_library import active_references, stable_numbers
from comparison_reading import installation
from foundation import canonical, digest, loads, now
from inspection_io import reading
from model_adapter import capability
from pair_evidence import pin
from research_sets import recipe, require
from theme_groups import design_facts


AXES = {'optical': re.compile(r'(?:表面)?光学(?:策略|切换|状态)?'),
        'thermal': re.compile(r'(?:材料)?热阻(?:策略|调节|状态)?')}
VALUES = {'optical': {'固定 A', '季节光学切换'}, 'thermal': {'固定蓬松', '固定压缩', '按反馈调节热阻'}}
CHANNEL = {'optical': 'orientation', 'thermal': 'thermal'}


def describe(record):
    return dict(ref=pin(record), name=record['name'], archived=bool(record.get('archived')))


def choices_for_cell(design, cell):
    axes = design['axes']
    choices = {}
    for pos, axis in enumerate(axes):
        field = next((key for key, pattern in AXES.items() if pattern.fullmatch(axis['name'])), None)
        value = axis['values'][(cell >> (len(axes)-pos-1)) & 1]
        require(field and value in VALUES[field], '这项自定义设置需要手动选择方案版本。')
        require(field not in choices, '两条研究轴指向了同一项控制，请先调整设计。')
        choices[field] = value
    return choices


def setting(record, field):
    condition = record['factors']['condition']
    control = next(c for c in condition['controls'] if c['channel'] == CHANNEL[field])
    return dict(control=control, references=active_references(record) if field=='optical' else [])


def basis(record):
    # All input outside the two named controls, including unrelated references, must agree.
    condition = record['factors']['condition']
    used = {r['id'] for r in active_references(record)}
    rest = dict(condition, controls=[{k:c[k] for k in ('application_id','channel','target_ids')}
                                      for c in condition['controls']],
                reference_runs=[r for r in condition['reference_runs'] if r['id'] not in used])
    provenance = record['provenance']
    return digest(stable_numbers([provenance['adapter'], provenance['snapshot_id'], record['numerics'],
                                  dict(record['factors'],condition=rest)]))


def fixed_setting(base, field, value):
    original = setting(base,field)['control']
    control = {k:v for k,v in original.items() if k in ('application_id','channel','target_ids','id')}
    control['mode'] = 'fixed'
    if field=='thermal':
        name = value.removeprefix('固定')
        states = base['factors']['materials']['definitions'][0]['states']
        matches = [s['id'] for s in states if s['name']==name]
        require(len(matches)==1, '来源材料需要一份可唯一识别的'+name+'态实测定义。')
        control['state_id'] = matches[0]
    else:
        control['face_id'] = 'A'
    return dict(control=control,references=[])


def setting_key(rule):
    return digest(stable_numbers(rule))


def rule_detail(rule):
    c=rule['control']
    if c['mode']=='feedback':
        policy=c.get('policy',{})
        return ' / '.join(str(v) for v in (c.get('rule'), str(c.get('update',{}).get('minutes','—'))+' min 判断',
                           str(policy.get('minimum_hold_minutes','—'))+' min 保持',
                           str(policy.get('cold_C','—'))+'–'+str(policy.get('hot_C','—'))+' °C',
                           str(policy.get('flux_deadband_W_m2','—'))+' W/m² 死区'))
    if c['mode']=='calendar':
        return '、'.join(str(r['snapshot'].get('name') or r['id'])+' · v'+str(r['snapshot'].get('revision','—'))
                        for r in rule['references'])
    return ''


def preview(store, db, design, cell, selected, *, expected_recipe=None, expected_ref=None, check_model=True):
    want = choices_for_cell(design,cell)
    source = store.get(design['base']['id'],design['base']['revision'])
    app = installation(source)
    require(app,'起始版本需要有可识别的材料应用及热学、光学控制。请调整起始版本或手动选用。')
    source_facts=design_facts(source)
    source_basis=basis(source)
    expected={}
    donors={}
    for field in CHANNEL:
        if field not in want or want[field]==source_facts[field]:
            expected[field]=setting(source,field)
        elif want[field].startswith('固定'):
            expected[field]=fixed_setting(source,field,want[field])
        else:
            donors[field]={}
    expected_keys={field:setting_key(rule) for field,rule in expected.items()}
    matches=[]
    occupied=False
    versions=(loads(r[0]) for r in db.execute('SELECT payload FROM versions ORDER BY created DESC,revision DESC,id'))
    for record in chain(versions,store.catalog['records'].values()):
        if record['provenance']['snapshot_id']!=source['provenance']['snapshot_id'] or not installation(record) or basis(record)!=source_basis:
            continue
        facts=design_facts(record)
        for field,variants in donors.items():
            if facts[field]==want[field]:
                rule=setting(record,field)
                variants.setdefault(setting_key(rule),(describe(record),rule))
        if not all(facts[f]==v for f,v in want.items()):continue
        if not all(setting_key(setting(record,f))==key for f,key in expected_keys.items()):continue
        if expected_ref and pin(record)!=expected_ref:continue
        if expected_recipe and recipe(record)!=expected_recipe:continue
        if pin(record) in design['cells']:
            occupied=True
        else:
            detail=[rule_detail(setting(record,f)) for f in CHANNEL if facts[f] in ('季节光学切换','按反馈调节热阻')]
            matches.append(dict(**describe(record),detail=' · '.join(detail),recipe=recipe(record)))
    coordinates=dict(design=design['id'],revision=design['revision'],cell=cell)
    common=dict(source=describe(source),goal=' · '.join(want.values()),source_state=source_facts['summary'],
                walls=app['count'],material=app['material'],building=source['factors']['building']['name'],
                step=source['numerics']['step_minutes'],period=source['factors']['scope']['period'],
                sites=source['factors']['scope']['site_ids'])
    if matches:
        return dict(common,kind='existing',matches=matches,token=digest([coordinates,matches])),None
    require(not expected_ref,'追问指定的保存版本与本格当前输入不再匹配，请返回追问重新核对。')
    require(not occupied,'匹配的版本已绑定在本设计的其他格，请先核对工况设置。')
    options={}
    origins={}
    for field,variants in donors.items():
        require(variants,'缺少与本材料、应用范围和计算条件一致的'+want[field]+'来源，请先保存相应规则。')
        key=selected.get(field)
        if key is None and len(variants)==1:key=next(iter(variants))
        if key is None:
            options[field]=[dict(version=v,key=k,detail=rule_detail(rule)) for k,(v,rule) in variants.items()]
        else:
            require(key in variants,'所选规则来源已变化，请重新预览。')
            origins[field],expected[field]=variants[key]
    if options:return dict(common,kind='options',options=options),None
    factors=copy.deepcopy(source['factors'])
    condition=factors['condition']
    condition['controls']=[expected[next(f for f,ch in CHANNEL.items() if ch==c['channel'])]['control']
                           for c in condition['controls']]
    if setting_key(expected['optical'])!=setting_key(setting(source,'optical')):
        old={r['id'] for r in active_references(source)}
        refs=[r for r in condition['reference_runs'] if r['id'] not in old]
        for r in expected['optical']['references']:
            require(not any(x['id']==r['id'] and x!=r for x in refs),'日历引用编号冲突，请核对来源。')
            if r not in refs:refs.append(r)
        condition['reference_runs']=refs
    name=(source['factors']['building']['name']+' · '+ ' · '.join(want.get(f,source_facts[f]) for f in CHANNEL))[:100]
    target=store.update_payload(source,dict(name=name,factors=factors))
    require(not expected_recipe or recipe(target)==expected_recipe,'所选规则与原追问的工况不符，请重新核对。')
    after=design_facts(target)
    require(basis(target)==source_basis and all(after[f]==v for f,v in want.items()) and
            all(setting_key(setting(target,f))==setting_key(rule) for f,rule in expected.items()),
            '实际输入与预期改动不一致，请核对来源。')
    require(recipe(source)!=recipe(target),'来源版本已具有这项输入。')
    if check_model:
        with reading():supported=capability(target,store.catalog)
        require(supported['supported'],'；'.join(supported.get('reasons',[])) or '当前模型尚不支持此工况。')
    changes=[dict(label={'thermal':'热阻策略','optical':'表面光学策略'}[f],before=source_facts[f],after=after[f])
             for f in CHANNEL if setting_key(setting(source,f))!=setting_key(expected[f])]
    states=source['factors']['materials']['definitions'][0]['states']
    def state(record):
        c=setting(record,'thermal')['control']
        return next((s for s in states if s['id']==c.get('state_id')), {})
    first,last=state(source),state(target)
    for k,label in [('thickness_mm','厚度 / mm'),('density_kg_m3','密度 / kg/m³'),
                    ('conductivity_W_mK','导热率 / W/(m·K)'),('specific_heat_J_kgK','比热 / J/(kg·K)'),
                    ('resistance_m2K_W','热阻 / m²·K/W')]:
        if first.get(k)!=last.get(k) and k in first and k in last:
            changes.append(dict(label=label,before=first[k],after=last[k]))
    result=dict(common,kind='derive',name=name,target_state=after['summary'],changes=changes,origins=origins,
                rules={f:rule_detail(expected[f]) for f in origins})
    result['token']=digest([coordinates,result,recipe(target),source['execution']])
    return result,target


def resolve_cell(store,body,confirm=False):
    ident,revision,cell=body.get('id'),body.get('revision'),body.get('cell')
    require(isinstance(ident,str) and type(revision) is int and type(cell) is int,'请选择已保存设计中的工况。')
    selected=body.get('rules',{})
    require(isinstance(selected,dict) and all(k in CHANNEL and isinstance(v,str) for k,v in selected.items()),'规则选择无效。')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE' if confirm else 'BEGIN')
        row=db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
        require(row,'未找到已保存的设计。')
        design=loads(row[0])
        require(0<=cell<len(design['cells']),'工况位置无效。')
        receipt=design.get('cell_action',{})
        if confirm and design['revision']==revision+1 and receipt.get('cell')==cell and receipt.get('token')==body.get('token') and receipt.get('choice')==body.get('choice'):
            return design
        require(design['revision']==revision and not design['cells'][cell],'设计版本或所选工况已变化，请重新打开。')
        result,target=preview(store,db,design,cell,selected,expected_recipe=body.get('expected_recipe'),expected_ref=body.get('expected_ref'))
        if not confirm:return result
        require(result.get('token') and result['token']==body.get('token'),'来源或可用版本已变化，请重新预览。')
        if result['kind']=='existing':
            choice=body.get('choice')
            require(any(v['ref']==choice for v in result['matches']),'请选择预览中的已有版本。')
        else:
            require(body.get('choice') is None and target is not None,'请先完成派生预览。')
            base=design['base']
            record=store.insert_draft(db,store.get(base['id'],base['revision']),target)
            choice=pin(record)
        design['cells'][cell]=choice
        design.update(revision=revision+1,updated=now(),cell_action=dict(cell=cell,token=result['token'],choice=body.get('choice')))
        design.setdefault('cell_origins',{})[str(cell)]=dict(kind=result['kind'],source=result['source'],bound=choice,
                  name=result.get('name'),origins=result.get('origins',{}),changes=result.get('changes',[]))
        db.execute('INSERT INTO comparison_designs VALUES(?,?,?)',(ident,revision+1,canonical(design)))
        return design
