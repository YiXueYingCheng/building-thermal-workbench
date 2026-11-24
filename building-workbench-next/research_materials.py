"""Material-library examples and physical inputs for fixed phase-change and spectral walls."""
import copy
import math

PCM = 'phase_change_layer_v1'
SPECTRAL = 'spectral_exterior_v1'
TYPES = {PCM: 'pcm', SPECTRAL: 'spectral'}
PCM_FIELDS = {'solidus_C', 'liquidus_C', 'latent_kJ_kg', 'mass_fraction'}
SPECTRAL_FIELDS = {'pe_resistance', 'sw_reflectance', 'sw_transmittance', 'emitter_sw_reflectance',
                   'window_transmittance', 'window_absorptance', 'emitter_window_emissivity',
                   'outside_window_emissivity', 'broadband_emissivity'}
VARIANTS = {'covered', 'bare', 'broadband'}


def template(category):
    from material_types import template as physical
    d = physical('solid')
    d.update(category=category, model=PCM if category=='pcm' else SPECTRAL)
    if category=='pcm':
        d['phase_change'] = dict(basis='effective', **dict.fromkeys(PCM_FIELDS))
    else:
        d['spectral'] = dict(variant='covered', **dict.fromkeys(SPECTRAL_FIELDS))
        d['optics'] = {}
    return d


def example(category, variant=None):
    d = template(category)
    if category=='pcm':
        name = 'C18 · 外置相变层'
        note = '研究示例，纯 C18，升降温共用线性相变区间。0.938 太阳反射率与 0.988 长波发射率属于外侧光学表面。'
        d['phase_change'].update(solidus_C=27.65, liquidus_C=28.65, latent_kJ_kg=242.)
        d['optics']['A_R'].update(solar_absorptance=.062, emissivity=.988)
        thermal = (10., .28, 800., 2200.)
    else:
        name = 'PE 覆盖选择性发射层' if variant!='broadband' else '常规宽带辐射制冷面 · 匹配太阳吸收'
        note = '单墙研究示例。太阳透射率为假设值。宽带对照按覆盖系统的太阳吸收率匹配；载体物性共用。'
        d['spectral'].update(variant=variant or 'covered', pe_resistance=.30,
            sw_reflectance=.922, sw_transmittance=.060, emitter_sw_reflectance=.942,
            window_transmittance=.8, window_absorptance=.1, emitter_window_emissivity=1.,
            outside_window_emissivity=0., broadband_emissivity=.95)
        thermal = (4., 1.5, 2000., 900.)
    d.update(id='example_'+category+'_'+(variant or 'default'), name=name, source_note=note,
             property_source=dict(method='demonstration', note=note))
    s = d['states'][0]
    s.update(zip(('thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK'), thermal))
    s['resistance_m2K_W'] = thermal[0]/1000/thermal[1]
    return d


def presets():
    from foundation import digest
    return [dict(id='builtin_'+d['id'], revision=1, name=d['name'], content=d, builtin=True,
                 source='8777 材料计算示例',source_sha256=digest(d),license='工作台研究参数')
            for d in (example('pcm'),example('spectral'),example('spectral','broadband'))]


def latent(d):
    p = d['phase_change']
    return p['latent_kJ_kg']*1000*(p['mass_fraction'] if p['basis']=='fraction' else 1.)


def solar_split(p):
    r,t,b = (p[k] for k in ('sw_reflectance','sw_transmittance','emitter_sw_reflectance'))
    through = t/(1-r*b) if r*b<1 else 0.
    return (1-r-t)*(1+b*through), (1-b)*through


def errors(d, complete):
    pcm = d['model']==PCM
    key = 'phase_change' if pcm else 'spectral'
    p = d.get(key)
    fields = PCM_FIELDS if pcm else SPECTRAL_FIELDS
    choice = 'basis' if pcm else 'variant'
    if not isinstance(p,dict) or set(p)-fields-{choice} or p.get(choice) not in ({'effective','fraction'} if pcm else VARIANTS):
        return ['请核对材料计算方式及专用字段。']
    required = set(fields)
    if pcm and p['basis']=='effective': required.remove('mass_fraction')
    if not pcm:
        if p['variant']=='bare': required={'emitter_sw_reflectance','emitter_window_emissivity'}
        elif p['variant']=='broadband': required={'sw_reflectance','sw_transmittance','emitter_sw_reflectance','broadband_emissivity'}
        else: required.remove('broadband_emissivity')
    problems=[]
    for field in fields:
        v = p.get(field)
        if v is None:
            if complete and field in required: problems.append('待补参数 '+field)
            continue
        if type(v) not in (int,float) or not math.isfinite(v):
            problems.append('需填写有限数值 '+field)
        elif field=='pe_resistance' and v<=0 or field=='latent_kJ_kg' and v<0:
            problems.append('无效热物性 '+field)
        elif field not in ('pe_resistance','latent_kJ_kg','solidus_C','liquidus_C') and not 0<=v<=1:
            problems.append('比例须在 0 到 1 之间 '+field)
    if problems:return problems
    if pcm:
        if p.get('solidus_C') is not None and p.get('liquidus_C') is not None and p['solidus_C']>=p['liquidus_C']:
            problems.append('液相线温度应高于固相线。')
    else:
        for a,b in [('sw_reflectance','sw_transmittance'),('window_transmittance','window_absorptance')]:
            if p.get(a) is not None and p.get(b) is not None and p[a]+p[b]>1+1e-12:
                problems.append('同波段反射、透射和吸收之和须为 1。')
    return problems


def validate(d, complete):
    from material_types import validate
    extra = 'phase_change' if d['model']==PCM else 'spectral'
    if d.get('category')!=TYPES[d['model']] or d.get('faces')!=['A'] or d.get('optics_depend_on_state') is not False:
        return ['固定材料的类别或表面定义不一致。']
    if d['model']==SPECTRAL and d.get('optics')!={}:return ['光谱边界应使用分波段参数。']
    base = copy.deepcopy(d)
    base.pop(extra,None)
    base.update(model='solid_layer_v1',category='solid')
    return validate(base,complete)+errors(d,complete)


def pcm_layer(model, name, construction, state, d):
    p = d['phase_change']
    low,high = p['solidus_C'],p['liquidus_C']
    heat = latent(d)
    if heat:
        start,end=min(-100.,low-10),max(150.,high+10)
        points=[(start,0.),(low,0.),(high,heat),(end,heat)]
        model.setdefault('MaterialProperty:PhaseChange',{})[name] = {
            'temperature_coefficient_for_thermal_conductivity':0.,
            'values':[dict(temperature=t,enthalpy=state['specific_heat_J_kgK']*(t-start)+h) for t,h in points]}
    model.setdefault('SurfaceProperty:HeatTransferAlgorithm:Construction',{})[construction]=dict(
        construction_name=construction,algorithm='ConductionFiniteDifference')
    settings=model.setdefault('HeatBalanceSettings:ConductionFiniteDifference',{})
    if not settings:
        settings['WB FD']=dict(difference_scheme='FullyImplicitFirstOrder',space_discretization_constant=3.,
                               relaxation_factor=1.,inside_face_surface_temperature_convergence_criteria=.001)
