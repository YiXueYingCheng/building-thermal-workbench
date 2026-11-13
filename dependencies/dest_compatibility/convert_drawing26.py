"""Drawing26 DeST snapshot conversion; intermediate source mapping before Kiva/control assembly.

Middle-plane, layer-order, azimuth and schedule decoding rules were checked
against hongyuanjia/destep (MIT). This is a separate Python implementation.
No R package was executed. Source databases are never modified.
"""
import base64
import argparse
import calendar
import collections
import copy
import hashlib
import html
import json
import math
import pathlib
import sqlite3
import struct
import subprocess
from energyplus_runtime import ENGINE, MODEL_VERSION

PROJECT=pathlib.Path(__file__).resolve().parents[1]
WORKSPACE=PROJECT.parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--tables',type=pathlib.Path,default=WORKSPACE/'outputs/01a0805a-fcec-7b73-9ee0-021b342ea2a4/drawing26-model-data/tables')
parser.add_argument('--reference-tables',type=pathlib.Path,default=WORKSPACE/'work/dest-model-only/tables/TEST.accdb',help='Previously checked standard door and material rows; exact comparison remains required.')
parser.add_argument('--destep-source',type=pathlib.Path,default=WORKSPACE/'work/third-party/destep-source.zip',help='Reviewed third-party source archive, read only for provenance hashing; not executed.')
parser.add_argument('--source',type=pathlib.Path,default=WORKSPACE/'outputs/01a0805a-fcec-7b73-9ee0-021b342ea2a4/drawing26-model-data/source')
parser.add_argument('--output',type=pathlib.Path,default=PROJECT/'projects/Drawing26/source-mapped')
parser.add_argument('--confirmed-door-thickness-mm',type=float,default=25.3,help='Explicit Drawing26 door thickness assumption, based on the identical previously UI-checked standard door library record; not inferred from wall thickness.')
parser.add_argument('--model-only',action='store_true',default=True,help='Generate the EnergyPlus model without reading DeST result or shadow-calculation tables.')
parser.add_argument('--source-original',type=pathlib.Path,default=WORKSPACE/'work/drawing26-extraction-20260917/source',help='Reference folder for source-copy hash verification; may be an immutable earlier snapshot.')
parser.add_argument('--project-id',default='Drawing26')
parser.add_argument('--ignore-shading',action='store_true',help='Explicitly omit source shading after user authorization; retain an audit record.')
parser.add_argument('--align-world-north',action='store_true',help='Rotate drawing coordinates into true-north world coordinates; preserve legacy defaults unless explicitly requested.')
args=parser.parse_args()
TABLES=args.tables.resolve()
OUT=args.output.resolve()
OUT.mkdir(parents=True,exist_ok=True)
D={p.stem:json.loads(p.read_text(encoding='utf-8-sig')) for p in TABLES.glob('*.json')}
R={} if args.model_only else {p.stem:json.loads(p.read_text(encoding='utf-8-sig')) for p in (TABLES/'TEST_Result.accdb').glob('*.json')}
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def keyed(table,key):return {r[key]:r for r in D[table]}
ROOM=keyed('ROOM','ID');SURF=keyed('SURFACE','SURFACE_ID');ENC=keyed('MAIN_ENCLOSURE','ID')
PLANE=keyed('PLANE','PLANE_ID');GEOM=keyed('GEOMETRY','GEOMETRY_ID');POINT=keyed('POINT','POINT_ID')
MATERIAL=keyed('SYS_MATERIAL','MATERIAL_ID');STOREY=keyed('STOREY','ID')
ENV=D['ENVIRONMENT'][0]
LOOPS=collections.defaultdict(list)
for r in D['LOOP_POINT']:LOOPS[r['LOOP_ID']].append(r)
def sub(a,b):return [x-y for x,y in zip(a,b)]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):return math.sqrt(dot(a,a))
def normal(v):
    return [sum(cross(a,b)[j] for a,b in zip(v,v[1:]+v[:1])) for j in range(3)]
