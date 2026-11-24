"""Single-worker, resumable provider downloads with independent quality checks."""
import copy, hashlib, json, re, shutil, threading, uuid
from urllib.parse import urlsplit
from pathlib import Path
from foundation import read_json, write_json, now, sha
from starter_library import bundled_file
import weather_fetch, weather_quality

LOCK=threading.RLock()
ACTIVE={}
CLASSES='Af Am Aw BWh BWk BSh BSk Csa Csb Csc Cwa Cwb Cwc Cfa Cfb Cfc Dsa Dsb Dsc Dsd Dwa Dwb Dwc Dwd Dfa Dfb Dfc Dfd ET EF'.split()


def catalog():
    data=read_json(bundled_file('examples/weather/sources.json'));rows=data['weather']
    groups=[]
    for code in CLASSES:
        candidates=[r['id'] for r in rows if r.get('climate_label_from_historical_table')==code]
        groups.append(dict(climate=code,ids=candidates,default_id=candidates[0] if candidates else None,
            status='historical_label' if candidates else 'missing_verified_source'))
    return dict(rows=rows,climates=groups,china34=[r['id'] for r in rows if r['source_group']=='china34'],
        global30=[g['default_id'] for g in groups if g['default_id']],
        notice='中国按地区列出具体站点；全球沿用历史分类标签，选点代表性需另行核对。Csc 尚缺核对后的下载源。气象从原提供方下载，程序不随包携带 EPW。')


def path(root,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'download_[a-f0-9]{32}',ident):raise ValueError('下载批次编号无效。')
    return Path(root)/'data/weather-downloads'/(ident+'.json')


def status(root,ident):
    with LOCK:
        data=read_json(path(root,ident));active=ACTIVE.get(str(Path(root).resolve()))
        if data['state'] in ('running','cancelling') and (not active or active['id']!=ident or not active['thread'].is_alive()):
            data['state']='interrupted';data['message']='服务已重启，可继续未完成项。'
        return data


def listing(root):
    return sorted([status(root,p.stem) for p in (Path(root)/'data/weather-downloads').glob('download_*.json')],key=lambda x:x['created'],reverse=True)[:20]


def save(root,data):
    data['updated']=now();write_json(path(root,data['id']),data,root)


def output_folder(value):
    if not isinstance(value,str) or not value.strip() or not Path(value).is_absolute():raise ValueError('请选择气象下载文件夹的完整路径。')
    p=Path(value).resolve()
    if p.parent==p:raise ValueError('请选择磁盘下的气象文件夹，不直接使用盘符根目录。')
    if p.exists() and not p.is_dir():raise ValueError('下载位置不是文件夹。')
    return p


def _launch(root,data):
    key=str(Path(root).resolve());active=ACTIVE.get(key)
    if active and active['thread'].is_alive():raise ValueError('已有气象批次正在下载，请先等待或停止。')
    event=threading.Event();thread=threading.Thread(target=_run,args=(Path(root),data['id'],event),daemon=True)
    data['state']='running';data['message']='';data['network_issues']=[];save(root,data)
    ACTIVE[key]=dict(id=data['id'],thread=thread,event=event)
    thread.start()
    return data


def _new_batch(ids,output,rows,**extra):
    if not isinstance(ids,list) or not ids or len(ids)>len(rows) or any(not isinstance(i,str) or i not in rows for i in ids) or len(ids)!=len(set(ids)):raise ValueError('请选择清单中不重复的可下载地点。')
    folder=output_folder(output)
    ancestor=folder
    while not ancestor.exists():ancestor=ancestor.parent
    expected=sum(rows[i]['bytes'] for i in ids)
    if shutil.disk_usage(ancestor).free<expected+100*1024**2:raise ValueError('气象文件夹所在磁盘余量不足，需另选目录。')
    data=dict(id='download_'+uuid.uuid4().hex,created=now(),output=str(folder),expected_bytes=expected,state='pending',
        items=[dict(id=i,name=rows[i]['name'],state='pending',attempts=0,source=copy.deepcopy(rows[i])) for i in ids],**extra)
    return data


