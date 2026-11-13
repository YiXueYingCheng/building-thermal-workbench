"""Daily reference registration is the accepted, identity-bound queue result.

No duplicate result library or automatic warning acceptance. Every read rechecks
the immutable plan, accepted result, source files and full daily SQL coverage.
"""
from pathlib import Path
from foundation import ROOT,read_json,sha,owned,digest
import output_storage
from daily_reference import CONTRACT,verify_sql,daily_csv,require


def inspect(model,case,evidence,root):
    require(evidence.get('accepted') is True,'逐日参考结果尚未接受。')
    require(case.get('output_contract')==CONTRACT,'算例不是逐日参考输出。')
    result_path=output_storage.checked_path(evidence['result_path'],root)
    require(sha(result_path)==evidence['result_sha256'],'结果汇总发生变化。')
    result=read_json(result_path)
    require(result.get('output_contract')==CONTRACT and result['status']=='passed' and not result['pending_warnings'],'逐日参考输出或接受状态不符。')
    from execution_results import verify_artifacts,close
    verify_artifacts(result)
    def artifact(name):
        paths=[output_storage.checked_path(p,root) for p in result['artifacts'] if Path(p).name==name]
        require(len(paths)==1,'逐日参考缺少唯一的 '+name)
        return paths[0]
    sql=artifact('eplusout.sql');csv=artifact('daily-loads.csv');actual_model=artifact('model.epJSON')
    require(sha(actual_model)==case['model_sha256'] and read_json(actual_model)==model,'运行模型与冻结清单不一致。')
    checked=verify_sql(sql,model,case['step_minutes'])
    require(checked==result.get('daily_reference'),'逐日核验记录与实际 SQL 不一致。')
    require(csv.read_bytes()==daily_csv(checked).encode('utf-8-sig'),'逐日 CSV 与核验数据不一致。')
    for key,value in checked['totals'].items():close(value,result['loads'][key])
    require(len(result['monthly'])==12,'父结果月度汇总不完整。')
    for a,b in zip(checked['monthly'],result['monthly']):
        require(a['month']==b['month'],'父结果月份不一致。')
        for key in checked['totals']:close(a[key],b[key])
    require(sha(result_path)==evidence['result_sha256'],'读取期间结果变化。')
    return dict(status='verified',usable=True,message='365 天逐日冷热需求已核验，运行结果及接受依据已核对。日历生成适配另行检查。',
        contract=CONTRACT,days=365,totals=checked['totals'],data_sha256=digest(checked),csv_path=str(csv),csv_sha256=sha(csv))


def registered(root,batch_id,index):
    """Read a specific registered queue result; never accepts a raw upload."""
    from reference_readiness import queue_snapshot,frozen_batch,result_evidence
    from execution_inputs import load_review
    require(type(index) is int and index>=0,'算例编号无效。')
    root=Path(root).resolve();batches,jobs=queue_snapshot(root)
    matches=[b for b in batches if b['id']==batch_id];require(len(matches)==1,'批次不存在。')
    b=matches[0];p,r,folder=frozen_batch(b,root);load_review(root,b['review'],b['checksum'])
    require(p['output_contract']==CONTRACT and index<len(p['cases']),'不是有效的逐日参考算例。')
    c=p['cases'][index];evidence=result_evidence(jobs.get((batch_id,index)),c,root)
    model=read_json(owned(folder/c['model_file'],folder))
    return inspect(model,c,evidence,root)


def csv_bytes(root,batch_id,index):
    data=registered(root,batch_id,index);p=Path(data['csv_path']);content=p.read_bytes()
    import hashlib
    require(hashlib.sha256(content).hexdigest()==data['csv_sha256'],'下载期间逐日数据变化。')
    return content
