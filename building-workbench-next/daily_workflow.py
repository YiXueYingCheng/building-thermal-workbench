"""Read-only preparation lifecycle; queue and accepted evidence remain authoritative."""
from collections import Counter
from contextlib import closing
from pathlib import Path
import sqlite3
from foundation import read_json,now,owned
from daily_reference import CONTRACT,record_key,require_baseline
from execution_inputs import public
from preparation_recovery import checked
import reference_readiness as rr


def registry(root):
    path=Path(root)/'data/execution/preparations.sqlite'
    if not path.exists():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM preparations ORDER BY created DESC,rowid DESC')]


def exact_record(plan,record,folder):
    return (plan.get('record_id'),plan.get('revision'),plan.get('output_contract'))==(record['id'],record['revision'],CONTRACT) and record_key(read_json(folder/'record.json'))==record_key(record)


def batch_label(mode,counts):
    if counts.get('running'):return '计算中 · 等待当前完成后暂停' if mode=='pause' else '计算中'
    if counts.get('pending'):return '已提交 · 暂停' if mode=='pause' else '已提交 · 排队'
    if counts.get('review'):return '计算结束 · 待复核'
    if counts.get('failed'):return '计算结束 · 有失败'
    if counts.get('interrupted'):return '计算中断'
    if counts.get('cancelled'):return '批次结束 · 含取消'
    return '计算已结束 · 可用性见逐日核对'


def build(record,catalog,root,input_ready=True):
    root=Path(root).resolve();batches,jobs=rr.queue_snapshot(root)
    out=dict(checked_at=now(),state='none',label='尚未创建逐日清单',preparations=[],batches=[],sites=[],issues=[],
        note='收起只隐藏清单，输入文件继续保留；未提交的清单不排队、不占计算进程。可从这里恢复，不必重新生成。')
    for item in registry(root):
        try:
            folder=owned(root/'data/execution/reviews'/item['review'],root)
            plan=read_json(folder/'plan.json')
            if not exact_record(plan,record,folder):continue
            # Submitted reviews belong to batches, not to the unsubmitted list.
            if any(b['review']==item['review'] for b in batches):continue
            row=dict(id=item['review'],plan_sha256=item['checksum'],created=plan['created'],valid=False,site_ids=[c['site_id'] for c in plan['cases']],issue='')
            out['preparations'].append(row)
            try:
                checked(root,item['review'],item['checksum'],item['bundle_id'],item['bundle_sha256'],record)
                row['valid']=True
            except (ValueError,KeyError,TypeError,OSError) as exc:row['issue']='原清单保留，需核对后恢复：'+str(exc)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            out['issues'].append('清单登记未能读取：'+str(exc))
    ready=rr.build(record,catalog,root) if input_ready else dict(rows=[],issues=[])
    out['issues'].extend(ready['issues']);related=set()
    for row in ready['rows']:
        candidates=[c for c in row['candidates'] if c['input_match'] and c.get('daily',{}).get('contract')==CONTRACT]
        # Pending/review results have no verified daily payload yet: use the frozen contract.
        for c in row['candidates']:
            if c['input_match'] and c not in candidates:
                b=next((b for b in batches if b['id']==c['batch_id']),None)
                if b:
                    try:
                        plan,_,_=rr.frozen_batch(b,root)
                        if plan['output_contract']==CONTRACT:candidates.append(c)
                    except (ValueError,KeyError,TypeError,OSError):pass
        for c in candidates:related.add(c['batch_id'])
        usable=[c for c in candidates if c['accepted'] and c['daily']['usable']]
        site=dict(site_id=row['site_id'],city=row['city'],ready=bool(usable),downloads=[],label='尚无可用逐日结果')
        for c in usable:site['downloads'].append(dict(batch_id=c['batch_id'],index=c['index']))
        if usable:site['label']='已有可用逐日参考'
        elif candidates:site['label']='已有匹配批次 · 结果尚不可用'
        elif any(p['valid'] and row['site_id'] in p['site_ids'] for p in out['preparations']):site['label']='已准备清单 · 未提交'
        out['sites'].append(site)
    for b in batches:
        try:
            plan,_,folder=rr.frozen_batch(b,root)
            if plan['output_contract']!=CONTRACT:continue
            exact=exact_record(plan,record,folder)
            if not exact and b['id'] not in related:continue
            counts=Counter(j['status'] for (bid,_),j in jobs.items() if bid==b['id'])
            out['batches'].append(dict(id=b['id'],created=b['created'],record_name=plan['record_name'],revision=plan['revision'],
                label=batch_label(b['mode'],counts),counts=dict(counts),same_saved_version=exact))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            if b['id'] in related:out['issues'].append('批次未能核对：'+str(exc))
    count=sum(s['ready'] for s in out['sites']);total=len(record['factors']['scope']['site_ids'])
    out['summary']=dict(prepared=sum(p['valid'] for p in out['preparations']),submitted=len(out['batches']),daily_ready=count,sites=total)
    if input_ready and total and count==total:out.update(state='available',label='已有可用逐日参考')
    elif count:out.update(state='partial',label='部分地点已有可用逐日参考')
    elif out['batches']:out.update(state='submitted',label='已有提交批次')
    elif out['summary']['prepared']:out.update(state='prepared',label='已准备清单 · 未提交')
    elif out['preparations'] or out['issues']:out.update(state='needs_check',label='已有记录需核对')
    if not input_ready:out.update(state='input_blocked',label='当前输入尚未就绪')
    return out


def enrich(preview,record,catalog,root):
    preview['workflow']=build(record,catalog,root,preview['input_ready'])
    preview['storage_note']='以上为逐日输出规模，不是待运行任务数或磁盘估算。实际空间请查看计算清单预算中的实测样本。'
    return preview


def restore(root,record,review_id,checksum,expected_record_sha256):
    """Restore registered preparation for this exact saved record, without writes."""
    require_baseline(record)
    if record_key(record)!=expected_record_sha256:raise ValueError('保存版本与核对内容不同，请重新打开。')
    rows=[r for r in registry(root) if (r['review'],r['checksum'])==(review_id,checksum)]
    if len(rows)!=1:raise ValueError('清单未在准备记录中唯一登记，请重新核对。')
    r=rows[0];plan=checked(root,review_id,checksum,r['bundle_id'],r['bundle_sha256'],record)
    folder=Path(root)/'data/execution/reviews'/review_id
    if not exact_record(plan,record,folder):raise ValueError('清单不属于当前保存版本的逐日参考。')
    batches,_=rr.queue_snapshot(root);matches=[b for b in batches if b['review']==review_id]
    for b in matches:
        queued,_,_=rr.frozen_batch(b,root)
        if queued!=plan:raise ValueError('原批次与清单内容不同。')
    return dict(public(plan,root),preparation_reused=True,existing_batch={k:matches[0][k] for k in ('id','mode','created')} if matches else None,existing_batch_count=len(matches))
