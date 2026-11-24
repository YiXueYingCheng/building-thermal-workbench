"""Explicit deletion of unreferenced saved snapshots, with atomic audit receipts.

No cascade, file removal, VACUUM, result rebinding or automatic computation.
"""
from pathlib import Path
from contextlib import closing
import json,re,sqlite3,time,uuid
from functools import lru_cache
from study_relations import action_for,name_relations
from handoff_inventory import HandoffInventory
from foundation import canonical,digest,loads,now,read_json,write_json
from storage_management import safe_child,blockers
from result_storage import documents,label_for,maintenance,databases_locked

KEPT=['建筑、材料、作息、日历、气象及只读来源',
      '计算输入、准备清单、任务、原始结果、保留汇总、比较关系和对比集',
      '导出文件、已有备份、操作历史、备注修改历史及删除记录']
IMPACT='只删除列出的保存版本及其当前备注，不连带删除任何文件或其他业务对象。仍有引用时禁止删除。删除内容不能直接撤销，恢复需使用已有备份；操作历史保留。数据库文件不自动压缩，不能把删除版本数当作释放磁盘空间。'
AUDIT_TABLES={'events','version_note_events','dissolved_set_snapshots','plan_deletion_receipts','plan_deleted_versions'}

def dbpath(root):
 p=safe_child(root,Path(root)/'data/drafts.sqlite')
 if p.stat().st_nlink!=1:raise ValueError('方案数据库存在共享硬链接，不能执行独立删除。')
 return p

def table_exists(db,name):return db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone() is not None

def connect_read(path):
 db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row;db.execute('BEGIN');return db

def match_reference(value,ident,revisions):
 """Match a version where specified; an unversioned/unknown reference protects all.

 Consume paired identifiers before descending, so a reference to v1 does not
 accidentally protect unrelated v2 just because both have the same record ID.
 """
 hits=[]
 def add(rev,description):
  if isinstance(rev,str) and rev.isdigit():rev=int(rev)
  if type(rev) is int and rev>0:
   if revisions is None or rev in revisions:hits.append(description+' · v'+str(rev))
  else:hits.append(description+' · 未限定版本，保守保留')
 def walk(v):
  if isinstance(v,dict):
   consumed=set()
   for key,revision_keys in [('id',('revision',)),('record_id',('revision','record_revision')),('parent_id',('parent_revision',)),('origin_id',('origin_revision',))]:
    if v.get(key)==ident:
     rev=next((v[k] for k in revision_keys if k in v),None);add(rev,'方案引用' if key in ('id','record_id') else '另存／来源追溯');consumed.add(key)
   for k,x in v.items():
    if k==ident:add(None,'以方案编号为键的引用')
    if k not in consumed:walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
  elif isinstance(v,str) and re.search(re.escape(ident)+r'(?![a-f0-9])',v):add(None,'文本／路径中的方案引用')
 walk(value);return sorted(set(hits))

DRAFT_IDS=re.compile(rb'draft_[a-f0-9]{32}')
MAX_METADATA=128*2**20

def indexed_document(path,size):
 with path.open('rb') as stream:
  raw=stream.read(size+1)
 if len(raw)!=size:raise ValueError('文件在核对期间发生变化，请重新核对')
 value=loads(raw.decode('utf-8-sig'))
 # JSON escapes can hide an ASCII identifier in either a key or a value.
 if b'\\u00' in raw:raw=json.dumps(value,ensure_ascii=True).encode('ascii')
 ids=frozenset(DRAFT_IDS.findall(raw)) if b'draft_' in raw else frozenset()
 return ids,value

@lru_cache(maxsize=32768)
def file_ids(path,signature):
 return indexed_document(path,signature[2])[0]

class PlanFiles:
 def __init__(self,ident,fresh):
  self.ident=ident;self.token=ident.encode('ascii');self.fresh=fresh
 def read(self,path,st):
  if st.st_size>MAX_METADATA:raise ValueError('单份方案核对资料超过 128 MiB，尚未核对')
  # Only previews reuse the lightweight identifier index. Execution rereads every file.
  if self.fresh:
   ids,value=indexed_document(path,st.st_size)
   return value if self.token in ids else None
  if self.token in file_ids(path,(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)):
   return indexed_document(path,st.st_size)[1]
  return None
 def row_matches(self,row):
  return any(isinstance(x,str) and (self.ident in x or '\\u00' in x) for x in (*row.keys(),*row.values()))

