"""Screen complete consecutive weather warmup days without changing engine decisions."""
import json
import math
from pathlib import Path
from statistics import median

import output_storage
from foundation import read_json, owned

WINDOW = 20
MIN_DAYS = 10
TAIL_BYTES = 2 * 1024 * 1024
MEASURES = {'Min Temp': (0, '最低温'), 'Max Temp': (1, '最高温')}


def classify(values, tolerance):
    changes = [b - a for a, b in zip(values, values[1:])]
    magnitudes = list(map(abs, changes))
    two_days = [abs(b - a) for a, b in zip(values, values[2:])]
    kind = 'unclear'
    if len(values) >= MIN_DAYS and magnitudes[-1] > tolerance:
        alternating = all(a*b < 0 for a, b in zip(changes, changes[1:]))
        typical = median(magnitudes)
        if (alternating and min(magnitudes) > tolerance and
                max(magnitudes) - min(magnitudes) <= .1 * typical and
                max(two_days) <= .1 * min(tolerance, typical)):
            kind = 'period_two'
        else:
            # Require a sustained reduction across three equal-sized segments.
            third = len(changes) // 3
            early = median(magnitudes[:third])
            middle = median(magnitudes[third:-third])
            late = median(magnitudes[-third:])
            consistent = alternating or all(x > 0 for x in changes) or all(x < 0 for x in changes)
            if consistent and late < middle < early and late <= .8 * early and magnitudes[-1] < magnitudes[0]:
                kind = 'shrinking'
    return dict(kind=kind, previous=values[-2], latest=values[-1], delta=magnitudes[-1],
                max_two_day_delta=max(two_days) if two_days else None)


def tail(path):
    # Read complete lines only, including while the engine appends today's line.
    with path.open('rb') as stream:
        end = stream.seek(0, 2)
        start = max(0, end - TAIL_BYTES)
        stream.seek(start)
        if start:
            stream.readline(TAIL_BYTES)
        lines = stream.read(max(0, end-stream.tell())).split(b'\n')[:-1]
    records = [json.loads(line) for line in lines[-(WINDOW+1):]]
    ended = bool(records and 'ended' in records[-1])
    if ended:
        end_env = records.pop()['ended']
        if records and records[-1].get('env') != end_env:
            raise ValueError('预热环境不一致')
    days = []
    for row in reversed(records):
        if 'rooms' not in row:
            break
        if days and (row['env'] != days[-1]['env'] or row['day'] != days[-1]['day']-1
                     or row['steps'] != days[-1]['steps']):
            break
        days.append(row)
        if len(days) == WINDOW:
            break
    return days[::-1], ended


def screen(folder, checks=None):
    """With checks, only diagnose the exact failed metric reported by the engine."""
    result = dict(rows=[], note='', live=checks is None)
    missing = '缺少可核对的逐预热日室温记录，无法判断趋势。可用本版按原条件为该地点重新生成输入、计算。'
    try:
        case = read_json(owned(folder/'launch.json', folder))['case']
        settings = case.get('warmup_observer')
        if not settings:
            return dict(result, note=missing)
        days, ended = tail(owned(folder/'warmup.jsonl', folder))
        if len(days) < 2:
            return dict(result, note='目前不足两个完整预热日，尚不能计算相邻日温差。')
        first, last = days[0], days[-1]
        step = 60 / last['steps']
        tolerance = float(settings['tolerance'])
        if not (step == case['step_minutes'] and math.isfinite(tolerance) and tolerance > 0):
            return dict(result, note='记录的步长或温度限值与算例不符，无法判断趋势。')
        result.update(first=first['day'], last=last['day'], step=step, ended=ended,
                      minimum_days=settings.get('minimum_days', 6))
        candidates = checks if checks is not None else (
            dict(zone=z, measure=m, tolerance=tolerance) for z in last['rooms'] for m in MEASURES)
        unavailable = 0
        for check in candidates:
            measure = check['measure']
            if measure not in MEASURES:
                continue
            zone = check['zone'].upper()
            column, label = MEASURES[measure]
            values = [r['rooms'].get(zone, [None, None])[column] for r in days]
            if not all(type(v) in (float,int) and math.isfinite(v) for v in values):
                unavailable += 1
                continue
            stats = classify(values, tolerance)
            if checks is None:
                if stats['delta'] <= tolerance:
                    continue
            elif not (check.get('environment_kind') == 'RunPeriod' and
                    check.get('environment', '').upper() == settings['environment'].upper() and
                    check['days'] == last['day'] and math.isclose(check['tolerance'], tolerance, rel_tol=1e-5) and
                    math.isclose(check['value'], stats['delta'], rel_tol=1e-5, abs_tol=1e-6)):
                unavailable += 1
                continue
            result['rows'].append(dict(stats, zone=check['zone'], label=label, tolerance=tolerance))
        result['rows'].sort(key=lambda r: (('period_two','shrinking','unclear').index(r['kind']), -r['delta']))
        if unavailable:
            result['note'] = f'{unavailable} 项缺少完整日序列或与原日志不符，趋势待定。'
        elif not result['rows']:
            result['note'] = ('最近两天各房间最高温和最低温的温差均在限值内。' if checks is None else
                              '引擎未报告可用于温度趋势判断的失败项，请查看原日志中的负荷等检查项。')
        return result
    except FileNotFoundError:
        return dict(result, note=missing if checks is not None else '尚无完整预热日记录。')
    except (OSError, ValueError, TypeError, KeyError, IndexError, ArithmeticError):
        return dict(result, rows=[], note='逐预热日记录无法完整读取，趋势待定。')


def case_view(root, batch, index):
    from warmup_review import source
    from execution_failure_view import describe
    _, job = source(root, batch, index)
    if job['status'] == 'failed':
        info = describe(job, root) or {}
        return info.get('warmup_trend') or dict(rows=[], note='请查看本次引擎错误记录。')
    if job['status'] == 'running':
        return screen(output_storage.attempt_folder(root, job['attempt']))
    return dict(rows=[], note='本次计算已结束，可在结果明细查看核验状态。')
