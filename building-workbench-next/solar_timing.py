"""Read-only solar timing clues. Never recommends a file shift or grants acceptance."""
import csv,io,math
import numpy as np
import weather_quality
from foundation import now

VERSION='solar-timing-clues-v1'
NOAA='https://gml.noaa.gov/grad/solcalc/solareqns.PDF'
EPW='https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html'


def cosine(days,hours,latitude,longitude,timezone):
    """NOAA fractional-year approximation; local standard clock, no DST."""
    g=2*np.pi/365*(np.asarray(days)-1+(np.asarray(hours)-12)/24)
    e=229.18*(.000075+.001868*np.cos(g)-.032077*np.sin(g)-.014615*np.cos(2*g)-.040849*np.sin(2*g))
    dec=.006918-.399912*np.cos(g)+.070257*np.sin(g)-.006758*np.cos(2*g)+.000907*np.sin(2*g)-.002697*np.cos(3*g)+.00148*np.sin(3*g)
    ha=np.deg2rad((np.asarray(hours)*60+e+4*longitude-60*timezone)/4-180)
    lat=math.radians(latitude)
    return np.sin(lat)*np.sin(dec)+np.cos(lat)*np.cos(dec)*np.cos(ha)


def geometry(days,hours,latitude,longitude,timezone,shift=0):
    # Midpoints of twelve five-minute bins over the preceding EPW hour.
    points=cosine(np.asarray(days)[:,None],np.asarray(hours)[:,None]-1+((np.arange(12)+.5)/12)+shift,latitude,longitude,timezone)
    return np.maximum(points,0).mean(axis=1),points.max(axis=1)


