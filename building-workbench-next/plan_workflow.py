"""Read-only workflow projection. No independent completion flags or submission."""
from pathlib import Path
from foundation import ROOT,digest,now,read_json,owned,sha
from contracts import calculation_recipe
import plan_activity
import navigation_cache
from daily_workflow import registry
from preparation_recovery import checked
from capability_summary import describe

def source_bindings(catalog,root,record):
    # An empty workspace has no set membership; reading its workflow must not
    # create the records database just to discover that fact.
    if not (Path(root)/'data/drafts.sqlite').exists():return []
    from preparation_status import approved_sources
    from research_sets import Sets
    return approved_sources(Sets(catalog,root),record)

def preparations(record,activity,root,include_history=False,bindings=None):
    rows=[];issues=[];history=[]
    # Match exact saved versions, not names or the most recently used building.
    from preparation_status import Submissions
    registered=registry(root);submissions=Submissions(root) if registered else None
    for r in registered:
        item=None
        try:
            folder=owned(Path(root)/'data/execution/reviews'/r['review'],root)
            plan=read_json(folder/'plan.json')
            if (plan['record_id'],plan['revision'])!=(record['id'],record['revision']):continue
            item=dict(id=r['review'],bundle_id=r['bundle_id'],output_contract=plan['output_contract'],created=r['created'],valid=False,note='')
            rows.append(item)
            if sha(folder/'plan.json')!=r['checksum']:raise ValueError('准备清单摘要不符。')
            if plan['record_sha256']!=digest(record):raise ValueError('准备清单与当前保存版本的内容不一致。')
            life=submissions.plan(plan,r['checksum'],bindings=bindings);item['lifecycle']=life
            if life['kind'] in ('submitted','finished'):
                history.append(item);rows.pop();continue
            if life['kind'] in ('unknown','partial'):
                item['note']=life['label']+'；请查看关联批次，不重复提交。';continue
            checked(root,r['review'],r['checksum'],r['bundle_id'],r['bundle_sha256'],record)
            item['valid']=True
        except (ValueError,KeyError,TypeError,OSError) as exc:
            if item is not None:item['note']=str(exc)
            else:issues.append('准备记录未能读取：'+str(exc))
    return (rows,issues,history) if include_history else (rows,issues)

def batch_node(batch,verified=None):
    if not batch:return dict(state='waiting',label='尚无批次',note='准备并明确提交后才会开始计算。')
    c=batch['counts'];n=batch['case_count']
    if verified is not None:
        accepted=verified['accepted'];reviewed=verified.get('reviewed',0)
        if n and accepted==n:return dict(state='done',label=f'{accepted}/{n} 已接受',note=f'已读取并核验所选批次；其中 {reviewed} 项附说明接受。')
        if c['running'] or c['pending']:return dict(state='active',label=f'{accepted}/{n} 已接受',note='其余算例仍在运行或排队；查看本批进度。')
        return dict(state='attention',label=f'{accepted}/{n} 已接受',note='部分结果未接受或未完成；查看本批核验说明。')
    if c['running']:return dict(state='active',label='计算中',note='当前算例结束后暂停。' if batch['mode']=='pause' else '当前批次正在计算。')
    if c['pending']:return dict(state='waiting',label='已暂停' if batch['mode']=='pause' else '排队中',note=f'排队 {c["pending"]} 项；暂停不会丢弃已完成结果。')
    if c['failed'] or c['interrupted'] or c['cancelled']:return dict(state='attention',label='部分未完成',note='本批含失败、中断或取消项，不能视为全部完成。')
    return dict(state='check',label='已结束 · 待读取',note='队列登记已结束；读取结果后才能确认有效数量与接受依据。')

