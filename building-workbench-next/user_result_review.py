"""Public warning review, bounded to one immutable completed result.

Technical verification is independent of a user's scientific interpretation.
No simulation, warning allowlist, private research evidence, or raw-result edits.
"""
from pathlib import Path
import shutil
import tempfile
from foundation import read_json, write_json, sha, now
import output_storage

KIND='user_review_with_notes_v1'
CONTRACT='public_result_integrity_v1'

def inspect(root,job):
    from result_review import target,binding,require,load_review
    from execution_results import verify,verify_artifacts
    root=Path(root);b,j,raw=target(root,job['batch'],job['index']);checks=[]
    def check(label,ok,detail=''):
        require(ok,label+'未通过。');checks.append(dict(label=label,passed=True,detail=detail))
    check('绑定本次待复核结果',j['status']=='review' and binding(j)==job['binding'])
    verify_artifacts(raw,root)
    check('模型、日志与结果原文件校验值一致',True)
    plan=load_review(root,b['review'],b['checksum'],historical=True);case=plan['cases'][j['idx']]
    check('保存方案、冻结输入与算例一致',case['identity']==j['identity'])
    run=output_storage.result_folder(raw,root)
    check('实际执行模型与冻结模型一致',sha(run/'model.epJSON')==case['model_sha256'])
    execution=read_json(run/'execution.json')
    # The daily verifier writes a derived CSV: isolate that branch so even its
    # deterministic output cannot replace any original research artifact.
    def verify_at(path):return verify(path,case,execution['returncode'],raw['elapsed_seconds'])
    if case.get('output_contract')=='daily_sensible_reference_v1':
        with tempfile.TemporaryDirectory(prefix='review-check-') as tmp:
            work=Path(tmp);(work/'run').mkdir();shutil.copy2(run/'model.epJSON',work/'model.epJSON')
            for name in ('eplusout.sql','eplusout.err','eplusout.end'):shutil.copy2(run/'run'/name,work/'run'/name)
            fresh=verify_at(work)
    else:fresh=verify_at(run)
    check('引擎正常结束、无严重错误且数据库完整',True)
    check('覆盖所选日期与步长，单位和汇总一致',True,
          f"{raw['period'][0]}月{raw['period'][1]}日—{raw['period'][2]}月{raw['period'][3]}日，{raw['days']} 天，{raw['step_minutes']} min；不要求全年。")
    fields=('status','site_id','city','mode','period','days','step_minutes','loads','monthly','rooms','temperatures','temperature_extrema','warnings','pending_warnings','checks','daily_reference','time_detail','output_contract')
    check('重新读取的数值和警告与原汇总一致',all(fresh.get(k)==raw.get(k) for k in fields))
    check('确有待用户判断的警告',bool(raw['pending_warnings']))
    _,current,_=target(root,j['batch'],j['idx']);verify_artifacts(raw,root)
    check('核查期间原结果保持不变',binding(current)==binding(j))
    log=(run/'run/eplusout.err').read_text('utf-8',errors='replace')
    # Include the exact warning paragraphs and surrounding context, not merely
    # their titles. Bounds are disclosed; the original log is always exported.
    lines=log.splitlines();indices=set()
    for i,line in enumerate(lines):
        if '** Warning **' in line:
            indices.update(range(max(0,i-1),min(len(lines),i+12)))
    excerpts='\n'.join(lines[i] for i in sorted(indices))
    return b,j,raw,checks,excerpts[:24000],len(excerpts)>24000

def analyse(root,ident):
    from result_review import folder
    root=Path(root);p=folder(root,ident);job=read_json(p/'job.json')
    try:
        b,j,raw,checks,excerpts,truncated=inspect(root,job)
        report=dict(created=now(),contract=CONTRACT,recommendation='user_decision',
            title='完整性检查通过，警告由你判断',
            explanation='本次输出完整并与冻结输入一致。平台没有证明这些警告无害，也不会替你采用结果。',
            checks=checks,pending_warnings=raw['pending_warnings'],warning_excerpt=excerpts,excerpt_truncated=truncated,
            scope=f"{raw['city']}；{raw['period'][0]}/{raw['period'][1]}—{raw['period'][2]}/{raw['period'][3]}；{raw['step_minutes']} min；"+('温控显热需求' if raw['mode']=='controlled' else '自然室温'),
            next_step='查看警告与原日志后，可填写理由和用途，登记为“用户审阅后采用”；也可保持待复核。',
            limits=['采用只绑定这个冻结结果，不会自动放行同名警告。','原始数值、日志和警告保留；采用标记随比较与导出保留。','采用后的结果可进入匹配条件的比较和参考；适用性仍以你填写的用途说明为准。'])
    except (OSError,ValueError,KeyError,IndexError,TypeError) as exc:
        report=dict(created=now(),contract=CONTRACT,recommendation='repair_required',title='完整性检查未通过',
            explanation=str(exc),checks=[],next_step='请根据具体原因核对缺失文件或计算输出。修复后重新检查；已有结果保留。',
            limits=['此处是文件或输出完整性问题，不能用警告采用说明替代。','未重新运行计算，也未改动原结果。'])
    write_json(p/'report.json',report,root)
    return report

def prepare_decision(root,ident,report,job,decision):
    from result_review import folder,target,require
    p=folder(root,ident)
    _,j,raw=target(root,job['batch'],job['index'])
    # Idempotent retry never overwrites the evidence of an adopted result.
    if j['status']=='passed' and raw.get('scientific_review',{}).get('id')==ident:return
    require(report.get('contract')==CONTRACT,'请重新进行公开版完整性检查。')
    require(isinstance(decision,dict) and decision.get('acknowledged') is True,'请明确确认已查看警告并自行判断用途。')
    clean={}
    for key,label,limit in [('reviewer','审阅人',80),('reason','采用理由',3000),('scope','用途范围',2000)]:
        value=decision.get(key)
        require(isinstance(value,str) and 1<=len(value.strip())<=limit,f'请填写{label}（最多 {limit} 字）。')
        clean[key]=value.strip()
    if decision.get('acceptance_mode')=='bulk_force':
        clean.update(acceptance_mode='bulk_force',bulk_review_id=decision.get('bulk_review_id'))
    clean['acknowledged']=True
    b,j,raw,checks,_,_=inspect(root,job)
    clean['reviewed_at']=now()
    conclusion=dict(batch=j['batch'],index=j['idx'],identity=j['identity'],site_id=raw['site_id'],attempt=j['attempt'],
        original_result=j['result'],original_result_sha256=j['result_sha256'],decision='accepted_with_notes',
        evidence_kind=KIND,scientific_scope=clean['scope'],user_decision=clean)
    evidence=dict(created=now(),passed=True,technical_checks_passed=True,automatic_warning_clearance=False,
        review_conclusions=[conclusion],checks=checks,building_simulations=0,
        verified_sources=[dict(path=str(p/'report.json'),sha256=sha(p/'report.json'))],
        original_warnings=raw['pending_warnings'])
    write_json(p/'outcome.json',evidence,root)
    write_json(p/'decision.json',dict(user_decision=clean,evidence_sha256=sha(p/'outcome.json')),root)