def inspect(raw,basic=None):
    q=basic or weather_quality.inspect(raw)
    out=dict(scanner=VERSION,sha256=q['sha256'],checked_at=now(),status='insufficient',message='时间序列或太阳辐射数据不足，未判断偏移。',
             clock='全年非闰典型年；EPW 第 h 小时按当地标准时 h−1 至 h 处理。统一分钟 0/60 不单独作为偏移证据；不应用夏令时或真实来源年份。',
             method='以 (GHI−DHI)/DNI 对照每小时 12 点太阳天顶角余弦均值；固定同一组较强直射样本，比较 −3 至 +3 小时（0.25 h 间隔）的几何时刻。',
             limits=['这是几何一致性线索，不是辐射真实性或建筑结果验收。','云量变化、辐射分解算法、小时平均方法和太阳位置近似都会影响拟合；最小误差位置不是修正建议。','经度偏离时区中央经线可合法存在；高纬低太阳角或样本少时保留证据不足。','筛查不改气象、不改变地点可用性或既有复核、不启动模拟。'],
             thresholds=dict(dni_min=100,beam_horizontal_min=50,base_cosine_min=.15,annual_samples_min=300,monthly_samples_min=30,shift_clue_min_hours=.5,relative_gain_min=.25,absolute_gain_min=.02,best_error_max=.08,consistent_months_min=6,night_solar_depression_deg=6,night_ghi_min=10,night_hours_min=24,night_energy_fraction_min=.01),references=[NOAA,EPW],monthly=[],fit=None,night=None)
    if not q['timeline'].get('complete') or q['timeline'].get('minute_markers') not in ([0],[60]):return out
    try:
        h=q['header'];lat,lon,tz=(float(h[k]) for k in ('latitude','longitude','timezone'))
        if not all(math.isfinite(v) for v in (lat,lon,tz)) or not(-90<=lat<=90 and -180<=lon<=180 and -12<=tz<=14):return out
        rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))[8:];rows=[r for r in rows if r]
        arr=np.array([[float(r[i]) for i in (1,13,14,15)] for r in rows]);months=arr[:,0];ghi,dni,dhi=arr[:,1:].T
    except (ValueError,KeyError,UnicodeError):return out
    valid=np.isfinite(arr[:,1:]).all(axis=1)&(arr[:,1:]>=0).all(axis=1)&(arr[:,1:]<9999).all(axis=1)
    days=np.repeat(np.arange(1,366),24);hours=np.tile(np.arange(1,25),365)
    base,maximum=geometry(days,hours,lat,lon,tz)
    obs=np.divide(ghi-dhi,dni,out=np.zeros(8760),where=dni>0)
    mask=valid&(dni>=100)&((ghi-dhi)>=50)&(obs>=.1)&(obs<=1.05)&(base>=.15)
    shifts=np.arange(-3,3.001,.25);errors=np.array([np.abs(obs-geometry(days,hours,lat,lon,tz,float(s))[0]) for s in shifts])
    def fit(which,minimum):
        n=int(which.sum())
        if n<minimum:return dict(samples=n,sufficient=False)
        scores=np.median(errors[:,which],axis=1);best=int(np.argmin(scores));zero=float(scores[12]);err=float(scores[best])
        return dict(samples=n,sufficient=True,best_geometry_offset_hours=float(shifts[best]),zero_error=round(zero,5),best_error=round(err,5),absolute_gain=round(zero-err,5),relative_gain=round((zero-err)/zero,4) if zero>0 else 0,search_edge=best in (0,len(shifts)-1))
    annual=fit(mask,300);out['fit']=annual
    out['monthly']=[dict(month=m,**fit(mask&(months==m),30)) for m in range(1,13)]
    night=valid&(maximum<math.sin(math.radians(-6)))
    positive=night&(ghi>10);energy=float(ghi[positive].sum());total=float(ghi[valid].sum());fraction=energy/total if total>0 else None
    night_clue=bool(positive.sum()>=24 and fraction is not None and fraction>=.01)
    out['night']=dict(hours=int(positive.sum()),energy_kWh_m2=round(energy/1000,3),fraction=round(fraction,6) if fraction is not None else None,clue=night_clue)
    out['valid_solar_hours']=int(valid.sum());out['central_meridian_offset_hours']=round(lon/15-tz,3)
    timing=False
    if annual['sufficient']:
        off=annual['best_geometry_offset_hours']
        consistent=[m['month'] for m in out['monthly'] if m['sufficient'] and abs(m['best_geometry_offset_hours']-off)<=.25 and abs(m['best_geometry_offset_hours'])>=.5 and m['absolute_gain']>=.02 and m['relative_gain']>=.25 and m['best_error']<=.08]
        annual['consistent_months']=consistent
        timing=abs(off)>=.5 and annual['relative_gain']>=.25 and annual['absolute_gain']>=.02 and annual['best_error']<=.08 and len(consistent)>=6
    if timing and abs(annual['best_geometry_offset_hours'])==.5 and not night_clue:
        out.update(status='component_convention',message='辐射分量比例更接近小时边界几何；需区分分量计算时刻与整份气象错时，不能直接平移数据。')
    elif timing or night_clue:out.update(status='review',message='发现值得查看的太阳时序线索；需结合来源说明核实，不能直接据此平移气象。')
    elif annual['sufficient'] and annual['best_error']<=.08:out.update(status='no_strong_clue',message='本次筛查未发现稳定的明显时序线索；不等于已排除所有偏移。')
    else:out['message']='辐射分量与几何拟合不足以判断时序；保留指标，需结合来源说明。'
    out['timing_clue']=bool(timing)
    return out


def detail(ident,catalog):
    from scope_management import weather_detail
    from source_locations import resolve
    r=weather_detail(ident,catalog);r['solar_screen']=None
    if r['status']!='matches':return r
    ref,_=resolve(r['site']['weather'],catalog)
    identity,raw=weather_quality.read_snapshot(ref['path'],r['site']['weather']['sha256']);r.update(identity)
    if raw is not None:r['solar_screen']=inspect(raw)
    r['note']='上方保留登记身份和原来源说明；太阳时序线索另列于下方。本次检查不改变已登记状态或既有结论。'
    return r
