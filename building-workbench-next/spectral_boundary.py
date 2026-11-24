"""Generate a two-band exterior heat balance using native EnergyPlus EMS.
Opaque host surfaces remain Outdoors, so their apertures retain the original solar geometry.
The input contains the entire solver; there is no external script dependency at runtime.
"""
import math
from ordinary_materials import measure
from research_materials import solar_split

# Polynomial fits to hemispherical Planck integrals (W/m²), temperature normalized by 100°C.
# Simpson quadrature, 400 subintervals; maximum errors < 0.001 W/m² from -110 to 150°C.
WINDOW=(93.2300055674,175.127726336,104.382989371,11.272431135,-5.968406942,.498732658,.347027062,-.150628028,.021998295)
B4=(111.358064260,215.096202580,136.217915159,20.062341099,-7.067812295,-.042348201,.523620279,-.136115328,.009869260)
SIGMA=5.670374419e-8
NATIVE_EPS=1e-6


def lines(statements):
    return {'lines':[{'program_line':s} for s in statements]}


def add(model,kind,key,value):
    objects=model.setdefault(kind,{})
    if key in objects:raise ValueError('材料边界对象名称冲突 '+key)
    objects[key]=value


def sensor(model,ident,key,variable):
    add(model,'EnergyManagementSystem:Sensor',ident,dict(output_variable_or_output_meter_index_key_name=key,
        output_variable_or_output_meter_name=variable))


def request(model,key,name):
    r=model.setdefault('Output:Variable',{})
    if any(row.get('key_value','*').casefold() in ('*',key.casefold()) and row.get('variable_name','').casefold()==name.casefold() and row.get('reporting_frequency','').casefold()=='timestep' for row in r.values()):return
    label='WB_Material_Report_'+str(len(r))
    while label in r:label+='x'
    r[label]=dict(key_value=key,variable_name=name,reporting_frequency='Timestep')


def globals_(model,names):
    add(model,'EnergyManagementSystem:GlobalVariable','WB spectral variables',
        {'variables':[{'erl_variable_name':n} for n in names]})


def poly(name,coef):
    # Horner form uses separate lines for compatibility with Erl's parser.
    seq=['SET x = wbTemp / 100',f'SET wbBand = {coef[-1]:.12f}']
    seq.extend(f'SET wbBand = (wbBand * x) + ({v:.12f})' for v in reversed(coef[:-1]))
    return name,lines(seq)


def shared(model):
    globals_(model,['wbTemp','wbBand','wbSkyW','wbSkyAll','wbAirSiteW'])
    for name,coef in [('WB_WindowPlanck',WINDOW),('WB_B4Planck',B4)]:
        k,v=poly(name,coef)
        add(model,'EnergyManagementSystem:Subroutine',k,v)
    for key,var in [('wbTsky','Site Sky Temperature'),('wbTa','Site Outdoor Air Drybulb Temperature'),
                    ('wbTd','Site Outdoor Air Dewpoint Temperature'),('wbRain','Site Rain Status')]:
        sensor(model,key,'Environment',var)
    # Li–Coimbra clear-sky spectral deficit fraction; scale to the EPW all-sky broadband deficit.
    ref=sum(c*(.2105**i) for i,c in enumerate(B4))/(SIGMA*294.2**4)
    statements=['SET wbTemp = wbTa','RUN WB_WindowPlanck','SET wbAirSiteW = wbBand','RUN WB_B4Planck',
        'SET pw = 17.67 * wbTd / (wbTd + 243.5)','SET pw = 0.00603356367 * (@Exp pw)',
        'SET pw = @Max 0.0025 pw','SET pw = @Min 0.0225 pw',
        'SET ec = 0.6173 + (1.6940 * (pw ^ 0.5035))','SET eb = 0.1057 + (5.8689 * (pw ^ 0.9633))',
        f'SET share = ({ref:.13f} - eb) / (1 - ec)','SET share = share * wbAirSiteW / wbBand',
        'SET wbSkyAll = 0.00000005670374419 * ((wbTsky + 273.15) ^ 4)',
        'SET bb = 0.00000005670374419 * ((wbTa + 273.15) ^ 4)',
        'SET wbSkyW = wbAirSiteW - ((bb - wbSkyAll) * share)',
        'SET wbSkyW = @Max 0 wbSkyW','SET wbSkyW = @Min wbSkyAll wbSkyW']
    add(model,'EnergyManagementSystem:Program','WB_SpectralWeather',lines(statements))


