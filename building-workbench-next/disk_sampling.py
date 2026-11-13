"""Small independent observer of active attempt directories; never controls jobs."""
from contextlib import closing
import datetime as dt
import json
import msvcrt
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from foundation import ROOT, owned, read_json, write_json, sha, digest, now
import output_storage

INTERVAL=5.0
PATTERN=r'attempt_[a-f0-9]{32}'


def measure(folder):
    """Logical file lengths, not allocated blocks; never follow links."""
    total=count=0
    for base,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs:
            p=Path(base)/name
            if p.is_symlink() or p.is_junction():raise ValueError('执行目录含链接，未展开采样')
        for name in files:
            p=Path(base)/name
            if p.is_symlink():raise ValueError('执行目录含链接文件')
            total+=p.stat().st_size;count+=1
            if count>10000:raise ValueError('执行目录文件数异常，停止本次采样')
    return total,count


def observation_path(root,attempt):
    if not re.fullmatch(PATTERN,str(attempt)):raise ValueError('执行编号无效')
    return owned(Path(root)/'data/execution/disk-observations'/(attempt+'.json'),root)


def load_observations(root):
    rows=[];issues=[]
    for p in sorted((Path(root)/'data/execution/disk-observations').glob('*.json')):
        try:
            r=read_json(p);h=r.pop('sha256')
            if digest(r)!=h or p!=observation_path(root,r['attempt']):raise ValueError('采样记录摘要或编号不符')
            needed=('schema','finalized','late_start','max_gap_seconds','failed_samples','clock_discontinuity','active_sample_count','sample_count','peak_bytes','city','status','batch','index','identity','last_observed_at')
            if any(k not in r for k in needed) or r['schema']!=1:raise ValueError('采样记录格式不完整')
            if any(type(r[k]) is not int or r[k]<0 for k in ('sample_count','active_sample_count','failed_samples')):raise ValueError('采样计数无效')
            rows.append(r)
        except (OSError,ValueError,KeyError,TypeError) as e:issues.append(dict(file=p.name,error=str(e)))
    return rows,issues