def start(root,ids,output):
    rows={r['id']:r for r in catalog()['rows']}
    data=_new_batch(ids,output,rows,kind='primary')
    with LOCK:return _launch(root,data)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def fallback_preview(root,ident):
    with LOCK:
        data=status(root,ident)
        if data['state'] in ('running','cancelling'):raise ValueError('请先等待本批完成或停止，再查看备用来源。')
        if data.get('kind')=='fallback':raise ValueError('备用批次可重试本批来源；其他备用请回原批次查看。')
        originals={r['id']:r for r in catalog()['rows']}
        alternative_data=weather_fetch.alternatives()
        available={r['original_id']:r for r in alternative_data['weather']}
        unavailable={r['original_id']:r['reason'] for r in alternative_data.get('unavailable',[])}
        rows=[]
        for item in data['items']:
            if item['state']=='ready':continue
            source=item.get('source') or originals.get(item['id'])
            alt=available.get(item['id'])
            reason=unavailable.get(item['id'],'此地点尚无已核对的备用来源；可重试原来源或自行导入 EPW。')
            if alt and (not source or alt['original_epw_sha256']!=source['epw_sha256']):
                alt=None;reason='原文件版本与备用核对记录不一致，请重新核对来源。'
            rows.append(dict(id=item['id'],name=item['name'],state=item['state'],original=source,alternative=alt,unavailable_reason='' if alt else reason))
        return dict(batch_id=ident,stamp=_digest([data,alternative_data]),rows=rows,
            notice='备用是另一套气象数据，不是原文件镜像。确认后新建独立下载批次，原批次保留；下载后仍需核对并登记。')


def fallback_start(root,ident,ids,stamp,reviewed=False):
    if reviewed is not True:raise ValueError('请先确认备用来源、年份、坐标与时区差异。')
    with LOCK:
        preview=fallback_preview(root,ident)
        if not isinstance(stamp,str) or stamp!=preview['stamp']:raise ValueError('下载记录或备用清单已经变化，请重新查看并确认。')
        allowed={r['id']:r['alternative'] for r in preview['rows'] if r['alternative']}
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) or i not in allowed for i in ids) or len(set(ids))!=len(ids):raise ValueError('请选择有已核对备用来源的地点。')
        fingerprint=_digest([ident,stamp,sorted(ids)])
        # A repeated confirmation returns the same child, even after it finishes.
        for file in (Path(root)/'data/weather-downloads').glob('download_*.json'):
            old=read_json(file)
            if old.get('confirmation')==fingerprint:return status(root,old['id'])
        parent=status(root,ident);rows={allowed[i]['id']:allowed[i] for i in ids}
        child=_new_batch(list(rows),parent['output'],rows,kind='fallback',parent_batch_id=ident,confirmation=fingerprint)
        for item in child['items']:item['replaces_item_id']=item['source']['original_id']
        return _launch(root,child)


def resume(root,ident):
    with LOCK:
        data=status(root,ident)
        if data['state'] in ('running','cancelling'):raise ValueError('本批仍在执行。')
        for item in data['items']:
            if item['state'] not in ('ready','quality_issues'):item.update(state='pending')
        if not any(i['state']=='pending' for i in data['items']):raise ValueError('没有待重试的下载；质量问题需核对数据源。')
        return _launch(root,data)


def cancel(root,ident):
    with LOCK:
        data=status(root,ident);active=ACTIVE.get(str(Path(root).resolve()))
        if not active or active['id']!=ident or not active['thread'].is_alive():return data
        active['event'].set();data['state']='cancelling';data['message']='完成当前文件检查后停止；已完成项保留。';save(root,data);return data