def schedule_actuator(model,name):
    model.setdefault('ScheduleTypeLimits',{}).setdefault('WB Spectral Unbounded',{'numeric_type':'Continuous'})
    add(model,'Schedule:Constant',name,dict(hourly_value=1,schedule_type_limits_name='WB Spectral Unbounded'))
    add(model,'EnergyManagementSystem:Actuator',name+'Act',dict(actuated_component_unique_name=name,
        actuated_component_type='Schedule:Constant',actuated_component_control_type='Schedule Value'))
    return name+'Act'


def set_convection(model,wall,schedule):
    # Modify only the opaque surface's outside coefficient, preserving its interior film.
    data=model.setdefault('SurfaceProperty:ConvectionCoefficients',{})
    obj=next((v for v in data.values() if v['surface_name'].casefold()==wall.casefold()),None)
    if obj is None:
        obj={'surface_name':wall}
        data['WB H '+wall]=obj
    for i in (1,2):
        prefix=f'convection_coefficient_{i}'
        side=obj.get(prefix+'_location')
        if not side or side=='Outside':
            for k in list(obj):
                if k==prefix or k.startswith(prefix+'_'):del obj[k]
            obj.update({prefix+'_location':'Outside',prefix+'_type':'Schedule',prefix+'_schedule_name':schedule})
            return
    raise ValueError('外墙对流边界重复 '+wall)


