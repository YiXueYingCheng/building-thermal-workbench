"""Workspace-only daily plan visibility and explicit append-only version editing.

This catalog is never consulted when compiling a pinned room configuration.
Imported snapshots and component payloads are immutable; hiding changes selection only.
"""
import copy,sqlite3
from pathlib import Path
from contextlib import closing
from threading import RLock
from foundation import ROOT,now
from usage_schedules import profiles,save_profile

# The local page server is threaded. Serialize lookup + save so simultaneous
# "save as new" requests cannot bypass the shared numerical deduplication.
SAVE_LOCK=RLock()

def visibility(root=ROOT):
 path=Path(root)/'data/daily-library.sqlite'
 if not path.exists():return {}
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='visibility'").fetchone():return {}
  return {row[0]:dict(hidden=bool(row[1]),state_revision=row[2],updated=row[3])
          for row in db.execute('SELECT id,hidden,revision,updated FROM visibility')}

def catalog(root=ROOT,include_hidden=False,history=False):
 rows=copy.deepcopy(profiles(Path(root)));states=visibility(root);latest={}
 for row in rows:
  s=row['snapshot'];latest[s['id']]=max(latest.get(s['id'],0),s['revision'])
 result=[]
 for row in rows:
  s=row['snapshot'];row.update(states.get(s['id'],dict(hidden=False,state_revision=0,updated=None)))
  row.update(latest_revision=latest[s['id']],is_latest=s['revision']==latest[s['id']],
             editable=row['origin']=='本工作区日计划')
  if (include_hidden or not row['hidden']) and (history or row['is_latest']):result.append(row)
 return result

def find(root,ident,revision=None):
 row=next((r for r in catalog(root,True,True) if r['snapshot']['id']==ident
           and (r['snapshot']['revision']==revision if revision is not None else r['is_latest'])),None)
 if row is None:raise ValueError('日计划版本不存在，请刷新日计划库。')
 return row

def set_visibility(root,ident,hidden,expected_revision):
 if type(hidden) is not bool or type(expected_revision) is not int or expected_revision<0:
  raise ValueError('请提供有效的停用状态及其版本。')
 find(root,ident)
 path=Path(root)/'data/daily-library.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
 with closing(sqlite3.connect(path,timeout=10)) as db,db:
  db.execute('CREATE TABLE IF NOT EXISTS visibility(id TEXT PRIMARY KEY,hidden INTEGER,revision INTEGER,updated TEXT)')
  db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT,hidden INTEGER,revision INTEGER,created TEXT,PRIMARY KEY(id,revision))')
  db.execute('BEGIN IMMEDIATE')
  old=db.execute('SELECT hidden,revision,updated FROM visibility WHERE id=?',(ident,)).fetchone() or (0,0,None)
  if old[1]!=expected_revision:raise ValueError('日计划的停用状态已有变化，请刷新后再操作。')
  if bool(old[0])==hidden:return dict(id=ident,hidden=hidden,state_revision=old[1],updated=old[2])
  revision=old[1]+1;stamp=now()
  db.execute('INSERT OR REPLACE INTO visibility VALUES(?,?,?,?)',(ident,int(hidden),revision,stamp))
  db.execute('INSERT INTO events VALUES(?,?,?,?)',(ident,int(hidden),revision,stamp))
 return dict(id=ident,hidden=hidden,state_revision=revision,updated=stamp)

def save(root,name,content,parent=None,copied_from=None):
 with SAVE_LOCK:return _save(root,name,content,parent,copied_from)

def _save(root,name,content,parent=None,copied_from=None):
 if parent and copied_from:raise ValueError('请选择更新此计划或复制成新计划。')
 if parent:
  if not isinstance(parent,dict) or type(parent.get('revision')) is not int:raise ValueError('日计划父版本不完整。')
  selected=find(root,parent.get('id'),parent['revision'])
  if not selected['editable']:raise ValueError('导入日计划只读，请复制为本工作区计划。')
  if not selected['is_latest']:raise ValueError('日计划已有新版本；当前编辑保留，请重新选择或另存新计划。')
  if parent.get('sha256') and parent['sha256']!=selected['snapshot']['sha256']:raise ValueError('日计划父版本摘要不匹配。')
 if copied_from:
  if not isinstance(copied_from,dict) or type(copied_from.get('revision')) is not int:raise ValueError('复制来源版本不完整。')
  selected=find(root,copied_from.get('id'),copied_from['revision'])
  content=copy.deepcopy(content)
  content['provenance']={'copied_from':{key:selected['snapshot'][key] for key in ('id','revision','name','sha256')}}
 result=save_profile(Path(root),name,content,parent)
 row=find(root,result['profile']['id'],result['profile']['revision'])
 return dict(**result,hidden=row['hidden'],is_latest=row['is_latest'],latest_revision=row['latest_revision'])
