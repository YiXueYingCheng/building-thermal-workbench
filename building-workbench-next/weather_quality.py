"""Read-only, bounded EPW screening. No repair, registration or eligibility changes."""
from __future__ import annotations
import calendar
import csv
import datetime as dt
import hashlib
import io
import math
from pathlib import Path

VERSION = 'epw-hourly-screen-v1'
MAX_BYTES = 32 * 1024 * 1024
DOC = 'https://bigladdersoftware.com/epx/docs/26-1/auxiliary-programs/auxiliary-programs.html#energyplus-weather-file-epw-data-dictionary'
HEADERS = ('LOCATION', 'DESIGN CONDITIONS', 'TYPICAL/EXTREME PERIODS', 'GROUND TEMPERATURES',
           'HOLIDAYS/DAYLIGHT SAVINGS', 'COMMENTS 1', 'COMMENTS 2', 'DATA PERIODS')
# index, key, label, unit, missing threshold, lower, upper, required for this screen
FIELDS = (
    (6, 'dry_bulb', '干球温度', '°C', 99.9, -70, 70, True),
    (7, 'dew_point', '露点温度', '°C', 99.9, -70, 70, True),
    (8, 'relative_humidity', '相对湿度', '%', 999, 0, 110, True),
    (9, 'pressure', '站点气压', 'Pa', 999999, 31000, 120000, True),
    (12, 'infrared', '水平长波辐射', 'Wh/m²', 9999, 0, None, False),
    (13, 'ghi', '水平总太阳辐射', 'Wh/m²', 9999, 0, None, False),
    (14, 'dni', '法向直射辐射', 'Wh/m²', 9999, 0, None, True),
    (15, 'dhi', '水平散射辐射', 'Wh/m²', 9999, 0, None, True),
    (20, 'wind_direction', '风向', '°', 999, 0, 360, True),
    (21, 'wind_speed', '风速', 'm/s', 999, 0, 40, True),
    (23, 'opaque_sky', '不透明云量', '十分量', 99, 0, 10, False),
)


