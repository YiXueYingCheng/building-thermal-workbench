"""Single-site follow-up attempts and explicit selection for the parent report."""
from collections import Counter
from pathlib import Path
import re
import tempfile

from foundation import digest, loads, now, owned, read_json, sha, write_json
from execution_inputs import OBSERVER, code_hashes, load_review, stage_observer
from schedule_sharing import share_files
import output_storage


def step_label(steps):
    counts = Counter(steps)
    return '、'.join(f'{step} min × {count}' for step, count in sorted(counts.items())) or '—'


BEIJING_PROFILE = 'five_storey_condfd_1min_v1'
BEIJING_STEP_NOTE = '北京五层专用工况的求解步长固定为 1 分钟。'


def beijing_profile(record):
    return record.get('numerics', {}).get('heat_transfer_profile') == BEIJING_PROFILE


def allowed_steps(record, source, purpose='recovery'):
    if beijing_profile(record):
        # Failed cases can be repeated at their calibrated step. A passed case
        # already supplies the 1-minute reference for a comparison.
        return [1] if source == 1 and purpose == 'recovery' else []
    feedback = [c for c in record['factors']['condition'].get('controls', [])
                if c.get('mode') == 'feedback']
    solid = any('reference_step_minutes' in c for c in feedback)
    intervals = [c['update']['minutes'] for c in feedback if c['update']['kind'] == 'minutes']
    return [s for s in (1, 2, 5, 10, 15, 30, 60) if s != source and
            (not solid or s == 1) and all(i % s == 0 for i in intervals)]


def validate_step(record, old, step, purpose):
    if beijing_profile(record) and (type(step) is not int or step != 1 or old != 1):
        raise ValueError(BEIJING_STEP_NOTE)
    if type(step) is not int or step not in allowed_steps(record, old, purpose):
        raise ValueError('请选择与原步长不同且符合材料控制间隔的求解步长。')


def change_model_step(model, record, old, step, purpose='recovery'):
    validate_step(record, old, step, purpose)
    periods = list(model.get('Timestep', {}).values())
    if len(periods) != 1 or periods[0]['number_of_timesteps_per_hour'] != 60 // old:
        raise ValueError('原模型求解步长与冻结记录不符。')
    if old == step:
        return
    periods[0]['number_of_timesteps_per_hour'] = 60 // step
    # Legacy feedback programs count elapsed minutes in explicit wall/group clocks.
    lines = model.get('EnergyManagementSystem:Program', {}).get('ECA_Update', {}).get('lines', [])
    controls = record['factors']['condition'].get('controls', [])
    for row in lines:
        line = row['program_line']
        tick = re.fullmatch(r'SET (ECA_\w+_Age|NX_G\d+_\w+_Clock) = \1 \+ (\d+)', line)
        if tick:
            if int(tick[2]) != old:
                raise ValueError('原反馈时钟与求解步长不一致。')
            row['program_line'] = f'SET {tick[1]} = {tick[1]} + {step}'
        interval = re.fullmatch(r'IF (NX_G(\d+)_\w+_Clock) >= ([\d.]+)', line)
        if interval and controls[int(interval[2])]['update']['kind'] == 'solver_step':
            row['program_line'] = f'IF {interval[1]} >= {step}'


def parent_job(db, parent, index, attempt, purpose='recovery'):
    if type(index) is not int or index < 0:
        raise ValueError('请选择有效的地点算例。')
    row = db.execute('SELECT j.*,b.review,b.checksum,b.plan FROM jobs j JOIN batches b ON b.id=j.batch '
                     'WHERE j.batch=? AND j.idx=?', (parent, index)).fetchone()
    if purpose not in ('recovery','comparison'):
        raise ValueError('请选择补算或对照加算。')
    accepted = ('passed','reused') if purpose=='comparison' else ('failed',)
    if not row or row['status'] not in accepted or not attempt or row['attempt'] != attempt:
        raise ValueError('该地点状态与所选操作不符，请刷新本批结果。')
    if 'site_recalculation' in loads(row['plan']):
        raise ValueError('请从原批次的地点记录提交。')
    return row


