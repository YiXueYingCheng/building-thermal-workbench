"""Register completed annual warmup evidence as an unaccepted review candidate.

No simulations and no scientific acceptance here. Only an independently prepared,
hash-bound assessment may move a failed job to review. The existing separate
acceptance workflow then records the user's decision and retains original files.
"""
from pathlib import Path
from contextlib import closing
import json,re,sqlite3,uuid
from foundation import read_json,write_json,sha,now,owned
from execution_inputs import load_review
from execution_results import verify_artifacts
from history_locations import workspace_path, input_path

CONTRACT='annual_warmup_assessment_v1'
FIELDS=('batch','idx','status','identity','attempt','result','result_sha256','error','updated')

def require(ok,message):
    if not ok:raise ValueError(message)

def source(root,batch,index):
    require(bool(re.fullmatch(r'batch_[a-f0-9]{32}',str(batch))) and type(index) is int and index>=0,'算例编号无效。')
    with closing(sqlite3.connect((Path(root)/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        b=db.execute('select * from batches where id=?',(batch,)).fetchone()
        j=db.execute('select * from jobs where batch=? and idx=?',(batch,index)).fetchone()
    require(b is not None and j is not None,'未找到该算例。');return dict(b),dict(j)

def failure_binding(job):return {key:job[key] for key in FIELDS}

def assessment_path(root,job):
    require(bool(re.fullmatch(r'attempt_[a-f0-9]{32}',str(job['attempt']))),'原计算记录编号无效。')
    return owned(Path(root)/'data/execution/warmup-assessments'/(job['attempt']+'.json'),root)

def validate_assessment(root,b,j,expected_failure=None):
    root=Path(root).resolve();path=assessment_path(root,j)
    require(path.is_file(),'本项还没有完整的年度诊断依据；保留未通过状态，不建议直接重复计算。')
    a=read_json(path)
    require(a.get('contract')==CONTRACT and a.get('source_job')==(expected_failure or failure_binding(j)),'诊断依据与本次失败记录不一致。')
    candidate=owned(workspace_path(root,a['candidate_path']),root/'verification');evidence=owned(workspace_path(root,a['evidence_path']),root/'verification')
    require(sha(candidate)==a['candidate_sha256'] and sha(evidence)==a['evidence_sha256'],'诊断候选或分析依据发生变化。')
    raw=read_json(candidate);proof=read_json(evidence);report=a['report']
    require(raw['status']=='review' and raw['identity']==j['identity'] and raw['attempt']==j['attempt'],'诊断候选不属于本次算例。')
    require(raw.get('warmup_diagnostic',{}).get('origin')=='failed_warmup_result' and raw['warmup_diagnostic'].get('automatic_acceptance') is False,'缺少原预热失败说明。')
    require(raw['checks'].get('warmup_converged') is False and raw['pending_warnings'],'预热失败原因未完整保留。')
    severe=[row['message'] for row in raw['warmup_diagnostic']['severe_records']]
    require(severe and all(message in raw['pending_warnings'] for message in severe),'原预热严重错误被遗漏。')
    require(not raw.get('scientific_review') and proof.get('passed') is True,'诊断依据未完成。')
    require(proof.get('source_job')==a['source_job'] and proof.get('candidate_sha256')==a['candidate_sha256'],'分析结论未绑定本次候选。')
    require(proof.get('original_loads')==raw['loads'] and proof.get('all_original_issues_reviewed') is True,'原需求或全部警告尚未完成核查。')
    require(report.get('recommendation')=='accept_with_notes' and report.get('scope') and report.get('limits'),'缺少具体接受范围和限制。')
    require(report['scope']==proof.get('scope') and report.get('checks') and all(c.get('passed') is True for c in report['checks']),'检查结论不完整。')
    refs=proof.get('verified_sources',[])
    require(refs and len({v['path'] for v in refs})==len(refs),'分析来源缺失或重复。')
    for ref in refs:require(sha(input_path(root,ref['path'],ref['sha256']))==ref['sha256'],'诊断引用资料发生变化，请重新分析。')
    for file,h in raw['artifacts'].items():
        require(any(v['path']==file and v['sha256']==h for v in refs),'原始计算文件没有绑定到分析依据。')
    plan=load_review(root,b['review'],b['checksum'],historical=True);case=plan['cases'][j['idx']]
    require(case['identity']==j['identity'] and case['site_id']==raw['site_id'] and case['model_sha256']==a['model_sha256'],'冻结输入与诊断对象不一致。')
    model_path=next((path for path in raw['artifacts'] if Path(path).name=='model.epJSON'),None)
    require(model_path is not None and sha(workspace_path(root,model_path))==case['model_sha256'],'实际模型与冻结输入不一致。')
    require(raw['days']==365 and raw['step_minutes']==5 and raw['mode']=='controlled' and raw['checks']['full_period'] and raw['checks']['monthly_reconciliation'],'当前只支持完整全年 5 min 显热诊断。')
    if raw.get('daily_reference'):
        require(raw['daily_reference']['data_checks_passed'] and raw['daily_reference']['days']==365 and proof.get('daily_calendar_reviewed') is True,'逐日参考与日历敏感性尚未核查。')
    verify_artifacts(raw,root)
    return path,a,raw,proof

def failed_view(root,batch,index):
    b,j=source(root,batch,index)
    if j['status']!='failed':return None
    from execution_failure_view import describe
    info=describe(j,root)
    if not info or info['kind']!='warmup_convergence':return None
    ready=False;error=''
    try:validate_assessment(root,b,j);ready=True
    except (ValueError,OSError,KeyError,TypeError) as exc:error=str(exc)
    return dict(id=None,batch=batch,index=index,state='ready',workflow='warmup_annual',
        report=dict(recommendation='prepare_review' if ready else 'needs_analysis',
            title='年度诊断依据已齐备，尚未采用' if ready else '预热未通过，等待诊断依据',
            explanation='核对后建立待复核记录；只有明确采用结论，才纳入研究汇总。' if ready else error,
            checks=[],scope='',next_step='点击“核对并建立复核记录”，再查看结论并决定是否采用。' if ready else '保留原输入与输出；先完成原因分析及必要的隔离诊断，再回来刷新。',
            limits=['查看或检查不会启动新的建筑计算。','原预热未收敛记录保持；完整年度输出不等于预热已收敛。']),
        failure_info=info,assessment_available=ready)

def existing(root,j):
    root=Path(root)
    for path in (root/'verification/result-reviews').glob('review_*/job.json'):
        job=read_json(path)
        if job.get('workflow')!='warmup_annual' or job.get('batch')!=j['batch'] or job.get('index')!=j['idx']:continue
        bound=job['binding']
        if j['attempt']==bound['attempt'] and j['identity']==bound['identity'] and j['result']==bound['result'] and j['result_sha256']==bound['result_sha256']:
            return path.parent,job
    return None

def handle_start(root,batch,index):
    """Return None for ordinary results; warmup cases use registered evidence."""
    root=Path(root).resolve();b,j=source(root,batch,index)
    if j['status']=='review' and j['result']:
        from output_storage import checked_path
        result_path=checked_path(j['result'],root)
        require(sha(result_path)==j['result_sha256'],'待复核候选文件发生变化。')
        raw=read_json(result_path)
        if not raw.get('warmup_diagnostic'):return None
        match=existing(root,j);require(match is not None,'未找到对应的预热复核记录。')
        _,job=match;validate_assessment(root,b,j,job['original_failure'])
        from result_review import status
        return status(root,job['id'])
    if j['status']!='failed':return None
    from execution_failure_view import describe
    info=describe(j,root)
    if not info or info['kind']!='warmup_convergence':return None
    try:path,a,raw,proof=validate_assessment(root,b,j)
    except (ValueError,OSError,KeyError,TypeError):return failed_view(root,batch,index)
    from result_review import folder,binding,status
    from execution_queue import Queue
    ident='review_'+uuid.uuid4().hex;p=folder(root,ident);created=now()
    original=failure_binding(j)
    write_json(p/'original-failure.json',original,root)
    write_json(p/'candidate.json',raw,root);candidate=p/'candidate.json';candidate_sha=sha(candidate)
    conclusion=dict(identity=j['identity'],site_id=raw['site_id'],batch=batch,index=index,
        original_result=str(candidate),original_result_sha256=candidate_sha,decision='accepted_with_notes',
        evidence_kind='annual_warmup_sensitivity_assessment',scientific_scope=a['report']['scope'])
    refs={v['path']:v['sha256'] for v in proof['verified_sources']}
    refs.update({str(path):sha(path),a['evidence_path']:a['evidence_sha256'],a['candidate_path']:a['candidate_sha256'],str(p/'original-failure.json'):sha(p/'original-failure.json')})
    outcome=dict(created=created,passed=True,review_conclusions=[conclusion],verified_sources=[dict(path=k,sha256=h) for k,h in refs.items()],
        original_failure=original,diagnostic_assessment=proof)
    write_json(p/'outcome.json',outcome,root)
    write_json(p/'report.json',dict(a['report'],created=created,evidence_sha256=sha(p/'outcome.json')),root)
    proposed={**j,'status':'review','result':str(candidate),'result_sha256':candidate_sha}
    job=dict(id=ident,batch=batch,index=index,created=created,finished=created,state='ready',workflow='warmup_annual',
        binding=binding(proposed),original_failure=original,message='年度诊断依据已核对，尚未采用结论。')
    write_json(p/'job.json',job,root)
    q=Queue(root)
    with q.db() as db:
        require(not db.execute('SELECT 1 FROM site_recalculations WHERE parent=? AND idx=?',(batch,index)).fetchone(),'该失败记录已关联单地点补算，请在原地点查看或确认补算结果。')
        cur=db.execute("update jobs set status='review',result=?,result_sha256=?,error=NULL,updated=? where batch=? and idx=? and status='failed' and attempt=? and identity=? and result IS ? and result_sha256 IS ? and error IS ? and updated=?",
            (str(candidate),candidate_sha,created,batch,index,j['attempt'],j['identity'],j['result'],j['result_sha256'],j['error'],j['updated']))
        require(cur.rowcount==1,'原失败记录已变化，没有建立新的可用结果。')
        q.event(db,batch,'warmup_diagnostic_registered',dict(index=index,review_id=ident,original_failure=str(p/'original-failure.json'),original_failure_sha256=sha(p/'original-failure.json'),accepted=False))
    return status(root,ident)
