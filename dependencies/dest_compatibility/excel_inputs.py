"""Read the room workbook without modifying it; connect validated inputs to EP.

Only input cells are read. Excel formula caches and dropdown validation are not
trusted as simulation validation. Daily profile columns are discovered by name.
"""
import csv
import datetime
import hashlib
import math
import pathlib
import re
import warnings

import openpyxl

from run_annual import TABLES, read, save


def numeric(value, location, lower=0, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{location}: 必须填写数字，不能留空或使用未计算的公式。')
    if value < lower or (upper is not None and value > upper):
        raise ValueError(f'{location}: 数值超出允许范围 {lower}–{upper or "不限"}。')
    return float(value)


def text(value, location):
    if not isinstance(value, str) or not value.strip() or value.startswith('='):
        raise ValueError(f'{location}: 必须填写有效名称。')
    if value != value.strip():
        raise ValueError(f'{location}: 名称前后不能有空格。')
    return value


def load_inputs(path):
    path = pathlib.Path(path).resolve()
    with warnings.catch_warnings():
        # Read-only use: unsupported Excel x14 validation is neither needed nor saved.
        warnings.filterwarnings('ignore', message='Data Validation extension is not supported.*')
        workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        room_sheet = workbook['房间参数']
        daily = workbook['每日作息']
        profile_row, time_col = next((c.row, c.column) for row in daily for c in row if c.value == '时段')
        profiles = {}
        for col in range(time_col + 1, daily.max_column + 1):
            value = daily.cell(profile_row, col).value
            if value is None:
                if any(daily.cell(profile_row + 1 + h, col).value is not None for h in range(24)):
                    raise ValueError(f'每日作息: 第{col}列有数据但缺少计划名称。')
                continue
            name = text(value, f'每日作息!{daily.cell(profile_row, col).coordinate}')
            if name in profiles:
                raise ValueError(f'每日作息: 计划名称重复 {name}')
            profiles[name] = [numeric(daily.cell(profile_row + 1 + h, col).value,
                                     f'每日作息!{daily.cell(profile_row + 1 + h, col).coordinate}', 0, 1)
                              for h in range(24)]
        if not profiles:
            raise ValueError('每日作息: 未找到24小时计划。')
        for h in range(24):
            label = daily.cell(profile_row + 1 + h, time_col).value
            if label not in (f'{h:02d}:00–{h+1:02d}:00', f'{h:02d}:00-{h+1:02d}:00', f'{h:02d}–{h+1:02d}'):
                # Current template uses e.g. 00:00–01:00; reject reordered time rows.
                raise ValueError(f'每日作息: 第{h+1}个时段不匹配: {label!r}')
        header_rows = [c.row for row in room_sheet for c in row if c.value == '房间编号']
        if len(header_rows) != 2:
            raise ValueError('房间参数: 应有人员设置和照明/设备设置两张输入表。')
        normalize = lambda value: ''.join(str(value).split())
        tables = []
        for table_index, header_row in enumerate(header_rows):
            headers = {normalize(c.value): c.column for c in room_sheet[header_row] if c.value is not None}
            records = {}
            row = header_row + 1
            while room_sheet.cell(row, headers['房间编号']).value is not None:
                record = {key: room_sheet.cell(row, col).value for key, col in headers.items()}
                name = text(record['房间编号'], f'房间参数!B{row}')
                if name in records:
                    raise ValueError(f'房间参数: 房间编号重复 {name}')
                records[name] = record
                row += 1
            end_row = header_rows[table_index + 1] if table_index + 1 < len(header_rows) else room_sheet.max_row + 1
            for trailing_row in range(row, end_row):
                value = room_sheet.cell(trailing_row, headers['房间编号']).value
                if isinstance(value, str) and re.fullmatch(r'R\d+-\d+', value):
                    raise ValueError(f'房间参数: 第{trailing_row}行的房间被空行隔开，请连续填写房间记录。')
            tables.append(records)
        source_rooms = {r['NAME']: r for r in read(TABLES / 'ROOM.json')}
        for table in tables:
            if table.keys() != source_rooms.keys():
                raise ValueError(f'房间编号与几何模型不一致；缺少{set(source_rooms)-set(table)}，新增{set(table)-set(source_rooms)}。实际分割房间需要更新DeST几何模型。')
        rooms = {}
        for name, source in source_rooms.items():
            r, g = tables[0][name], tables[1][name]
            area = numeric(r['面积m²'], f'{name}面积', 0.000001)
            if abs(area - source['AREA']) > 1e-5:
                raise ValueError(f'{name}: Excel面积{area}与几何面积{source["AREA"]}不符。')
            conditioned = r['接入空调']
            if conditioned not in ('是', '否'):
                raise ValueError(f'{name}: 接入空调必须为是/否。')
            item = {'zone': name, 'area_m2': area, 'use': text(r['拟定用途'], name),
                    'max_people': numeric(r['最大人数人/间'], f'{name}最大人数'),
                    'conditioned': conditioned == '是', 'basis': text(r['取值依据'], name)}
            for tag, label, table in [('people', '人员', r), ('lighting', '照明', g), ('equipment', '设备', g)]:
                for day, day_label in [('weekday', '工作日'), ('weekend', '周末')]:
                    profile = text(table[f'{label}作息{day_label}'], f'{name}{label}{day_label}')
                    if profile not in profiles:
                        raise ValueError(f'{name}: 未定义计划 {profile}')
                    item[f'{tag}_{day}'] = profile
                if tag != 'people':
                    for bound, bound_label in [('min', '最小'), ('max', '最大')]:
                        item[f'{tag}_{bound}_W_m2'] = numeric(table[f'{label}{bound_label}W/m²'], f'{name}{label}{bound_label}')
                    if item[f'{tag}_min_W_m2'] > item[f'{tag}_max_W_m2']:
                        raise ValueError(f'{name}: {label}最小值大于最大值。')
            rooms[name] = item
        return {'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'rooms': rooms,
                'profiles': profiles,
                'calendar': {'days': 365, 'hours': 8760, 'jan_1_weekday': 'Monday', 'weekday_days': 261,
                             'weekend_days': 104, 'holidays': False,
                             'description': '沿用原基准的365天日历，1月1日为星期一；周一至周五为工作日，周六日为周末，不另设法定节假日。北京CSWD典型年，不对应特定实际公历年。'},
                'profile_full_load_hours': {k: sum(v) for k, v in profiles.items()}}
    finally:
        workbook.close()


def expected_at(inputs, zone, day_index, hour_index):
    room = inputs['rooms'][zone]
    day_type = 'weekday' if day_index % 7 < 5 else 'weekend'
    fractions = {tag: inputs['profiles'][room[f'{tag}_{day_type}']][hour_index]
                 for tag in ('people', 'lighting', 'equipment')}
    return [room['max_people'] * fractions['people']] + [
        room['area_m2'] * (room[f'{tag}_min_W_m2'] + fractions[tag] *
                           (room[f'{tag}_max_W_m2'] - room[f'{tag}_min_W_m2']))
        for tag in ('lighting', 'equipment')]


def apply_inputs(model, out, inputs, period):
    bindings = {}
    for index, (zone, room) in enumerate(inputs['rooms'].items()):
        values = [expected_at(inputs, zone, d, h) for d in range(365) for h in range(24)]
        bindings[zone] = {}
        for column, tag in enumerate(('people', 'lighting', 'equipment')):
            kind = 'People' if tag == 'people' else 'ElectricEquipment'
            prefix = {'people': 'OCCUPANT_GAINS_', 'lighting': 'LIGHT_GAINS_', 'equipment': 'EQUIPMENT_GAINS_'}[tag]
            matches = [(n, v) for n, v in model[kind].items() if n.startswith(prefix) and
                       v['zone_or_zonelist_or_space_or_spacelist_name'] == zone]
            if len(matches) != 1:
                raise ValueError(f'{zone}: 应有一个{tag}热源对象，实际{len(matches)}。')
            name, item = matches[0]
            schedule_name = f'Excel_R{index+1}_{tag}'
            target = out / 'schedules' / f'{schedule_name}.txt'
            target.write_text('\n'.join(format(row[column], '.15g') for row in values) + '\n', encoding='ascii')
            model['Schedule:File'][schedule_name] = {
                'schedule_type_limits_name': 'Any Number', 'file_name': str(target.resolve()),
                'column_number': 1, 'rows_to_skip_at_top': 0, 'number_of_hours_of_data': 8760,
                'column_separator': 'Comma', 'interpolate_to_timestep': 'No', 'minutes_per_item': 60,
                'adjust_schedule_for_daylight_savings': 'No'}
            if tag == 'people':
                item['number_of_people_schedule_name'] = schedule_name
                item['number_of_people_calculation_method'] = 'People'
                item['number_of_people'] = 1
            else:
                item['schedule_name'] = schedule_name
                item['design_level_calculation_method'] = 'EquipmentLevel'
                item['design_level'] = 1
            bindings[zone][tag] = {'object': name, 'schedule': schedule_name}
            model['Output:Variable'][f'Excel schedule {index} {tag}'] = {
                'key_value': schedule_name, 'variable_name': 'Schedule Value', 'reporting_frequency': 'Hourly'}
    offset = (datetime.date(2025, period[0], period[1]) - datetime.date(2025, 1, 1)).days
    next(iter(model['RunPeriod'].values()))['day_of_week_for_start_day'] = [
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][offset % 7]
    inputs['bindings'] = bindings
    save(out / 'excel-inputs.json', inputs)


def verify_consumed_inputs(out):
    """Compare every emitted EP schedule and zone gain against original Excel inputs."""
    from summarize_annual import Results
    inputs = read(out / 'excel-inputs.json')
    audit = read(out / 'model-audit.json')
    expected_hours = ((datetime.date(2025, audit['period'][2], audit['period'][3]) -
                       datetime.date(2025, audit['period'][0], audit['period'][1])).days + 1) * 24
    checks = []
    for case in ('natural', 'controlled'):
        results = Results(out / case / 'run/eplusout.sql')
        model = read(out / case / 'model.epJSON')
        with (out / f'逐时输入核查_{case}.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['房间', '月', '日', '小时终点', '人数', '照明输入_W', '设备输入_W', '人员显热_kWh', '照明与设备入室热_kWh'])
            for zone in inputs['rooms']:
                schedules = [results.hours(inputs['bindings'][zone][tag]['schedule'], 'Schedule Value')
                             for tag in ('people', 'lighting', 'equipment')]
                people_heat = results.hours(zone, 'Zone People Sensible Heating Energy')
                equipment_heat = results.hours(zone, 'Zone Electric Equipment Total Heating Energy')
                assert all(len(s) == expected_hours and s.keys() == people_heat.keys() == equipment_heat.keys() for s in schedules)
                max_error, annual_people, annual_equipment = 0, 0, 0
                for hour in people_heat:
                    month, day, end = hour
                    day_index = (datetime.date(2025, month, day) - datetime.date(2025, 1, 1)).days
                    expected = expected_at(inputs, zone, day_index, end - 1)
                    actual = [s[hour] for s in schedules]
                    for a, b in zip(actual, expected):
                        assert math.isclose(a, b, abs_tol=1e-7, rel_tol=1e-10), (case, zone, hour, a, b)
                        max_error = max(max_error, abs(a - b))
                    person = model['People'][inputs['bindings'][zone]['people']['object']]
                    activity = model['Schedule:Constant'][person['activity_level_schedule_name']]['hourly_value']
                    expected_person_J = expected[0] * activity * person['sensible_heat_fraction'] * 3600
                    expected_equipment_J = sum(expected[i] * (1 - model['ElectricEquipment'][inputs['bindings'][zone][tag]['object']]['fraction_lost']) * 3600
                                               for i, tag in [(1, 'lighting'), (2, 'equipment')])
                    assert math.isclose(people_heat[hour], expected_person_J, abs_tol=1e-5, rel_tol=1e-9)
                    assert math.isclose(equipment_heat[hour], expected_equipment_J, abs_tol=1e-5, rel_tol=1e-9)
                    annual_people += people_heat[hour] / 3.6e6
                    annual_equipment += equipment_heat[hour] / 3.6e6
                    writer.writerow([zone, *hour, *actual, people_heat[hour] / 3.6e6, equipment_heat[hour] / 3.6e6])
                checks.append({'case': case, 'zone': zone, 'hours': expected_hours, 'max_schedule_error': max_error,
                               'people_sensible_kWh': annual_people, 'lighting_equipment_heat_kWh': annual_equipment})
        results.connection.close()
    save(out / 'excel-input-verification.json', {'passed': True, 'checks': checks,
         'profile_names': list(inputs['profiles']), 'calendar': inputs['calendar'],
         'source_sha256': inputs['source_sha256']})
    print(f'Excel input verification passed: {len(checks) * expected_hours:,} room-hours in paired simulations.', flush=True)
