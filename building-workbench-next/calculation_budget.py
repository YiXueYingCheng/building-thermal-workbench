"""Read-only submission estimates. The frozen executor remains the authority."""
from contextlib import closing
from pathlib import Path
import json
import math
import sqlite3
import statistics
from foundation import read_json, sha, digest, owned, now
import output_storage
from execution_inputs import load_review
from execution_results import verify_artifacts
import resources


def queue_snapshot(root):
    path = Path(root)/'data/execution/queue.sqlite'
    if not path.exists():
        return dict(batches=[], jobs=[], cache=[], settings=[])
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        return {t: [dict(r) for r in db.execute('SELECT * FROM '+t)]
                for t in ('batches', 'jobs', 'cache', 'settings')}


def verified_result(root, path, checksum, identity):
    path = output_storage.checked_path(path, root)
    if not checksum or sha(path) != checksum:
        raise ValueError('结果汇总校验不符')
    result = read_json(path)
    if result['identity'] != identity:
        raise ValueError('结果身份不符')
    verify_artifacts(result,root)
    return result


def sample_key(plan, record, case):
    # Conservative: changed building/material/controls get no inherited estimate.
    return digest(dict(factors={k:v for k,v in record['factors'].items() if k!='scope'},
        numerics=record['numerics'], mode=case['mode'], period=case['period'],
        step_minutes=case['step_minutes'], engine=plan['engine_files'],
        code=plan['code_hashes'], output=plan['output_contract']))


def range_of(values):
    return dict(min=min(values), median=statistics.median(values), max=max(values))


def retained_bytes(root, result_path, result):
    # Scientific review copies live elsewhere; count the original attempt, not
    # the small review-results directory (which can also contain other cases).
    from storage_recovery import walk_files
    paths={output_storage.checked_path(result_path,root),*(output_storage.checked_path(p,root) for p in result['artifacts'])}
    attempts=set()
    for path in paths:
        if path.is_relative_to(Path(root).resolve()/'runs'):
            rel=path.relative_to(Path(root).resolve()/'runs')
            if len(rel.parts)>=2:attempts.add(Path(root).resolve()/'runs'/rel.parts[0])
        elif not path.is_relative_to(Path(root).resolve()):attempts.add(output_storage.result_folder(result,root))
    if not attempts:raise ValueError('缺少可核对的原始算例目录')
    for folder in attempts:
        files,links=walk_files(folder)
        if links:raise ValueError('算例目录含未展开链接')
        paths.update(files)
    return sum(p.stat().st_size for p in paths)


def disk_evidence(root, state):
    """Match independently sampled attempts to their frozen queue identities."""
    from disk_sampling import load_observations, INTERVAL
    rows, issues = load_observations(root)
    jobs = {j.get('attempt'): j for j in state['jobs'] if j.get('attempt')}
    batches = {b['id']: b for b in state['batches']}
    matched = {}
    for row in rows:
        try:
            j = jobs[row['attempt']]; b = batches[j['batch']]; p = json.loads(b['plan']); c = p['cases'][j['idx']]
            if (row['batch'],row['index'],row['identity'],row['plan_sha256'],row['model_sha256']) != (j['batch'],j['idx'],j['identity'],b['checksum'],c['model_sha256']):
                raise ValueError('采样与冻结任务不一致')
            if type(row['peak_bytes']) is not int or row['peak_bytes'] < 0 or row['sample_count'] < 1:
                raise ValueError('采样大小无效')
            adequate = (row['finalized'] and row['active_sample_count']>0 and not row['late_start'] and not row['failed_samples']
                        and not row['clock_discontinuity'] and isinstance(row['max_gap_seconds'],(int,float))
                        and math.isfinite(row['max_gap_seconds']) and 0<=row['max_gap_seconds']<=INTERVAL*2+2)
            matched[row['attempt']] = dict(**row,adequate=bool(adequate),current_status=j['status'])
        except (KeyError,ValueError,TypeError,IndexError):
            issues.append(dict(attempt=row.get('attempt'),error='采样身份、数值或队列记录未通过核对'))
    return matched, issues


