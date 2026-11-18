"""Read-only validation of a result's scientific acceptance evidence.

This does not decide whether a warning is acceptable or change the queue.
Acceptance is bound to its original result, exact evidence, and stated scope.
"""
from pathlib import Path
from foundation import ROOT, read_json, sha, owned
import output_storage

LABELS = {
    'user_review_with_notes_v1': '用户判断与用途说明（非自动消除警告）',
    'annual_warmup_sensitivity_assessment': '年度初始化敏感性与原警告复核',
    'corrected_five_storey_full_weather_function_replay': '修正基准核对与全年天气函数事件复核',
    'corrected_five_storey_exact_event_replay': '修正基准核对与同引擎湿球函数复核',
    'five_storey_flip_exact_event_function_replay': '同引擎湿球函数重放与翻面输入核查',
    'full_year_boundary_intervention_pair': '全年原样与修正边界对照',
    'same_engine_full_year_function_replay_and_prior_weather_review': '全年数值函数复核与已审查气象核对',
}
SCOPE_LABELS = {
    'user_review_with_notes_v1': '用户判断与用途说明（非自动消除警告）',
    'Frozen W00 model, 5 min, controlled sensible heating/cooling demand; same adopted weather and disabled rain/wetbulb-dependent equipment paths':
        '本次冻结的 W00 模型，5 min 步长，温控显热冷热需求；沿用所采用的气象，关闭雨淋及依赖湿球温度的设备。',
}


def reviewed(result, root=ROOT):
    review = result.get('scientific_review')
    if not review:
        if result.get('reviewed_warnings'):
            raise ValueError('结果含已复核警告，但缺少接受依据，请核查。')
        return None
    try:
        original = output_storage.checked_path(review['original_result'], root)
        evidence_path = owned(review['evidence'], Path(root)/'verification')
        if sha(original) != review['original_result_sha256'] or sha(evidence_path) != review['evidence_sha256']:
            raise ValueError('原结果或复核依据内容发生变化')
        raw, evidence = read_json(original), read_json(evidence_path)
        if raw['status'] != 'review' or result['status'] != 'passed' or result['pending_warnings']:
            raise ValueError('原结果和接受状态不一致')
        if result.get('reviewed_warnings') != raw['pending_warnings'] or not raw['pending_warnings']:
            raise ValueError('原警告与复核记录不一致')
        for key in raw:
            if key not in ('status', 'pending_warnings') and result.get(key) != raw[key]:
                raise ValueError('复核副本改变了原结果内容')
        matches = [r for r in evidence.get('review_conclusions', [])
                   if r.get('identity') == result['identity'] and r.get('site_id') == result['site_id']
                   and Path(r.get('original_result', '')).resolve() == original
                   and r.get('original_result_sha256') == review['original_result_sha256']]
        if evidence.get('passed') is not True or len(matches) != 1:
            raise ValueError('依据中没有该结果的唯一接受结论')
        conclusion = matches[0]
        if review['decision'] != 'accepted_with_notes' or conclusion['decision'] != review['decision']:
            raise ValueError('复核结论未接受该结果')
        if not review['scope'] or review['scope'] != conclusion['scientific_scope'] or review['evidence_kind'] != conclusion['evidence_kind']:
            raise ValueError('接受范围与依据不一致')
        user=review['evidence_kind']=='user_review_with_notes_v1'
        decision=conclusion.get('user_decision',{})
        if user:
            if evidence.get('automatic_warning_clearance') is not False or not evidence.get('technical_checks_passed'):
                raise ValueError('用户审阅缺少独立完整性检查或警告保留声明')
            if not all(isinstance(decision.get(k),str) and decision[k].strip() for k in ('reviewer','reason','scope')) or decision.get('acknowledged') is not True:
                raise ValueError('用户审阅说明不完整')
            if decision['scope']!=review['scope']:
                raise ValueError('用户声明的用途发生变化')
        return dict(decision='accepted_with_notes',label=('用户强制采用' if decision.get('acceptance_mode')=='bulk_force' else '用户审阅后采用') if user else '附说明接受',
                    evidence_kind=review['evidence_kind'],user_decision=decision if user else None,
                    method=LABELS.get(review['evidence_kind'],'逐项科研复核'),
                    reviewed_at=review['reviewed_at'],scope=review['scope'],display_scope=SCOPE_LABELS.get(review['scope'],review['scope']),
                    note=('用户自行判断警告对所述用途的影响；平台仅核对完整性，未证明警告无害。' if user else '结论仅适用于本次冻结输入与研究指标；原始警告和结果保留。'),
                    warnings=raw['pending_warnings'],original_result=str(original),
                    original_result_sha256=review['original_result_sha256'],
                    evidence=str(evidence_path),evidence_sha256=review['evidence_sha256'])
    except (KeyError, TypeError, OSError, ValueError) as error:
        raise ValueError('科学复核记录未能核对，暂不读取或导出该结果：'+str(error)) from error
