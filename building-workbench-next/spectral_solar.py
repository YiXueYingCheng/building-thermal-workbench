"""Freeze current-step exterior irradiance including EnergyPlus shading and reflections."""
from contextlib import closing
import copy
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from foundation import digest, sha, read_json

SOLAR='Surface Outside Face Incident Solar Radiation Rate per Area'


FACE_WEATHER={'G':SOLAR,'Air':'Surface Outside Face Outdoor Air Drybulb Temperature',
              'Wet':'Surface Outside Face Outdoor Air Wetbulb Temperature','Wind':'Surface Outside Face Outdoor Air Wind Speed'}


def freeze(model,report,reader,engine_files,root):
    material=report.get('material_application',{})
    if material.get('model')!='spectral_exterior_v1':return model,report
    # Solar forcing must be independent of the final skin temperature.
    if model.get('WindowShadingControl') or model.get('WindowMaterial:GlazingGroup:Thermochromic'):
        raise ValueError('温度关联窗遮阳或热致变色系统需先验证逐面日照反馈。')
    probe=copy.deepcopy(model)
    walls=[r['surface'] for r in material['surfaces']]
    wd=report['weather'];weather=Path(reader.check(wd)).resolve()
    engine=next(Path(k) for k in engine_files if Path(k).name.lower()=='energyplus.exe')
    for kind in list(probe):
        if kind.startswith('EnergyManagementSystem:'):
            probe[kind]={k:v for k,v in probe[kind].items() if not k.startswith(('WBSp','WB_','WB spectral','WB Exterior','WB Cover','WB Window','WB Boundary','WB Incident','WB Emitter','wb'))}
            if not probe[kind]:del probe[kind]
    # Keep unrelated model controls and optical properties. The native probe only reads outdoor irradiance.
    for k,v in list(probe.get('SurfaceProperty:HeatBalanceSourceTerm',{}).items()):
        if k.startswith('WBSp'):del probe['SurfaceProperty:HeatBalanceSourceTerm'][k]
    channels=[(wall,variable) for wall in walls for variable in FACE_WEATHER.values()]
    windows=[key for row in material['surfaces'] for key in row['apertures']]
    window_channels=[(w,SOLAR) for w in windows]
    window_channels.extend((w,'Surface Window Transmitted Solar Radiation Rate') for w in windows if model['FenestrationSurface:Detailed'][w]['surface_type'].lower() in ('window','glassdoor'))
    probe['Output:Variable']={f'Weather{i}':dict(key_value=obj,variable_name=var,reporting_frequency='Timestep') for i,(obj,var) in enumerate(channels+window_channels)}
    probe['Output:SQLite']={'WB solar':{'option_type':'Simple'}}
    probe['OutputControl:Files']={'WB solar':{'output_eso':'No','output_mtr':'No','output_sqlite':'Yes','output_csv':'No','output_tabular':'No'}}
    cache=Path(root)/'data/spectral-irradiance'
    cache.mkdir(parents=True,exist_ok=True)
    key=digest(dict(model=probe,weather=wd['sha256'],engine=engine_files,period=report['period'],
                    step=report['step_minutes'],walls=walls,version=2,
                    inputs=[(d['path'],d['sha256']) for d in report.get('dependencies',[])]))
    folder=cache/key
    if not folder.exists():
        with tempfile.TemporaryDirectory(dir=cache,prefix='probe-') as tmp:
            path=Path(tmp)
            (path/'solar.epJSON').write_text(json.dumps(probe,ensure_ascii=True),encoding='ascii')
            result=subprocess.run([str(engine),'-w',str(weather),'-d',str(path),'solar.epJSON'],cwd=path,
                 stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            err=(path/'eplusout.err').read_text(errors='replace') if (path/'eplusout.err').exists() else ''
            if result.returncode or 'EnergyPlus Completed Successfully' not in err:
                raise ValueError('逐面日照预计算失败 '+err[-2000:])
            data=path/'publish'
            data.mkdir()
            with closing(sqlite3.connect(path/'eplusout.sql')) as db:
                save_series(db,data/'irradiance.csv',channels,report['period'],report['step_minutes'])
                apertures=window_signatures(db,window_channels)
            (data/'receipt.json').write_text(json.dumps(dict(columns=channels,apertures=apertures,sha256=sha(data/'irradiance.csv'),identity=key)),encoding='utf8')
            try:data.rename(folder)
            except FileExistsError:pass
    meta=read_json(folder/'receipt.json')
    if meta['identity']!=key or meta['columns']!=[list(x) for x in channels]:raise ValueError('逐面辐射缓存与当前模型不符。')
    ref=dict(path=str(folder/'irradiance.csv'),sha256=meta['sha256'])
    reader.check(ref)
    for index,(wall,var) in enumerate(channels):
        k=f'WBSp{index//len(FACE_WEATHER)}'
        token=next(t for t,n in FACE_WEATHER.items() if n==var)
        name=k+'Forcing'+token
        model.setdefault('Schedule:File',{})[name]=dict(schedule_type_limits_name='WB Spectral Unbounded',
            file_name=ref['path'],column_number=index+1,rows_to_skip_at_top=0,number_of_hours_of_data=8760,
            column_separator='Comma',interpolate_to_timestep='No',minutes_per_item=report['step_minutes'],
            adjust_schedule_for_daylight_savings='No')
        model['EnergyManagementSystem:Sensor'][k+token]=dict(output_variable_or_output_meter_index_key_name=name,output_variable_or_output_meter_name='Schedule Value')
    from spectral_boundary import request
    for wall,var in window_channels:request(model,wall,var)
    report['spectral_solar']=dict(**ref,identity=key,walls=walls,aperture_signatures=meta['apertures'],method='本建筑同气象同时间步原生室外表面入射日照')
    report['dependencies']=[*report.get('dependencies',[]),ref]
    report['generated_model_digest']=digest(model)
    return model,report


def window_signatures(db,channels):
    import hashlib,struct
    items={(w.upper(),v):hashlib.sha256() for w,v in channels}
    for t,k,n,value in db.execute("""SELECT r.TimeIndex,d.KeyValue,d.Name,r.Value FROM ReportData r JOIN ReportDataDictionary d
        USING(ReportDataDictionaryIndex) WHERE d.ReportingFrequency='Zone Timestep' ORDER BY r.TimeIndex"""):
        if (k,n) in items:items[k,n].update(struct.pack('<d',round(value,6)))
    if any(h.digest()==hashlib.sha256().digest() for h in items.values()):raise ValueError('缺少洞口受照或透射值。')
    return {w+'|'+n:h.hexdigest() for (w,n),h in items.items()}


def save_series(db,path,channels,period,minutes):
    keys={(w.upper(),v):i for i,(w,v) in enumerate(channels)}
    n=len(channels)
    query="""SELECT t.Month,t.Day,t.Hour,t.Minute,d.KeyValue,d.Name,r.Value FROM ReportData r
    JOIN Time t USING(TimeIndex) JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
    WHERE d.ReportingFrequency='Zone Timestep' AND COALESCE(t.WarmupFlag,0)=0
    ORDER BY r.TimeIndex"""
    start=dt.date(2001,*period[:2]);end=dt.date(2001,*period[2:])
    with path.open('w',encoding='ascii',newline='') as out:
        prev=-1;values=[None]*n;count=0
        blank=','.join(['0']*n)+'\n'
        for month,day,h,m,key,var,v in db.execute(query):
            if (key,var) not in keys:continue
            date=dt.date(2001,month,day)
            slot=((date-dt.date(2001,1,1)).days*1440+h*60+m)//minutes-1
            if not start<=date<=end or not math.isfinite(v) or (var==SOLAR and v < -1e-5):raise ValueError('逐面太阳辐射日期、数值或构件不符。')
            if slot!=prev:
                if count:
                    if None in values or slot!=prev+1:raise ValueError('逐面日照时序不完整。')
                    out.write(','.join(format(x,'.12g') for x in values)+'\n')
                else:
                    for _ in range(slot):out.write(blank)
                values=[None]*n;prev=slot;count+=1
            i=keys[key,var]
            if values[i] is not None:raise ValueError('同一表面日照时段重复。')
            values[i]=max(0.,v) if var==SOLAR else v
        if count!=(1+(end-start).days)*1440//minutes or None in values:raise ValueError('逐面日照未覆盖计算期。')
        out.write(','.join(format(x,'.12g') for x in values)+'\n')
        for _ in range(prev+1,365*1440//minutes):out.write(blank)