def _run(root,ident,event):
    try:
        with LOCK:data=read_json(path(root,ident))
        sources={r['id']:r for r in weather_fetch.sources()}
        blocked={};failures={}
        for index,item in enumerate(data['items']):
            if event.is_set():break
            if item['state'] in ('ready','quality_issues'):continue
            source=item.get('source') or sources.get(item['id'])
            host=urlsplit(source['source_url']).hostname if source else None
            if host in blocked:
                item.update(state='pending',error='本来源连接受阻，暂未下载；可重试原来源或查看已核对备用。',error_host=host)
                with LOCK:save(root,data)
                continue
            try:
                if source!=sources.get(item['id']):raise ValueError('来源清单已变化，本批保留旧记录；请重新建立下载批次。')
                for attempt in range(2):
                    with LOCK:
                        item.update(state='downloading',attempts=item['attempts']+1,error=None,error_code=None,error_host=None);save(root,data)
                    try:
                        result=weather_fetch.fetch(item['id'],data['output']);break
                    except weather_fetch.WeatherNetworkError as e:
                        if attempt or not e.retryable or event.is_set():raise
                        with LOCK:
                            item['error']='连接暂时失败，将再尝试一次；不会更换来源。';save(root,data)
                        if event.wait(1):raise
                p=Path(result['path'])
                raw=p.read_bytes()
                import hashlib
                if hashlib.sha256(raw).hexdigest()!=result['sha256']:raise ValueError('下载完成后文件发生变化。')
                quality=weather_quality.inspect(raw)
                failures[host]=0
                with LOCK:item.update(state='quality_issues' if quality['status']=='issues' else 'ready',result=result,quality=quality)
            except Exception as e:
                with LOCK:
                    item.update(state='failed',error=str(e))
                    if isinstance(e,weather_fetch.WeatherNetworkError):
                        item.update(error_code=e.code,error_host=e.host)
                        failures[e.host]=failures.get(e.host,0)+1
                        if e.code in ('proxy_tunnel','tls') or (e.retryable and failures[e.host]>=2):
                            blocked[e.host]=str(e)
                            data['network_issues']=[dict(host=h,message=message) for h,message in blocked.items()]
            with LOCK:
                if event.is_set():data['state']='cancelling'
                save(root,data)
        with LOCK:
            data['state']='cancelled' if event.is_set() else ('connection_blocked' if blocked else ('completed_with_issues' if any(i['state'] in ('failed','quality_issues') for i in data['items']) else 'completed'))
            if blocked:data['message']='部分气象来源连接受阻，该来源余下项目保留待处理，其他来源继续。可重试本批来源，或为失败地点选择已核对备用；已完成项保留。'
            save(root,data)
    except Exception as e:
        with LOCK:
            data=read_json(path(root,ident));data.update(state='failed',message=str(e));save(root,data)


def register(root,ident,ids,catalog_data,reviewed=False,storage_mode='copy'):
    if reviewed is not True:raise ValueError('请先核对下载后的地点、来源和质量提示。')
    data=status(root,ident)
    if data['state'] in ('running','cancelling'):raise ValueError('请待批次停止后登记，避免与下载写入并发。')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):raise ValueError('请选择需要登记的地点。')
    sources={r['id']:r for r in weather_fetch.sources()};ready={r['id']:r for r in data['items'] if r['state']=='ready'}
    if not set(ids)<=set(ready):raise ValueError('只有取得完整文件且通过主要逐时检查的地点可以登记。')
    import weather_import
    results=[]
    for key in ids:
        row=ready[key];source=row.get('source') or sources[key]
        # Classification remains explicitly historical in the note, not promoted to a verified class.
        note='来源：'+source['source_url']+'；数据集：'+source['dataset']+'；'+source.get('period','')+'。历史分类：'+source.get('climate_label_from_historical_table','未指定')+'；未进行选点代表性复核。'
        if data.get('kind')=='fallback':note+=' 已确认的备用数据，非原 TMYx 文件；原地点编号：'+source['original_id']+'。'+source.get('note','')
        try:
            result=weather_import.register(root,row['result']['path'],row['result']['sha256'],dict(reviewed=True,name=source['name'],note=note[:1000],storage_mode=storage_mode),catalog_data)
            results.append(dict(id=key,status='registered',registration_id=result['registration']['id'],reused=result['reused']))
        except (ValueError,OSError) as e:results.append(dict(id=key,status='failed',error=str(e)))
    return dict(items=results,note='已登记地点可在范围中选择；没有改变任何方案或启动计算。')
