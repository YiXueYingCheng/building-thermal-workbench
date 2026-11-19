"""Read an existing input bundle without regenerating or preparing calculations."""
from pathlib import Path
import re
from foundation import owned,read_json,sha,digest,now
from preparation_recovery import saved_input,submitted

def inspect(root,ident,store):
    root=Path(root).resolve();m,r,checksum=saved_input(root,ident,store)
    folder=owned(root/'data/model-inputs'/ident,root)
    if type(m['case_count']) is not int or m['case_count']!=len(m['cases']):raise ValueError('输入清单数量不一致。')
    anchors=submitted(root,ident)
    for b in anchors:
        p=b['plan']
        if not re.fullmatch(r'review_[a-f0-9]{32}',b['review']):raise ValueError('原批次清单编号无效。')
        review=owned(root/'data/execution/reviews'/b['review']/'plan.json',root)
        if sha(review)!=b['checksum'] or read_json(review)!=p:raise ValueError('原批次冻结清单变化，请保留并核查。')
        if (p['bundle_sha256'],p['record_id'],p['revision'],p['record_sha256'])!=(checksum,r['id'],r['revision'],digest(r)):
            raise ValueError('输入包与原批次冻结记录不一致。')
    seen=set()
    for c in m['cases']:
        name=c['model_file']
        if not isinstance(name,str) or not re.fullmatch(r'[0-9]{3,}\.epJSON',name) or name in seen:raise ValueError('输入模型文件名无效或重复。')
        seen.add(name);path=owned(folder/name,folder)
        if sha(path)!=c['model_sha256']:raise ValueError('输入模型内容变化：'+name)
        if c.get('audit'):
            audit=c['audit'];detail=owned(folder/audit['file'],folder)
            if audit.get('kind')!='case_audit_v1' or sha(detail)!=audit['sha256']:raise ValueError('算例详情校验不符，请保留输入包并核查。')
        elif digest(read_json(path))!=c['generated_model_digest']:raise ValueError('输入模型内容变化：'+name)
    if sha(folder/'manifest.json')!=checksum or read_json(folder/'record.json')!=r:raise ValueError('读取期间输入记录发生变化，请重新读取。')
    return dict(manifest=m,record={k:r[k] for k in ('id','revision','name')},operation_mode=r['factors']['condition']['operation']['mode'],
        period=r['factors']['scope']['period'],manifest_sha256=checksum,checked_models=len(seen),batch_anchor_count=len(anchors),checked_at=now())

def case_detail(root,ident,index,store):
    import copy,json
    from input_pipeline import read_audit
    m,r,checksum=saved_input(root,ident,store)
    if not 0<=index<len(m['cases']):raise ValueError('算例序号无效。')
    folder=owned(Path(root)/'data/model-inputs'/ident,root);row=m['cases'][index]
    model=owned(folder/row['model_file'],folder)
    if sha(model)!=row['model_sha256'] or digest(read_json(model))!=row['generated_model_digest']:raise ValueError('所选模型内容变化，请保留并核查。')
    fields=('city','mode','period','step_minutes','wall_assignments','wall_assignments_basis','differences',
        'usage_configuration','usage_version','operation_overrides','control_groups','source_model','weather','dependencies','calendar_binding','orientation_calendar','drawing_wall_scope')
    complete=read_audit(folder,row);report={k:copy.deepcopy(complete[k]) for k in fields if k in complete};del complete
    if isinstance(report.get('usage_version'),dict):report['usage_version']={k:report['usage_version'][k] for k in ('id','revision','name') if k in report['usage_version']}
    url=f'/api/model-inputs/{ident}/'+row.get('audit',{}).get('file','manifest.json')
    # Keep all paths and counts visible, read long values only on demand.
    for difference in report.get('differences',[]):
        for side in ('before','after'):
            value=difference.get(side)
            if isinstance(value,(dict,list)) and len(json.dumps(value,ensure_ascii=False))>2048:
                difference[side+'_preview']=dict(items=len(value),url=url)
                difference.pop(side,None)
    return dict(report,model_file=row['model_file'],audit_url=url,manifest_sha256=checksum)