def area(v):return norm(normal(v))/2
def polygon(plane_id):
    loop=GEOM[PLANE[plane_id]['GEOMETRY']]['BOUNDARY_LOOP_ID']
    v=[[round(POINT[r['POINT']][ax],7) for ax in ('X','Y','Z')] for r in sorted(LOOPS[loop],key=lambda x:x['POINT_NO'])]
    if norm(sub(v[0],v[-1]))<1e-8:v.pop()
    changed=True
    while changed and len(v)>3:
        changed=False
        for i in range(len(v)):
            a,b,c=v[i-1],v[i],v[(i+1)%len(v)]
            if norm(cross(sub(b,a),sub(c,a)))/norm(sub(c,a))<1e-6 and dot(sub(b,a),sub(b,c))<=0:
                v.pop(i);changed=True;break
    assert len(v)>=3 and area(v)>1e-6
    return v
def orient(v,s):
    a,t=s['AZIMUTH'],s['TILT']
    if a==999:expected=[0,0,-1]
    elif a==-999:expected=[0,0,1]
    else:
        angle=math.radians(ENV['SOUTH_DIRECTION']-180-a);tilt=math.radians(t)
        expected=[math.cos(angle)*math.sin(tilt),math.sin(angle)*math.sin(tilt),math.cos(tilt)]
    n=normal(v);alignment=dot(n,expected)/norm(n)
    assert abs(alignment)>.9999,('direction mismatch',s['SURFACE_ID'],alignment)
    v=v if alignment>0 else list(reversed(v))
    if abs(expected[2])<1e-6:
        right=[-expected[1],expected[0],0]
        top=max(p[2] for p in v)
        start=min((i for i,p in enumerate(v) if abs(p[2]-top)<1e-7),key=lambda i:dot(v[i],right))
        v=v[start:]+v[:start]
    return v
def epvertices(v):return [dict(zip(('vertex_x_coordinate','vertex_y_coordinate','vertex_z_coordinate'),p)) for p in v]

model={};surface_map=[];construction_map=[];window_map=[];door_map=[];schedule_map=[]
issues=[
 'Drawing26 only: source geometry and thermal properties retained; not a general DeST import guarantee.',
 'ROOM_RELATION is empty; no ventilation or infiltration is introduced.',
 'Source furniture coefficients are all 1; no added furniture capacity is introduced.',
 'Window.TYPE is resolved through WINDOW_TYPE_DATA as in the inspected destep mapper; SHGC=0.87*SC is approximate. The detailed construction reference is retained for review.',
 'Door thickness 25.3 mm is an explicit mapping assumption. Its SYS_DOOR record and wood properties match the previously UI-confirmed standard door. GAP_LENGTH is not treated as a generic thickness field for other door types.',
 'Door 2892 exceeds physical room-side wall boundaries by 71.56 mm; source middle-plane location is retained, with a separate boundary report.',
 'Visible absorptance, roughness and aggregate radiant distribution are approximations.',
 'The intermediate monthly ground and lighting objects are replaced by the final project assembler; use the final model files for computation.',
]
assert all(r['FURNITURE_COEF']==1 for r in ROOM.values()), 'Furniture mapping must be reviewed'
if args.project_id!='Drawing26':
    issues=[v for v in issues if not v.startswith('Drawing26 only:') and not v.startswith('Door 2892')]
    issues.insert(0,f'{args.project_id}: independently audited source geometry; not an arbitrary ACCDB compatibility guarantee.')
if args.ignore_shading:
    issues.append('User authorized omission of additional source shading. Building self-shading is retained; source tables are unchanged.')
else:
    assert not D['SHADING'], 'Explicit shading conversion is required'
    assert all(w['CURTAIN']==0 and w['SHADINGID']==0 for w in D['WINDOW']), 'Window shading controls must be mapped'
reference=args.reference_tables.resolve()
reference_doors=json.loads((reference/'SYS_DOOR.json').read_text(encoding='utf-8-sig'))
reference_materials=json.loads((reference/'SYS_MATERIAL.json').read_text(encoding='utf-8-sig'))
for door in D['DOOR']:
    record=next(r for r in D['SYS_DOOR'] if r['DOOR_ID']==door['DOOR_CONSTRUCTION'])
    old=next(r for r in reference_doors if r['DOOR_ID']==record['DOOR_ID'])
    assert record==old, 'Door differs from previously checked standard library record'
    material=MATERIAL[record['MATERIAL_ID']]
    assert material==next(r for r in reference_materials if r['MATERIAL_ID']==record['MATERIAL_ID'])
def add(kind,name,**fields):
    assert name not in model.setdefault(kind,{}),(kind,name)
    model[kind][name]=fields
