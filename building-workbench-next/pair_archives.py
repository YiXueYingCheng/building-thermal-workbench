"""Resolve both sides from one verified set export, pinned to the actual input hashes."""
import re
import coverage_results
import comparison_results

from comparison_reading import verified_export
from foundation import digest,owned,read_json
from research_sets import require


def record_key(record):
    return record['id'],record['revision'],digest(record)


def monthly_case(record, site, archived, root):
    """Follow an exported case to its original result, retaining its exact identity."""
    evidence=archived.get('evidence') or {}
    identifiers=('batch_id','index','result_sha256','model_sha256')
    require(all(evidence.get(k) not in (None,'') for k in identifiers),'归档未记录完整的批次、算例与文件校验值。')
    def matches(case):
        return (case and case.get('monthly') and not case.get('pending_warnings')
                and case.get('status') in ('passed','reused')
                and all(case.get('evidence',{}).get(k)==evidence[k] for k in identifiers)
                and all(case.get(k)==archived.get(k) for k in ('loads','mode','period','step_minutes','weather_sha256','days')))
    found=None
    for option in coverage_results.sources(record,root):
        case=coverage_results.observed(record,option['id'],root)['cases'].get(site)
        if matches(case):
            require(found is None or case['monthly']==found['monthly'],'同一原始结果有不同的月度记录，请复查来源。')
            found=case
    if found is not None:return found
    batch=evidence['batch_id']
    if re.fullmatch(r'batch_[0-9a-f]{32}',batch) and comparison_results.batch_rows(root,batch):
        case=comparison_results.execution(record,batch,archived['mode'],root)['cases'].get(site)
        if matches(case):return case
    raise ValueError('尚未找到与归档批次、模型和结果校验值一致的月度记录。')


def load(sets,root,ident,wanted,*,min_matches=2):
    require(isinstance(ident,str) and re.fullmatch(r'set_export_[0-9a-f]{32}',ident),'组导出编号无效。')
    folder=owned(root/'data/research-set-exports'/ident,root)
    receipt=read_json(owned(folder/'receipt.json',folder))
    group=sets.evidence_version(receipt['set_id'],receipt['revision'])
    roles={}
    for role,member in group['members'].items():
        ref=member['record']
        k=(ref['id'],ref['revision'],ref['sha256'])
        if k in wanted:
            require(k not in roles,'同一导出有多项使用相同版本，请在原组核对。')
            roles[k]=role
    if len(roles)<min_matches:
        return None
    selected=verified_export(folder,receipt,group)
    return dict(id=ident,group=group['name'],revision=group['revision'],
                cases={k:selected[role] for k,role in roles.items()})


def for_members(reader,records,notices,*,min_matches=2):
    root=reader.store.root
    wanted={record_key(r) for r in records}
    found=[]
    for folder in sorted((root/'data/research-set-exports').glob('set_export_*')):
        try:
            data=load(reader.sets,root,folder.name,wanted,min_matches=min_matches)
        except (OSError,ValueError,KeyError,TypeError):
            notices.append('一份组导出需要重新核对来源。')
            continue
        if data:found.append(data)
    return found


def matching(exports,left,right):
    keys=[record_key(left),record_key(right)]
    distinct={}
    for export in exports:
        if all(k in export['cases'] for k in keys):
            signature=digest([export['cases'][k] for k in keys])
            distinct.setdefault(signature,export)
    return list(distinct.values())
