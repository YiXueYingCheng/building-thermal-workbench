"""Single-worker, resumable provider downloads with independent quality checks."""
import copy, re, shutil, threading, uuid
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
    data['state']='running';save(root,data)
    ACTIVE[key]=dict(id=data['id'],thread=thread,event=event)
    thread.start()
    return data


def start(root,ids,output):
    rows={r['id']:r for r in catalog()['rows']}
    if not isinstance(ids,list) or not ids or len(ids)>len(rows) or any(not isinstance(i,str) or i not in rows for i in ids) or len(ids)!=len(set(ids)):raise ValueError('请选择清单中不重复的可下载地点。')
    folder=output_folder(output)
    ancestor=folder
    while not ancestor.exists():ancestor=ancestor.parent
    expected=sum(rows[i]['bytes'] for i in ids)
    if shutil.disk_usage(ancestor).free<expected+100*1024**2:raise ValueError('气象文件夹所在磁盘余量不足，需另选目录。')
    data=dict(id='download_'+uuid.uuid4().hex,created=now(),output=str(folder),expected_bytes=expected,state='pending',
        items=[dict(id=i,name=rows[i]['name'],state='pending',attempts=0) for i in ids])
    with LOCK:return _launch(root,data)


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
        for index,item in enumerate(data['items']):
            if event.is_set():break
            if item['state'] in ('ready','quality_issues'):continue
            with LOCK:
                item.update(state='downloading',attempts=item['attempts']+1,error=None);save(root,data)
            try:
                result=weather_fetch.fetch(item['id'],data['output']);p=Path(result['path'])
                raw=p.read_bytes()
                import hashlib
                if hashlib.sha256(raw).hexdigest()!=result['sha256']:raise ValueError('下载完成后文件发生变化。')
                quality=weather_quality.inspect(raw)
                with LOCK:item.update(state='quality_issues' if quality['status']=='issues' else 'ready',result=result,quality=quality)
            except Exception as e:
                with LOCK:item.update(state='failed',error=str(e))
            with LOCK:
                if event.is_set():data['state']='cancelling'
                save(root,data)
        with LOCK:
            data['state']='cancelled' if event.is_set() else ('completed_with_issues' if any(i['state'] in ('failed','quality_issues') for i in data['items']) else 'completed')
            save(root,data)
    except Exception as e:
        with LOCK:
            data=read_json(path(root,ident));data.update(state='failed',message=str(e));save(root,data)


def register(root,ident,ids,catalog_data,reviewed=False):
    if reviewed is not True:raise ValueError('请先核对下载后的地点、来源和质量提示。')
    data=status(root,ident)
    if data['state'] in ('running','cancelling'):raise ValueError('请待批次停止后登记，避免与下载写入并发。')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):raise ValueError('请选择需要登记的地点。')
    sources={r['id']:r for r in catalog()['rows']};ready={r['id']:r for r in data['items'] if r['state']=='ready'}
    if not set(ids)<=set(ready):raise ValueError('只有取得完整文件且通过主要逐时检查的地点可以登记。')
    import weather_import
    results=[]
    for key in ids:
        row=ready[key];source=sources[key]
        # Classification remains explicitly historical in the note, not promoted to a verified class.
        note='来源：'+source['source_url']+'；数据集：'+source['dataset']+'；'+source.get('period','')+'。历史分类：'+source.get('climate_label_from_historical_table','未指定')+'；未进行选点代表性复核。'
        try:
            result=weather_import.register(root,row['result']['path'],row['result']['sha256'],dict(reviewed=True,name=source['name'],note=note[:1000]),catalog_data)
            results.append(dict(id=key,status='registered',registration_id=result['registration']['id'],reused=result['reused']))
        except (ValueError,OSError) as e:results.append(dict(id=key,status='failed',error=str(e)))
    return dict(items=results,note='已登记地点可在范围中选择；没有改变任何方案或启动计算。')