def read_snapshot(path, expected_sha256):
    """Hash exactly the bytes inspected; changed/unbound bytes never get a quality report."""
    p = Path(path)
    try:
        before = p.stat()
        if before.st_size > MAX_BYTES:
            return dict(status='too_large', actual_sha256=None), None
        with p.open('rb') as f:
            raw = f.read(MAX_BYTES + 1)
        after = p.stat()
        actual = hashlib.sha256(raw).hexdigest()
        value = dict(status='matches', actual_sha256=actual, bytes=len(raw))
        if len(raw) > MAX_BYTES:
            value['status'] = 'too_large'
        elif (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            value['status'] = 'changed_during_read'
        elif actual != expected_sha256:
            value['status'] = 'mismatch'
        return value, raw if value['status'] == 'matches' else None
    except FileNotFoundError:
        return dict(status='missing', actual_sha256=None), None
    except OSError:
        return dict(status='unreadable', actual_sha256=None), None


def inspect(raw):
    """Screen one non-leap hourly year. Mixed TMY source years are metadata, not a gap."""
    if len(raw) > MAX_BYTES:
        raise ValueError('单份 EPW 超过 32 MiB 核查上限。')
    issues = {}
    report = dict(scanner=VERSION, sha256=hashlib.sha256(raw).hexdigest(), format_reference=DOC,
                  scope='单数据段、全年 8760 条逐时记录；主要传热气象字段',
                  status='clear', issues=[], fields=[], monthly=[], timeline={}, header={},
                  limits=['未检查太阳时序与经纬度的一致性，不据此排除整小时偏移。',
                          '未评估站点区域代表性、气候归类或观测真实性；既有复核结论继续保留。',
                          '不填补缺测、不调整数值、不重新判定已完成结果；仅检查下表列出的主要字段。'])

    def issue(code, severity, label, record=None, observed=None, count=1, line=None):
        row = issues.setdefault(code, dict(code=code, severity=severity, label=label, count=0, examples=[]))
        row['count'] += count
        if record is not None and len(row['examples']) < 3:
            row['examples'].append(dict(record=record, line=line, observed=str(observed)[:160]))

    def finish():
        report['issues'] = list(issues.values())
        report['status'] = 'issues' if any(i['severity'] == 'error' for i in issues.values()) else 'notes' if issues else 'clear'
        return report

    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        issue('encoding', 'error', '当前核查只支持 UTF-8 或 ASCII 编码')
        return finish()
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        headers = [next(reader) for _ in range(8)]
    except (StopIteration, csv.Error):
        issue('headers', 'error', '缺少完整的 8 行 EPW 表头或 CSV 格式无效')
        return finish()
    for actual, wanted in zip(headers, HEADERS):
        allowed={wanted, 'HOLIDAYS/DAYLIGHT SAVING'} if wanted == 'HOLIDAYS/DAYLIGHT SAVINGS' else {wanted}
        if not actual or actual[0].strip().upper() not in allowed:
            issue('headers', 'error', '表头名称或顺序不符合 EPW 格式')
    h = headers[0]
    if len(h) != 10:
        issue('location', 'error', 'LOCATION 地点表头应有 10 列')
    else:
        report['header'] = dict(zip(('city', 'region', 'country', 'source', 'station', 'latitude', 'longitude', 'timezone', 'elevation'), h[1:]))
        try:
            lat, lon, zone, elev = map(float, h[6:10])
            if not all(map(math.isfinite, (lat, lon, zone, elev))) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and -12 <= zone <= 14 and -1000 <= elev <= 9999):
                raise ValueError()
        except ValueError:
            issue('location', 'error', '地点参数缺失、非有限数值或超出 EPW 范围')
    period = headers[7]
    supported = len(period) == 7 and [v.strip() for v in period[1:3]] == ['1', '1']
    try:
        supported = supported and tuple(int(x) for x in period[5].split('/')) == (1, 1) and tuple(int(x) for x in period[6].split('/')) == (12, 31)
    except (IndexError, ValueError):
        supported = False
    if not supported:
        issue('period', 'error', '当前核查要求单段、每小时一条、1 月 1 日至 12 月 31 日')
    expected = [(d.month, d.day, hour) for day in range(365) for d in [dt.date(2025, 1, 1) + dt.timedelta(days=day)] for hour in range(1, 25)]
    expected_set = set(expected)
    seen, minutes, years = set(), set(), set()
    minute_counts = {}
    rows, duplicates, invalid_time, out_of_sequence = 0, 0, 0, 0
    stats = {key: dict(key=key, label=label, unit=unit, valid=0, missing=0, invalid=0, out_of_range=0, minimum=None, maximum=None)
             for _, key, label, unit, *_ in FIELDS}
    monthly = {m: dict(month=m, hours=calendar.monthrange(2025, m)[1] * 24, dry=[], ghi=[], dni=[], dhi=[]) for m in range(1, 13)}
    ir_fallback = ir_unavailable = 0
    try:
        for row in reader:
            if not row:
                issue('blank', 'warning', '数据区存在空行（未计为小时）')
                continue
            rows += 1
            if rows > 8784:
                issue('record_limit', 'error', '记录超过 8784 条，停止后续扫描；本报告不是完整核查')
                break
            if len(row) != 35:
                issue('columns', 'error', '数据行列数不是 35', rows, len(row), line=reader.line_num)
            stamp = None
            try:
                year, month, day, hour, minute = map(int, row[:5])
                years.add(year); minutes.add(minute)
                minute_counts[minute] = minute_counts.get(minute, 0) + 1
                stamp = (month, day, hour)
                if stamp not in expected_set or not 0 <= minute <= 60:
                    raise ValueError()
                if stamp in seen:
                    duplicates += 1
                seen.add(stamp)
                if rows > 8760 or stamp != expected[rows - 1]:
                    out_of_sequence += 1
                    issue('sequence', 'error', '月日小时与全年顺序不一致', rows, '/'.join(row[:5]), line=reader.line_num)
            except (ValueError, TypeError):
                invalid_time += 1
                issue('time', 'error', '无效月日小时或分钟（当前不支持闰年）', rows, '/'.join(row[:5]), line=reader.line_num)
            values = {}
            states = {}
            for index, key, label, unit, missing, low, high, required in FIELDS:
                stat = stats[key]
                try:
                    val = float(row[index])
                    if not math.isfinite(val):
                        raise ValueError()
                    kind = 'missing' if val >= missing else 'out_of_range' if val < low or (high is not None and val > high) else 'valid'
                except (IndexError, ValueError):
                    val = None
                    kind = 'missing' if len(row) > index and not row[index].strip() else 'invalid'
                stat[kind] += 1
                states[key] = kind
                if kind == 'valid':
                    values[key] = val
                    stat['minimum'] = val if stat['minimum'] is None else min(stat['minimum'], val)
                    stat['maximum'] = val if stat['maximum'] is None else max(stat['maximum'], val)
                elif required or key == 'ghi':
                    severity = 'error' if required and kind != 'out_of_range' else 'warning'
                    label_suffix = dict(missing='缺测', invalid='无法解析为有限数值', out_of_range='超出文档数值范围')[kind]
                    issue(key + '_' + kind, severity, label + label_suffix, rows, row[index] if len(row) > index else '缺列', line=reader.line_num)
            if states['infrared'] == 'missing' and all(k in values for k in ('opaque_sky', 'dry_bulb', 'dew_point')):
                ir_fallback += 1
            elif 'infrared' not in values:
                ir_unavailable += 1
                issue('infrared_unavailable', 'error', '长波辐射异常或缺少补算所需的云量/温度', rows, row[12] if len(row) > 12 else '缺列', line=reader.line_num)
            if stamp in expected_set:
                m = monthly[stamp[0]]
                for field, target in (('dry_bulb', 'dry'), ('ghi', 'ghi'), ('dni', 'dni'), ('dhi', 'dhi')):
                    if field in values:
                        m[target].append(values[field])
    except csv.Error:
        issue('csv', 'error', 'CSV 数据解析中断；本报告不是完整核查')
    if rows != 8760:
        issue('row_count', 'error', '记录数不等于 8760', count=abs(rows - 8760))
    if duplicates:
        issue('duplicates', 'error', '重复的月日小时', count=duplicates)
    if len(seen) < 8760:
        issue('missing_hours', 'error', '缺少的月日小时', count=8760 - len(seen))
    if 0 in minutes:
        issue('minute_zero', 'warning', '存在分钟标记 0，保留原有 CSWD/TMY 兼容解释；不据此平移数据', count=minute_counts[0])
    if minutes - {0, 60} or len(minutes) > 1:
        issue('minute_other', 'warning', '分钟标记不是统一的 0 或 60；需结合来源说明，不能单独推断小时偏移', count=sum(n for m,n in minute_counts.items() if m not in (0,60)) or sum(minute_counts.values()))
    if ir_fallback:
        issue('infrared_fallback', 'warning', '长波辐射缺测，但云量和温度可用于引擎补算；本核查不补写', count=ir_fallback)
    # Sky cover is only needed for the fallback above; do not reject valid measured IR.
    sky_bad = sum(stats['opaque_sky'][k] for k in ('missing', 'invalid', 'out_of_range'))
    if sky_bad:
        issue('opaque_sky_notes', 'warning', '部分不透明云量不可用；长波补算依赖另行逐条检查', count=sky_bad)
    complete = supported and rows == 8760 and not (invalid_time or duplicates or out_of_sequence) and len(seen) == 8760 and not any(k in issues for k in ('headers', 'csv', 'columns'))
    report['timeline'] = dict(records_scanned=rows, expected_records=8760, complete=complete, duplicate_hours=duplicates,
                              missing_hours=8760-len(seen), invalid_time=invalid_time, out_of_sequence=out_of_sequence,
                              minute_markers=sorted(minutes), minute_counts={str(k):v for k,v in sorted(minute_counts.items())}, source_years=sorted(years))
    report['fields'] = list(stats.values())
    report['infrared'] = dict(fallback_hours=ir_fallback, unavailable_hours=ir_unavailable)
    if complete:
        for m in monthly.values():
            vals = m['dry']
            report['monthly'].append(dict(month=m['month'], expected_hours=m['hours'], temperature_hours=len(vals),
                temperature_mean_C=sum(vals)/len(vals) if vals else None,
                temperature_min_C=min(vals) if vals else None, temperature_max_C=max(vals) if vals else None,
                solar={k:dict(valid_hours=len(m[k]), energy_kWh_m2=sum(m[k])/1000 if len(m[k]) == m['hours'] else None) for k in ('ghi', 'dni', 'dhi')}))
    return finish()
