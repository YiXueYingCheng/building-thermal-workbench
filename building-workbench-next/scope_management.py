"""Reusable scope snapshots; never changes weather, schemes, models or queue state."""
from __future__ import annotations
import copy
import csv
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import uuid
from foundation import ROOT, digest, now, sha
from record_store import Conflict


def registered(catalog):
    return {k:v for k,v in catalog['sites'].items() if v.get('source_kind') in ('reviewed_global','imported_epw_v1','verified_building_project','imported_building') or k in {s['site']['id'] for s in catalog.get('ordinary_buildings',{}).values()}}


def scope_value(value, catalog, allow_empty=False):
    if not isinstance(value,dict):raise ValueError('范围应包含地点和起止月日。')
    ids=value.get('site_ids');period=value.get('period')
    if not isinstance(ids,list) or (not ids and not allow_empty) or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('请选择至少一个地点，地点不能重复。')
    sites=registered(catalog)
    for ident in ids:
        site=sites.get(ident)
        if not site or not site.get('eligible') or not site.get('weather',{}):raise ValueError('地点未接受或暂无可用气象：'+ident)
        if not re.fullmatch('[a-f0-9]{64}',site['weather'].get('sha256','')):raise ValueError('缺少登记的气象标识：'+ident)
    try:
        if not isinstance(period,list) or len(period)!=4 or any(type(x) is not int for x in period):raise ValueError()
        if dt.date(2025,*period[:2])>dt.date(2025,*period[2:]):raise ValueError()
    except (TypeError,ValueError):raise ValueError('起止月日必须属于同一非闰年，结束不能早于开始。') from None
    return dict(site_ids=sorted(ids),period=list(period))


def pins(value,catalog):
    sites=registered(catalog)
    return {i:dict(name=sites[i]['name'],climate=sites[i]['climate'],sha256=sites[i]['weather']['sha256']) for i in value['site_ids']}


def coverage(value,catalog):
    selected=set(value.get('site_ids',[]));sites=list(registered(catalog).values());rows=[]
    for c in catalog['global_bundle']['classes']:
        group=[s for s in sites if s['climate']==c['climate']]
        eligible=[s for s in group if s.get('eligible') and s.get('weather')]
        count=sum(s['id'] in selected for s in eligible)
        rows.append(dict(climate=c['climate'],name=c['name'],selected=count,available=len(eligible),held=len(group)-len(eligible),status='selected' if count else 'not_selected' if eligible else 'unavailable'))
    return rows


def listing(root=ROOT):
    file=Path(root)/'data/scope-library.sqlite'
    if not file.exists():return []
    db=sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)
    try:
        rows=[]
        for ident,revision,name,created,payload,checksum in db.execute('SELECT id,revision,name,created,payload,checksum FROM versions ORDER BY created DESC,id,revision DESC'):
            content=json.loads(payload)
            if digest(content)!=checksum:raise ValueError('范围组合内容校验失败：'+ident)
            rows.append(dict(id=ident,revision=revision,name=name,created=created,**content))
        return rows
    finally:db.close()


def get(root,ref):
    if not isinstance(ref,dict) or not re.fullmatch(r'scope_[a-f0-9]{32}',ref.get('id','')) or type(ref.get('revision')) is not int:
        raise ValueError('请选择明确的范围组合版本。')
    for row in listing(root):
        if row['id']==ref['id'] and row['revision']==ref['revision']:return row
    raise ValueError('没有该范围组合版本。')


def save(root,name,value,catalog,parent=None):
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('范围组合名称应为 1–100 个字符。')
    name=name.strip();scope=scope_value(value,catalog);content=dict(scope=scope,weather=pins(scope,catalog));checksum=digest(content)
    if parent is not None:get(root,parent)
    file=Path(root)/'data/scope-library.sqlite';file.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(file,timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS versions(id TEXT,revision INTEGER,name TEXT,created TEXT,payload TEXT,checksum TEXT,PRIMARY KEY(id,revision))')
        db.execute('BEGIN IMMEDIATE')
        if parent:
            latest=db.execute('SELECT revision,name,checksum FROM versions WHERE id=? ORDER BY revision DESC LIMIT 1',(parent['id'],)).fetchone()
            if not latest or latest[0]!=parent['revision']:raise Conflict('范围组合已有新版本；请重新选择，或另存为新组合。')
            if latest[1:]==(name,checksum):
                db.rollback();return get(root,parent)
            ident=parent['id'];revision=latest[0]+1
        else:
            prior=db.execute('SELECT v.id,v.revision FROM versions v WHERE name=? AND checksum=? AND revision=(SELECT MAX(revision) FROM versions WHERE id=v.id) LIMIT 1',(name,checksum)).fetchone()
            if prior:
                db.rollback();return get(root,dict(id=prior[0],revision=prior[1]))
            ident='scope_'+uuid.uuid4().hex;revision=1
        created=now();db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?)',(ident,revision,name,created,json.dumps(content,ensure_ascii=False,allow_nan=False),checksum));db.commit()
        return dict(id=ident,revision=revision,name=name,created=created,**content)
    finally:db.close()


