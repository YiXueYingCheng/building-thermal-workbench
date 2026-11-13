"""Read real EnergyPlus SQL outputs, verify controller behavior, and export data."""
import base64
import calendar
import collections
import csv
import datetime
import math
import pathlib
import sqlite3
import struct

from run_annual import TABLES, next_mode, read, save

HEAT = 'Zone Ideal Loads Zone Sensible Heating Energy'
COOL = 'Zone Ideal Loads Zone Sensible Cooling Energy'
TEMP = 'Zone Mean Air Temperature'


class Results:
    def __init__(self, path):
        self.connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        self.dictionary = list(self.connection.execute('SELECT ReportDataDictionaryIndex,KeyValue,Name,ReportingFrequency,Units FROM ReportDataDictionary'))
        self.time = {r[0]: r[1:] for r in self.connection.execute('SELECT TimeIndex,Month,Day,Hour,Minute,Interval FROM Time WHERE WarmupFlag=0')}

    def series(self, key, name, frequency, optional=False):
        ids = [r[0] for r in self.dictionary if r[1].upper() == key.upper() and r[2].upper() == name.upper() and r[3] == frequency]
        if not ids and optional:
            return {}
        assert len(ids) == 1, (key, name, frequency, ids)
        result = dict(self.connection.execute('SELECT TimeIndex,Value FROM ReportData WHERE ReportDataDictionaryIndex=? ORDER BY TimeIndex', (ids[0],)))
        assert all(math.isfinite(x) for x in result.values())
        assert set(result) <= self.time.keys()
        return result

    def hours(self, key, name, optional=False):
        data = self.series(key, name, 'Hourly', optional)
        return {hour_key(self.time[t]): value for t, value in data.items()}


def hour_key(time):
    month, day, hour, minute, interval = time
    # SQL Hour/Minute denote the interval endpoint; retain 24:00 on the source day.
    return month, day, math.ceil((hour * 60 + minute) / 60)


def schedule_index(time):
    month, day, hour = hour_key(time)
    return (datetime.date(2025, month, day).timetuple().tm_yday - 1) * 24 + hour - 1


