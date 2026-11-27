"""Physical material input is independent of the calibrated ECA control adapter."""
import math,copy
import research_materials as research
import composite_materials as stack
from foundation import digest

MODELS = {'optical_surface_v1', 'solid_layer_v1', 'solid_variable_v1'}
CATEGORIES = {'film':'薄膜／涂层', 'solid':'固定实体材料', 'variable':'可调实体材料'}


def template(category='solid', include_thermal=False):
    if category in research.TYPES.values():return research.template(category)
    if category not in CATEGORIES: raise ValueError('请选择材料类别。')
    thermal = category != 'film' or include_thermal
    states = []
    for ident, name in ([('R','状态 1'), ('C','状态 2')] if category == 'variable' else [('R','固定状态')]):
        states.append(dict(id=ident, name=name, thermal_input='conductivity_thickness' if thermal else 'optical_only',
            thickness_mm=None, conductivity_W_mK=None, density_kg_m3=None, specific_heat_J_kgK=None, resistance_m2K_W=None))
    return dict(id='user_material', name='', kind='single_layer', category=category,
        model=('solid_variable_v1' if category=='variable' else 'solid_layer_v1') if thermal else 'optical_surface_v1',
        state_identity='independent', states=states, faces=['A'], optics_depend_on_state=False,
        optics={'A_R':dict(input_basis='effective_surface_absorptance', solar_absorptance=None, emissivity=None)},
        property_source=dict(method='user_input', note=''), source_note='')


def supported(definition):
    return definition.get('model') == stack.MODEL or definition.get('model') in MODELS or definition.get('model') in research.TYPES


def validate(definition, complete=False):
    if definition.get('model') == stack.MODEL:return stack.validate(definition)
    if definition.get('model') in research.TYPES:return research.validate(definition,complete)
    d=definition; errors=[]
    allowed={'id','name','kind','model','category','state_identity','states','faces','optics_depend_on_state','optics','property_source','source_note','state_relationship'}
    if set(d)-allowed: errors.append('材料含尚未适配的字段。')
    if d.get('category') not in CATEGORIES or d.get('kind')!='single_layer' or d.get('state_identity')!='independent':errors.append('材料类别或状态定义无效。')
    if d.get('model')=='optical_surface_v1' and d.get('category')!='film':errors.append('仅表面光学模型限于薄膜／涂层。')
    if (d.get('model')=='solid_variable_v1') != (d.get('category')=='variable'):errors.append('可调材料需使用独立多状态定义。')
    expected=['R','C'] if d.get('category')=='variable' else ['R']
    states=d.get('states',[])
    if not isinstance(states,list) or [s.get('id') for s in states if isinstance(s,dict)]!=expected:errors.append('请保留该类别的独立状态。')
    if d.get('faces') not in (['A'],['A','B']):errors.append('请选择一个表组或 A/B 两组。')
    if type(d.get('optics_depend_on_state')) is not bool:errors.append('请明确光学与状态的关系。')
    thermal=d.get('model')!='optical_surface_v1'
    fields=('thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK')
    for s in states:
        if not isinstance(s,dict):continue
        if set(s)-{'id','name','thermal_input',*fields,'resistance_m2K_W'}:errors.append('状态含尚未适配的物性字段。')
        if not isinstance(s.get('name'),str) or not s['name'].strip():errors.append('请填写状态名称。')
        if s.get('thermal_input')!=('conductivity_thickness' if thermal else 'optical_only'):errors.append('输入方式与材料计算模型不一致。')
        for k in fields:
            v=s.get(k)
            if not thermal and v is not None:errors.append('仅表面光学模式不保存隐含的热学参数。')
            if thermal and ((v is None and complete) or (v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<=0))):errors.append('请补齐正数厚度、导热率、密度和比热。')
        cp=s.get('specific_heat_J_kgK')
        if not thermal and s.get('resistance_m2K_W') is not None:errors.append('仅表面光学模式不保存隐含热阻。')
        if thermal and type(cp) in (int,float) and cp<100:errors.append('当前引擎要求比热不低于 100 J/(kg·K)。')
    optics=d.get('optics',{})
    if not isinstance(optics,dict):return errors+['光学参数格式无效。']
    expected_keys={face+'_'+state for face in d.get('faces',[]) for state in expected}
    if set(optics)-expected_keys:errors.append('存在未声明表面或状态的光学参数。')
    for key,o in optics.items():
        if not isinstance(o,dict):errors.append('光学参数格式无效。');continue
        if set(o)-{'input_basis','solar_absorptance','emissivity','visible_absorptance','solar_input'} or o.get('input_basis')!='effective_surface_absorptance':errors.append('请填写覆盖后的有效表面吸收率与发射率。')
        errors.extend(validate_solar_input(o))
        for k in ('solar_absorptance','emissivity','visible_absorptance'):
            v=o.get(k)
            if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1):errors.append('光学参数应为 0–1 的有限数值。')
        v=o.get('emissivity')
        if type(v) in (int,float) and not 0<v<=.99999:errors.append('发射率须大于 0 且不超过 0.99999。')
    source=d.get('property_source',{})
    if not isinstance(source,dict) or set(source)!={'method','note'} or source.get('method') not in ('user_input','measured','derived','source_reference','demonstration') or not isinstance(source.get('note'),str) or len(source.get('note',''))>1000:errors.append('请明确物性来源类型和说明。')
    if complete and not source.get('note','').strip():errors.append('计算前请填写物性来源或推算依据。')
    errors.extend(validate_relationship(d))
    return list(dict.fromkeys(errors))