def build(record,saved,catalog,store,root=ROOT,batch_id=None,verify_results=False,branch=False,defer_branch=False):
    activity=navigation_cache.activity(saved,catalog,store,root);cap=describe(record,catalog)
    dirty=any(record.get(k)!=saved.get(k) for k in ('name','factors','numerics','execution'));same_recipe=calculation_recipe(record)==calculation_recipe(saved)
    bindings=source_bindings(catalog,root,saved)
    pending,issues,history=preparations(saved,activity,root,include_history=True,bindings=bindings);batches=activity['batches']
    if batch_id is not None and batch_id not in {b['id'] for b in batches}:raise ValueError('所选批次不属于当前保存版本，请刷新流程。')
    selected=next((b for b in batches if b['id']==batch_id),batches[0] if batches else None)
    verified=None;verification_error=None
    if verify_results and selected:
        try:
            from batch_results import build as batch_results
            verified=batch_results(selected['id'],catalog,root)['counts']
        except (ValueError,KeyError,TypeError,OSError) as exc:verification_error=str(exc)
    run=batch_node(selected,verified)
    if verification_error:run=dict(state='attention',label='结果需核对',note=verification_error)
    valid=[p for p in pending if p['valid']]
    budget=dict(state='done',label='已提交',note='所选批次已有提交记录，查看不会重新提交。') if selected else dict(state='ready',label='已准备 · 未提交',note='已有清单保留，可恢复后核对预算。') if valid else dict(state='attention',label='原清单需核对',note='已有准备记录但当前核对未通过，先查看原因。') if pending else dict(state='waiting',label='尚未准备',note='在已有输入包处准备清单，再明确提交。')
    if selected and pending:budget=dict(state='ready' if valid else 'attention',label=f'已提交 · 另有 {len(pending)} 份清单',note='既有批次保留；另有未提交准备清单，可在下方核对并恢复。')
    if not selected and history:
        run=dict(state='check',label='已有关联计算',note='历史准备已关联计算批次；请打开批次核对结果接受情况。')
        if not pending:budget=dict(state='done',label='已有提交记录',note='准备清单已有匹配批次，折叠到历史记录；查看不会再次提交。')
        else:budget=dict(state='ready' if valid else 'attention',label=f'已有提交 · 另有 {len(pending)} 份清单',note='历史批次保留；其余清单需分别核对。')
    nodes=[dict(id='prepare',title='四因素准备',state='ready' if cap['supported'] else 'attention',label='可生成输入' if cap['supported'] else '设置需核对',note='当前组合支持生成；生成时继续检查来源文件。' if cap['supported'] else '；'.join(cap['reasons'])),
        dict(id='inputs',title='输入核对',state='ready' if activity['inputs'] else 'waiting',label=f'{len(activity["inputs"])} 份已登记' if activity['inputs'] else '尚未生成',note='输入包绑定当前保存版本，打开时继续核验文件与变化。'),
        dict(id='budget',title='预算与提交',**budget),dict(id='results',title='计算与复核',**run),
        dict(id='compare',title='对照与出图',state='check' if activity['comparisons'] else 'waiting',label=f'{len(activity["comparisons"])} 组已绑定' if activity['comparisons'] else '尚未建对照',note='本总览显示已保存比较关系，尚未读取双方配对结果；进入比较查看已有结果或选择双方批次。单批结果也可独立查看与导出。')]
    branches=None
    active=any(c.get('mode')=='calendar' for c in record['factors']['condition']['controls'])
    if branch or active:
        from calendar_library import prepare
        if not defer_branch:branches=calendar_branch(record,prepare(record,catalog,root))
    return dict(checked_at=now(),record_sha256=digest(record),saved_sha256=digest(saved),id=saved['id'],revision=saved['revision'],dirty=dirty,same_recipe=same_recipe,
        nodes=nodes,branches=branches,selected_batch=selected['id'] if selected else None,batches=batches,verified=verified,preparations=pending,preparation_history=history,
        comparisons=activity['comparisons'],inputs=activity['inputs'],other_versions=activity['other_versions'],issues=activity['issues']+issues,
        scope_sites=len(record['factors']['scope']['site_ids']),new_simulations=0)

def restore(record,review,catalog,store,root=ROOT):
    """Reopen a known frozen review; never create another one or submit it."""
    rows,_=preparations(record,{},root,bindings=source_bindings(catalog,root,record))
    item=next((x for x in rows if x['id']==review),None)
    if not item or not item['valid']:raise ValueError('此版本的未提交清单已变化或核对未通过，请刷新流程。')
    from execution_inputs import public
    plan=read_json(owned(Path(root)/'data/execution/reviews'/review/'plan.json',root))
    return dict(public(plan,root),preparation_reused=True,existing_batch=None)


def calendar_branch(record,p):
    active=any(c.get('mode')=='calendar' for c in record['factors']['condition']['controls'])
    rows=p['rows'];ready=sum(r['ready'] for r in rows);total=len(record['factors']['scope']['site_ids'])
    applied=[x for x in p['bound'] if x['active'] and x['valid']]
    ordinary=record['provenance']['adapter']=='ordinary_building_v1'
    return dict(optional=not active,ready=ready,total=total,issues=p['issues'],rows=[dict(city=r['city'],ready=r['ready'],issues=r['issues'],orientation_input=r.get('orientation_input',{}).get('note')) for r in rows],nodes=[
        dict(id='reference',title='原构造逐日参考',state='done' if total and ready==total else 'attention',label=f'{ready}/{total} 地点就绪',note='按本方案实际建筑、气象、温控和步长匹配。'),
        dict(id='calendar',title='日历版本',state='done' if applied else 'ready' if p['can_save'] else 'attention',label='已采用 · 条件匹配' if applied else '可预览 / 保存' if p['can_save'] else '参考需核对',note='独立保存不等于已采用到研究方案。'),
        dict(id='orientation',title='翻面执行',state='ready' if p['can_apply'] or applied else 'attention',label='可继续核对' if p['can_apply'] or applied else '材料 / 条件需核对',note='；'.join(p['application_issues']) or '五层固定 R 翻面短期核查与统一队列已接通；采用后保存方案，再准备计算。' if ordinary else '；'.join(p['application_issues']) or '采用与保存方案仍需明确操作。')])