def outgoing(record,catalog,db):
 edges=[]
 def add(kind,identifier,name=None,version=None):
  if identifier:edges.append(dict(kind=kind,id=str(identifier),name=str(name or identifier),version=version))
 prov=record.get('provenance',{})
 for key,title in [('parent','另存来源'),('origin','最初来源')]:
  ident=prov.get(key+'_id');revision=prov.get(key+'_revision')
  if not ident or (key=='origin' and ident==prov.get('parent_id')):continue
  name=catalog['records'].get(ident,{}).get('name')
  if not name and ident.startswith('draft_'):
   row=db.execute('SELECT payload FROM versions WHERE id=? AND revision=?',(ident,revision)).fetchone()
   if row:name=loads(row[0]).get('name')
  add(title,ident,name,revision)
 factors=record.get('factors',{});building=factors.get('building',{})
 add('建筑',building.get('id'),building.get('name'))
 for title,obj in [('房间作息',building.get('usage_profile')),('研究材料',factors.get('materials',{}).get('definition_reference'))]:
  if isinstance(obj,dict):add(title,obj.get('id'),obj.get('name') or (obj.get('content') or {}).get('name'),obj.get('revision'))
 for ref in factors.get('condition',{}).get('reference_runs',[]):
  if isinstance(ref,dict):
   snap=ref.get('snapshot') or {}
   add('工况参考',ref.get('id'),snap.get('name') or ref.get('name'),ref.get('revision') or snap.get('revision'))
 sites=catalog.get('sites',{})
 for site in factors.get('scope',{}).get('site_ids',[]):
  info=sites.get(site,{}) if isinstance(sites,dict) else {}
  add('气象地点',site,info.get('name') or info.get('label'))
 return edges

def target_snapshot(root,catalog,ident,scope,revision):
 if scope not in ('record','version'):raise ValueError('请选择删除整个方案或单个保存版本。')
 if not isinstance(ident,str):raise ValueError('方案编号无效。')
 if ident in catalog['records']:
  r=catalog['records'][ident]
  return dict(id=ident,scope=scope,revision=revision,name=r['name'],versions=[],remaining_versions=[],latest_before=r['revision'],latest_after=r['revision'],notes=[],audit_counts={},blocked=['只读来源不在本次删除范围。来源、建筑及原数据保持。'])
 if not re.fullmatch('draft_[a-f0-9]{32}',ident):raise ValueError('本次只支持本工作区研究方案。')
 if scope=='version' and (type(revision) is not int or revision<1):raise ValueError('请指定有效的保存版本号。')
 if scope=='record' and revision is not None:raise ValueError('整个方案删除不接受单版本参数。')
 with closing(connect_read(dbpath(root))) as db:
  rows=[dict(r) for r in db.execute('SELECT * FROM versions WHERE id=? ORDER BY revision',(ident,))]
  if not rows:raise ValueError('方案不存在或已经删除，请刷新方案库。')
  selected=[r for r in rows if scope=='record' or r['revision']==revision]
  if not selected:raise ValueError('没有该保存版本，请刷新记录。')
  ids={r['revision'] for r in selected};notes=[];counts={}
  for r in rows:
   value=loads(r['payload'])
   if value['id']!=ident or value['revision']!=r['revision']:raise ValueError('保存版本身份与登记不一致。')
   r['name']=value['name'];r['sha256']=digest(value)
   if r['revision'] in ids:r['outgoing']=outgoing(value,catalog,db)
  if table_exists(db,'version_notes'):
   notes=[dict(r) for r in db.execute('SELECT * FROM version_notes WHERE record_id=? ORDER BY revision',(ident,)) if str(r['revision']) in {str(n) for n in ids}]
  for table in ('events','version_note_events'):
   if table_exists(db,table):counts[table]=db.execute('SELECT COUNT(*) FROM '+table+' WHERE record_id=?',(ident,)).fetchone()[0]
  owner=db.execute('SELECT * FROM research_set_members WHERE record_id=?',(ident,)).fetchone()
 versions=[{k:r[k] for k in ('revision','name','created','sha256','outgoing')} for r in selected]
 remaining=[r['revision'] for r in rows if r['revision'] not in ids]
 return dict(id=ident,scope=scope,revision=revision,name=rows[-1]['name'],versions=versions,remaining_versions=remaining,latest_before=rows[-1]['revision'],latest_after=max(remaining) if remaining else None,notes=notes,audit_counts=counts,
  head_fingerprint=digest(rows),blocked=['该方案是计算型对比集的成员。可在关系树中解散该集，再核对清理范围。'] if owner else [])

