"""On-demand evidence availability; does not change acceptance, files or reuse rules."""
from pathlib import Path
from contextlib import closing
import hashlib,json,re,sqlite3,time,stat
from foundation import now
import output_storage
from storage_management import safe_child

LABELS={'verified':'核对一致','missing':'文件缺失','changed':'校验不一致','unknown':'未知／待核对'}
BULK={'eplusout.sql','eplusout.csv','eplusout.eso','eplusout.mtr'}

def jobs(root,batch):
 if not re.fullmatch(r'batch_[a-f0-9]{32}',str(batch)):raise ValueError('批次编号无效。')
 p=safe_child(root,Path(root)/'data/execution/queue.sqlite')
 with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
  db.row_factory=sqlite3.Row;db.execute('BEGIN')
  if not db.execute('SELECT 1 FROM batches WHERE id=?',(batch,)).fetchone():raise ValueError('未找到该批次。')
  return [dict(r) for r in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx',(batch,))]

def listing(root,batch):
 return dict(batch=batch,checked_at=now(),cases=[dict(index=j['idx'],status=j['status'],attempt=j.get('attempt'),has_summary=bool(j.get('result'))) for j in jobs(root,batch)],
  note='登记状态保留当时结论；逐项核对现在的文件。打开列表不扫描全部原始结果。')

def stamp(p):
 s=p.stat();return (s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev)

def path_checked(root,path):
 raw=Path(path)
 if not raw.is_absolute():raise ValueError('资料路径不是完整路径。')
 if raw.is_relative_to(Path(root).resolve()):safe_child(root,raw)
 return output_storage.checked_path(raw,root)

def check_file(root,path,checksum,deadline):
 row=dict(path=str(path),name=Path(str(path)).name,status='unknown',bytes=None,reason='')
 try:
  if not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum):raise ValueError('原登记校验值无效。')
  # Verify an external location before deciding that a file is missing.
  p=path_checked(root,path)
  if not p.exists():row.update(status='missing',reason='保存位置可访问，但未找到文件。');return row,None
  if not stat.S_ISREG(p.stat().st_mode):raise ValueError('不是普通文件。')
  before=stamp(p);row['bytes']=before[0];h=hashlib.sha256()
  with p.open('rb') as f:
   while True:
    if time.monotonic()>deadline:raise ValueError('超过本次核对时间；本项未完成，不能当作一致。')
    chunk=f.read(1024**2)
    if not chunk:break
    h.update(chunk)
  if stamp(p)!=before:raise ValueError('读取期间文件发生变化，请重新核对。')
  row.update(status='verified' if h.hexdigest()==checksum else 'changed',reason='' if h.hexdigest()==checksum else '内容与原结果登记不一致。')
  return row,(p,before)
 except (OSError,ValueError,TypeError) as e:row['reason']=str(e);return row,None

