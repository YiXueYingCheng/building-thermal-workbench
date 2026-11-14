"""Explicit, file-specific retention evidence for presentation readers only."""
from pathlib import Path
import re,copy
from foundation import digest,read_json,sha,write_json
from storage_management import safe_child
import output_storage

NOTE='部分或全部明细已受控清理，保留原已接受汇总。可比较及导出已有时段／月度／房间汇总；不能还原已删明细，所需原始资料缺失时不能自动复用计算或重新核验。原接受范围和警告继续适用。'
FIELDS=('batch','idx','attempt','identity','result','result_sha256')
BULK={'run/eplusout.sql','run/eplusout.csv','run/eplusout.eso','run/eplusout.mtr'}
def binding(job):return {k:job[k] for k in FIELDS}
def location(root,attempt):
 if not re.fullmatch('attempt_[a-f0-9]{32}',str(attempt)):raise ValueError('运行编号无效。')
 return safe_child(root,Path(root)/'data/storage-management/retention'/(attempt+'.json'))
def write(root,payload):
 write_json(location(root,payload['binding']['attempt']),dict(payload=payload,sha256=digest(payload)),root)
def receipt(root,job):
 p=location(root,job['attempt'])
 if not p.exists():return None
 envelope=read_json(p);v=envelope['payload']
 if set(envelope)!={'payload','sha256'} or digest(v)!=envelope['sha256'] or v.get('kind')!='summary_retention_v1' or v.get('binding')!=binding(job):raise ValueError('保留汇总记录与原任务不一致。')
 if v.get('state') not in ('executing','complete'):raise ValueError('保留汇总记录状态无效。')
 folder=Path(root).resolve()/'runs'/job['attempt'][8:]
 seen=set()
 for row in v['files']:
  p=safe_child(root,Path(root)/row['relative'])
  if not p.is_relative_to(folder) or p.relative_to(folder).as_posix() not in BULK or str(p) in seen:raise ValueError('清理记录含非允许明细路径或重复项。')
  seen.add(str(p))
  if row['status'] not in ('removed','retained','pending') or not re.fullmatch('[a-f0-9]{64}',str(row['sha256'])):raise ValueError('清理记录不完整。')
 return v
def verify(root,job,result):
 """Missing files require a matching confirmed removal; changed/pending files never pass."""
 if not isinstance(result.get('artifacts'),dict) or not result['artifacts']:raise ValueError('结果缺少原始资料清单。')
 proof=receipt(root,job) if location(root,job['attempt']).exists() else None;missing=[]
 for name,checksum in result['artifacts'].items():
  p=output_storage.checked_path(name,root)
  if p.exists():
   if sha(p)!=checksum:raise ValueError('原始资料内容变化，不能按保留汇总读取：'+str(p))
   continue
  if proof is None:proof=receipt(root,job)
  allowed=next((r for r in proof['files'] if Path(root)/r['relative']==p and r['status']=='removed' and r['sha256']==checksum),None) if proof else None
  if not allowed or result['status']!='passed' or job['status']!='passed':raise ValueError('原始资料缺失且没有匹配的受控清理记录：'+str(p))
  missing.append(str(p))
 if proof:
  for row in proof['files']:
   p=Path(root)/row['relative']
   if row['status']=='removed' and not p.exists() and str(p) not in missing:missing.append(str(p))
 if not missing:return None
 if result['status']!='passed' or job['status']!='passed':raise ValueError('保留汇总只适用于原已通过的独立结果。')
 # Scientific review remains independently verified by the original evidence reader.
 from review_evidence import reviewed
 reviewed(result,root)
 return dict(mode='summary_retained',note=NOTE,receipt=str(location(root,job['attempt'])),receipt_sha256=digest(proof),removed_artifacts=missing,original_result_sha256=job['result_sha256'])
def notices(value):
 found={}
 def walk(x):
  if isinstance(x,dict):
   if x.get('mode')=='summary_retained' and 'receipt_sha256' in x:found[x['receipt_sha256']]=x
   else:
    for v in x.values():walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(value);return list(found.values())
def export_notice(folder,data):
 rows=notices(data)
 if rows:
  (Path(folder)/'保留汇总说明.txt').write_text(NOTE+'\n每项原结果与清理记录标识见 summary-retention.json；原始明细未包含在本包。\n',encoding='utf-8-sig')
  write_json(Path(folder)/'summary-retention.json',dict(note=NOTE,records=rows),folder)
 return rows
