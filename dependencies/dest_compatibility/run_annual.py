"""Annual sensible thermal demand and free-floating temperatures for the TEST fixture.

Reads the validated model-only snapshot, never changes the DeST databases.
The EMS controller retains heating/cooling state until the target is reached.
Unconditioned zones retain their geometry, gains and interzone heat transfer.
"""
import argparse
import base64
import calendar
import concurrent.futures
import copy
import csv
import datetime
import hashlib
import json
import math
import pathlib
import re
import shutil
import sqlite3
import struct
import subprocess
from energyplus_runtime import ENGINE, use_current_version, engine_record

PROJECT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
BASE = PROJECT / 'results/dest-model-only/TEST_20260910'
TABLES = WORKSPACE / 'work/dest-model-only/tables/TEST.accdb'
WEATHER = PROJECT / 'weather/china34/CHN_Beijing.Beijing.545110_CSWD.epw'


def read(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))


def save(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def next_mode(previous, temperature, available, low, heat, cool, high, epsilon=0.001):
    """Reference state machine: 0 off, 1 heat, 2 cool. Trigger limits are strict."""
    if not available:
        return 0
    if previous == 1 and temperature < heat - epsilon:
        return 1
    if previous == 2 and temperature > cool + epsilon:
        return 2
    if temperature < low:
        return 1
    if temperature > high:
        return 2
    return 0


def vertices(surface):
    return [tuple(v[f'vertex_{a}_coordinate'] for a in 'xyz') for v in surface['vertices']]


def overlap_length(a, b, c, d):
    delta = tuple(b[i] - a[i] for i in range(3))
    length = math.dist(a, b)
    unit = [x / length for x in delta]
    project = lambda p: sum((p[i] - a[i]) * unit[i] for i in range(3))
    def distance(p):
        t = project(p)
        return math.sqrt(sum((p[i] - a[i] - t * unit[i]) ** 2 for i in range(3)))
    if distance(c) > 1e-5 or distance(d) > 1e-5:
        return 0.0
    lo, hi = sorted([project(c), project(d)])
    return max(0.0, min(length, hi) - max(0.0, lo))


def build(out, config, period, excel_inputs=None, wall_inputs=None, wall_catalog=None):
    out.mkdir(parents=True, exist_ok=True)
    d = {p.stem: read(p) for p in TABLES.glob('*.json')}
    rooms = {r['ID']: r for r in d['ROOM']}
    groups = {r['ROOM_GROUP_ID']: r for r in d['ROOM_GROUP']}
    schedules = {r['SCHEDULE_ID']: struct.unpack('<8760d', base64.b64decode(r['DATA']['base64'])) for r in d['SCHEDULE_YEAR']}
    room_names = {r['NAME'] for r in rooms.values()}
    assert set(config['rooms']) <= room_names, 'Unknown room in configuration'
    assert config['ventilation_ach'] == 0, 'Only the confirmed zero-ventilation case is supported'
    assert config['humidity_control'] == 'None', 'This entry computes sensible thermal demand'
    assert config['ground']['model'] == 'Kiva'
    assert config['timesteps_per_hour'] in (6, 12, 20, 30, 60)
    assert 0 < config['stop_tolerance_C'] < 0.05
    model = use_current_version(read(BASE / 'model.epJSON'))
    add = lambda kind, name, **fields: model.setdefault(kind, {}).__setitem__(name, fields)
    add('RunPeriod', 'Annual TEST', begin_month=period[0], begin_day_of_month=period[1],
        end_month=period[2], end_day_of_month=period[3], day_of_week_for_start_day='Monday',
        use_weather_file_holidays_and_special_days='No', use_weather_file_daylight_saving_period='No',
        use_weather_file_rain_indicators='No', use_weather_file_snow_indicators='No')
    model['RunPeriod'] = {'Annual TEST': model['RunPeriod']['Annual TEST']}
    model['Timestep'] = {'Timestep': {'number_of_timesteps_per_hour': config['timesteps_per_hour']}}
    add('ZoneAirHeatBalanceAlgorithm', 'Air balance', algorithm='AnalyticalSolution')
    # Shared, self-contained copies of all source schedules.
    schdir = out / 'schedules'
    schdir.mkdir(exist_ok=True)
    for item in model.get('Schedule:File', {}).values():
        source = pathlib.Path(item['file_name'])
        target = schdir / source.name
        shutil.copy2(source, target)
        item['file_name'] = str(target.resolve())

    def schedule(sid):
        name = f'DeST_Schedule_{sid}'
        target = schdir / f'{name}.txt'
        if name not in model['Schedule:File']:
            target.write_text('\n'.join(format(x, '.15g') for x in schedules[sid]) + '\n', encoding='ascii')
            add('Schedule:File', name, schedule_type_limits_name='Any Number', file_name=str(target.resolve()),
                column_number=1, rows_to_skip_at_top=0, number_of_hours_of_data=8760, column_separator='Comma',
                interpolate_to_timestep='No', minutes_per_item=60, adjust_schedule_for_daylight_savings='No')
        return name

    # Model the source heat/electric ratio explicitly: 0.9 reaches the room,
    # split 70% radiant / 30% convective, and 0.1 does not heat the room.
    # ElectricEquipment is an equivalent heat source, not a Lights meter.
    lighting_audit = []
    dist = {r['DIST_MODE_ID']: r for r in d['DIST_MODE']}
    for g in d['LIGHT_GAINS']:
        name = f"LIGHT_GAINS_{g['GAIN_ID']}"
        old = model['Lights'].pop(name)
        ratio = g['HEAT_RATE']
        assert 0 <= ratio <= 1
        radiant = ratio * (1 - dist[g['DIST_MODE']]['DIST_AIR'])
        add('ElectricEquipment', name, zone_or_zonelist_or_space_or_spacelist_name=old['zone_or_zonelist_or_space_or_spacelist_name'],
            schedule_name=old['schedule_name'], design_level_calculation_method='EquipmentLevel', design_level=old['lighting_level'],
            fraction_latent=0, fraction_radiant=radiant, fraction_lost=1 - ratio,
            end_use_subcategory='DeST Lighting Equivalent')
        lighting_audit.append({'zone': rooms[g['OF_ROOM']]['NAME'], 'heat_electric_ratio': ratio,
                               'radiant_fraction_of_input': radiant, 'convective_fraction_of_input': ratio - radiant,
                               'lost_fraction_of_input': 1 - ratio})
    assert not model.pop('Lights')

    # Kiva uses weather and zone conditions, not the diagnostic DeST monthly ground temperatures.
    model.pop('Site:GroundTemperature:BuildingSurface')
    soil = config['ground']
    add('Foundation:Kiva:Settings', 'Soil assumptions', soil_conductivity=soil['soil_conductivity_W_mK'],
        soil_density=soil['soil_density_kg_m3'], soil_specific_heat=soil['soil_specific_heat_J_kgK'],
        ground_solar_absorptivity=0.9, ground_thermal_absorptivity=0.9, ground_surface_roughness=0.03,
        far_field_width=40, deep_ground_boundary_condition='Autoselect', deep_ground_depth='Autocalculate',
        minimum_cell_dimension=0.02, maximum_cell_growth_coefficient=1.5, simulation_timestep='Timestep')
    surfaces = model['BuildingSurface:Detailed']
    exterior_edges = []
    for s in surfaces.values():
        if s['outside_boundary_condition'] == 'Outdoors' and s['surface_type'] == 'Wall':
            v = vertices(s)
            exterior_edges.extend((a, b) for a, b in zip(v, v[1:] + v[:1]) if abs(a[2] - b[2]) < 1e-7)
    ground_audit = []
    for name, s in surfaces.items():
        if s['outside_boundary_condition'] != 'Ground':
            continue
        v = vertices(s)
        lengths = [math.dist(a, b) for a, b in zip(v, v[1:] + v[:1])]
        exposed = [sum(overlap_length(a, b, c, e) for c, e in exterior_edges) for a, b in zip(v, v[1:] + v[:1])]
        assert all(-1e-6 <= p <= length + 1e-5 for p, length in zip(exposed, lengths))
        assert sum(exposed) > 0
        assert all(p < 1e-5 or abs(p - length) < 1e-5 for p, length in zip(exposed, lengths)), 'Split partly exposed floor segments first'
        ext = next(x for x in surfaces.values() if x['zone_name'] == s['zone_name'] and x['outside_boundary_condition'] == 'Outdoors' and x['surface_type'] == 'Wall')
        foundation = f'Foundation_{name}'
        add('Foundation:Kiva', foundation, initial_indoor_air_temperature=soil['initial_indoor_temperature_C'],
            wall_height_above_grade=soil['wall_height_above_grade_m'], wall_depth_below_slab=soil['wall_depth_below_slab_m'],
            footing_wall_construction_name=ext['construction_name'])
        add('SurfaceProperty:ExposedFoundationPerimeter', f'Perimeter_{name}', surface_name=name,
            exposed_perimeter_calculation_method='BySegment', total_exposed_perimeter=sum(exposed), exposed_perimeter_fraction=sum(exposed) / sum(lengths),
            surfaces=[{'surface_segment_exposed': 'Yes' if p > 1e-5 else 'No'} for p in exposed])
        s['outside_boundary_condition'] = 'Foundation'
        s['outside_boundary_condition_object'] = foundation
        # Kiva evaluates its own surface convection.
        model['SurfaceProperty:ConvectionCoefficients'].pop('Film_' + name, None)
        ground_audit.append({'surface': name, 'zone': s['zone_name'], 'exposed_perimeter_m': sum(exposed),
                             'total_perimeter_m': sum(lengths), 'segment_exposed_lengths_m': exposed,
                             'edge_wall_construction_assumption': ext['construction_name']})

    model['Output:Variable'] = {}
    def output(variable, frequency='Hourly', key='*'):
        add('Output:Variable', f'Output_{len(model["Output:Variable"])}', key_value=key,
            variable_name=variable, reporting_frequency=frequency)
    for var in ['Zone Mean Air Temperature', 'Zone Air Relative Humidity', 'Site Outdoor Air Drybulb Temperature']:
        output(var)
    output('Zone Mean Air Temperature', 'Timestep')
    output('Zone Electric Equipment Total Heating Energy')
    output('Zone People Sensible Heating Energy')
    add('Output:VariableDictionary', 'Dictionary', key_field='IDF')
    add('Output:Constructions', 'Construction audit', details_type_1='Constructions', details_type_2='Materials')
    # One room-config source is used for both modes.
    room_audit = []
    for rid, room in rooms.items():
        group = groups[room['OF_ROOM_GROUP']]
        settings = config['rooms'].get(room['NAME'], {})
        enabled = settings.get('conditioned', bool(group['IS_AC_ROOM']))
        assert isinstance(enabled, bool)
        ids = {k: group[field] for k, field in [('available', 'AC_SCHEDULE_ID'), ('low', 'AC_T_MIN_SCHEDULE'),
               ('heat', 'SET_T_MIN_SCHEDULE'), ('cool', 'SET_T_MAX_SCHEDULE'), ('high', 'AC_T_MAX_SCHEDULE')]}
        values = {k: schedules[sid] for k, sid in ids.items()}
        assert all(lo <= h < c <= hi for lo, h, c, hi in zip(values['low'], values['heat'], values['cool'], values['high']))
        room_audit.append({'name': room['NAME'], 'room_id': rid, 'conditioned': enabled, 'area_m2': room['AREA'],
                           'schedules': ids, 'temperature_ranges_C': {k: [min(values[k]), max(values[k])] for k in ['low', 'heat', 'cool', 'high']}})
        for sid in ids.values():
            schedule(sid)
    if excel_inputs is not None:
        from excel_inputs import apply_inputs
        apply_inputs(model, out, excel_inputs, period)
    # Apply above-grade walls after constructing Kiva: foundation edge walls keep
    # their original DeST construction, avoiding an implicit foundation retrofit.
    from wall_assignments import apply_assignments, export_audit
    wall_audit = apply_assignments(model, wall_inputs, wall_catalog or {'materials': [], 'constructions': []})
    export_audit(out, wall_audit)
    free = copy.deepcopy(model)
    globals_, initialize, control_programs = [], [], []
    epsilon = config['stop_tolerance_C']
    for room in room_audit:
        if not room['conditioned']:
            continue
        zone, rid = room['name'], room['room_id']
        prefix = f'R{rid}'
        ids = room['schedules']
        for tag, source in [('T', ('Zone Mean Air Temperature', zone))] + [(k, ('Schedule Value', schedule(sid))) for k, sid in ids.items()]:
            add('EnergyManagementSystem:Sensor', prefix + '_' + tag,
                output_variable_or_output_meter_index_key_name=source[1], output_variable_or_output_meter_name=source[0])
        state, reference, previous = prefix + '_mode', prefix + '_reference_T', prefix + '_previous'
        globals_.extend([state, reference, previous])
        initialize.extend([f'SET {state} = 0', f'SET {reference} = 20', f'SET {previous} = 0'])
        ctrl = prefix + '_control'
        avail = prefix + '_enable'
        for name in (ctrl, avail):
            # Initial nonzero values ensure heating/cooling types are known during input processing.
            add('Schedule:Constant', name, schedule_type_limits_name='Any Number', hourly_value=1)
            add('EnergyManagementSystem:Actuator', name + '_act', actuated_component_unique_name=name,
                actuated_component_type='Schedule:Constant', actuated_component_control_type='Schedule Value')
        t, av = prefix + '_T', prefix + '_available'
        low, heat, cool, high = [prefix + '_' + k for k in ('low', 'heat', 'cool', 'high')]
        lines = [f'SET {reference} = {t}', f'SET {previous} = {state}',
                 f'IF {av} <= 0', f'  SET {state} = 0',
                 f'ELSEIF ({state} == 1) && ({t} < ({heat} - {epsilon}))', f'  SET {state} = 1',
                 f'ELSEIF ({state} == 2) && ({t} > ({cool} + {epsilon}))', f'  SET {state} = 2',
                 f'ELSEIF {t} < {low}', f'  SET {state} = 1',
                 f'ELSEIF {t} > {high}', f'  SET {state} = 2', 'ELSE', f'  SET {state} = 0', 'ENDIF',
                 f'SET {ctrl}_act = {state}', f'SET {avail}_act = 0',
                 f'IF {state} > 0', f'  SET {avail}_act = 1', 'ENDIF']
        pname = prefix + '_controller'
        add('EnergyManagementSystem:Program', pname, lines=[{'program_line': x} for x in lines])
        control_programs.append({'program_name': pname})
        for label, variable in [('Mode', state), ('Reference Temperature', reference), ('Previous Mode', previous)]:
            output_name = zone + ' Control ' + label
            add('EnergyManagementSystem:OutputVariable', output_name, ems_variable_name=variable,
                type_of_data_in_variable='Averaged', update_frequency='ZoneTimestep')
            output(output_name, 'Timestep')
        add('ThermostatSetpoint:SingleHeating', prefix + '_heating', setpoint_temperature_schedule_name=schedule(ids['heat']))
        add('ThermostatSetpoint:SingleCooling', prefix + '_cooling', setpoint_temperature_schedule_name=schedule(ids['cool']))
        add('ZoneControl:Thermostat', prefix + '_thermostat', zone_or_zonelist_name=zone, control_type_schedule_name=ctrl,
            control_1_object_type='ThermostatSetpoint:SingleHeating', control_1_name=prefix + '_heating',
            control_2_object_type='ThermostatSetpoint:SingleCooling', control_2_name=prefix + '_cooling')
        system = prefix + '_ideal'
        add('ZoneHVAC:IdealLoadsAirSystem', system, availability_schedule_name=avail, zone_supply_air_node_name=prefix + '_supply',
            maximum_heating_supply_air_temperature=50, minimum_cooling_supply_air_temperature=13,
            heating_limit='NoLimit', cooling_limit='NoLimit', dehumidification_control_type='None',
            humidification_control_type='None', outdoor_air_economizer_type='NoEconomizer', heat_recovery_type='None')
        add('ZoneHVAC:EquipmentList', prefix + '_equipment', load_distribution_scheme='SequentialLoad', equipment=[{
            'zone_equipment_object_type': 'ZoneHVAC:IdealLoadsAirSystem', 'zone_equipment_name': system,
            'zone_equipment_cooling_sequence': 1, 'zone_equipment_heating_or_no_load_sequence': 1}])
        add('ZoneHVAC:EquipmentConnections', prefix + '_connections', zone_name=zone,
            zone_conditioning_equipment_list_name=prefix + '_equipment', zone_air_inlet_node_or_nodelist_name=prefix + '_supply',
            zone_air_node_name=prefix + '_air', zone_return_air_node_or_nodelist_name=prefix + '_return')
    if globals_:
        add('EnergyManagementSystem:GlobalVariable', 'Controller memory', variables=[{'erl_variable_name': x} for x in globals_])
        add('EnergyManagementSystem:Program', 'InitializeControllers', lines=[{'program_line': x} for x in initialize])
        add('EnergyManagementSystem:ProgramCallingManager', 'Initialize', energyplus_model_calling_point='BeginNewEnvironment',
            programs=[{'program_name': 'InitializeControllers'}])
        add('EnergyManagementSystem:ProgramCallingManager', 'Control', energyplus_model_calling_point='BeginTimestepBeforePredictor',
            programs=control_programs)
        for var in ['Zone Ideal Loads Zone Sensible Heating Energy', 'Zone Ideal Loads Zone Sensible Cooling Energy']:
            output(var)
            output(var, 'Timestep')
    for name, m in [('natural', free), ('controlled', model)]:
        # Avoid absolute non-ASCII paths in EnergyPlus Schedule:File parsing.
        # All plans were copied/generated inside this independent result folder.
        for item in m.get('Schedule:File', {}).values():
            source = pathlib.Path(item['file_name']).resolve(strict=True)
            relative = source.relative_to(out.resolve())
            item['file_name'] = '../' + relative.as_posix()
        save(out / name / 'model.epJSON', m)
    audit = {'city': '北京', 'weather': str(WEATHER), 'weather_sha256': digest(WEATHER), 'period': period,
             'rooms': room_audit, 'config': config, 'ground': ground_audit, 'lighting': lighting_audit,
             'wall_assignments': wall_audit,
             'base_model_sha256': digest(BASE / 'model.epJSON'),
             'demand_definition': 'Delivered sensible heating/cooling thermal energy in kWh; no humidity conditioning, no equipment electricity.',
             'natural_definition': 'Independent whole-building simulation with all HVAC removed; not the temperatures of unconditioned rooms next to conditioned rooms.',
             'assumptions': ['Source material properties and schedules retained; source lighting heat/electric ratio corrected.',
                 'Kiva soil properties are EnergyPlus defaults, not measured Beijing soil.',
                 'Slab at grade, no basement, no separate footing block; slab edge wall uses adjacent exterior wall construction.',
                 'Kiva initialization indoor temperature 20 C, same in both runs; no research coating applied.',
                 'Zero outdoor air, infiltration and window opening; no humidity control.',
                 'Source window SHGC=0.87*SC approximation and aggregate radiant heat split retained; not a DeST equivalence certification.',
                 'EMS decision uses the previous completed timestep temperature; thresholds can be crossed within a timestep before the next decision.']}
    if excel_inputs is not None:
        audit['excel_inputs'] = excel_inputs
        audit['assumptions'][0] = 'Room use, occupants, lighting/equipment powers, weekday/weekend schedules and HVAC inclusion read from the saved Excel snapshot. Materials and per-person heat/activity and radiant fractions retained from DeST.'
        audit['assumptions'].append(excel_inputs['calendar']['description'])
    if wall_audit['changed_wall_count']:
        audit['assumptions'][0] += ' Selected above-grade wall constructions are replaced from the saved public-library snapshot; see wall audit.'
        audit['assumptions'][3] = 'Kiva initialization indoor temperature 20 C, same in both runs. Wall optical properties follow the explicit assignment settings.'
    audit['assumptions'].append(wall_audit['foundation_policy'])
    save(out / 'model-audit.json', audit)
    from wall_assignments import verify_models
    verify_models(out)
    shutil.copy2(BASE / 'floor-plans.svg', out / 'floor-plans.svg')
    return audit


def simulate(folder):
    folder = pathlib.Path(folder).resolve()
    save(folder / 'engine-runtime.json', engine_record(ENGINE))
    run = folder / 'run'
    run.mkdir(exist_ok=True)
    with (run / 'console.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([str(ENGINE), '-w', str(WEATHER), '-d', str(run), str(folder / 'model.epJSON')],
                                stdout=log, stderr=subprocess.STDOUT, cwd=folder)
    err = (run / 'eplusout.err').read_text(encoding='utf-8', errors='replace')
    if result.returncode or re.search(r'\*\*\s+(Severe|Fatal)\s+\*\*', err):
        raise RuntimeError(f'EnergyPlus failed in {folder}:\n{err[-7000:]}')
    print(f'{folder.name}: {err.splitlines()[-1]}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=pathlib.Path, default=PROJECT / 'config/dest_TEST_annual.json')
    parser.add_argument('--output', type=pathlib.Path)
    parser.add_argument('--input-workbook', type=pathlib.Path, help='Read the saved room-input workbook; retain an immutable input copy in this run.')
    parser.add_argument('--library-catalog', type=pathlib.Path, default=PROJECT / 'library/catalog.json')
    parser.add_argument('--period', nargs=4, type=int, default=[1, 1, 12, 31], metavar=('BEGIN_MONTH', 'BEGIN_DAY', 'END_MONTH', 'END_DAY'))
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args()
    out = (args.output or PROJECT / 'results/dest-annual' / datetime.datetime.now().strftime('TEST_%Y%m%d_%H%M%S')).resolve()
    if args.summarize_only:
        from summarize_annual import summarize
        summarize(out)
        return
    if (out / 'model-audit.json').exists():
        raise FileExistsError(f'Use a new output folder to preserve earlier results: {out}')
    config = read(args.config)
    excel_inputs = None
    wall_inputs = wall_catalog = None
    if args.input_workbook:
        from excel_inputs import load_inputs
        out.mkdir(parents=True, exist_ok=True)
        snapshot = out / '输入参数快照.xlsx'
        if snapshot.exists():
            raise FileExistsError(f'Input snapshot exists; choose a new output folder: {out}')
        snapshot.write_bytes(args.input_workbook.read_bytes())
        excel_inputs = load_inputs(snapshot)
        from wall_assignments import load_assignments
        catalog_bytes = args.library_catalog.read_bytes()
        wall_catalog = json.loads(catalog_bytes.decode('utf-8-sig'))
        wall_inputs = load_assignments(snapshot, wall_catalog)
        if wall_inputs is not None:
            library_snapshot = out / '公共库快照.json'
            library_snapshot.write_bytes(catalog_bytes)
            wall_inputs['catalog_file_sha256'] = digest(library_snapshot)
        excel_inputs['source_file'] = str(args.input_workbook.resolve())
        excel_inputs['snapshot'] = snapshot.name
        config['rooms'] = {name: {'conditioned': item['conditioned']} for name, item in excel_inputs['rooms'].items()}
        config['description'] = 'TEST 两层八房间；房间参数与作息来自Excel快照；首层接地；容忍温度触发、恢复设定温度后停机。'
    build(out, config, args.period, excel_inputs, wall_inputs, wall_catalog)
    print(f'Prepared {out}', flush=True)
    if args.prepare_only:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(simulate, [out / 'natural', out / 'controlled']))
    from wall_assignments import verify_engine_materials
    verify_engine_materials(out)
    from summarize_annual import summarize
    summarize(out)
    if excel_inputs is not None:
        from excel_inputs import verify_consumed_inputs
        verify_consumed_inputs(out)


if __name__ == '__main__':
    main()