def number(value):return type(value) in (int,float) and math.isfinite(value)


def validate_solar_input(optics):
    if 'solar_input' not in optics:return [] # Preserve old snapshots and their meanings.
    entry=optics['solar_input'];alpha=optics.get('solar_absorptance')
    if not isinstance(entry,dict) or set(entry)!={'quantity','value'} or entry['quantity'] not in ('absorptance','reflectance'):
        return ['太阳光学输入依据无效。']
    value=entry['value']
    if value is None and alpha is None:return []
    if not number(value) or not 0<=value<=1 or not number(alpha):return ['太阳光学输入需为 0–1 数值。']
    expected=value if entry['quantity']=='absorptance' else 1-value
    return [] if math.isclose(alpha,expected,rel_tol=0,abs_tol=1e-12) else ['太阳吸收率与所记输入依据不一致，请重新核对；未自动改写。']


def relationship_inputs(source,target,cp_rule):
    return dict(source_thickness_mm=source.get('thickness_mm'),source_density_kg_m3=source.get('density_kg_m3'),
        target_thickness_mm=target.get('thickness_mm'),source_specific_heat_J_kgK=source.get('specific_heat_J_kgK') if cp_rule=='shared' else None)


def density_preview(definition,source_state='R',cp_rule='independent',confirmed=False):
    if not isinstance(definition,dict) or definition.get('model')!='solid_variable_v1' or confirmed is not True:
        raise ValueError('仅在明确确认同一试件、质量及覆盖面积不变后，才能推算另一状态密度。')
    if cp_rule not in ('independent','shared'):raise ValueError('请明确比热独立填写或共用。')
    entries=definition.get('states')
    if not isinstance(entries,list) or len(entries)!=2 or any(not isinstance(s,dict) or s.get('id') not in ('R','C') for s in entries):
        raise ValueError('请选择明确的两个材料状态。')
    states={s['id']:s for s in entries}
    if set(states)!={'R','C'} or source_state not in states:raise ValueError('请选择明确的基准状态。')
    source=states[source_state];target=states['C' if source_state=='R' else 'R'];inputs=relationship_inputs(source,target,cp_rule)
    if any(not number(v) or v<=0 for k,v in inputs.items() if k!='source_specific_heat_J_kgK'):
        raise ValueError('请先填写正数的基准厚度、基准密度及目标厚度。')
    if cp_rule=='shared' and (not number(inputs['source_specific_heat_J_kgK']) or inputs['source_specific_heat_J_kgK']<100):
        raise ValueError('共用比热需要先填写有效的基准比热。')
    density=source['density_kg_m3']*source['thickness_mm']/target['thickness_mm']
    if not number(density) or density<=0:raise ValueError('密度推算超出有效范围。')
    relationship=dict(mode='constant_mass_area',source_state=source['id'],target_state=target['id'],specific_heat=cp_rule,inputs=inputs)
    changed=copy.deepcopy(target);changed['density_kg_m3']=density
    if cp_rule=='shared':changed['specific_heat_J_kgK']=source['specific_heat_J_kgK']
    return dict(relationship=relationship,source=source,target_before=target,target_after=changed,
        source_summary=state_summary(source),target_summary=state_summary(changed),
        note='同一试件、质量及覆盖面积不变；目标密度 = 基准密度 × 基准厚度 ÷ 目标厚度。导热率保持各态输入。')