def references(root,ident,scope,revision,fresh=False):
 root=Path(root).resolve();issues=[];refs=[];revisions=None if scope=='record' else {revision};own=str(root/'data/drafts.sqlite')
 inventory=HandoffInventory(root)
 def consider(source,value):
  table=value.get('_storage_table','') if isinstance(value,dict) else ''
  if source==own+'#'+table:
   if table in AUDIT_TABLES or table=='version_notes':return
   if table=='versions' and value.get('id')==ident and (revisions is None or value.get('revision') in revisions):return
  hits=match_reference(value,ident,revisions)
  if not hits:return
  payload=value.get('payload',value) if isinstance(value,dict) else {}
  name=(payload.get('name') or payload.get('record_name') or payload.get('id')) if isinstance(payload,dict) else None
  path=Path(source);relative=path.relative_to(root).parts if path.is_relative_to(root) else ()
  historical=inventory.contains(path)
  kind=label_for(source,value);owner=path.name;owner_key=source
  if table:
   owner=str(value.get('id') or value.get('record_id') or owner)
   if table=='batches':
    plan=value.get('plan') or {};kind='计算批次';name=plan.get('record_name') or name
   elif table=='research_set_members':kind='研究对比集成员';owner=value.get('set_id') or owner
   elif table=='versions':owner+=' · v'+str(value.get('revision'))
   owner_key=source+'#'+owner
  elif len(relative)>=3 and relative[:2]==('data','model-inputs'):owner=relative[2];owner_key=str(root.joinpath(*relative[:3]))
  elif len(relative)>=4 and relative[:3]==('data','execution','reviews'):owner=relative[3];owner_key=str(root.joinpath(*relative[:4]))
  elif len(relative)==3 and relative[:2]==('data','input-preparations'):
   owner=path.stem;kind='输入准备任务'
  action=action_for(table,value) if source in (own+"#"+table,str(root/"data/execution/queue.sqlite")+"#"+table) else None
  refs.append(dict(action=action,kind=kind,label=str(name or owner),owner=owner,owner_key=owner_key,source=source,relations=hits,historical=historical))
 for source,value in documents(root,issues,include_all_databases=True,plan_files=PlanFiles(ident,fresh)):consider(source,value)
 name_relations(root,refs)
 return sorted({digest(r):r for r in refs}.values(),key=lambda r:(r['kind'],r['source'],r['label'])),sorted(set(issues))

def inspect(root,catalog,ident,scope,revision=None,active=False,fresh=False):
 root=Path(root).resolve();target=target_snapshot(root,catalog,ident,scope,revision)
 all_refs,issues=references(root,ident,scope,revision,fresh) if target['versions'] else ([],[])
 history_refs=[r for r in all_refs if r['historical']]
 refs=[r for r in all_refs if not r['historical']]
 if target!=target_snapshot(root,catalog,ident,scope,revision):raise ValueError('检查期间方案或备注变化，请重新预览。')
 reasons=target['blocked']+blockers(root,active)
 if issues:reasons.append('有 '+str(len(issues))+' 项资料尚未核对，详见检查范围。')
 if refs:
  owners={(r['kind'],r['owner_key']) for r in refs}
  reasons.append('有 '+str(len(owners))+' 个对象需要追溯到本次版本：'+'、'.join(sorted({k for k,_ in owners}))+'。具体版本、编号和文件见下方关系树。')
 value=dict(target=target,references=refs,historical_mentions=history_refs,issues=issues,blocked=list(dict.fromkeys(reasons)),kept=KEPT,impact=IMPACT,
  scope_note='检查本工作区全部保存版本、数据库与受管 JSON（含归档、准备、日历、导出、验证及登记的外置结果）；未限定版本的引用保守保护。平台外手工复制的资料无法自动追踪。浏览缓存不作为研究引用，重新读取时按数据库更新。')
 value['fingerprint']=digest(value);return value

def preview(root,catalog,ident,scope,revision=None,active=False,cleanup=False):
 from plan_cleanup import inspect as inspect_cleanup
 root=Path(root).resolve()
 info=(inspect_cleanup if cleanup else inspect)(root,catalog,ident,scope,revision,active)
 value=dict(id='plan_delete_'+uuid.uuid4().hex,kind='plan_deletion',root=str(root),created=now(),expires_epoch=time.time()+900,inspection=info)
 write_json(safe_child(root,root/'data/storage-management/previews'/(value['id']+'.json')),value,root)
 return dict(value,sha256=digest(value))

