"""Explicit output-only resolutions. Existing summary contracts stay unchanged."""
import datetime as dt
import math

CONTRACTS = {'timeseries_daily_v1': ('Daily', 2, '逐日'),
             'timeseries_hourly_v1': ('Hourly', 1, '逐时'),
             'timeseries_timestep_v1': ('Timestep', -1, '逐步')}


def days(period):
    return (dt.date(2025, *period[2:])-dt.date(2025, *period[:2])).days+1


def validate(record, contract):
    if contract not in CONTRACTS:
        raise ValueError('不支持的结果输出类型。')
    if contract == 'timeseries_timestep_v1' and days(record['factors']['scope']['period']) > 31:
        raise ValueError('逐步输出用于连续不超过 31 天的短算例；较长时段请选择逐时或逐日。')


def prepare(original, contract):
    from execution_inputs import compact_model
    model = compact_model(original)
    frequency = CONTRACTS[contract][0]
    # Each retained variable/object keeps its existing semantics. All resolutions
    # retain monthly and run-period reports for old comparisons and exports.
    for name, row in list(model['Output:Variable'].items()):
        if row['reporting_frequency'] == 'Monthly':
            model['Output:Variable'][name+'_Detail'] = {**row, 'reporting_frequency': frequency}
    return model


def description(contract, period, step):
    count = days(period)
    monthly = period[2]-period[0]+1
    if contract not in CONTRACTS:
        return dict(label='逐日参考' if contract=='daily_sensible_reference_v1' else '月度',
                    points_per_series=count if contract=='daily_sensible_reference_v1' else monthly,
                    additional_points_per_series=count if contract=='daily_sensible_reference_v1' else 0,
                    note='保留月度与整个计算时段汇总。')
    frequency, _, label = CONTRACTS[contract]
    points = count * (1440//step if frequency=='Timestep' else 24 if frequency=='Hourly' else 1)
    return dict(label=label, points_per_series=points, additional_points_per_series=points,
                summary_points_per_series=monthly+1,
                note='时间点数按每个变量、每个对象计算，再乘房间／系统／表面及算例数量；不是文件大小估计。保留月度与整个时段汇总。')


def verify(db, case, model):
    """Bounded SQL aggregates, not a Python copy of the full time series."""
    contract = case['output_contract']
    frequency, interval_type, _ = CONTRACTS[contract]
    sql_frequency = 'Zone Timestep' if frequency=='Timestep' else frequency
    minutes = case['step_minutes'] if interval_type==-1 else 60 if interval_type==1 else 1440
    n = days(case['period'])*1440//minutes
    def require(ok, message):
        if not ok: raise ValueError(message)
    coverage = [dict(r) for r in db.execute('''SELECT SimulationDays,Month,Day,COUNT(*) n,
        COUNT(DISTINCT Hour*60+Minute) slots,MIN(Hour*60+Minute) first,MAX(Hour*60+Minute) last,
        SUM(CASE WHEN Hour IS NULL OR Minute IS NULL OR Minute<0 OR Minute>=60
        OR (Hour*60+Minute)%?<>0 OR Interval<>? THEN 1 ELSE 0 END) invalid
        FROM Time WHERE IntervalType=? AND COALESCE(WarmupFlag,0)=0 GROUP BY SimulationDays,Month,Day''',
        (minutes,minutes,interval_type))]
    origin=dt.date(2025,*case['period'][:2]);count=days(case['period'])
    require(len(coverage)==count and {r['SimulationDays'] for r in coverage}==set(range(1,count+1)),
            '明细日期覆盖不完整或重复。')
    for row in coverage:
        date=origin+dt.timedelta(days=row['SimulationDays']-1)
        require((row['Month'],row['Day'])==(date.month,date.day) and row['n']==row['slots']==1440//minutes
                and row['first']==minutes and row['last']==1440 and row['invalid']==0,
                '明细日期或区间结束时刻不一致。')
    dictionary = [dict(r) for r in db.execute('SELECT * FROM ReportDataDictionary WHERE ReportingFrequency=?', (sql_frequency,))]
    require(bool(dictionary), '缺少所选频率的时序输出。')
    keys = {(r['KeyValue'].upper(),r['Name']) for r in dictionary if not r['IsMeter']}
    require(len(keys)==len(dictionary), '明细变量／对象重复或包含非预期表计。')
    for kind, name in [('Zone','Zone Mean Air Temperature'),('Zone','Zone Operative Temperature'),
                       ('ZoneHVAC:IdealLoadsAirSystem','Zone Ideal Loads Zone Sensible Heating Energy'),
                       ('ZoneHVAC:IdealLoadsAirSystem','Zone Ideal Loads Zone Sensible Cooling Energy')]:
        require(all((k.upper(),name) in keys for k in model.get(kind,{})), '明细缺少房间温度或冷热需求输出。')
    grouped={}
    for part in db.execute('''SELECT r.ReportDataDictionaryIndex,t.Month, COUNT(*) n,COUNT(DISTINCT r.TimeIndex) unique_n,
            MIN(t.Interval) min_interval, MAX(t.Interval) max_interval,
            MIN(r.Value) minimum,MAX(r.Value) maximum,
            SUM(CASE WHEN r.Value IS NULL OR ABS(r.Value)>1e300 THEN 1 ELSE 0 END) invalid,
            SUM(r.Value) total,SUM(r.Value*t.Interval)/SUM(t.Interval) average
            FROM ReportData r JOIN Time t USING(TimeIndex) JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            WHERE d.ReportingFrequency=? AND t.IntervalType=? AND COALESCE(t.WarmupFlag,0)=0
            GROUP BY r.ReportDataDictionaryIndex,t.Month''',(sql_frequency,interval_type)):
        grouped.setdefault(part['ReportDataDictionaryIndex'],[]).append(dict(part))
    summaries={}
    for row in db.execute('''SELECT d.Name,d.KeyValue,d.Units,d.Type,t.Month,r.Value FROM ReportData r
            JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
            WHERE d.ReportingFrequency='Monthly' AND COALESCE(t.WarmupFlag,0)=0'''):
        key=(row['Name'],row['KeyValue'],row['Units'],row['Type'])
        monthly=summaries.setdefault(key,{})
        require(row['Month'] not in monthly, '月度输出重复。')
        monthly[row['Month']]=row['Value']
    for row in dictionary:
        require(row['Type'] in ('Avg','Sum'), '明细统计方式不受支持。')
        parts=grouped.get(row['ReportDataDictionaryIndex'],[])
        require(sum(p['n'] for p in parts)==n and all(p['unique_n']==p['n'] and p['invalid']==0 and
                p['min_interval']==p['max_interval']==minutes for p in parts), '明细时间覆盖不完整、重复或含无效数值。')
        if row['Name'] in ('Zone Ideal Loads Zone Sensible Heating Energy','Zone Ideal Loads Zone Sensible Cooling Energy'):
            require(row['Type']=='Sum' and row['Units']=='J' and all(p['minimum']>=0 for p in parts),
                    '明细冷热需求单位、类型或符号不符。')
        monthly=summaries.get((row['Name'],row['KeyValue'],row['Units'],row['Type']),{})
        require(set(monthly)=={p['Month'] for p in parts}, '明细缺少对应月度汇总。')
        for part in parts:
            value=part['total' if row['Type']=='Sum' else 'average']
            require(math.isfinite(value) and math.isclose(value,monthly[part['Month']],rel_tol=1e-7,abs_tol=1e-6), '明细与月度汇总不一致。')
    return dict(frequency=sql_frequency, points_per_series=n, series_count=len(dictionary), monthly_reconciliation=True)
