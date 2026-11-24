"""Read timestep material responses from pinned EnergyPlus results."""
from contextlib import closing
from pathlib import Path
import sqlite3
import numpy as np
from foundation import read_json,sha
from input_pipeline import read_audit
from research_materials import PCM,SPECTRAL,latent
from output_storage import checked_path

INSIDE='Surface Inside Face Conduction Heat Transfer Rate per Area'
OUTSIDE='Surface Outside Face Conduction Heat Transfer Rate per Area'
SOLAR='Surface Outside Face Incident Solar Radiation Rate per Area'
TEMP='Surface Outside Face Temperature'


def summarize(case,app,d,root,with_series=False,aperture_signatures=None):
    if case.get('output_contract')!='timeseries_timestep_v1':
        raise ValueError('材料时段响应需要保留逐步输出。')
    sql=next((checked_path(p,root) for p in case.get('artifacts',{}) if Path(p).name=='eplusout.sql'),None)
    if sql is None or not sql.is_file():raise ValueError('本次逐步结果已移出，请恢复相应计算结果。')
    if sha(sql)!=case['artifacts'][str(sql)]:raise ValueError('逐步结果校验不符。')
    count=case['time_detail']['points_per_series']
    step=case['step_minutes']
    rows=app['surfaces']
    area=sum(w['net_m2'] for w in rows)
    sums={k:np.zeros(count) for k in ('solar','inside','surface','cover','sky','fraction','charging','releasing','warming','cooling')}
    max_solar=max_balance=max_applied=0.
    boundary_checked=0
    aperture_signatures=aperture_signatures or {}
    with closing(sqlite3.connect(sql.as_uri()+'?mode=ro',uri=True)) as db:
        keys={(n.casefold(),k.casefold()):i for i,n,k in db.execute(
            "SELECT ReportDataDictionaryIndex,Name,KeyValue FROM ReportDataDictionary WHERE ReportingFrequency='Zone Timestep'")}
        times=db.execute("SELECT TimeIndex,Month,Day,Hour,Minute FROM Time WHERE IntervalType=-1 AND COALESCE(WarmupFlag,0)=0 ORDER BY TimeIndex").fetchall()
        ids=[t[0] for t in times]
        if len(ids)!=count:raise ValueError('逐步时间轴不完整。')
        db.execute('CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)')
        selected={i for (v,k),i in keys.items() if v in {x.casefold() for x in (INSIDE,OUTSIDE,SOLAR,TEMP,"Surface Window Transmitted Solar Radiation Rate")} or v.startswith(('wb ','condfd surface temperature node ','zone ideal loads zone sensible ')) or (v=='schedule value' and k.startswith('wbsp') and k.endswith('h'))}
        db.executemany('INSERT INTO ids VALUES (?)',[(i,) for i in selected])
        db.execute('CREATE TEMP TABLE samples AS SELECT ReportDataDictionaryIndex AS id,TimeIndex,Value FROM ReportData JOIN ids ON ids.id=ReportDataDictionaryIndex')
        db.execute('CREATE INDEX temp.samples_key ON samples(id,TimeIndex)')
        def values(var,key):
            idx=keys.get((var.casefold(),key.casefold()))
            if idx is None:raise ValueError('缺少逐步物理量 '+key+' '+var)
            data=db.execute('SELECT TimeIndex,Value FROM samples WHERE id=? ORDER BY TimeIndex',(idx,)).fetchall()
            if len(data)!=count or [p[0] for p in data]!=ids:raise ValueError('各材料变量时间轴有缺项。')
            return np.asarray([p[1] for p in data],dtype=float)
        if aperture_signatures:
            import hashlib,struct
            for label,signature in aperture_signatures.items():
                surface,var=label.rsplit('|',1)
                check=hashlib.sha256()
                for v in values(var,surface):check.update(struct.pack('<d',round(float(v),6)))
                if check.hexdigest()!=signature:raise ValueError('洞口受照或透射辐射与原生日照计算不符 '+surface)
        for index,row in enumerate(rows):
            w=row['surface'];weight=row['net_m2']/area
            sun=values(SOLAR,w)
            sums['solar']+=weight*sun
            sums['inside']+=weight*values(INSIDE,w)
            sums['surface']+=weight*values(TEMP,w)
            if d['model']==PCM:
                p=d['phase_change'];n=row['pcm_elements']
                for node in range(1,n+2):
                    v=values(f'CondFD Surface Temperature Node {node}',w)
                    fraction=np.clip((v-p['solidus_C'])/(p['liquidus_C']-p['solidus_C']),0.,1.)
                    wt=weight*(.5 if node in (1,n+1) else 1.)/n
                    change=np.diff(fraction,prepend=fraction[0])
                    sums['fraction']+=wt*fraction
                    sums['charging']+=wt*np.maximum(change,0.)
                    sums['releasing']+=wt*np.maximum(-change,0.)
            else:
                def em(key):return values('WB '+key+' '+w,'EMS')
                max_solar=max(max_solar,float(max(abs(em('Incident Solar')-sun))))
                max_balance=max(max_balance,float(max(abs(em('Cover Balance')))))
                hkey=f'WBSp{index}H'
                if ('schedule value',hkey.casefold()) in keys:
                    boundary_checked+=1
                    actual=em('Boundary Forcing')-values('Schedule Value',hkey)*(values(TEMP,w)-em('Emitter Linearization Temperature'))
                    max_applied=max(max_applied,float(max(abs(actual+values(OUTSIDE,w)))))
                sums['cover']+=weight*(em('Cover Temperature') if d['spectral']['variant']=='covered' else values(TEMP,w))
                sums['sky']+=weight*em('Window Sky Loss')
        for kind,key in [('warming','Heating'),('cooling','Cooling')]:
            name='Zone Ideal Loads Zone Sensible '+key+' Energy'
            for var,obj in keys:
                if var==name.casefold():sums[kind]+=values(name,obj)/3.6e6
    if not all(np.isfinite(x).all() for x in sums.values()):raise ValueError('材料响应出现非有限值。')
    day=sums['solar']>1
    result=dict(area_m2=area,walls=len(rows),openings=sum(len(w['apertures']) for w in rows),
        step_minutes=step,points=count,period=case['period'],loads=case['loads'],model=d['model'],segments={})
    for label,mask in [('day',day),('night',~day),('all',np.ones(count,dtype=bool))]:
        if not mask.any():continue
        r=dict(hours=float(np.sum(mask))*step/60,emitter_C=float(sums['surface'][mask].mean()),
               inward_W_m2=float(sums['inside'][mask].mean()),inward_kWh_m2=float(sums['inside'][mask].sum())*step/60000)
        if d['model']==SPECTRAL:
            r.update(cover_C=float(sums['cover'][mask].mean()),sky_window_W_m2=float(sums['sky'][mask].mean()))
        result['segments'][label]=r
    if d['model']==SPECTRAL:
        result.update(solar_residual_W_m2=max_solar,pe_residual_W_m2=max_balance,applied_boundary_residual_W_m2=max_applied if boundary_checked==len(rows) else None,aperture_series_verified=len(aperture_signatures))
        if max_solar>1.e-5 or max_balance>.01 or max_applied>.01:raise ValueError('逐步受照、PE 热平衡或外墙实际热流未通过，请复核。')
    else:
        s=d['states'][0]
        capacity=latent(d)*s['thickness_mm']/1000*s['density_kg_m3']*area/3.6e6
        active=sums['charging']+sums['releasing']>1.e-7
        result['pcm_daily']=[]
        day_keys=[(t[1],t[2]) for t in times]
        for date in dict.fromkeys(day_keys):
            mask=np.array([value==date for value in day_keys])
            result['pcm_daily'].append(dict(date='%02d-%02d'%date,
                charged_kWh=float(sums['charging'][mask].sum()*capacity),
                released_kWh=float(sums['releasing'][mask].sum()*capacity),
                active_hours=float((mask&active).sum())*step/60 if capacity else 0.))
        result['pcm']=dict(initial_storage_kWh=capacity*sums['fraction'][0],final_storage_kWh=capacity*sums['fraction'][-1],capacity_kWh=capacity,storage_min_kWh=capacity*min(sums['fraction']),
            storage_max_kWh=capacity*max(sums['fraction']),charged_kWh=capacity*sum(sums['charging']),
            released_kWh=capacity*sum(sums['releasing']),active_hours=float(sum(active))*step/60 if capacity else 0.,
            cooling_during_activity_kWh=float(sum(sums['cooling'][active])) if capacity else 0.)
    if with_series:return result,times,sums
    return result