def known_input_space(root, plan, cases):
    """Already stored inputs and deterministic future model copies; not output estimates."""
    from storage_recovery import walk_files
    folders=[owned(root/'data/execution/reviews'/plan['id'],root)]
    if plan.get('bundle_id'):folders.append(owned(root/'data/model-inputs'/plan['bundle_id'],root))
    files=set()
    for folder in folders:
        if not folder.is_dir():continue
        entries, links=walk_files(folder)
        if links:raise ValueError('准备目录含未展开链接，不能核算占用')
        files.update(entries)
    copies=0;complete=True
    for c,row in zip(plan['cases'],cases):
        if row['reusable']:continue
        if not c.get('model_file'):complete=False;continue
        copies+=owned(folders[0]/c['model_file'],folders[0]).stat().st_size
    return dict(prepared_bytes=sum(p.stat().st_size for p in files),prepared_files=len(files),
                execution_model_copy_bytes=copies if complete else None)


def build(root, ident, checksum):
    root = Path(root).resolve()
    plan = load_review(root, ident, checksum)
    record = read_json(root/'data/execution/reviews'/ident/'record.json')
    state = queue_snapshot(root)
    disk_rows, disk_issues = disk_evidence(root, state)
    policy = next((json.loads(r['value']) for r in state['settings'] if r['key']=='resources'),
                  resources.settings(dict(profile='balanced')))
    cache = {r['identity']:r for r in state['cache']}
    verified = {}
    def result(path, h, identity):
        key = (path, h, identity)
        if key not in verified:
            try: verified[key] = verified_result(root, path, h, identity)
            except (OSError, ValueError, KeyError, TypeError): verified[key] = None
        return verified[key]
    cases = []
    for c in plan['cases']:
        entry = cache.get(c['identity'])
        r = result(entry['path'], entry['checksum'], c['identity']) if entry else None
        reusable = bool(r and r.get('status')=='passed')
        cases.append(dict(index=c['index'], city=c['city'], site_id=c['site_id'], mode=c['mode'],
            reusable=reusable, cache_invalid=bool(entry and not reusable),
            reason='身份及结果文件核对通过' if reusable else '已有缓存未通过核验，按需算计入' if entry else '没有身份一致且核验通过的缓存'))
    samples = {}
    seen = set()
    historical = {}
    for b in state['batches']:
        try:
            p = json.loads(b['plan'])
            rec = read_json(owned(root/'data/execution/reviews'/p['id']/'record.json', root))
            if digest(rec) != p['record_sha256']: continue
            historical[b['id']] = (p,rec)
        except (OSError, ValueError, KeyError, TypeError): continue
    excluded = 0
    for j in state['jobs']:
        if j['status'] not in ('passed','reused') or not j['result'] or j['batch'] not in historical: continue
        if j['result'] in seen: continue
        seen.add(j['result'])
        p,rec = historical[j['batch']]
        c = p['cases'][j['idx']]
        r = result(j['result'], j.get('result_sha256'), j['identity'])
        if not r or not isinstance(r.get('elapsed_seconds'), (float,int)) or not math.isfinite(r['elapsed_seconds']) or r['elapsed_seconds']<=0:
            excluded += 1; continue
        try:retained = retained_bytes(root,j['result'],r)
        except (OSError,ValueError):excluded+=1;continue
        key = sample_key(p,rec,c)
        observation=disk_rows.get(r.get('attempt'))
        peak=observation['peak_bytes'] if observation and observation['adequate'] and j.get('attempt')==r.get('attempt') else None
        samples.setdefault(key,[]).append(dict(elapsed=r['elapsed_seconds'],retained=retained,peak=peak,
            batch=j['batch'],site_id=c['site_id'],result=j['result']))
    groups = {}
    for c, row in zip(plan['cases'], cases):
        key = sample_key(plan,record,c)
        g = groups.setdefault(key,dict(mode=c['mode'],period=c['period'],step_minutes=c['step_minutes'],
            total=0,needs_compute=0,samples=samples.get(key,[])))
        g['total'] += 1; g['needs_compute'] += not row['reusable']
    estimates = []
    for g in groups.values():
        ss = g.pop('samples')
        usable = len(ss)>=3
        peaks=[s['peak'] for s in ss if s['peak'] is not None]
        estimates.append(dict(**g,sample_count=len(ss),sample_sites=sorted({s['site_id'] for s in ss}),
            sample_batches=sorted({s['batch'] for s in ss}),
            per_case_seconds=range_of([s['elapsed'] for s in ss]) if usable else None,
            per_case_retained_bytes=range_of([s['retained'] for s in ss]) if usable else None,
            disk_sample_count=len(peaks),observed_peak_range=range_of(peaks) if peaks else None,
            per_case_sampled_peak_bytes=range_of(peaks) if len(peaks)>=3 else None))
    unknown = sum(g['needs_compute'] for g in estimates if not g['per_case_seconds'])
    def total(field):
        if unknown: return None
        return {k:sum(g['needs_compute']*(g[field][k] if g[field] else 0) for g in estimates) for k in ('min','median','max')}
    serial = total('per_case_seconds'); retained = total('per_case_retained_bytes')
    needed = sum(not c['reusable'] for c in cases)
    lanes = min(policy['max_parallel'],needed) if needed else 0
    ideal = {k:v/lanes if lanes else 0 for k,v in serial.items()} if serial is not None else None
    machine = resources.snapshot(root)
    cpu = resources.cpu_budget.admission(policy,machine,[])
    existing = [b for b in state['batches'] if b['review']==ident]
    known=known_input_space(root,plan,cases)
    known['available_after_reserve_bytes']=max(0,int((machine['disk_free_gib']-policy['disk_reserve_gib'])*2**30))
    unknown_peaks=sum(g['needs_compute'] for g in estimates if not g['per_case_sampled_peak_bytes'])
    # Sum each case's observed directory peak, including completed folders that remain.
    # This deliberately does not claim to reconstruct simultaneous workspace peaks.
    allocation=None if unknown_peaks else {k:sum(g['needs_compute']*(g['per_case_sampled_peak_bytes'][k] if g['per_case_sampled_peak_bytes'] else 0) for g in estimates) for k in ('min','median','max')}
    known.update(unknown_peak_cases=unknown_peaks,historical_peak_allocation_bytes=allocation,
        observations=[dict({k:r[k] for k in ('attempt','city','peak_bytes','last_bytes','sample_count','active_sample_count','finalized','adequate')},status=r['current_status'],sampled_status=r['status']) for r in disk_rows.values() if any(b['id']==r['batch'] for b in existing)],
        excluded_disk_observations=len(disk_issues))
    destination=output_storage.batch_destination(root,existing[0]['id']) if existing else output_storage.capture(root=root)
    capacity=output_storage.capacity(destination,known['execution_model_copy_bytes'] or 0,0,policy['disk_reserve_gib'],root)
    known['destination']=destination;known['capacity']=capacity
    known['available_after_reserve_bytes']=max(0,capacity['target_free_bytes']-capacity['reserve_bytes'])
    counts = {}
    for j in state['jobs']:
        if any(b['id']==j['batch'] for b in existing): counts[j['status']]=counts.get(j['status'],0)+1
    return dict(created=now(),id=ident,plan_sha256=checksum,case_count=len(cases),reusable=len(cases)-needed,
        needs_compute=needed,invalid_cache=sum(c['cache_invalid'] for c in cases),cases=cases,groups=estimates,
        unknown_estimate_cases=unknown,excluded_history=excluded,serial_seconds=serial,
        ideal_parallel_seconds=ideal,assumed_parallel=lanes,additional_retained_bytes=retained,cpu=cpu,
        peak_extra_bytes=None if needed else 0,storage=known,policy=policy,machine=machine,existing_counts=counts,
        queue_running=sum(j['status']=='running' for j in state['jobs']),
        queue_pending=sum(j['status']=='pending' for j in state['jobs']),
        basis='同建筑、材料、工况、数值配置、运行模式、时段、步长、引擎、执行程序及输出约定；至少 3 个不同结果，跨地点的实测范围。',
        limits=['耗时范围是历史观测，不是置信区间；理想并行值忽略排队、资源等待和并行减速，不是完成时间承诺。',
                '已准备输入已经占用当前磁盘；执行模型副本仅是确定的新增文件量，不包含输出与日志，不能作为完整预算。',
                '保留量按完整算例目录实测；采样空间参考按各算例历史采样最大值相加，保留结束后目录。它不是同时运行峰值或容量保证，也不按并行数简单乘除。',
                '采样参考要求至少 3 个同类已接受结果且观测覆盖合格；少量样本仅作参考。5 秒采样可能漏过瞬时峰值。',
                '预算只读；提交和派发时重新核验。已有批次的复用/需算是当前输入的重提预算，不会重新排队。'])