add('Version','Version',version_identifier=MODEL_VERSION)
add('Building',args.project_id+' source geometry',north_axis=(ENV['SOUTH_DIRECTION']+90)%360,terrain='City',solar_distribution='FullExterior',maximum_number_of_warmup_days=100,minimum_number_of_warmup_days=25)
add('SimulationControl','Control',do_zone_sizing_calculation='No',do_system_sizing_calculation='No',do_plant_sizing_calculation='No',run_simulation_for_sizing_periods='No',run_simulation_for_weather_file_run_periods='Yes')
add('GlobalGeometryRules','Geometry',starting_vertex_position='UpperLeftCorner',vertex_entry_direction='Counterclockwise',coordinate_system='World')
add('Timestep','Timestep',number_of_timesteps_per_hour=6)
add('HeatBalanceAlgorithm','Heat balance',algorithm='ConductionTransferFunction')
add('SurfaceConvectionAlgorithm:Inside','Inside',algorithm='TARP')
add('SurfaceConvectionAlgorithm:Outside','Outside',algorithm='DOE-2')
add('Site:Location',ENV['CITY_NAME']+' DeST location',latitude=ENV['LATITUDE'],longitude=ENV['LONGITUDE'],time_zone=8,elevation=ENV['ELEVATION'])
add('RunPeriod','Annual '+args.project_id,begin_month=1,begin_day_of_month=1,end_month=12,end_day_of_month=31,day_of_week_for_start_day='Monday',use_weather_file_holidays_and_special_days='No',use_weather_file_daylight_saving_period='No',use_weather_file_rain_indicators='No',use_weather_file_snow_indicators='No')
add('ScheduleTypeLimits','Any Number')
ground=sorted(D['GROUND_DATA'],key=lambda x:x['HOUR']);start=0;temps={}
for m in range(1,13):
    n=calendar.monthrange(2025,m)[1]*24;chunk=ground[start:start+n];start+=n
    assert len(chunk)==n
    temps[calendar.month_name[m].lower()+'_ground_temperature']=sum(x['T'] for x in chunk)/n
add('Site:GroundTemperature:BuildingSurface','DeST monthly ground',**temps)
add('Site:GroundReflectance','DeST ground reflectance',**{calendar.month_name[m].lower()+'_ground_reflectance':ENV['GROUND_REFLECT_COEF'] for m in range(1,13)})
for rid,r in ROOM.items():
    assert STOREY[r['OF_STOREY']]['MULTIPLE']==1,'Storey multipliers need additional conversion'
    add('Zone',r['NAME'],ceiling_height=STOREY[r['OF_STOREY']]['HEIGHT'],floor_area=r['AREA'],volume=r['VOLUME'],multiplier=1)

kinds={1:'SYS_OUTWALL',2:'SYS_INWALL',3:'SYS_ROOF',4:'SYS_GROUNDFLOOR',5:'SYS_MIDDLEFLOOR',6:'SYS_AIRFLOOR'}
material_names={}
def make_construction(e,side,s,peer):
    table=kinds[e['KIND']]
    rows=sorted([x for x in D[table+'_MATERIAL'] if x['STRUCT_ID']==e['CONSTRUCTION']],key=lambda x:x['LAYER_NO'])
    assert rows
    if len(rows)==1 and any(s[k]!=peer[k] for k in ('ABSORB_COEF','BLACKNESS')):
        raise ValueError(f'E{e["ID"]}: 单层构造两面光学参数不同，当前无法无损转换；请先明确真实多层构造。')
    if side==1:rows.reverse()
    cname=f"Construction_E{e['ID']}_Side{side}";names=[]
    layers=[]
    for i,row in enumerate(rows):
        m=MATERIAL[row['MATERIAL_ID']];mn=f'{cname}_L{i+1}'
        optics=peer if i==0 else s
        props=dict(roughness='MediumSmooth',thickness=row['LENGTH']/1000,conductivity=m['CONDUCTIVITY'],density=m['DENSITY'],specific_heat=m['SPECIFIC_HEAT'],thermal_absorptance=optics['BLACKNESS'],solar_absorptance=optics['ABSORB_COEF'],visible_absorptance=optics['ABSORB_COEF'])
        assert all(props[x]>0 for x in ('thickness','conductivity','density','specific_heat'))
        signature=json.dumps(props,sort_keys=True)
        if signature in material_names:mn=material_names[signature]
        else:add('Material',mn,**props);material_names[signature]=mn
        names.append(mn)
        layers.append({'source_material_id':row['MATERIAL_ID'],'source_name':m['CNAME'],'source_layer':row['LAYER_NO'],**props})
    add('Construction',cname,**{('outside_layer' if i==0 else f'layer_{i+1}'):v for i,v in enumerate(names)})
    construction_map.append({'name':cname,'source_enclosure':e['ID'],'side':side,'layers_outside_to_inside':layers})
    return cname