def preview(root,current,ref,catalog):
    before=scope_value(current,catalog,allow_empty=True);row=get(root,ref)
    after=scope_value(row['scope'],catalog);current_pins=pins(after,catalog)
    changed=[ident for ident in after['site_ids'] if any(current_pins[ident][key]!=row['weather'].get(ident,{}).get(key) for key in ('sha256','climate'))]
    if changed:raise ValueError('登记的气象或气候类型与组合快照不一致，请先核查来源：'+'、'.join(changed))
    # Preserve the current ordering of retained sites; selecting the same set is a no-op.
    after['site_ids']=[i for i in current['site_ids'] if i in after['site_ids']]+[i for i in after['site_ids'] if i not in before['site_ids']]
    return dict(scope=copy.deepcopy(after),reference=dict(id=row['id'],revision=row['revision'],name=row['name']),
        added=sorted(set(after['site_ids'])-set(before['site_ids'])),removed=sorted(set(before['site_ids'])-set(after['site_ids'])),
        period_before=before['period'],period_after=after['period'],coverage=coverage(after,catalog),
        weather_identity='catalog_matches_saved_snapshot',files_checked=False)


def weather_detail(ident,catalog):
    site=registered(catalog).get(ident)
    if site is None:raise ValueError('请选择已登记地点。')
    result=dict(site=copy.deepcopy(site),checked_at=now(),status='unregistered',actual_sha256=None,
        note='本次只核对文件身份及 EPW 地点表头；不重新判定逐时连续性、时间偏移或区域代表性。既有复核说明继续适用。')
    ref=site.get('weather')
    if not ref:return result
    from source_locations import resolve
    actual,location=resolve(ref,catalog)
    if location:result.update(actual_path=actual['path'],relocation=location)
    path=Path(actual['path'])
    try:
        before=path.stat()
        if before.st_size>32*1024*1024:result['status']='too_large';return result
        checksum=sha(path)
        with path.open(encoding='utf-8-sig',errors='replace',newline='') as stream:header=next(csv.reader(stream),[])
        after=path.stat()
        result.update(actual_sha256=checksum,bytes=after.st_size)
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):result['status']='changed_during_read'
        elif checksum!=ref.get('sha256'):result['status']='mismatch'
        else:result['status']='matches'
        if header and header[0]=='LOCATION' and len(header)>=10:
            result['epw_header']=dict(zip(('city','region','country','source','station','latitude','longitude','timezone','elevation'),header[1:10]))
    except FileNotFoundError:result['status']='missing'
    except OSError:result['status']='unreadable'
    return result


def weather_quality_detail(ident,catalog):
    """Audit only registered bytes. Never writes a new review or changes a site."""
    import weather_quality
    site=registered(catalog).get(ident)
    if site is None:raise ValueError('请选择已登记地点。')
    result=dict(site=copy.deepcopy(site),checked_at=now(),status='unregistered',actual_sha256=None,quality=None,
        note='本次只读筛查逐时记录及主要气象字段；与既有复核说明并列保存。不会修正文件、改变地点可用状态或启动计算。')
    ref=site.get('weather')
    if not ref:return result
    from source_locations import resolve
    actual,location=resolve(ref,catalog)
    if location:result.update(actual_path=actual['path'],relocation=location)
    identity,raw=weather_quality.read_snapshot(actual['path'],ref['sha256']);result.update(identity)
    if raw is not None:
        result['quality']=weather_quality.inspect(raw)
        result['epw_header']=result['quality']['header'] or None
    return result
