"""Bounded, read-only calendar inspection jobs shared by both viewing entries."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock
import copy,time,uuid
from foundation import digest,now
from inspection_io import reading
import calendar_library

TRANSITION_CONFIRMATION='出现多段或不确定季节，可查看完整曲线，但保存前需共同确认，不自动合并。'
LEGACY_APPLICATION_HINT='本建筑已接通日历预览和独立版本；材料朝向执行尚待适配，本轮不能启用翻面。'

def complete_pending_preview(record,result):
    """Cache viewing only when every source/day is present; never allow adoption."""
    if result.get('can_save') or result.get('can_apply') or result.get('issues'):
        return False
    if result.get('source_kind')!='accepted_queue_daily_v1':return False
    expected=record['factors']['scope']['site_ids'];rows=result.get('rows',[])
    if not expected or len(rows)!=len(expected) or {r.get('site_id') for r in rows}!=set(expected):return False
    pending=False
    for row in rows:
        preview=row.get('preview');source=row.get('source')
        if not preview or len(preview.get('days',[]))!=365 or not source or not source.get('batch_id'):return False
        if row.get('ready'):
            if row.get('issues') or (preview.get('transition_review_needed') and not row.get('transition_review',{}).get('confirmed')):return False
        else:
            if preview.get('transition_review_needed') is not True or row.get('issues')!=[TRANSITION_CONFIRMATION]:return False
            pending=True
    return pending

def display_result(result):
    # This presentation correction does not alter the calendar adapter or its
    # frozen model-input identity. Full calendars still use capability checks.
    if result.get('source_kind')=='accepted_queue_daily_v1' and not result.get('can_save'):
        result=copy.deepcopy(result)
        result['application_issues']=[
            '日历尚未就绪；请先完成逐日参考核对或季节切换确认，再核对材料与翻面执行。' if v==LEGACY_APPLICATION_HINT else v
            for v in result.get('application_issues',[])]
    return result

def inspection_key(record,catalog,transition_confirmations):
    if transition_confirmations is not None:
        from transition_confirmation import selections
        checked=selections(transition_confirmations)
        if not set(checked)<=set(record['factors']['scope']['site_ids']):raise ValueError('季节确认地点不在当前范围。')
        transition_confirmations=[checked[k] for k in sorted(checked)]
    return digest([record,catalog,transition_confirmations]),transition_confirmations

class Inspections:
    def __init__(self,root,prepare=None):
        self.root=Path(root);self.prepare=prepare or calendar_library.prepare
        self.lock=RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='calendar-view')
        self.jobs=OrderedDict();self.cache=OrderedDict();self.closed=False
    def start(self,record,catalog,force=False,transition_confirmations=None):
        key,transition_confirmations=inspection_key(record,catalog,transition_confirmations)
        with self.lock:
            for job in self.jobs.values():
                if job['key']==key and job['state'] in ('queued','running'):return self.public(job)
            if sum(j['state'] in ('queued','running') for j in self.jobs.values())>=3:
                raise ValueError('已有核对正在处理，请稍后重新核对。')
            while len(self.jobs)>=12:
                old=next((k for k,j in self.jobs.items() if j['state'] not in ('queued','running')),None)
                if old is None:break
                self.jobs.pop(old)
            job=dict(id=uuid.uuid4().hex,key=key,state='queued',progress=dict(stage='等待核对',completed=0,total=len(record['factors']['scope']['site_ids']),city=''),created=now())
            self.jobs[job['id']]=job
            self.pool.submit(self.run,job,copy.deepcopy(record),copy.deepcopy(catalog),force,copy.deepcopy(transition_confirmations))
            return self.public(job)
    def public(self,job):return copy.deepcopy({k:v for k,v in job.items() if k not in ('key','validated_monotonic')})
    def get(self,ident):
        with self.lock:
            if ident not in self.jobs:raise ValueError('核对记录已过期，请重新核对。')
            return self.public(self.jobs[ident])
    def update(self,job,**values):
        with self.lock:job.update(values)
    def run(self,job,record,catalog,force,transition_confirmations=None):
        start=time.perf_counter();key=job['key'];self.update(job,state='running')
        try:
            from manage import current
            if (self.root/'data/current.json').exists():
                if digest(current(self.root))!=digest(catalog):raise ValueError('来源目录已更新，请重新核对。')
            cached=self.cache.get(key)
            self.update(job,progress=dict(stage='检查来源变化',completed=0,total=job['progress']['total'],city=''))
            if not force and cached and time.monotonic()-cached['time']<300 and cached['evidence'].valid():
                result=cached['result'];reused=True
            else:
                with reading(lambda p:self.update(job,progress=p)) as reads:
                    # Pin a logical registry view. Dispatch/heartbeat bookkeeping
                    # may change while accepted sources and plans stay identical.
                    from inspection_registry import watch_queue
                    watch_queue(reads,self.root)
                    for suffix in ('','-wal','-journal'):reads.watch(self.root/'data'/('components.sqlite'+suffix))
                    for p in [*self.root.glob('*.py'),Path(__file__),Path(calendar_library.__file__),self.root/'data/current.json']:
                        reads.watch(p)
                    if (self.root/'data/current.json').exists():
                        from foundation import read_json
                        reads.watch(self.root/read_json(self.root/'data/current.json')['catalog'])
                    prepared=self.prepare(record,catalog,self.root) if transition_confirmations is None else self.prepare(record,catalog,self.root,transition_confirmations=transition_confirmations)
                    result=display_result(prepared)
                    self.update(job,progress=dict(stage='复核来源完整性',completed=len(result['rows']),total=job['progress']['total'],city=''))
                reused=False
                # Missing/invalid sources still require a fresh inspection.
                # Complete data awaiting a research decision may reuse a checked
                # read-only preview; its save/apply gates remain false.
                if result['can_save'] or complete_pending_preview(record,result):
                    self.cache[key]=dict(result=result,evidence=reads.evidence(),time=time.monotonic())
                    self.cache.move_to_end(key)
                    while len(self.cache)>4:self.cache.popitem(last=False)
                else:self.cache.pop(key,None)
            if (self.root/'data/current.json').exists() and digest(current(self.root))!=digest(catalog):
                raise ValueError('核对期间来源目录改变，请重新核对。')
            from plan_workflow import calendar_branch
            self.update(job,state='ready',result=result,branch=calendar_branch(record,result),reused=reused,validated_at=now(),validated_monotonic=time.monotonic(),elapsed_seconds=time.perf_counter()-start)
        except Exception as exc:
            self.cache.pop(key,None)
            self.update(job,state='error',error=str(exc),elapsed_seconds=time.perf_counter()-start)
    def for_adoption(self,ident,record,catalog,transition_confirmations=None):
        # The client sends only an inspection id and its expected hashes. The
        # result and complete source evidence always come from this service.
        key,_=inspection_key(record,catalog,transition_confirmations)
        problem='本次预览已过期、来源变化或选择不一致，请重新核对；尚未保存或采用。'
        with self.lock:
            job=self.jobs.get(ident) if isinstance(ident,str) else None
            cached=self.cache.get(key)
            if not job or job['state']!='ready' or job['key']!=key or not cached:raise ValueError(problem)
            if time.monotonic()-job.get('validated_monotonic',0)>300:raise ValueError(problem)
            result=cached['result']
            if not result.get('can_save') or result.get('content_sha256')!=job['result'].get('content_sha256'):raise ValueError(problem)
            evidence=cached['evidence']
        from manage import current
        if (self.root/'data/current.json').exists() and digest(current(self.root))!=digest(catalog):raise ValueError(problem)
        if not evidence.valid():raise ValueError(problem)
        return copy.deepcopy(result)
    def save_or_apply(self,ident,record,catalog,expected,accept,action,record_sha256,parent=None,transition_confirmations=None):
        if action not in ('save','apply') or accept is not True:raise ValueError('请明确接受本轮展示的参考来源、原警告和已有规则。')
        fresh=self.for_adoption(ident,record,catalog,transition_confirmations)
        return calendar_library._save_prepared(record,catalog,self.root,expected,accept,action,record_sha256,fresh,parent)
    def close(self):self.pool.shutdown(wait=True,cancel_futures=True)