def submit(q, parent, index, attempt, step, purpose='recovery'):
    if type(step) is not int:
        raise ValueError('求解步长须为整数分钟。')
    with q.db() as db:
        job = parent_job(db, parent, index, attempt,purpose)
        history = [r for r in links(db,parent) if r['idx']==index and r['step']==step and r['purpose']==purpose]
        previous = history[-1] if history else None
    reviews = q.folder/'reviews'
    source = owned(reviews/job['review'], reviews)
    record = read_json(source/'record.json')
    pinned = loads(job['plan'])
    if digest(record) != pinned['record_sha256']:
        raise ValueError('方案快照变化。')
    validate_step(record, pinned['cases'][index]['step_minutes'], step, purpose)
    original = load_review(q.root, job['review'], job['checksum'], historical=True, only_index=index)
    case = original['cases'][index]
    if case['identity'] != job['identity'] or case['index'] != index:
        raise ValueError('原地点算例与清单不符。')
    if previous and previous['status'] not in ('failed','cancelled','interrupted'):
        return dict(id=previous['child'],reused_submission=True)
    model = read_json(owned(source/case['model_file'], source))
    # A new child gets its own local physical filenames. Keep the parent bytes,
    # attempt and checksum intact, including the original schedule-sharing report.
    from history_locations import engine_location, input_path
    engine, files = engine_location(q.root, original)
    original = dict(original, engine=engine, engine_files=files)
    case = dict(case)
    deps = case['dependencies']
    rebound = {p:str(input_path(q.root,p,h)) for p,h in deps.items()}
    for schedule in model.get('Schedule:File',{}).values():
        path = schedule['file_name']
        if path not in deps:raise ValueError('冻结模型含未登记的作息文件。')
        schedule['file_name'] = rebound[path]
    case['weather'] = rebound[case['weather']]
    case['dependencies'] = {rebound[p]:h for p,h in deps.items()}
    change_model_step(model, record, case['step_minutes'], step, purpose)
    if case.get('stack_response') and step!=case['step_minutes']:
        from stack_response import change_step
        change_step(model,case,original['output_contract'])
    sharing = case.get('schedule_sharing') or share_files(
        model, case['dependencies'], trusted_observer=OBSERVER if case.get('warmup_observer') else None)
    codes = code_hashes()
    lineage = dict(parent=parent, idx=index, original_attempt=attempt, original_identity=case['identity'],
                   predecessor=previous['child'] if previous else '',
                   parent_checksum=job['checksum'], original_step=case['step_minutes'],
                   original_model_sha256=case['model_sha256'], step=step)
    if purpose=='comparison':
        lineage.update(purpose=purpose,original_result_sha256=job['result_sha256'])
    ident = 'review_' + digest(dict(lineage=lineage, codes=codes))[:32]
    folder = reviews/ident
    if not folder.exists():
        with tempfile.TemporaryDirectory(dir=reviews, prefix='s-') as temp:
            stage = Path(temp)/'r'
            name = '000.epJSON'
            write_json(stage/name, model, q.root)
            physical = {k:v for k,v in model.items() if not k.startswith('Output')}
            inputs = digest(dict(site_id=case['site_id'],mode=case['mode'],period=case['period'],model=digest(model), dependencies=case['dependencies'],
                                 engine_files=original['engine_files'], output_contract=original['output_contract']))
            child = dict(case, index=0, model_file=name, model_sha256=sha(stage/name),
                         step_minutes=step, physical_digest=digest(physical), identity=digest(dict(inputs=inputs, executor=codes)))
            if sharing:
                child['schedule_sharing'] = sharing
                child['identity'] = digest(dict(inputs=inputs, executor=codes, schedule_sharing=sharing))
            if child.get('warmup_observer'):
                stage_observer(stage, codes)
            label='对照加算' if purpose=='comparison' else '补算'
            plan = dict(original, id=ident, created=now(), cases=[child], case_count=1, code_hashes=codes,
                        record_name=f"{record['name']} · {case['city']}{label}（{step} min）", site_recalculation=lineage)
            write_json(stage/'record.json', record, q.root)
            write_json(stage/'plan.json', plan, q.root)
            try:
                stage.rename(folder)
            except OSError:
                if not folder.is_dir():
                    raise
    if read_json(folder/'plan.json').get('site_recalculation') != lineage:
        raise ValueError('补算清单来源不符。')
    return q.submit(ident, sha(folder/'plan.json'), output_storage.batch_destination(q.root,parent))


def attach(db, plan, child):
    ref = plan['site_recalculation']
    purpose = ref.get('purpose','recovery')
    job = parent_job(db, ref['parent'], ref['idx'], ref['original_attempt'],purpose)
    if purpose=='comparison' and ref['original_result_sha256'] != job['result_sha256']:
        raise ValueError('原通过结果已经变化。')
    if job['identity'] != ref['original_identity'] or job['checksum'] != ref['parent_checksum']:
        raise ValueError('补算来源发生变化。')
    if db.execute('SELECT 1 FROM site_recalculations WHERE parent=? AND idx=? AND adopted IS NOT NULL',
                  (ref['parent'], ref['idx'])).fetchone():
        raise ValueError('该地点已确认并入补算结果。')
    previous = [r for r in links(db,ref['parent']) if r['idx']==ref['idx'] and r['step']==ref['step']]
    if previous and (ref['predecessor'] != previous[-1]['child'] or previous[-1]['status'] not in ('failed','cancelled','interrupted')):
        raise ValueError('该步长的补算状态已经变化，请刷新。')
    db.execute('INSERT INTO site_recalculations(parent,idx,original_attempt,child,step,predecessor) VALUES(?,?,?,?,?,?)',
               (ref['parent'], ref['idx'], ref['original_attempt'], child, ref['step'],ref['predecessor']))