class Sampler:
    def __init__(self,root=ROOT,clock=time.time):
        self.root=Path(root).resolve();self.clock=clock;self.stop_event=threading.Event()
        rows,issues=load_observations(self.root)
        self.tracked={r['attempt']:r for r in rows if not r['finalized']}
        self.thread=None;self.lock=None;self.last_error='';self.last_poll=None
        self.initial_issues=issues

    def jobs(self):
        path=self.root/'data/execution/queue.sqlite'
        if not path.exists():return []
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT batch,idx,status,identity,attempt,pid FROM jobs')]

    def begin(self,j,stamp):
        path=observation_path(self.root,j['attempt'])
        if path.exists():raise ValueError('同一执行已有完成采样记录，未覆盖')
        folder=output_storage.attempt_folder(self.root,j['attempt'])
        if not folder.is_dir():raise ValueError('执行目录尚不可用')
        launch_path=folder/'launch.json';launch=read_json(launch_path)
        with closing(sqlite3.connect((self.root/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            b=db.execute('SELECT review,checksum,plan FROM batches WHERE id=?',(j['batch'],)).fetchone()
        if not b:raise ValueError('执行批次不存在')
        plan=json.loads(b[2]);review=owned(self.root/'data/execution/reviews'/b[0]/'plan.json',self.root)
        if sha(review)!=b[1] or read_json(review)!=plan:raise ValueError('冻结清单核验失败')
        c=plan['cases'][j['idx']]
        if launch['batch']!=j['batch'] or launch['pid']!=j['pid'] or launch['case']!=c or c['identity']!=j['identity']:
            raise ValueError('启动日志与排队身份不一致')
        if sha(folder/'model.epJSON')!=c['model_sha256']:raise ValueError('执行模型与冻结身份不一致')
        started=dt.datetime.fromisoformat(launch['started'])
        if started.tzinfo is None:raise ValueError('启动时间缺少时区')
        return dict(schema=1,attempt=j['attempt'],batch=j['batch'],index=j['idx'],identity=j['identity'],
            city=c['city'],mode=c['mode'],step_minutes=c['step_minutes'],started=launch['started'],
            launch_sha256=sha(launch_path),model_sha256=c['model_sha256'],plan_sha256=b[1],
            interval_seconds=INTERVAL,first_observed_at=stamp,last_observed_at=None,
            late_start=stamp-started.timestamp()>INTERVAL+2,clock_discontinuity=stamp<started.timestamp()-2,
            sample_count=0,active_sample_count=0,failed_samples=0,peak_bytes=None,peak_at=None,
            last_bytes=None,max_gap_seconds=0,finalized=False,status=j['status'],last_error=None)

    def save(self,r):
        write_json(observation_path(self.root,r['attempt']),dict(**r,sha256=digest(r)),self.root)

    def observe(self,r,stamp,active):
        previous=r['last_observed_at']
        if previous is not None:
            gap=stamp-previous;r['max_gap_seconds']=max(r['max_gap_seconds'],gap)
            if gap<0:r['clock_discontinuity']=True
        r['last_observed_at']=stamp
        try:
            folder=output_storage.attempt_folder(self.root,r['attempt'])
            if not folder.is_dir():raise ValueError('执行目录缺失')
            value,count=measure(folder)
            r['sample_count']+=1;r['active_sample_count']+=bool(active)
            r['last_bytes']=value;r['last_file_count']=count;r['last_error']=None
            if r['peak_bytes'] is None or value>r['peak_bytes']:r['peak_bytes']=value;r['peak_at']=stamp
        except (OSError,ValueError) as e:r['failed_samples']+=1;r['last_error']=str(e)

    def tick(self):
        if (self.root/'.recovery-copy.json').exists():raise ValueError('恢复副本禁止运行采样器')
        stamp=self.clock();jobs=self.jobs();current={j['attempt']:j for j in jobs if j['attempt']}
        self.last_poll=stamp;self.last_error=''
        for j in jobs:
            if j['status']!='running' or not j['pid'] or not j['attempt']:continue
            if j['attempt'] not in self.tracked:
                try:self.tracked[j['attempt']]=self.begin(j,stamp)
                except (OSError,ValueError,KeyError,TypeError,IndexError) as e:self.last_error=str(e);continue
        for ident,r in list(self.tracked.items()):
            j=current.get(ident)
            if j and (j['identity']!=r['identity'] or j['batch']!=r['batch'] or j['idx']!=r['index']):
                self.last_error='已有采样与任务身份冲突，未覆盖';continue
            active=bool(j and j['status']=='running')
            self.observe(r,stamp,active)
            r['status']=j['status'] if j else 'attempt_replaced'
            r['finalized']=not active
            self.save(r)
            if r['finalized']:del self.tracked[ident]

    def run(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception as e:self.last_error=str(e)
            self.stop_event.wait(INTERVAL)

    def start(self):
        if (self.root/'.recovery-copy.json').exists():raise ValueError('恢复副本禁止运行采样器')
        if self.thread and self.thread.is_alive():return
        path=owned(self.root/'data/execution/disk-sampler.lock',self.root);path.parent.mkdir(parents=True,exist_ok=True)
        try:
            self.lock=path.open('a+b');self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            if os.fstat(self.lock.fileno()).st_size==0:self.lock.write(b'0');self.lock.flush()
        except OSError as error:
            if self.lock:self.lock.close()
            self.lock=None;self.last_error='采样锁不可用，可能已有观测进程：'+str(error);return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self.run,name='workbench-disk-sampling',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=10)
        if self.thread and self.thread.is_alive():return # never release a live writer's lock
        if self.lock:
            self.lock.seek(0);msvcrt.locking(self.lock.fileno(),msvcrt.LK_UNLCK,1);self.lock.close();self.lock=None

    def status(self):
        return dict(enabled=True,running=bool(self.thread and self.thread.is_alive()),interval_seconds=INTERVAL,
            last_poll=self.last_poll,error=self.last_error)


def report(root=ROOT,observer=None):
    root=Path(root).resolve();rows,issues=load_observations(root)
    for r in rows:
        reasons=[]
        if r['late_start']:reasons.append('较晚开始')
        if r['max_gap_seconds']>INTERVAL*2+2:reasons.append('采样有间断')
        if r['failed_samples']:reasons.append('存在读取失败')
        if r['clock_discontinuity']:reasons.append('墙钟不连续')
        if not r['active_sample_count']:reasons.append('未取得运行中有效样本')
        r['coverage']='；'.join(reasons) or '已取得常规间隔样本'
    return dict(created=now(),observer=observer.status() if observer else dict(enabled=False,running=False,interval_seconds=INTERVAL),
        observations=rows,issues=issues,
        notes=['记录执行目录文件长度之和，每 5 秒一次；这是采样最大占用，不是保证捕获的瞬时绝对峰值，也不是整个磁盘的空闲空间。',
               '只观测本工作区正在运行的算例，队列读取和目录采样不改变计算、并行或资源保留设置。',
               '关闭网页后页面服务继续运行即可采样；服务停止或重启造成的缺口保留标记。没有运行时不回填历史峰值。',
               '采样摘要单独保存，纳入以后创建的本地备份；当前不据此自动调整调度或给出硬性磁盘容量保证。'])
