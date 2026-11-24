"""Append-only named component versions; schemes embed an explicit snapshot."""
import copy,re,sqlite3,uuid
from contextlib import closing
from pathlib import Path
from foundation import ROOT,canonical,loads,digest,now

KINDS=('usage','material','daily','calendar','construction')
def check_material_origin(origin):
 if not isinstance(origin,dict) or set(origin)!={'id','revision','name','license','sha256'}:
  raise ValueError('材料示例来源信息不完整。')
 if not all(isinstance(origin[k],str) and 0<len(origin[k].strip())<=300 for k in ('id','name','license')):
  raise ValueError('请核对材料示例名称、编号与许可。')
 if type(origin['revision']) is not int or origin['revision']<1 or not re.fullmatch('[0-9a-f]{64}',str(origin['sha256'])):
  raise ValueError('请核对材料示例版本与文件校验值。')

def payload_hash(row):return digest({k:v for k,v in row.items() if k!='sha256'})
def verify(row,kind=None):
 fields={'kind','id','revision','name','created','content','sha256'}
 if isinstance(row,dict) and row.get('kind')=='material' and 'example_origin' in row:
  check_material_origin(row['example_origin'])
  fields.add('example_origin')
 if not isinstance(row,dict) or set(row)!=fields:raise ValueError('组件版本快照不完整。')
 if row['kind'] not in KINDS or (kind and row['kind']!=kind) or row['sha256']!=payload_hash(row):raise ValueError('组件版本快照核对失败。')
 if not re.fullmatch(r'component_[a-f0-9]{32}',str(row['id'])) or type(row['revision']) is not int or row['revision']<1:raise ValueError('组件版本编号不正确。')
 return row
class Library:
 def __init__(self,root=ROOT):self.path=Path(root)/'data/components.sqlite'
 def version(self,kind,ident,revision):
  if not self.path.is_file():return None
  with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
   row=db.execute('SELECT payload FROM components WHERE kind=? AND id=? AND revision=?',(kind,ident,revision)).fetchone()
  return verify(loads(row[0]),kind) if row else None
 def all(self,kind):
  if kind not in KINDS:raise ValueError('组件类型不受支持。')
  if not self.path.exists():return []
  with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
   return [verify(loads(r[0]),kind) for r in db.execute('SELECT payload FROM components WHERE kind=? ORDER BY created DESC,revision DESC',(kind,))]
 def save(self,kind,name,content,parent=None,*,example_origin=None):
  if kind not in KINDS or not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('请填写组件名称。')
  if example_origin is not None:
   if kind!='material':raise ValueError('只有材料版本可登记示例来源。')
   check_material_origin(example_origin)
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS components(kind TEXT,id TEXT,revision INTEGER,created TEXT,payload TEXT,PRIMARY KEY(id,revision))')
   db.execute('BEGIN IMMEDIATE')
   ident='component_'+uuid.uuid4().hex;revision=1
   if parent:
    old=db.execute('SELECT revision,payload FROM components WHERE id=? AND kind=? ORDER BY revision DESC LIMIT 1',(parent['id'],kind)).fetchone()
    if not old or old[0]!=parent['revision']:raise ValueError('组件已有新版本，请先重新选择；当前修改未覆盖原版本。')
    existing=verify(loads(old[1]),kind)
    if example_origin is not None and example_origin!=existing.get('example_origin'):
     raise ValueError('同一材料的新版本应沿用原示例来源。')
    example_origin=existing.get('example_origin')
    if kind=='usage' and any(existing['content'].get(k)!=content.get(k) for k in ('building_id','baseline_sha256')):raise ValueError('建筑配置的新版本须属于同一建筑与来源；不同建筑请新建配置。')
    if existing['name']==name.strip() and existing['content']==content:return existing
    ident=parent['id'];revision=old[0]+1
   row=dict(kind=kind,id=ident,revision=revision,name=name.strip(),created=now(),content=copy.deepcopy(content))
   if example_origin is not None:row['example_origin']=copy.deepcopy(example_origin)
   row['sha256']=payload_hash(row)
   db.execute('INSERT INTO components VALUES(?,?,?,?,?)',(kind,ident,revision,row['created'],canonical(row)))
   return row