def configure(model,wall,p,index):
    if any(row.get('surface_name','').casefold()==wall.casefold() for row in model.get('SurfaceProperty:HeatBalanceSourceTerm',{}).values()):
        raise ValueError('目标已有附加热源，须先核对 '+wall)
    surface=model['BuildingSurface:Detailed'][wall]
    if any(row.get('exterior_surface_name','').casefold()==wall.casefold() for row in model.get('SurfaceProperty:LocalEnvironment',{}).values()):
        raise ValueError('目标使用自定义局地辐射环境，须单独给出其分波段辐照。')
    area,normal=measure(surface)
    up=normal[2]/area
    if next(iter(model['GlobalGeometryRules'].values())).get('vertex_entry_direction','Counterclockwise')=='Clockwise':up=-up
    ground=surface.get('view_factor_to_ground','Autocalculate')
    if not isinstance(ground,(int,float)):ground=(1-up)/2
    sky=1-ground
    k=f'WBSp{index}'
    for token,var in [('Te','Surface Outside Face Temperature'),('G','Surface Outside Face Incident Solar Radiation Rate per Area'),
                      ('Air','Surface Outside Face Outdoor Air Drybulb Temperature'),('Wet','Surface Outside Face Outdoor Air Wetbulb Temperature'),
                      ('Wind','Surface Outside Face Outdoor Air Wind Speed')]:
        sensor(model,k+token,wall,var)
    q=schedule_actuator(model,k+'Q')
    hc=schedule_actuator(model,k+'H')
    set_convection(model,wall,k+'H')
    request(model,k+'H','Schedule Value')
    add(model,'SurfaceProperty:HeatBalanceSourceTerm',k,dict(surface_name=wall,outside_face_heat_source_term_schedule_name=k+'Q'))
    variant=p['variant']
    covered=variant=='covered'
    if variant=='bare':ap,ae=0.,1-p['emitter_sw_reflectance']
    else:ap,ae=solar_split(p)
    absorptance=ap+ae
    statements=[f'SET te = {k}Te',f'SET ta = {k}Air',f'SET sun = {k}G',f'SET h = 5.7 + (3.8 * {k}Wind)',
        'SET wbTemp = ta','RUN WB_WindowPlanck','SET gw = wbBand','SET ga = 0.00000005670374419 * ((ta + 273.15) ^ 4)',
        f'SET iw = ({sky:.12f} * wbSkyW) + ({ground:.12f} * gw)',
        f'SET ia = ({sky:.12f} * wbSkyAll) + ({ground:.12f} * ga)',
        'SET wbTemp = te','RUN WB_WindowPlanck','SET ew = wbBand','SET ea = 0.00000005670374419 * ((te + 273.15) ^ 4)']
    if covered:
        a,t,e,R=(p[n] for n in ('window_absorptance','window_transmittance','emitter_window_emissivity','pe_resistance'))
        r=max(0.,1-a-t)
        den=1-r*(1-e)
        exchange=e/den if den>0 else 0.
        eo=p['outside_window_emissivity']
        # Eliminate emission/reflection from the opaque bottom by a radiosity balance.
        def pe_balance():
            return ['SET wbTemp = tp','RUN WB_WindowPlanck','SET ep = wbBand',
                'SET epfull = 0.00000005670374419 * ((tp + 273.15) ^ 4)',
                f'SET qew = {exchange:.14f} * (({t:.14f} * iw) + ({a:.14f} * ep) - ({1-r:.14f} * ew))',
                f'SET jbottom = ({e:.14f} * ew) + ({1-e:.14f} * (({t:.14f} * iw) + ({a:.14f} * ep) + ({r:.14f} * ew)))' if den==0 else
                f'SET jbottom = (({e:.14f} * ew) + ({1-e:.14f} * (({t:.14f} * iw) + ({a:.14f} * ep)))) / {den:.14f}',
                f'SET qpew = {a:.14f} * (iw + jbottom - (2 * ep))',
                f'SET qpeo = {eo:.14f} * (ia - iw - epfull + ep)',
                f'SET balance = (h * (ta - tp)) + ({ap:.14f} * sun) + qpew + qpeo - ((tp - te) / {R:.14f})']
        statements+=['SET tp = ta','SET iteration = 0','WHILE iteration < 12']+pe_balance()+[
            f'SET slope = h + (1 / {R:.14f}) + (2 * {a:.14f} * 2.3) + ({eo:.14f} * 4.2)',
            'SET tp = tp + (balance / slope)','SET iteration = iteration + 1','ENDWHILE']+pe_balance()+[
            f'SET targetQ = ((tp - te) / {R:.14f}) + ({ae:.14f} * sun) + qew',
            f'SET windowSky = {sky*exchange*t:.14f} * (ew - wbSkyW)',
            f'SET heff = (h / (1 + (h * {R:.14f}))) + {exchange*(1-r)*2.2:.14f}']
    else:
        e=p['broadband_emissivity'] if variant=='broadband' else p['emitter_window_emissivity']
        rad='ia - ea' if variant=='broadband' else 'iw - ew'
        statements+=['SET tp = te','SET balance = 0',
            f'SET targetQ = (h * (ta - te)) + ({absorptance:.14f} * sun) + ({e:.14f} * ({rad}))',
            f'SET windowSky = {sky*e:.14f} * (ew - wbSkyW)',
            f'SET heff = h + {e*(6 if variant=="broadband" else 2.2):.14f}']
    statements+=['SET tref = ta']
    if surface.get('wind_exposure','WindExposed')=='WindExposed':
        statements+=['IF wbRain > 0',f'SET tref = {k}Wet','ENDIF']
    statements+=[f'SET {hc} = heff',f'SET {q} = targetQ - (heff * (tref - te)) - ({absorptance:.14f} * sun)']
    add(model,'EnergyManagementSystem:Program',k,lines(statements))
    for name,variable,unit in [('Cover Temperature','tp','C'),('Cover Balance','balance','W/m2'),
        ('Window Sky Loss','windowSky','W/m2'),('Boundary Forcing','targetQ','W/m2'),('Incident Solar','sun','W/m2'),
        ('Emitter Linearization Temperature','te','C')]:
        label=f'WB {name} {wall}'
        add(model,'EnergyManagementSystem:OutputVariable',label,dict(ems_variable_name=variable,
            type_of_data_in_variable='Averaged',update_frequency='ZoneTimestep',ems_program_or_subroutine_name=k,units=unit))
        request(model,'*',label)
    return k


def apply(model,spec,changed):
    shared(model)
    programs=['WB_SpectralWeather']
    for index,row in enumerate(changed):
        programs.append(configure(model,row['surface'],spec['definition']['spectral'],index))
    add(model,'EnergyManagementSystem:ProgramCallingManager','WB Exterior spectra',dict(
        energyplus_model_calling_point='BeginZoneTimestepAfterInitHeatBalance',programs=[dict(program_name=k) for k in programs]))