for eid,e in ENC.items():
    v=polygon(e['MIDDLE_PLANE'])
    for side in (1,2):
        s=SURF[e[f'SIDE{side}']];peer=SURF[e[f'SIDE{3-side}']]
        if s['OF_ROOM'] not in ROOM:continue
        name=f"S_{s['SURFACE_ID']}";v_side=orient(v,s)
        boundary='Outdoors' if peer['TYPE']==1 else 'Ground' if peer['TYPE']==2 else 'Surface'
        assert boundary!='Surface' or peer['OF_ROOM'] in ROOM
        kind='Wall' if e['KIND'] in (1,2) else 'Roof' if e['KIND']==3 else 'Floor' if e['KIND'] in (4,6) or s['AZIMUTH']==999 else 'Ceiling'
        con=make_construction(e,side,s,peer)
        values=dict(surface_type=kind,construction_name=con,zone_name=ROOM[s['OF_ROOM']]['NAME'],outside_boundary_condition=boundary,sun_exposure='SunExposed' if boundary=='Outdoors' else 'NoSun',wind_exposure='WindExposed' if boundary=='Outdoors' else 'NoWind',number_of_vertices=len(v_side),vertices=epvertices(v_side))
        if boundary=='Surface':values['outside_boundary_condition_object']=f"S_{peer['SURFACE_ID']}"
        add('BuildingSurface:Detailed',name,**values)
        coeff=dict(surface_name=name,convection_coefficient_1_location='Inside',convection_coefficient_1_type='Value',convection_coefficient_1=s['VENTILATION_COEF'])
        if boundary=='Outdoors':coeff.update(convection_coefficient_2_location='Outside',convection_coefficient_2_type='Value',convection_coefficient_2=peer['VENTILATION_COEF'])
        add('SurfaceProperty:ConvectionCoefficients','Film_'+name,**coeff)
        source_area=s['AREA']
        surface_map.append({'source_id':s['SURFACE_ID'],'enclosure_id':eid,'zone':ROOM[s['OF_ROOM']]['NAME'],'type':kind,'boundary':boundary,'peer_source_id':peer['SURFACE_ID'],'source_reported_area_m2':source_area,'middle_plane_gross_area_m2':area(v_side),'vertices':v_side,'name':name})

