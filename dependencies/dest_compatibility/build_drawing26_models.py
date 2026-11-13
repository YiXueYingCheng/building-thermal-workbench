"""Assemble portable Drawing26 natural and sensible-demand EnergyPlus models.

Source data are read-only. TEST entrypoints and workbooks are not modified.
"""
import base64
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
from run_annual import overlap_length
from energyplus_runtime import use_current_version

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
SOURCE = WORKSPACE/'outputs/01a0805a-fcec-7b73-9ee0-021b342ea2a4/drawing26-model-data'
OUT = PROJECT/'projects/Drawing26'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,data): Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verts(s): return [[p[f'vertex_{a}_coordinate'] for a in 'xyz'] for p in s['vertices']]
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def sub(a,b): return [x-y for x,y in zip(a,b)]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def normal(p): return [sum(cross(a,b)[i] for a,b in zip(p,p[1:]+p[:1])) for i in range(3)]
def area(p): return math.sqrt(sum(x*x for x in normal(p)))/2

def main(source=SOURCE,out=OUT,project_id='Drawing26',city='株洲',weather_path=None,weather_source_url=None):
    SOURCE,OUT=Path(source),Path(out)
    d={p.stem:read(p) for p in (SOURCE/'tables').glob('*.json')}
    model=use_current_version(read(OUT/'source-mapped/model.epJSON'))
    conversion=read(OUT/'source-mapped/conversion-audit.json')
    if weather_path is not None:
        with Path(weather_path).open(encoding='utf-8-sig',newline='') as f:location=next(csv.reader(f))
        assert location[0]=='LOCATION'
        model['Site:Location']={city+' EPW location':dict(latitude=float(location[6]),longitude=float(location[7]),time_zone=float(location[8]),elevation=float(location[9]))}
    def add(kind,name,**values):
        assert name not in model.setdefault(kind,{}),(kind,name)
        model[kind][name]=values
    def output(name,frequency='Hourly'):
        add('Output:Variable',f'Out_{len(model.get("Output:Variable",{}))}',key_value='*',variable_name=name,reporting_frequency=frequency)
    schedule_folder=OUT/'schedules';schedule_folder.mkdir(exist_ok=True)
    for s in model['Schedule:File'].values():
        original=Path(s['file_name']);target=schedule_folder/original.name
        shutil.copy2(original,target)
        s['file_name']='schedules/'+target.name
    schedules={r['SCHEDULE_ID']:struct.unpack('<8760d',base64.b64decode(r['DATA']['base64'])) for r in d['SCHEDULE_YEAR']}
    def schedule(sid):
        name='DeST_Schedule_'+str(sid)
        if name not in model['Schedule:File']:
            values=schedules[sid]
            (schedule_folder/(name+'.txt')).write_text('\n'.join(format(v,'.17g') for v in values)+'\n',encoding='ascii')
            add('Schedule:File',name,schedule_type_limits_name='Any Number',file_name='schedules/'+name+'.txt',
                column_number=1,rows_to_skip_at_top=0,number_of_hours_of_data=8760,column_separator='Comma',
                interpolate_to_timestep='No',minutes_per_item=60,adjust_schedule_for_daylight_savings='No')
        return name
    model['Timestep']={'Timestep':{'number_of_timesteps_per_hour':12}}
    add('ZoneAirHeatBalanceAlgorithm','Analytical zone balance',algorithm='AnalyticalSolution')
    model['Output:Variable']={}
    for name in ['Zone Mean Air Temperature','Site Outdoor Air Drybulb Temperature','Zone People Sensible Heating Energy',
                 'Zone Electric Equipment Total Heating Energy','Zone People Occupant Count','Schedule Value']:
        output(name)
    output('Zone Mean Air Temperature','Timestep')
    add('Output:Constructions','Applied materials',details_type_1='Constructions',details_type_2='Materials')
    add('Output:Surfaces:Drawing','DXF drawing',report_type='DXF',report_specifications_1='Triangulate3DFace')
    # Preserve electrical input schedules while respecting source heat/electric ratio.
    dist={r['DIST_MODE_ID']:r for r in d['DIST_MODE']}
    lighting=[]
    for g in d['LIGHT_GAINS']:
        name=f'LIGHT_GAINS_{g["GAIN_ID"]}'
        old=model['Lights'].pop(name)
        ratio=g['HEAT_RATE'];rad=ratio*(1-dist[g['DIST_MODE']]['DIST_AIR'])
        assert 0<=rad<=ratio<=1
        add('ElectricEquipment',name,zone_or_zonelist_or_space_or_spacelist_name=old['zone_or_zonelist_or_space_or_spacelist_name'],
            schedule_name=old['schedule_name'],design_level_calculation_method='EquipmentLevel',design_level=1,
            fraction_latent=0,fraction_radiant=rad,fraction_lost=1-ratio,end_use_subcategory='DeST Lighting Equivalent')
        lighting.append({'name':name,'heat_electric_ratio':ratio,'radiant_fraction':rad,'convective_fraction':ratio-rad,'lost_fraction':1-ratio})
    assert not model.pop('Lights')
    model.pop('Site:GroundTemperature:BuildingSurface')
    soil={'soil_conductivity':1.73,'soil_density':1842,'soil_specific_heat':419}
    add('Foundation:Kiva:Settings','Soil assumptions',**soil,ground_solar_absorptivity=.9,ground_thermal_absorptivity=.9,
        ground_surface_roughness=.03,far_field_width=40,deep_ground_boundary_condition='Autoselect',deep_ground_depth='Autocalculate',
        minimum_cell_dimension=.02,maximum_cell_growth_coefficient=1.5,simulation_timestep='Timestep')
    surfaces=model['BuildingSurface:Detailed']
    outside=[s for s in surfaces.values() if s['surface_type']=='Wall' and s['outside_boundary_condition']=='Outdoors']
    exterior_edges=[]
    for s in outside:
        v=verts(s)
        exterior_edges += [(a,b) for a,b in zip(v,v[1:]+v[:1]) if abs(a[2]-b[2])<1e-8]
    ground=[]
    for name,s in surfaces.items():
        if s['outside_boundary_condition']!='Ground': continue
        assert s['surface_type']=='Floor'
        v=verts(s);lengths=[math.dist(a,b) for a,b in zip(v,v[1:]+v[:1])]
        exposed=[sum(overlap_length(a,b,c,e) for c,e in exterior_edges) for a,b in zip(v,v[1:]+v[:1])]
        assert all(-1e-8<=p<=l+1e-7 for p,l in zip(exposed,lengths))
        adjacent=next((x for x in outside if x['zone_name']==s['zone_name']),outside[0])
        foundation='Foundation_'+name
        add('Foundation:Kiva',foundation,initial_indoor_air_temperature=20,wall_height_above_grade=0,
            wall_depth_below_slab=0,footing_wall_construction_name=adjacent['construction_name'])
        # Scalar exposed length supports the internal room and partly exposed edges.
        add('SurfaceProperty:ExposedFoundationPerimeter','Perimeter_'+name,surface_name=name,
            exposed_perimeter_calculation_method='TotalExposedPerimeter',total_exposed_perimeter=sum(exposed))
        s['outside_boundary_condition']='Foundation';s['outside_boundary_condition_object']=foundation
        model['SurfaceProperty:ConvectionCoefficients'].pop('Film_'+name,None)
        ground.append({'surface':name,'zone':s['zone_name'],'exposed_perimeter_m':sum(exposed),
                       'total_perimeter_m':sum(lengths),'exposed_length_each_edge_m':exposed,
                       'footing_wall_construction':adjacent['construction_name'],'method':'TotalExposedPerimeter'})
    # Both middle-plane containment and the separate physical-wall check are retained.
    opening_checks=[]
    for name,o in model['FenestrationSurface:Detailed'].items():
        wall=verts(surfaces[o['building_surface_name']]);n=normal(wall);n=[v/math.sqrt(dot(n,n)) for v in n]
        p=[[o[f'vertex_{i}_{a}_coordinate'] for a in 'xyz'] for i in range(1,o['number_of_vertices']+1)]
        edge_dist=[]
        for a,b in zip(wall,wall[1:]+wall[:1]):
            iv=cross(n,sub(b,a));iv=[v/math.sqrt(dot(iv,iv)) for v in iv]
            assert min(dot(sub(w,a),iv) for w in wall)>-1e-7
            edge_dist += [dot(sub(w,a),iv) for w in p]
        distance=max(abs(dot(sub(w,wall[0]),n)) for w in p)
        assert min(edge_dist)>-1e-6 and distance<1e-6,(name,min(edge_dist),distance)
        opening_checks.append({'name':name,'minimum_edge_clearance_m':min(edge_dist),'plane_distance_m':distance,'area_m2':area(p)})
    # Independent shared-wall reciprocity, reversed winding and layer checks.
    pair_count=0
    for name,s in surfaces.items():
        if s['outside_boundary_condition']!='Surface': continue
        peer=surfaces[s['outside_boundary_condition_object']]
        assert peer['outside_boundary_condition_object']==name
        assert {tuple(v) for v in verts(s)}=={tuple(v) for v in verts(peer)}
        assert dot(normal(verts(s)),normal(verts(peer)))<0
        assert list(model['Construction'][s['construction_name']].values())==list(model['Construction'][peer['construction_name']].values())[::-1]
        pair_count+=1
    natural=copy.deepcopy(model)
    rooms={r['ID']:r for r in d['ROOM']};groups={r['ROOM_GROUP_ID']:r for r in d['ROOM_GROUP']}
    room_audit=[];globals_=[];initial=[];programs=[]
    for rid,room in rooms.items():
        group=groups[room['OF_ROOM_GROUP']]
        ids={k:group[f] for k,f in [('available','AC_SCHEDULE_ID'),('low','AC_T_MIN_SCHEDULE'),('heat','SET_T_MIN_SCHEDULE'),('cool','SET_T_MAX_SCHEDULE'),('high','AC_T_MAX_SCHEDULE')]}
        values={k:schedules[sid] for k,sid in ids.items()}
        assert all(lo<=h<c<=hi for lo,h,c,hi in zip(values['low'],values['heat'],values['cool'],values['high']))
        conditioned=bool(group['IS_AC_ROOM']);zone=room['NAME']
        room_audit.append({'name':zone,'room_id':rid,'conditioned':conditioned,'area_m2':room['AREA'],'schedules':ids,
                           'temperature_ranges_C':{k:[min(values[k]),max(values[k])] for k in ['low','heat','cool','high']},
                           'availability_range':[min(values['available']),max(values['available'])]})
        if not conditioned: continue
        prefix='R'+str(rid);state=prefix+'_state';ref=prefix+'_ref';prev=prefix+'_previous'
        globals_ += [state,ref,prev];initial += [f'SET {state} = 0',f'SET {ref} = 20',f'SET {prev} = 0']
        add('EnergyManagementSystem:Sensor',prefix+'_T',output_variable_or_output_meter_index_key_name=zone,output_variable_or_output_meter_name='Zone Mean Air Temperature')
        for k,sid in ids.items():
            add('EnergyManagementSystem:Sensor',prefix+'_'+k,output_variable_or_output_meter_index_key_name=schedule(sid),output_variable_or_output_meter_name='Schedule Value')
        ctrl=prefix+'_control';enable=prefix+'_enable'
        for name in [ctrl,enable]:
            # Nonzero seed is required by the thermostat input checker; EMS
            # overwrites both schedules before each heat-balance prediction.
            add('Schedule:Constant',name,schedule_type_limits_name='Any Number',hourly_value=1)
            add('EnergyManagementSystem:Actuator',name+'_act',actuated_component_unique_name=name,actuated_component_type='Schedule:Constant',actuated_component_control_type='Schedule Value')
        t=prefix+'_T';lo=prefix+'_low';heat=prefix+'_heat';cool=prefix+'_cool';hi=prefix+'_high';av=prefix+'_available'
        lines=[f'SET {ref} = {t}',f'SET {prev} = {state}',f'IF {av} <= 0',f' SET {state} = 0',
               f'ELSEIF ({state} == 1) && ({t} < ({heat} - 0.01))',f' SET {state} = 1',
               f'ELSEIF ({state} == 2) && ({t} > ({cool} + 0.01))',f' SET {state} = 2',
               f'ELSEIF {t} < {lo}',f' SET {state} = 1',f'ELSEIF {t} > {hi}',f' SET {state} = 2',
               'ELSE',f' SET {state} = 0','ENDIF',f'SET {ctrl}_act = {state}',f'SET {enable}_act = 0',
               f'IF {state} > 0',f' SET {enable}_act = 1','ENDIF']
        pname=prefix+'_controller';add('EnergyManagementSystem:Program',pname,lines=[{'program_line':l} for l in lines]);programs.append({'program_name':pname})
        for label,var in [('Mode',state),('Reference Temperature',ref),('Previous Mode',prev)]:
            outname=zone+' Control '+label
            add('EnergyManagementSystem:OutputVariable',outname,ems_variable_name=var,type_of_data_in_variable='Averaged',update_frequency='ZoneTimestep');output(outname,'Timestep')
        add('ThermostatSetpoint:SingleHeating',prefix+'_heating',setpoint_temperature_schedule_name=schedule(ids['heat']))
        add('ThermostatSetpoint:SingleCooling',prefix+'_cooling',setpoint_temperature_schedule_name=schedule(ids['cool']))
        add('ZoneControl:Thermostat',prefix+'_thermostat',zone_or_zonelist_name=zone,control_type_schedule_name=ctrl,
            control_1_object_type='ThermostatSetpoint:SingleHeating',control_1_name=prefix+'_heating',
            control_2_object_type='ThermostatSetpoint:SingleCooling',control_2_name=prefix+'_cooling')
        system=prefix+'_ideal'
        add('ZoneHVAC:IdealLoadsAirSystem',system,availability_schedule_name=enable,zone_supply_air_node_name=prefix+'_supply',
            maximum_heating_supply_air_temperature=50,minimum_cooling_supply_air_temperature=13,heating_limit='NoLimit',cooling_limit='NoLimit',
            dehumidification_control_type='None',humidification_control_type='None',outdoor_air_economizer_type='NoEconomizer',heat_recovery_type='None')
        add('ZoneHVAC:EquipmentList',prefix+'_equipment',load_distribution_scheme='SequentialLoad',equipment=[{'zone_equipment_object_type':'ZoneHVAC:IdealLoadsAirSystem','zone_equipment_name':system,'zone_equipment_cooling_sequence':1,'zone_equipment_heating_or_no_load_sequence':1}])
        add('ZoneHVAC:EquipmentConnections',prefix+'_connections',zone_name=zone,zone_conditioning_equipment_list_name=prefix+'_equipment',
            zone_air_inlet_node_or_nodelist_name=prefix+'_supply',zone_air_node_name=prefix+'_air',zone_return_air_node_or_nodelist_name=prefix+'_return')
    add('EnergyManagementSystem:GlobalVariable','Controller memory',variables=[{'erl_variable_name':v} for v in globals_])
    add('EnergyManagementSystem:Program','InitializeControllers',lines=[{'program_line':l} for l in initial])
    add('EnergyManagementSystem:ProgramCallingManager','Initialize',energyplus_model_calling_point='BeginNewEnvironment',programs=[{'program_name':'InitializeControllers'}])
    add('EnergyManagementSystem:ProgramCallingManager','Control',energyplus_model_calling_point='BeginTimestepBeforePredictor',programs=programs)
    for variable in ['Zone Ideal Loads Zone Sensible Heating Energy','Zone Ideal Loads Zone Sensible Cooling Energy']:
        output(variable);output(variable,'Timestep')
    save(OUT/'model-natural.epJSON',natural);save(OUT/'model-controlled.epJSON',model)
    weather=Path(weather_path) if weather_path is not None else OUT/'weather/CHN_Hunan.Zhuzhou.577800_CSWD.epw'
    with weather.open(encoding='utf-8-sig',newline='') as f: weather_rows=list(csv.reader(f))
    assert len(weather_rows[8:])==8760
    if weather_path is None:assert weather_rows[0][1]=='Zhuzhou' and weather_rows[0][5]=='577800'
    weather_data=sorted(d['CLIMATE_DATA'],key=lambda r:r['HOUR'])
    dry_differences=[float(w[6])-r['DRY_BULB_T'] for w,r in zip(weather_rows[8:],weather_data)]
    audit={'project':project_id,'source':str(SOURCE),'city':city,'source_room_area_m2':sum(r['AREA'] for r in rooms.values()),
           'converted_rooms':conversion['rooms'],'rooms':room_audit,'middle_plane_openings':opening_checks,'interzone_wall_pairs':pair_count//2,
           'geometry_vertices_modified':False,'source_physical_opening_check':read(OUT/'conversion/physical-opening-check.json'),
           'lighting':lighting,'ground':ground,'soil_assumptions':soil,'soil_measured':False,
           'weather':{'file':str(weather.relative_to(OUT)).replace('\\','/'),'sha256':sha(weather),'header':weather_rows[0],
                      'source_url':weather_source_url or 'https://energyplus-weather.s3.amazonaws.com/asia_wmo_region_2/CHN/CHN_Hunan.Zhuzhou.577800_CSWD/CHN_Hunan.Zhuzhou.577800_CSWD.zip',
                      'hours':8760,'source_drybulb_mean_abs_difference_C':sum(abs(x) for x in dry_differences)/8760,
                      'source_drybulb_max_abs_difference_C':max(abs(x) for x in dry_differences)},
           'assumptions':[v for v in conversion['issues'] if not v.startswith('The intermediate monthly ground')]+[
             f'Final model uses Kiva for the {len(ground)} source ground floors, with default soil properties and slab-at-grade zero below-slab wall depth.',
             'Kiva uses total exposed perimeter from outside-wall intersections; this does not use its per-edge concave-corner adjustment.',
             'Lighting heat/electric ratio is modeled through an equivalent ElectricEquipment heat source.',
             'Source room HVAC inclusion and 8760-hour availability/temperature schedules are retained; source AHU/network/device equipment is replaced by ideal sensible loads, not an actual equipment energy model.',
             'Natural model has all HVAC removed; controlled model implements hysteresis from previous completed five-minute timestep temperature.',
             'Source raw solar/weather and air-moisture definitions are not claimed to be numerically identical to EnergyPlus.'],
           'source_table_hashes':{p.name:sha(p) for p in sorted((SOURCE/'tables').glob('*.json'))}}
    save(OUT/'conversion/model-audit.json',audit)
    save(OUT/'project.json',{'project':project_id,'city':city,'weather':audit['weather']['file'],'models':{'natural':'model-natural.epJSON','controlled':'model-controlled.epJSON'},
        'conversion_audit':'conversion/model-audit.json','conditioned_rooms':[r['name'] for r in room_audit if r['conditioned']],
        'calendar':'365-day typical year, January 1 Monday, no holidays or daylight savings',
        'demand_units':'kWh of sensible thermal demand, not equipment electricity','timesteps_per_hour':12})
    for filename in ['房间平面核对.png','房间平面核对.svg']:
        if (SOURCE/filename).is_file():shutil.copy2(SOURCE/filename,OUT/filename)
    print(json.dumps({'rooms':len(rooms),'air_conditioned_rooms':sum(r['conditioned'] for r in room_audit),'surfaces':len(surfaces),
                      'opening_surfaces':len(opening_checks),'ground_floors':len(ground),'zero_exposed_perimeter_rooms':[r['zone'] for r in ground if r['exposed_perimeter_m']==0],
                      'weather':audit['weather'],'outputs':[str(OUT/'model-natural.epJSON'),str(OUT/'model-controlled.epJSON')]},ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=SOURCE);parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--project-id',default='Drawing26');parser.add_argument('--city',default='株洲')
    parser.add_argument('--weather',type=Path);parser.add_argument('--weather-source-url')
    args=parser.parse_args()
    main(args.source,args.output,args.project_id,args.city,args.weather,args.weather_source_url)