def links(db, parent):
    return [dict(row) for row in db.execute(
        "SELECT s.*,j.status,j.attempt,j.identity,j.result_sha256,j.error,COALESCE(json_extract(b.plan,'$.site_recalculation.purpose'),'recovery') purpose FROM site_recalculations s "
        'JOIN batches b ON b.id=s.child JOIN jobs j ON j.batch=s.child AND j.idx=0 WHERE s.parent=? ORDER BY s.rowid', (parent,))]


def adopt(q, parent, index, child, expected):
    from comparison_results import execution
    with q.db() as db:
        link = next((r for r in links(db,parent) if r['idx']==index and r['child']==child and r['purpose']=='recovery'), None)
        if not link:
            raise ValueError('补算与所选地点不匹配。')
        job = parent_job(db,parent,index,link['original_attempt'])
    plan = loads(job['plan'])
    case = plan['cases'][index]
    record = read_json(q.folder/'reviews'/plan['id']/'record.json')
    source = execution(record,child,case['mode'],q.root)
    ref = source['site_recalculation']
    row = source['cases'].get(case['site_id'])
    if (not row or not ref or ref['parent'] != parent or ref['idx'] != index or
            ref['original_attempt'] != job['attempt'] or ref['original_identity'] != case['identity'] or
            ref['original_model_sha256'] != case['model_sha256'] or ref['parent_checksum'] != job['checksum'] or
            row['step_minutes'] != link['step'] or row['period'] != case['period'] or
            row['weather_sha256'] != case['dependencies'][case['weather']]):
        raise ValueError('补算来源与原失败算例不符。')
    if not expected or row['status'] not in ('passed','reused') or row['evidence']['result_sha256'] != expected:
        raise ValueError('补算尚未通过核验或结果已经变化，请刷新后确认。')
    with q.db() as db:
        parent_job(db,parent,index,link['original_attempt'])
        current = next(r for r in links(db,parent) if r['child']==child)
        if current['result_sha256'] != expected or current['attempt'] != row['evidence']['attempt'] or current['status'] not in ('passed','reused'):
            raise ValueError('补算状态已变化，请刷新。')
        selected = next((r for r in links(db,parent) if r['idx']==index and r['adopted']), None)
        if selected and selected['child'] != child:
            raise ValueError('该地点已采用另一次补算。')
        if not selected:
            db.execute('UPDATE site_recalculations SET adopted=?,selected_attempt=?,selected_hash=? WHERE child=?',
                       (now(),current['attempt'],expected,child))
            q.event(db,parent,'adopt_site_recalculation',dict(index=index,child=child,result_sha256=expected))
    return dict(parent=parent,index=index,child=child,adopted=True)


def effective(record, parent, cases, jobs, checksum, root, candidates):
    from comparison_results import execution
    sites_by_index={r['evidence']['index']:sid for sid,r in cases.items()}
    for link in candidates:
        if not link['adopted']:
            continue
        index = link['idx']
        job = jobs[index]
        sid = sites_by_index.get(index)
        if sid is None:
            continue
        original = cases[sid]
        if (original['status'] != 'failed' or job['attempt'] != link['original_attempt'] or
                link['attempt'] != link['selected_attempt'] or link['result_sha256'] != link['selected_hash']):
            raise ValueError('已采用补算的来源记录变化，请核对。')
        child = execution(record,link['child'],original['mode'],root)
        ref = child.get('site_recalculation') or {}
        value = child['cases'].get(sid)
        if (not value or value['status'] not in ('passed','reused') or value['step_minutes'] != link['step'] or
                value['weather_sha256'] != original['weather_sha256'] or value['period'] != original['period'] or
                ref.get('parent') != parent or ref.get('idx') != index or ref.get('parent_checksum') != checksum or
                ref.get('original_identity') != job['identity'] or ref.get('original_attempt') != job['attempt'] or
                value['evidence']['result_sha256'] != link['selected_hash']):
            raise ValueError('已采用的补算与原算例不一致。')
        value['evidence']['original_failure'] = dict(original['evidence'],status='failed',
            step_minutes=original['step_minutes'],error=job['error'],adopted=link['adopted'])
        cases[sid] = value