def comparison_response(catalog,root,body):
    from comparison_results import read_sources,compatible,pair_reason
    rel,recs,sources=read_sources(body['id'],body['left_source'],body['right_source'],body['mode'],catalog,root)
    sid=body['site_id']
    issues=compatible(*recs,body['mode'],rel['metric'])
    if issues:raise ValueError('；'.join(issues))
    cases=[s['cases'].get(sid) for s in sources]
    if not all(cases) or pair_reason(*cases):raise ValueError('材料响应需要两侧通过核对的同地点配对结果。')
    out={}
    for label,record,case,source in zip(('left','right'),recs,cases,sources):
        defs=record['factors']['materials']['definitions']
        if len(defs)!=1 or defs[0]['model'] not in (PCM,SPECTRAL):raise ValueError('所选方案缺少材料响应输出。')
        from comparison_results import batch_rows
        import json
        plan=json.loads(batch_rows(root,source['id'])[0]['plan'])
        folder=Path(root)/'data/model-inputs'/plan['bundle_id']
        manifest=read_json(folder/'manifest.json')
        entry=next(r for r in manifest['cases'] if r['site_id']==sid and r['mode']==body['mode'])
        audit=read_audit(folder,entry)
        out[label]=summarize(case,audit['material_application'],defs[0],root,
            aperture_signatures=audit.get('spectral_solar',{}).get('aperture_signatures'))
    return out