def validate_relationship(definition):
    if 'state_relationship' not in definition:return []
    relation=definition['state_relationship']
    try:
        if not isinstance(relation,dict) or set(relation)!={'mode','source_state','target_state','specific_heat','inputs'} or relation['mode']!='constant_mass_area':raise ValueError()
        current=density_preview(definition,relation['source_state'],relation['specific_heat'],True)
        if current['relationship']!=relation:raise ValueError()
        target=current['target_before'];expected=current['target_after']
        for key in ('density_kg_m3',*(['specific_heat_J_kgK'] if relation['specific_heat']=='shared' else [])):
            if not number(target.get(key)) or not math.isclose(target[key],expected[key],rel_tol=1e-12,abs_tol=1e-12):raise ValueError()
        return []
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
        return ['密度推算依据或派生值已变化：请重新预览并采用，或明确改为独立填写；未自动覆盖参数。']


def support_paths():
    return [dict(id='optical_surface_v1',name='仅表面光学',scope='贴覆不透明外墙／屋面的外表面',inputs='覆盖后的太阳吸收率与长波发射率；可见光可明确覆盖或按目标继承',control='固定光学参数组；原构造热阻与蓄热保留',status='过渡版已接入'),
        dict(id='solid_layer_v1',name='固定实体层',scope='不透明外墙／屋面外侧附加层',inputs='厚度、导热率、密度、比热及表面光学',control='一次计算固定一个状态；计入该层蓄热',status='过渡版已接入'),
        dict(id='solid_variable_v1',name='通用多状态实体',scope='方案所选不透明外墙／屋面',inputs='各态独立物性；可明确选用质量／面积不变推算辅助',control='固定态对照；面质量与比热守恒时支持反馈。双面实体可按日历切换表面光学参数。',status='本地候选版'),
        dict(id=stack.MODEL,name='多层组合材料',scope='外墙、屋面；外侧、内侧或原构造层间',inputs='按室外至室内顺序选取已保存材料版本和各层状态',control='外侧铺设的双组最外层可固定或按日历切换光学组。各层可固定，可指定一层面质量和比热守恒的两态实体参与热阻反馈。相变层采用有限差分焓法。',status='研究端已接入'),
        dict(id=research.PCM,name='相变层',scope='所选室外不透明墙外侧',inputs='实体物性、相变区间及有效潜热',control='固定层序，有限差分焓法',status='研究端已接入'),
        dict(id=research.SPECTRAL,name='辐射解耦与宽带对照',scope='所选室外不透明墙外侧',inputs='载体热物性、PE 热阻与分波段光学参数',control='固定光学与固定热阻，逐墙解表面热平衡',status='研究端已接入'),
        dict(id='legacy_eca',name='旧 ECA 示例路线',scope='已适配建筑、目标墙及原接法',inputs='原等效热阻和双面光学定义',control='按原示例支持固定、反馈或逐日光学切换；忽略等效层自身蓄热',status='保留旧模型含义'),
        dict(id='development_solid_eca',name='特定实体 ECA 动态研究',scope='开发版北京五层既定 135 面外墙',inputs='指定试件及校准物性、引擎和控制规则',control='北京特定四工况全年已验证；不推广为任意材料算法',status='开发版历史验证记录')]


def state_summary(state):
    d,k,rho,cp=(state.get(k) for k in ('thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK'))
    return dict(resistance_m2K_W=d/1000/k if d and k else None,
        areal_mass_kg_m2=rho*d/1000 if rho and d else None,
        areal_capacity_J_m2K=rho*cp*d/1000 if rho and cp and d else None)
