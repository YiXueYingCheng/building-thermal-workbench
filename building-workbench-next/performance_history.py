"""Reconstruct observed concurrency from completed attempts; never dispatch work."""
import datetime as dt
import json
import math
from pathlib import Path
import re
from foundation import ROOT, read_json, sha, digest, owned, now
import output_storage
from calculation_budget import queue_snapshot, verified_result, retained_bytes
from review_evidence import reviewed


def instant(value):
    d=dt.datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None:raise ValueError('运行记录缺少时区')
    return d.timestamp()


def overlap(rows):
    """Half-open intervals: a finish/start at the same instant is not overlap."""
    if not rows:return None
    events={}
    for r in rows:
        a,b=r['start_seconds'],r['finish_seconds']
        if not all(math.isfinite(x) for x in (a,b)) or b<=a:raise ValueError('运行起止时刻无效')
        events[a]=events.get(a,0)+1;events[b]=events.get(b,0)-1
    levels={};gaps=[];active=0;previous=None
    for stamp,delta in sorted(events.items()):
        if previous is not None and stamp>previous:
            seconds=stamp-previous;levels[active]=levels.get(active,0)+seconds
            if active==0:gaps.append(dict(start=previous,end=stamp,seconds=seconds))
        active+=delta;previous=stamp
    busy=sum(v for k,v in levels.items() if k>0)
    total=sum(levels.values());occupied=sum(k*v for k,v in levels.items())
    assert active==0 and busy>0
    return dict(first=min(events),last=max(events),span_seconds=total,busy_seconds=busy,
        gap_seconds=levels.get(0,0),occupied_lane_seconds=occupied,
        average_parallel_when_busy=occupied/busy,peak_parallel=max(levels),
        completed_cases_per_busy_hour=len(rows)*3600/busy,
        completed_cases_per_span_hour=len(rows)*3600/total,
        concurrency_seconds=[dict(parallel=k,seconds=v) for k,v in sorted(levels.items())],
        largest_gaps=sorted(gaps,key=lambda g:g['seconds'],reverse=True)[:5])


def attempt(root,job,plan):
    c=plan['cases'][job['idx']]
    if c['index']!=job['idx'] or c['identity']!=job['identity']:raise ValueError('清单与任务身份不一致')
    r=verified_result(root,job['result'],job['result_sha256'],job['identity'])
    reviewed(r,root)
    ident=r['attempt']
    if not re.fullmatch(r'attempt_[a-f0-9]{32}',ident):raise ValueError('原始执行编号无效')
    if job['attempt']!=ident:raise ValueError('结果不属于当前任务的原始执行')
    folder=output_storage.attempt_folder(root,ident)
    source={}
    def get(name):
        p=folder/name;h=sha(p);value=read_json(p)
        if sha(p)!=h:raise ValueError('读取期间运行日志变化')
        source[str(p)]=h;return value
    launch=get('launch.json');execution=get('execution.json')
    if launch['batch']!=job['batch'] or launch['case']!=c:raise ValueError('启动日志与冻结算例不一致')
    if launch['pid']!=execution['pid'] or execution['returncode']!=0:raise ValueError('进程或结束状态不一致')
    for k in ('elapsed_seconds','peak_gib'):
        v=execution[k]
        if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or v<0 or v!=r[k]:raise ValueError('运行实测与结果汇总不一致')
    if execution['elapsed_seconds']<=0:raise ValueError('算例耗时无效')
    if launch['resources']!=execution['resources']:raise ValueError('启动与结束的资源设置记录不一致')
    model=str(folder/'model.epJSON')
    if r['artifacts'].get(model)!=c['model_sha256'] or sha(model)!=c['model_sha256']:raise ValueError('原始模型不能与清单核对')
    start,end=instant(launch['started']),instant(execution['finished'])
    # Timestamps have one-second precision; elapsed is monotonic. Reject clock
    # jumps / inconsistent logs rather than turning them into parallel speedups.
    if end<=start or abs(end-start-execution['elapsed_seconds'])>3:raise ValueError('墙钟起止与单调计时不一致，需复核时间记录')
    source[job['result']]=job['result_sha256']
    return dict(attempt=ident,index=c['index'],site_id=c['site_id'],city=c['city'],mode=c['mode'],
        step_minutes=c['step_minutes'],period=c['period'],identity=c['identity'],status=job['status'],
        started=launch['started'],finished=execution['finished'],start_seconds=start,finish_seconds=end,
        elapsed_seconds=execution['elapsed_seconds'],peak_gib=execution['peak_gib'],
        retained_bytes=retained_bytes(root,job['result'],r),resources=execution['resources'],source_sha256=source)