def inspect(root,batch,index,budget_seconds=30):
 root=Path(root).resolve()
 if type(index) is not int or index<0:raise ValueError('算例序号无效。')
 row=next((j for j in jobs(root,batch) if j['idx']==index),None)
 if row is None:raise ValueError('未找到该算例。')
 deadline=time.monotonic()+budget_seconds;files=[];watches=[];issues=[];raw=None
 report=dict(batch=batch,index=index,attempt=row.get('attempt'),registered_status=row['status'],checked_at=now(),summary=None,files=files,issues=issues)
 if row.get('result'):
  summary,watch=check_file(root,row['result'],row.get('result_sha256'),deadline);report['summary_file']=summary
  if watch:watches.append((summary,watch))
  if summary['status']=='verified':
   try:
    if summary['bytes']>8*1024**2:raise ValueError('汇总超过本次读取上限。')
    raw=json.loads(path_checked(root,row['result']).read_text('utf8'))
    if not isinstance(raw,dict) or raw.get('identity')!=row['identity']:raise ValueError('结果身份与任务登记不一致。')
    if raw.get('status') not in ('passed','review') or row['status'] not in ('passed','review','reused'):raise ValueError('任务与汇总状态需要核对。')
    if row['status'] in ('passed','reused') and raw['status']!='passed':raise ValueError('任务与汇总接受状态不一致。')
    artifacts=raw.get('artifacts')
    if not isinstance(artifacts,dict) or not 1<=len(artifacts)<=1000:raise ValueError('原始资料清单缺失或超出核对范围。')
    for path,checksum in artifacts.items():
     item,watch=check_file(root,path,checksum,deadline);files.append(item)
     if watch:watches.append((item,watch))
    report['summary']={k:raw.get(k) for k in ('status','city','site_id','mode','period','step_minutes','loads','monthly','temperature_extrema','pending_warnings','output_contract')}
   except (OSError,ValueError,TypeError,KeyError) as e:issues.append(str(e));raw=None
  else:issues.append('汇总文件未通过核对，暂不读取其中的数值。')
 else:issues.append('此算例尚未登记完成汇总。')
 # Detect writes during the multi-file read, without changing any source.
 for item,(p,before) in watches:
  try:
   if stamp(p)!=before:raise ValueError('核对期间资料变化，请重新核对。')
  except (OSError,ValueError) as e:item.update(status='unknown',reason=str(e));issues.append(str(e))
 if next((j for j in jobs(root,batch) if j['idx']==index),None)!=row:issues.append('核对期间任务登记发生变化，请重新核对。')
 summary_ok=raw is not None and not issues
 if not summary_ok:report['summary']=None
 complete=summary_ok and all(f['status']=='verified' for f in files)
 accepted=summary_ok and row['status'] in ('passed','reused') and raw['status']=='passed'
 retained=None
 if summary_ok:
  try:
   from summary_retention import verify,location
   if location(root,row['attempt']).exists():retained=verify(root,row,raw)
  except (OSError,ValueError,KeyError,TypeError):pass
 if retained:
  for f in files:
   if f['status']=='missing' and f['path'] in retained['removed_artifacts']:f.update(status='removed',reason='已按受控清理记录移除；原汇总保留。')
 report['data_retention']=retained
 report.update(state='summary_retained' if retained else 'complete' if complete else 'summary_only' if summary_ok else 'unavailable',
  state_label='明细已受控清理，原汇总可用' if retained else '已登记资料核对一致' if complete else '汇总可读，原始资料未全部通过' if summary_ok else '资料未知／需核对',
  summary_verified=summary_ok,artifacts_verified=complete,
  capabilities=[
   dict(name='查看此处已保存汇总',ready=summary_ok,detail='仅展示原记录，不构成重新接受结果。'),
   dict(name='现有比较、结果读取与新导出',ready=bool((complete or retained) and accepted),detail='比较口径及原接受范围仍需符合。仅匹配受控清理记录时允许保留汇总读取；手工删失或损坏仍拒绝。'),
   dict(name='结果复用与重新复核',ready=complete,detail='资料完整只是前提；复用仍核对计算身份，复核仍核对适用方法。'),
   dict(name='逐日参考、日历与明细分析',ready=None,detail='不能仅凭文件完整推定支持：还需实际输出频率、变量和有效参考；月度／全年汇总不等于已有逐时数据。')],
  retention=dict(executable=False,files=[f for f in files if f['name'].lower() in BULK],
   note='此处只说明影响。可另行预览受控清理；首批限本地独立常规通过结果，是否允许以引用和文件核对为准。',
   kept=['方案与版本、计算输入、历史任务与接受结论','原汇总数值、诊断日志及已导出文件；保留文件不保证其全部后续功能可用'],
   lost=['经受控清理后可继续读取、比较及导出已有汇总；不扩展原接受范围，也不生成缺失的逐时信息','依赖原始明细的复核、自动复用及逐日／日历参考核对将受影响','未输出的逐时变量不能从汇总还原；恢复需找回原文件或另行计算，不会自动重跑']),
  note='这是本次只读核对，不改写历史接受状态。保留汇总读取需匹配受控清理记录，复核及复用仍要求所需原始资料完整。外置位置不可访问时显示未知。')
 return report