window_types=keyed('WINDOW_TYPE_DATA','ID');door_types=keyed('SYS_DOOR','DOOR_ID')
for table,kind in [('WINDOW','Window'),('DOOR','Door')]:
    for obj in D[table]:
        eid=obj['OF_ENCLOSURE'];e=ENC[eid];v=polygon(obj['MIDDLE_PLANE'])
        con=f"{kind}_Construction_{obj['ID']}"
        if table=='WINDOW':
            t=window_types[obj['TYPE']];shgc=.87*t['SC']
            assert t['K']>0 and 0<shgc<=1
            add('WindowMaterial:SimpleGlazingSystem',con,u_factor=t['K'],solar_heat_gain_coefficient=shgc,visible_transmittance=t['LIGHT_TRANS_RATIO'])
            add('Construction',con,outside_layer=con)
            window_map.append({'id':obj['ID'],'type_id':obj['TYPE'],'type_name':t['NAME'],'u_factor':t['K'],'SC':t['SC'],'SHGC_approximation':shgc,'visible_transmittance':t['LIGHT_TRANS_RATIO'],'detailed_construction_id':obj['WINDOW_CONSTRUCTION'],'area_m2':area(v)})
        else:
            t=door_types[obj['DOOR_CONSTRUCTION']]
            assert t['CONDUCT_CO']>0 and t['GLASS_RAT']==0 and t['APP_ID']==0
            if args.confirmed_door_thickness_mm is None:
                add('Material:NoMass',con,roughness='MediumSmooth',thermal_resistance=t['CONDUCT_CO'],thermal_absorptance=.85,solar_absorptance=.55,visible_absorptance=.55)
            else:
                assert args.confirmed_door_thickness_mm==25.3 and t['GAP_LENGTH']==25.3 and t['MATERIAL_ID']==62,'Explicit thickness mapping is limited to the identical standard wood-door record'
                wood=MATERIAL[t['MATERIAL_ID']]
                add('Material',con,roughness='MediumSmooth',thickness=args.confirmed_door_thickness_mm/1000,conductivity=wood['CONDUCTIVITY'],density=wood['DENSITY'],specific_heat=wood['SPECIFIC_HEAT'],thermal_absorptance=.85,solar_absorptance=.55,visible_absorptance=.55)
            add('Construction',con,outside_layer=con)
            door_map.append({'id':obj['ID'],'type_name':t['CNAME'],'thermal_resistance_used':t['CONDUCT_CO'] if args.confirmed_door_thickness_mm is None else args.confirmed_door_thickness_mm/1000/wood['CONDUCTIVITY'],'area_m2':area(v),'thermal_mass':'not converted' if args.confirmed_door_thickness_mm is None else 'confirmed wood thickness, density and heat capacity','source_CONDUCT_CO':t['CONDUCT_CO'],'confirmed_thickness_mm':args.confirmed_door_thickness_mm})
        for side in (1,2):
            s=SURF[obj[f'SIDE{side}']];peer=SURF[obj[f'SIDE{3-side}']]
            if s['OF_ROOM'] not in ROOM:continue
            host=next(SURF[e[f'SIDE{x}']] for x in (1,2) if SURF[e[f'SIDE{x}']]['OF_ROOM']==s['OF_ROOM'])
            v_side=orient(v,s)
            hp=polygon(e['MIDDLE_PLANE']);hn=normal(hp);hn=[x/norm(hn) for x in hn]
            assert max(abs(dot(sub(p,hp[0]),hn)) for p in v_side)<1e-5,('subsurface off host',obj['ID'])
            # Remove sub-micrometre rounding offsets from the shared host plane.
            v_side=[[p[i]-dot(sub(p,hp[0]),hn)*hn[i] for i in range(3)] for p in v_side]
            values=dict(surface_type=kind,construction_name=con,building_surface_name=f"S_{host['SURFACE_ID']}",number_of_vertices=len(v_side))
            if peer['OF_ROOM'] in ROOM:values['outside_boundary_condition_object']=f"{kind}_{peer['SURFACE_ID']}"
            values.update({f'vertex_{i}_{ax}_coordinate':val for i,p in enumerate(v_side,1) for ax,val in zip('xyz',p)})
            add('FenestrationSurface:Detailed',f"{kind}_{s['SURFACE_ID']}",**values)

schedules={}
for r in D['SCHEDULE_YEAR']:
    raw=base64.b64decode(r['DATA']['base64']);assert len(raw)==8760*8
    vals=struct.unpack('<8760d',raw);assert all(math.isfinite(v) for v in vals)
    schedules[r['SCHEDULE_ID']]=vals
    schedule_map.append({'id':r['SCHEDULE_ID'],'name':r['NAME'],'hours':len(vals),'min':min(vals),'max':max(vals),'binary_sha256':hashlib.sha256(raw).hexdigest()})
def schedule(name,values):
    filename=name+'.txt';(OUT/filename).write_text('\n'.join(format(x,'.15g') for x in values)+'\n',encoding='ascii')
    add('Schedule:File',name,schedule_type_limits_name='Any Number',file_name=str(OUT/filename),column_number=1,rows_to_skip_at_top=0,number_of_hours_of_data=8760,column_separator='Comma',interpolate_to_timestep='No',minutes_per_item=60,adjust_schedule_for_daylight_savings='No')
    return name