def summarize(out, source_schedules=None):
    out = pathlib.Path(out).resolve()
    audit = read(out / 'model-audit.json')
    controlled = Results(out / 'controlled/run/eplusout.sql')
    natural = Results(out / 'natural/run/eplusout.sql')
    if source_schedules is None:
        source_schedules = {r['SCHEDULE_ID']: struct.unpack('<8760d', base64.b64decode(r['DATA']['base64'])) for r in read(TABLES / 'SCHEDULE_YEAR.json')}
    outdoor = controlled.hours('Environment', 'Site Outdoor Air Drybulb Temperature')
    natural_outdoor = natural.hours('Environment', 'Site Outdoor Air Drybulb Temperature')
    assert outdoor == natural_outdoor, 'Paired simulations must use identical weather and times'
    p = audit['period']
    expected_hours = ((datetime.date(2025, p[2], p[3]) - datetime.date(2025, p[0], p[1])).days + 1) * 24
    assert len(outdoor) == expected_hours
    steps_per_hour = audit['config']['timesteps_per_hour']
    epsilon = audit['config']['stop_tolerance_C']
    rows, room_summary, monthly = [], [], []
    controller_checks = []
    timestep_path = out / '启停检查_计算步长.csv'
    with timestep_path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['房间', '月', '日', '时', '分', '步长分钟', '上步状态', '控制参考室温_C', '本步状态_0停1热2冷', '本步室温_C', '供暖需求_kWh', '制冷需求_kWh'])
        for room in audit['rooms']:
            zone = room['name']
            ideal = f'R{room["room_id"]}_ideal'
            temps = controlled.hours(zone, TEMP)
            free_temps = natural.hours(zone, TEMP)
            assert set(temps) == set(free_temps) == set(outdoor)
            heat = controlled.hours(ideal, HEAT, optional=not room['conditioned'])
            cool = controlled.hours(ideal, COOL, optional=not room['conditioned'])
            if room['conditioned']:
                assert set(heat) == set(cool) == set(temps)
            else:
                assert not heat and not cool
            durations = collections.defaultdict(lambda: [0.0, 0.0])
            check = {'zone': zone, 'conditioned': room['conditioned'], 'timesteps': 0, 'mode_counts': {0: 0, 1: 0, 2: 0},
                     'heating_starts': 0, 'cooling_starts': 0, 'verified_mode_decisions': 0,
                     'maximum_reference_vs_prior_reported_temperature_difference_C': 0.0,
                     'max_heating_return_error_C': 0.0, 'max_cooling_return_error_C': 0.0}
            timestep_temp = controlled.series(zone, TEMP, 'Zone Timestep')
            assert len(timestep_temp) == expected_hours * steps_per_hour
            if room['conditioned']:
                mode = controlled.series('EMS', zone + ' Control Mode', 'Zone Timestep')
                previous = controlled.series('EMS', zone + ' Control Previous Mode', 'Zone Timestep')
                reference = controlled.series('EMS', zone + ' Control Reference Temperature', 'Zone Timestep')
                hstep = controlled.series(ideal, HEAT, 'Zone Timestep')
                cstep = controlled.series(ideal, COOL, 'Zone Timestep')
                assert set(mode) == set(previous) == set(reference) == set(hstep) == set(cstep) == set(timestep_temp)
            else:
                mode = {t: 0.0 for t in timestep_temp}
                previous = mode
                reference = timestep_temp
                hstep = mode
                cstep = mode
            last_mode, last_temp = None, None
            for t, actual in timestep_temp.items():
                when = controlled.time[t]
                state, before, sensor = mode[t], previous[t], reference[t]
                assert state in (0, 1, 2) and before in (0, 1, 2), 'Mode is not an integer'
                assert hstep[t] >= -1e-8 and cstep[t] >= -1e-8
                assert not (hstep[t] > 1e-6 and cstep[t] > 1e-6), 'Simultaneous heating and cooling'
                if state != 1:
                    assert abs(hstep[t]) < 1e-6, 'Heating while off or cooling'
                if state != 2:
                    assert abs(cstep[t]) < 1e-6, 'Cooling while off or heating'
                if room['conditioned']:
                    if last_mode is not None:
                        assert before == last_mode, 'EMS memory was lost between steps'
                        delta = abs(sensor - last_temp)
                        check['maximum_reference_vs_prior_reported_temperature_difference_C'] = max(check['maximum_reference_vs_prior_reported_temperature_difference_C'], delta)
                        assert delta < 1e-6, 'Controller did not use the prior completed timestep'
                    idx = schedule_index(when)
                    s = {k: source_schedules[sid][idx] for k, sid in room['schedules'].items()}
                    expected = next_mode(before, sensor, s['available'] > 0, s['low'], s['heat'], s['cool'], s['high'], epsilon)
                    assert state == expected, ('Control decision mismatch', zone, when, state, expected)
                    check['verified_mode_decisions'] += 1
                    if state == 1 and before != 1:
                        check['heating_starts'] += 1
                        assert sensor < s['low']
                    if state == 2 and before != 2:
                        check['cooling_starts'] += 1
                        assert sensor > s['high']
                    if hstep[t] > 1e-6:
                        check['max_heating_return_error_C'] = max(check['max_heating_return_error_C'], abs(actual - s['heat']))
                    if cstep[t] > 1e-6:
                        check['max_cooling_return_error_C'] = max(check['max_cooling_return_error_C'], abs(actual - s['cool']))
                duration = when[4] / 60
                if state:
                    durations[hour_key(when)][int(state) - 1] += duration
                check['mode_counts'][int(state)] += 1
                check['timesteps'] += 1
                writer.writerow([zone, *when, int(before), sensor, int(state), actual, hstep[t] / 3.6e6, cstep[t] / 3.6e6])
                last_mode, last_temp = state, actual
            assert math.isclose(sum(hstep.values()), sum(heat.values()), rel_tol=1e-10, abs_tol=1e-5)
            assert math.isclose(sum(cstep.values()), sum(cool.values()), rel_tol=1e-10, abs_tol=1e-5)
            controller_checks.append(check)
            room_rows = []
            for hour, temp in temps.items():
                row = [zone, *hour, outdoor[hour], free_temps[hour], temp, heat.get(hour, 0) / 3.6e6,
                       cool.get(hour, 0) / 3.6e6, *durations[hour]]
                rows.append(row)
                room_rows.append(row)
            room_summary.append({'zone': zone, 'conditioned': room['conditioned'], 'area_m2': room['area_m2'],
                                 'hours': len(temps), 'heating_kWh': sum(heat.values()) / 3.6e6, 'cooling_kWh': sum(cool.values()) / 3.6e6,
                                 'natural_mean_C': sum(free_temps.values()) / len(free_temps),
                                 'natural_min_C': min(free_temps.values()), 'natural_max_C': max(free_temps.values()),
                                 'controlled_mean_C': sum(temps.values()) / len(temps)})
            for month in sorted({h[0] for h in temps}):
                selected = [r for r in room_rows if r[1] == month]
                monthly.append({'zone': zone, 'month': month, 'hours': len(selected), 'heating_kWh': sum(r[7] for r in selected),
                                'cooling_kWh': sum(r[8] for r in selected), 'natural_mean_C': sum(r[5] for r in selected) / len(selected)})
    headers = ['房间', '月', '日', '小时终点_1至24', '室外温度_C', '全楼自然室温_C', '按房间空调设置室温_C', '供暖显热需求_kWh', '制冷显热需求_kWh', '供暖启用时长_h', '制冷启用时长_h']
    with (out / '逐时结果.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)
    result = {'audit': audit, 'headers': headers, 'rows': rows, 'rooms': room_summary, 'monthly': monthly,
              'hours_per_room': expected_hours, 'heating_kWh': sum(x['heating_kWh'] for x in room_summary),
              'cooling_kWh': sum(x['cooling_kWh'] for x in room_summary)}
    save(out / 'annual-data.json', result)
    # A small UI summary avoids reading the full building's hourly JSON.
    building_monthly = {}
    for row in monthly:
        item = building_monthly.setdefault(row['month'], {'month': row['month'], 'heating_kWh': 0., 'cooling_kWh': 0.})
        for key in ['heating_kWh', 'cooling_kWh']:
            item[key] += row[key]
    save(out / 'monthly-summary.json', {'schema': 1, 'monthly': list(building_monthly.values())})
    save(out / 'verification.json', {'passed': True, 'hours_per_room': expected_hours, 'room_hour_rows': len(rows),
         'whole_building_natural_case_has_no_hvac': not read(out / 'natural/model.epJSON').get('ZoneHVAC:IdealLoadsAirSystem'),
         'paired_weather_identical': True, 'hourly_energy_equals_timestep_sum': True, 'controller': controller_checks,
         'heating_kWh': result['heating_kWh'], 'cooling_kWh': result['cooling_kWh']})
    print(f'Checked {len(rows):,} room-hours. Heating {result["heating_kWh"]:.3f} kWh; cooling {result["cooling_kWh"]:.3f} kWh.', flush=True)
    return result
