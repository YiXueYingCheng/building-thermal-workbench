"""Preview/confirm local accepted-result detail removal with durable summary evidence."""
from pathlib import Path
import copy,json,time,uuid,shutil,re,sqlite3
from foundation import read_json,write_json,digest,sha,now
from storage_management import safe_child,blockers,public_preview
import result_storage as rs
import summary_retention as sr
from result_reading import results

def compatible_reference(root,row):
 kind=row['kind'];source=row['source']
 if kind in ('结果复用索引','历史完成／复核','原始结果摘要'):return True
 for label,table in [('保存的两两比较','comparisons'),('对比集及结果绑定','research_sets')]:
  if kind==label:return source==str(Path(root)/'data/drafts.sqlite')+'#'+table
 if kind=='已导出资料':
  p=Path(source)
  for folder,prefix in [('batch-exports','batch_export_'),('comparison-exports','comparison_export_'),('research-set-exports','set_export_')]:
   base=Path(root)/'data'/folder
   if p.is_relative_to(base):
    parts=p.relative_to(base).parts
    return len(parts)>=2 and bool(re.fullmatch(prefix+'[a-f0-9]{32}',parts[0]))
 return False
IMPACT='保留原已接受汇总、月度和房间汇总、方案版本、输入、诊断日志及已导出文件；可继续按原口径比较和导出。删除明细后不能重新检查该明细、自动复用计算或建立依赖它的逐日／日历参考；不会自动重跑。'
def inspect(root,attempt,active=False):
 root=Path(root).resolve();info=rs.inspect(root,attempt);reasons=list(info['issues']);job=None
 if not info['local']:reasons.append('首批仅支持本工作区结果，外置资料保留。')
 if len(info['owners'])!=1:reasons.append('必须有唯一当前任务归属；共享或复用结果保留。')
 else:
  owner=info['owners'][0]
  from result_availability import jobs
  job=next(j for j in jobs(root,owner['batch']) if j['idx']==owner['index'])
  if job['status']!='passed' or job.get('pid') or not job.get('result'):reasons.append('只允许已通过、没有运行进程的独立结果；待复核与复用结果保留。')
  else:
   try:
    data=results(root,job['batch']);raw=next(r for r in data['results'] if r['index']==job['idx'])
    if raw['status']!='passed' or raw.get('pending_warnings'):raise ValueError('结果尚未完成接受。')
    if raw.get('scientific_review') or raw.get('reviewed_warnings'):raise ValueError('首批保留专项复核结果的原始明细。')
    if raw.get('output_contract')=='daily_sensible_reference_v1' or raw.get('daily_reference'):raise ValueError('逐日参考结果需要原始明细，保留。')
    folder=Path(info['path']);result_path=Path(job['result'])
    if not result_path.is_relative_to(folder):raise ValueError('结果登记不属于该运行目录。')
   except (OSError,ValueError,KeyError,StopIteration) as e:reasons.append('汇总与资料未能完整核对：'+str(e))
 unsupported=[r for r in info['references'] if not compatible_reference(root,r)]
 if unsupported:reasons.append('有依赖原始明细或未确认用途的资料引用，保留。')
 reasons+=blockers(root,active)
 files,retained=rs.candidates(root,info) if info['local'] else ([],[])
 for r in retained:reasons.append('候选明细存在共享、变化或不可读项：'+r['reason'])
 if not files:reasons.append('没有可清理的明细文件。')
 value=dict(attempt=attempt,path=info['path'],binding=sr.binding(job) if job else None,references=info['references'],unsupported_references=unsupported,blocked=list(dict.fromkeys(reasons)),files=files,retained=retained,impact=IMPACT)
 value['fingerprint']=digest(value);return value
def preview(root,attempt,active=False):
 root=Path(root).resolve();d=inspect(root,attempt,active)
 v=dict(id='cleanup_'+uuid.uuid4().hex,kind='accepted_summary_retention',root=str(root),created=now(),expires_epoch=time.time()+900,attempt=attempt,inspection=d,files=d['files'],blocked=d['blocked'],retained=d['retained'],impact=IMPACT,estimated_file_bytes=0 if d['blocked'] else sum(r['bytes'] for r in d['files']))
 write_json(safe_child(root,root/'data/storage-management/previews'/(v['id']+'.json')),v,root);return public_preview(v)
def execute(root,ident,checksum,confirmed,active=False):
 root=Path(root).resolve()
 if not re.fullmatch('cleanup_[a-f0-9]{32}',str(ident)) or confirmed is not True:raise ValueError('请先预览并明确确认清理列出的明细；汇总保留。')
 with rs.maintenance(root),rs.databases_locked(root):
  v=read_json(safe_child(root,root/'data/storage-management/previews'/(ident+'.json')))
  if digest(v)!=checksum or v.get('kind')!='accepted_summary_retention' or v.get('root')!=str(root):raise ValueError('预览不一致。')
  dest=safe_child(root,root/'data/storage-management/receipts'/(ident+'.json'))
  if dest.exists():return read_json(dest)
  if time.time()>v['expires_epoch']:raise ValueError('预览过期，请重新核对。')
  fresh=inspect(root,v['attempt'],active)
  if fresh['blocked']:raise ValueError('；'.join(fresh['blocked']))
  if fresh['fingerprint']!=v['inspection']['fingerprint']:raise ValueError('引用、任务或文件变化，请重新预览。')
  # Validate the entire submitted list before changing any file.
  if v['files']!=fresh['files']:raise ValueError('候选文件集合变化。')
  job=fresh['binding'];existing=sr.receipt(root,job) # receipt only needs immutable binding fields
  proof=copy.deepcopy(existing) if existing else dict(kind='summary_retention_v1',binding=job,files=[])
  proof.update(state='executing',operation=ident,updated=now())
  receipt=dict(id=ident,kind='accepted_summary_retention',attempt=v['attempt'],completed=now(),state='executing',preview_sha256=checksum,files=[],removed=0,retained=0,removed_file_bytes=0,observed_disk_free_change=None,note=IMPACT+' 部分失败只记录已确认删除的文件；未确认项不可作为保留汇总依据。')
  free=shutil.disk_usage(root).free;write_json(dest,receipt,root)
  for row in v['files']:
   item=dict(row,status='retained',reason='');proof['files']=[r for r in proof['files'] if r['relative']!=row['relative']]
   try:
    p=safe_child(root,root/row['relative']);s=p.lstat()
    if s.st_nlink!=1 or [s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]!=row['stamp'] or sha(p)!=row['sha256']:raise ValueError('文件变化或共享，保留。')
    item.update(status='pending',reason='删除尚未确认');proof['files'].append(copy.deepcopy(item));sr.write(root,proof);receipt['files'].append(item);write_json(dest,receipt,root)
    p.unlink();item.update(status='removed',reason='已受控清理，原汇总保留')
   except (OSError,ValueError) as e:item.update(status='retained',reason=str(e))
   if item not in receipt['files']:receipt['files'].append(item)
   proof['files']=[r for r in proof['files'] if r['relative']!=item['relative']]+[copy.deepcopy(item)];sr.write(root,proof)
   receipt.update(removed=sum(r['status']=='removed' for r in receipt['files']),retained=sum(r['status']!='removed' for r in receipt['files']),removed_file_bytes=sum(r['bytes'] for r in receipt['files'] if r['status']=='removed'));write_json(dest,receipt,root)
  proof.update(state='complete',updated=now());sr.write(root,proof)
  receipt.update(state='complete',completed=now(),observed_disk_free_change=shutil.disk_usage(root).free-free);write_json(dest,receipt,root);return receipt