dist=keyed('DIST_MODE','DIST_MODE_ID')
gain_map=[]
for table in ('OCCUPANT_GAINS','LIGHT_GAINS','EQUIPMENT_GAINS'):
    for g in D[table]:
        rid=g['OF_ROOM'];r=ROOM[rid];fraction=1-dist[g['DIST_MODE']]['DIST_AIR'];factor=r['AREA'] if g['PER_AREA'] else 1
        minimum=g['MINNUMBER'] if table=='OCCUPANT_GAINS' else g['MINPOWER']
        maximum=g['MAXNUMBER'] if table=='OCCUPANT_GAINS' else g['MAXPOWER']
        vals=[factor*(minimum+x*(maximum-minimum)) for x in schedules[g['SCHEDULE']]]
        name=f"{table}_{g['GAIN_ID']}";sch=schedule(name,vals)
        if table=='OCCUPANT_GAINS':
            activity=g['HEAT_PER_PERSON']+g['DAMP_PER_PERSON']*2500/3.6
            add('Schedule:Constant',name+'_activity',schedule_type_limits_name='Any Number',hourly_value=activity)
            add('People',name,zone_or_zonelist_or_space_or_spacelist_name=r['NAME'],number_of_people_schedule_name=sch,number_of_people_calculation_method='People',number_of_people=1,fraction_radiant=fraction,sensible_heat_fraction=g['HEAT_PER_PERSON']/activity,activity_level_schedule_name=name+'_activity')
        elif table=='LIGHT_GAINS':
            add('Lights',name,zone_or_zonelist_or_space_or_spacelist_name=r['NAME'],schedule_name=sch,design_level_calculation_method='LightingLevel',lighting_level=1,fraction_radiant=fraction,fraction_visible=0,return_air_fraction=0,fraction_replaceable=g['HEAT_RATE'])
        else:
            assert g['MAX_HUM']==g['MIN_HUM']==0
            add('ElectricEquipment',name,zone_or_zonelist_or_space_or_spacelist_name=r['NAME'],schedule_name=sch,design_level_calculation_method='EquipmentLevel',design_level=1,fraction_latent=0,fraction_radiant=fraction,fraction_lost=0)
        gain_map.append({'table':table,'id':g['GAIN_ID'],'zone':r['NAME'],'source_schedule_id':g['SCHEDULE'],'min_hourly_design_value':min(vals),'max_hourly_design_value':max(vals),'radiant_fraction':fraction})

assert not D['ROOM_RELATION'],'Ventilation mapping has not been enabled in this fixture converter'
add('Output:SQLite','SQLite',option_type='SimpleAndTabular')
add('Output:Table:SummaryReports','Summary',reports=[{'report_name':'AllSummary'}])
for i,v in enumerate(['Zone Mean Air Temperature','Zone People Sensible Heating Energy','Zone Lights Total Heating Energy','Zone Electric Equipment Total Heating Energy','Site Outdoor Air Drybulb Temperature']):
    add('Output:Variable',f'Output_{i}',key_value='*',variable_name=v,reporting_frequency='Hourly')
add('Output:Surfaces:List','Details',report_type='DetailsWithVertices')
add('Output:Diagnostics','Diagnostics',diagnostics=[{'key':'DisplayExtraWarnings'}])

summary_rooms=[]
for rid,r in ROOM.items():
    sur=[s for s in surface_map if s['zone']==r['NAME']]
    area_vector=[sum(normal(s['vertices'])[i]/2 for s in sur) for i in range(3)]
    volume=sum(dot(s['vertices'][0],normal(s['vertices']))/6 for s in sur)
    floor=sum(s['middle_plane_gross_area_m2'] for s in sur if s['type']=='Floor')
    assert norm(area_vector)<1e-4,(r['NAME'],'nonclosed',area_vector)
    assert math.isclose(volume,r['VOLUME'],abs_tol=1e-4),(r['NAME'],'volume mismatch',volume,r['VOLUME'])
    assert math.isclose(floor,r['AREA'],abs_tol=1e-4),(r['NAME'],'area mismatch',floor,r['AREA'])
    summary_rooms.append({'room_id':rid,'room_group_id':r['OF_ROOM_GROUP'],'name':r['NAME'],'storey':STOREY[r['OF_STOREY']]['NO']+1,'source_area_m2':r['AREA'],'converted_floor_area_m2':floor,'source_volume_m3':r['VOLUME'],'enclosed_volume_m3':volume,'surface_count':len(sur),'area_vector_residual_m2':norm(area_vector)})
for s in surface_map:
    if s['boundary']=='Surface':
        peer=next(p for p in surface_map if p['source_id']==s['peer_source_id'])
        assert peer['peer_source_id']==s['source_id'] and sorted(s['vertices'])==sorted(peer['vertices'])
        assert dot(normal(s['vertices']),normal(peer['vertices']))<0