def ensure(db):
 db.execute('CREATE TABLE IF NOT EXISTS plan_deletion_receipts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)')
 db.execute('CREATE TABLE IF NOT EXISTS plan_deleted_versions (record_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, operation TEXT NOT NULL, deleted_at TEXT NOT NULL, PRIMARY KEY(record_id,revision))')

def history(root):
 with closing(connect_read(dbpath(root))) as db:
  if not table_exists(db,'plan_deletion_receipts'):return []
  return [loads(r[0]) for r in db.execute('SELECT payload FROM plan_deletion_receipts ORDER BY created DESC,rowid DESC LIMIT 20')]

def execute(root,catalog,ident,checksum,confirmed,active=False):
 if not re.fullmatch('plan_delete_[a-f0-9]{32}',str(ident)) or confirmed is not True:raise ValueError('请先预览，并明确确认删除列出的方案版本。')
 root=Path(root).resolve();path=dbpath(root)
 import plan_cleanup as cleanup
 preview_path=safe_child(root,root/'data/storage-management/previews'/(ident+'.json'))
 v=read_json(preview_path)
 if digest(v)!=checksum or v.get('id')!=ident or v.get('root')!=str(root) or v.get('kind')!='plan_deletion':raise ValueError('预览不一致。')
 cascade='cleanup' in v['inspection']
 exclude=(path,root/'data/execution/queue.sqlite',root/'data/execution/preparations.sqlite') if cascade else (path,)
 with maintenance(root),databases_locked(root,exclude=exclude),closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=.2)) as db:
  db.row_factory=sqlite3.Row
  if cascade:cleanup.attach_queue(db,root)
  db.execute('BEGIN IMMEDIATE')
  staging_started=False
  try:
   if table_exists(db,'plan_deletion_receipts'):
    old=db.execute('SELECT payload FROM plan_deletion_receipts WHERE id=?',(ident,)).fetchone()
    if old:
     receipt=loads(old[0])
     if receipt['preview_sha256']!=checksum:raise ValueError('删除记录与预览不一致。')
     if cascade:cleanup.settle(root,ident,True)
     return receipt
   if time.time()>v['expires_epoch']:raise ValueError('预览已过期，请重新核对。')
   t=v['inspection']['target'];args=(root,catalog,t['id'],t['scope'],t['revision'],active)
   fresh=cleanup.inspect(*args,fresh=True) if cascade else inspect(*args,fresh=True)
   if fresh['blocked']:raise ValueError('；'.join(fresh['blocked']))
   if fresh!=v['inspection']:raise ValueError('版本、备注、任务或关联已经变化，请重新预览。')
   target=fresh['target'];at=now();ensure(db);notes_removed=0
   for row in target['versions']:
    key=(target['id'],row['revision'])
    db.execute('INSERT INTO plan_deleted_versions VALUES(?,?,?,?,?,?)',(*key,row['name'],row['sha256'],ident,at))
    if table_exists(db,'version_notes'):notes_removed+=db.execute('DELETE FROM version_notes WHERE record_id=? AND revision=?',(key[0],str(key[1]))).rowcount
    if db.execute('DELETE FROM versions WHERE id=? AND revision=?',key).rowcount!=1:raise ValueError('版本变化，删除已撤回。')
    db.execute('INSERT INTO events(at,action,record_id,revision) VALUES(?,?,?,?)',(at,'controlled_delete_version',*key))
   receipt=dict(id=ident,kind='plan_deletion',completed=at,preview_sha256=checksum,record_id=target['id'],name=target['name'],scope=target['scope'],versions=target['versions'],removed_versions=len(target['versions']),removed_current_notes=notes_removed,latest_after=target['latest_after'],files_deleted=0,kept=KEPT,note=IMPACT)
   if cascade:
    plan=fresh['cleanup']
    cleanup.remove_queue_rows(db,plan)
    receipt.update(cleanup=True,batches=plan['batches'],exclusive_bytes=plan['bytes'],files_deleted=len(plan['files']),kept=cleanup.KEPT,note=cleanup.NOTE,
                   input_jobs=[Path(g['path']).stem for g in plan['groups'] if g['kind']=='输入准备任务'])
    staging_started=True
    cleanup.stage(root,ident,plan['files'])
   db.execute('INSERT INTO plan_deletion_receipts VALUES(?,?,?)',(ident,canonical(receipt),at));db.commit()
  except BaseException:
   db.rollback()
   if staging_started:cleanup.settle(root,ident,False)
   raise
  if cascade:cleanup.settle(root,ident,True)
  return receipt