def build(root=ROOT):
    root=Path(root).resolve();state=queue_snapshot(root);batches=[];source={}
    for b in state['batches']:
        plan=json.loads(b['plan']);rows=[];issues=[];excluded={};seen=set()
        p=owned(root/'data/execution/reviews'/b['review']/'plan.json',root)
        try:
            if sha(p)!=b['checksum'] or read_json(p)!=plan:raise ValueError('冻结清单校验不符')
            source[str(p)]=b['checksum'];plan_ok=True
        except (OSError,ValueError,KeyError,TypeError) as e:plan_ok=False;issues.append(dict(index=None,reason=str(e)))
        for j in (j for j in state['jobs'] if j['batch']==b['id']):
            if j['status']=='reused':excluded['reused']=excluded.get('reused',0)+1;continue
            if j['status'] not in ('passed','review'):
                excluded[j['status']]=excluded.get(j['status'],0)+1;continue
            if not plan_ok:excluded['unverifiable']=excluded.get('unverifiable',0)+1;continue
            try:
                r=attempt(root,j,plan)
                if r['attempt'] in seen:raise ValueError('同一次执行重复登记')
                seen.add(r['attempt']);rows.append(r);source.update(r['source_sha256'])
            except (OSError,ValueError,KeyError,TypeError,IndexError) as e:
                issues.append(dict(index=j['idx'],reason=str(e)));excluded['unverifiable']=excluded.get('unverifiable',0)+1
        batches.append(dict(id=b['id'],record_name=plan['record_name'],record_id=plan['record_id'],revision=plan['revision'],
            selected_cases=plan['case_count'],included_cases=len(rows),excluded=excluded,issues=issues,
            metrics=overlap(rows),rows=rows,elapsed_seconds=sum(r['elapsed_seconds'] for r in rows),
            retained_bytes=sum(r['retained_bytes'] for r in rows),
            observed_peak_memory_gib=max((r['peak_gib'] for r in rows),default=None),
            requested_parallel_limits=sorted({r['resources']['max_parallel'] for r in rows})))
    after=queue_snapshot(root)
    if state['jobs']!=after['jobs'] or state['batches']!=after['batches']:raise ValueError('队列状态正在变化，请刷新运行实测记录。')
    for p,h in source.items():
        if sha(p)!=h:raise ValueError('读取期间依据变化，请刷新运行实测记录。')
    return dict(created=now(),batches=batches,source_sha256=source,source_digest=digest(source),new_simulations=0,
        notes=['只统计当前结果所对应且证据可核验的已完成执行；复用不作为新执行，失败/中断及已被替换的早期尝试不代表在本表内。',
               '实际并行按同一批次起止日志重建，日志精度为秒。平均并行数仅对至少一个已纳入算例运行的时间求平均，不等于 CPU 利用率。',
               '运行窗口为所纳入区间的并集；记录间空档可能包含暂停、资源等待或复核，不能仅凭日志确定原因。',
               '这是历史记录整理，混合设备投入、地点和系统负载；不能据此断言增加线程的因果收益，也不自动修改并行上限。',
               '磁盘数据为当前保留量。旧运行没有磁盘峰值采样，不能追溯成峰值；记录缺失或不一致会从统计中排除。'])