source=args.source.resolve()
original=args.source_original.resolve()
hashes=[]
for f in source.iterdir():
    if not f.is_file() or f.suffix not in ('.accdb','.dwg','.bak','.xlsm'):continue
    if args.model_only and args.project_id=='Drawing26' and f.name not in ('Drawing26 - 副本.accdb','Drawing26.dwg'):continue
    sha=hashlib.sha256(f.read_bytes()).hexdigest();original_sha=hashlib.sha256((original/f.name).read_bytes()).hexdigest()
    assert sha==original_sha,f.name
    hashes.append({'file':f.name,'bytes':f.stat().st_size,'sha256':sha,'original_matches':True})
save('source-manifest.json',{'source_folder':str(original),'snapshot_folder':str(source),'model_only':args.model_only,'dest_result_tables_used':not args.model_only,'dest_version_user':'not independently confirmed for this historical project','database_version':D['VERSION_CONTROL'],'cad_version_user':'not independently confirmed for this historical project','source_files':hashes,'converter_basis':'Separate constrained Python implementation; reviewed destep source; R package not run','destep_source_sha256':hashlib.sha256(args.destep_source.read_bytes()).hexdigest()})
if args.align_world_north:
    rotation=(ENV['SOUTH_DIRECTION']+90)%360
    cosine=round(math.cos(math.radians(rotation)),15);sine=round(math.sin(math.radians(rotation)),15)
    def world_point(v):
        x,y,z=v
        return [round(x*cosine+y*sine,10),round(-x*sine+y*cosine,10),z]
    for section in ('BuildingSurface:Detailed','FenestrationSurface:Detailed'):
        for item in model.get(section,{}).values():
            if 'vertices' in item:
                item['vertices']=epvertices([world_point([v['vertex_'+a+'_coordinate'] for a in 'xyz']) for v in item['vertices']])
            else:
                for i in range(1,int(item['number_of_vertices'])+1):
                    for a,value in zip('xyz',world_point([item[f'vertex_{i}_{a}_coordinate'] for a in 'xyz'])):
                        item[f'vertex_{i}_{a}_coordinate']=value
    angular_errors=[]
    for item in surface_map:
        item['vertices']=[world_point(v) for v in item['vertices']]
        if item['type']=='Wall':
            n=normal(item['vertices']); azimuth=math.degrees(math.atan2(n[0],n[1]))%360
            expected=SURF[item['source_id']]['AZIMUTH']
            angular_errors.append(abs((azimuth-expected+180)%360-180))
    assert max(angular_errors,default=0)<1e-7
    next(iter(model['Building'].values()))['north_axis']=0
    issues.append(f'Drawing coordinates explicitly rotated clockwise {rotation:g} degrees into true-north World coordinates; Building north_axis is zero to avoid ignored or double rotation.')
    save('orientation-verification.json',{'passed':True,'rotation_clockwise_deg':rotation,'vertical_surfaces_checked':len(angular_errors),'maximum_source_azimuth_error_deg':max(angular_errors,default=0),'coordinate_system':'World','building_north_axis':0})
save('model.epJSON',model)
if args.ignore_shading:
    save('shading-omission.json',{'authorized':True,'source_shading_records':D['SHADING'],
        'affected_windows':[{'id':w['ID'],'shading_id':w['SHADINGID'],'curtain':w['CURTAIN']} for w in D['WINDOW'] if w['CURTAIN'] or w['SHADINGID']],
        'additional_shading_objects_emitted':0,'building_self_shading_retained':True,'source_modified':False})
save('conversion-audit.json',{'rooms':summary_rooms,'storeys':D['STOREY'],'surfaces':surface_map,'constructions':construction_map,'windows':window_map,'doors':door_map,'schedules':schedule_map,'internal_gains':gain_map,'issues':issues,'object_counts':{k:len(v) for k,v in model.items()},'source_enclosure_count':len(ENC),'source_subsurface_counts':{'windows':len(D['WINDOW']),'doors':len(D['DOOR'])}})
if not args.model_only:
    save('dest-natural-temperature.json',{'source':'TEST_Result.accdb / RESULT_ROOM_GROUP','hour_index':'0 through 743; January; exact within-hour timestamp convention not yet independently confirmed','records':R['RESULT_ROOM_GROUP'],'log':R['LOG'],'result_state':R['RESULT_STATE']})
print(json.dumps({'rooms':summary_rooms,'object_counts':{k:len(v) for k,v in model.items()}},ensure_ascii=False))

