"""User-confirmed batch adoption of complete results; never invent failed outputs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3, threading, time, uuid, re
from foundation import read_json, write_json, sha, now, owned
import result_review


def selection(root, batch=None):
    if batch is not None and not re.fullmatch(r'batch_[a-f0-9]{32}',str(batch)):
        raise ValueError('批次编号无效。')
    path=Path(root)/'data/execution/queue.sqlite'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT batch,idx,status,identity,attempt,result,result_sha256 FROM jobs'+
              (' WHERE batch=?' if batch else '')+' ORDER BY batch,idx',(batch,) if batch else ())]
    return rows


class BulkReviews:
    def __init__(self,root,reviews):
        self.root=Path(root);self.reviews=reviews;self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='bulk-review')
        self.owner=uuid.uuid4().hex;self.active=set()
    def folder(self,ident):
        if not re.fullmatch(r'bulk_[a-f0-9]{32}',str(ident)):raise ValueError('批量复核编号无效。')
        return owned(self.root/'verification/bulk-reviews'/ident,self.root)
    def write(self,p,job,**changes):
        with self.lock:
            job.update(changes);write_json(p/'job.json',job,self.root)
    def get(self,ident):
        p=self.folder(ident);j=read_json(p/'job.json');j.pop('decision',None)
        if j.get('owner')!=self.owner and j['state'] in ('checking','accepting'):
            j.update(state='interrupted',error='服务已重启。已登记的采用结论保留；请重新预览其余待复核结果。')
        j.pop('owner',None)
        if (p/'preview.json').exists():j.update(preview=read_json(p/'preview.json'),preview_sha256=sha(p/'preview.json'))
        return j
    def start(self,batch=None):
        with self.lock:
            if self.active:raise ValueError('已有批量复核正在处理，请等待完成。')
            rows=selection(self.root,batch);targets=[r for r in rows if r['status']=='review']
            ident='bulk_'+uuid.uuid4().hex;p=self.folder(ident)
            job=dict(id=ident,owner=self.owner,created=now(),state='checking',batch=batch,total=len(targets),completed=0)
            self.write(p,job);self.active.add(ident);self.pool.submit(self.check,p,job,targets,rows)
            return self.get(ident)
    def check(self,p,job,targets,all_rows):
        items=[]
        try:
            for target in targets:
                item=dict(batch=target['batch'],index=target['idx'],eligible=False)
                try:
                    # Bind to the exact snapshot shown by this preview, never later jobs.
                    _,current,raw=result_review.target(self.root,item['batch'],item['index'])
                    if result_review.binding(current)!=result_review.binding(target) or current['status']!='review':
                        raise ValueError('结果状态已变化，请刷新后重新预览。')
                    item.update(city=raw.get('city'),warnings=raw.get('pending_warnings',[]))
                    record=self.reviews.start(item['batch'],item['index'],True)
                    while record['state'] in ('queued','running'):
                        time.sleep(.15);record=self.reviews.get(record['id'])
                    report=record.get('report',{})
                    if record['state']!='ready' or report.get('recommendation')!='user_decision':
                        raise ValueError(report.get('explanation') or record.get('error') or '完整性检查未通过。')
                    item.update(eligible=True,review_id=record['id'],report_sha256=record['report_sha256'],scope=report['scope'])
                except (ValueError,OSError,KeyError,TypeError) as exc:item['error']=str(exc)
                items.append(item);self.write(p,job,completed=len(items))
            preview=dict(created=now(),batch=job['batch'],scope='当前批次' if job['batch'] else '整个工作区',items=items,
                eligible=sum(i['eligible'] for i in items),blocked=sum(not i['eligible'] for i in items),
                failed=sum(r['status']=='failed' for r in all_rows),unfinished=sum(r['status'] in ('pending','running','interrupted') for r in all_rows),
                warning='强制采用只记录你的决定，不证明警告无害。原日志和数值保留，结果以“用户强制采用”参与比较和导出。计算失败或资料不完整的算例不改为通过。')
            write_json(p/'preview.json',preview,self.root);self.write(p,job,state='ready')
        except Exception as exc:self.write(p,job,state='error',error=str(exc))
        finally:
            with self.lock:self.active.discard(job['id'])
    def accept(self,ident,expected,decision,confirmed=False):
        if confirmed is not True:raise ValueError('请在弹窗中确认强制采用的范围和提示。')
        with self.lock:
            p=self.folder(ident);job=read_json(p/'job.json')
            if sha(p/'preview.json')!=expected:raise ValueError('批量复核预览已变化，请重新查看。')
            if job['state'] in ('done','accepting'):return self.get(ident)
            if job['state']!='ready' or self.active:raise ValueError('请先完成批量预览，或等待当前处理结束。')
            if not isinstance(decision,dict) or any(not isinstance(decision.get(k),str) or not 1<=len(decision[k].strip())<=limit
                    for k,limit in [('reviewer',80),('reason',3000),('scope',2000)]):raise ValueError('请填写审阅人、采用说明和用途范围。')
            preview=read_json(p/'preview.json')
            if not preview['eligible']:raise ValueError('没有完整性检查通过的待复核结果。')
            clean={k:decision[k].strip() for k in ('reviewer','reason','scope')}
            clean.update(acknowledged=True,acceptance_mode='bulk_force',bulk_review_id=ident)
            self.write(p,job,state='accepting',decision=clean,completed=0,total=preview['eligible'],outcomes=[])
            self.active.add(ident);self.pool.submit(self.adopt,p,job,preview,clean)
            return self.get(ident)
    def adopt(self,p,job,preview,decision):
        outcomes=[]
        try:
            for row in preview['items']:
                if not row['eligible']:continue
                out={k:row[k] for k in ('batch','index','review_id')}
                try:
                    done=result_review.accept(self.root,row['review_id'],row['report_sha256'],decision)
                    out.update(status='adopted',acceptance=done)
                except Exception as exc:out.update(status='not_adopted',error=str(exc))
                outcomes.append(out);self.write(p,job,completed=len(outcomes),outcomes=outcomes)
            self.write(p,job,state='done',finished=now(),adopted=sum(x['status']=='adopted' for x in outcomes))
        except Exception as exc:self.write(p,job,state='error',error=str(exc),outcomes=outcomes)
        finally:
            with self.lock:self.active.discard(job['id'])
    def close(self):self.pool.shutdown(wait=True,cancel_futures=False)
