"""Append-only draft versions, isolated from the source platform."""
import copy
from contextlib import contextmanager
import sqlite3
from pathlib import Path
import uuid
from foundation import ROOT, canonical, loads, now, owned
from contracts import normalize, validate, record_digest

class Conflict(ValueError):pass

def preserve_numeric_representation(base,value):
    """Restore unchanged integral floats lost in a browser JSON round trip.

    Keep existing physical fingerprints stable; never round changed values or
    coerce booleans/strings. Neither the saved object nor the request is mutated.
    """
    if isinstance(value,dict):
        old=base if isinstance(base,dict) else {}
        return {k:preserve_numeric_representation(old.get(k),v) for k,v in value.items()}
    if isinstance(value,list):
        old=base if isinstance(base,list) else []
        return [preserve_numeric_representation(old[i] if i<len(old) else None,v) for i,v in enumerate(value)]
    if type(base) is float and type(value) is int and base==value:return base
    return copy.deepcopy(value)

class Store:
    def __init__(self, catalog, root=ROOT):
        self.catalog=catalog
        self.root=Path(root).resolve()
        self.path=owned(self.root/'data/drafts.sqlite',self.root)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS versions (id TEXT, revision INTEGER, payload TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, record_id TEXT NOT NULL, revision INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS comparisons (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS research_sets (id TEXT, revision INTEGER, payload TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS research_set_members (record_id TEXT PRIMARY KEY, set_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(set_id,role))')

    def member_owners(self):
        with self.connect() as db:
            return {r['record_id']:dict(set_id=r['set_id'],role=r['role']) for r in db.execute('SELECT * FROM research_set_members')}

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self,ident,revision=None):
        if ident in self.catalog['records']:
            if revision is not None and revision!=self.catalog['records'][ident]['revision']:
                raise Conflict('来源方案版本不匹配。')
            return copy.deepcopy(self.catalog['records'][ident])
        with self.connect() as db:
            row=db.execute('SELECT payload FROM versions WHERE id=? '+('AND revision=?' if revision is not None else 'ORDER BY revision DESC LIMIT 1'),
                (ident,revision) if revision is not None else (ident,)).fetchone()
        if row is None:raise KeyError('没有该方案。')
        return loads(row['payload'])

    def all(self):
        with self.connect() as db:
            rows=db.execute('SELECT v.payload FROM versions v JOIN (SELECT id,MAX(revision) r FROM versions GROUP BY id) x ON v.id=x.id AND v.revision=x.r').fetchall()
        return [copy.deepcopy(r) for r in self.catalog['records'].values()]+[loads(r['payload']) for r in rows]

    def history(self,ident):
        if ident in self.catalog['records']:
            r=self.catalog['records'][ident]
            return [dict(revision=r['revision'],saved_at=self.catalog['created'],name=r['name'])]
        with self.connect() as db:
            rows=db.execute('SELECT revision,created,payload FROM versions WHERE id=? ORDER BY revision DESC',(ident,)).fetchall()
        return [dict(revision=r['revision'],saved_at=r['created'],name=loads(r['payload'])['name']) for r in rows]

    def update_payload(self,base,changes):
        if not isinstance(changes,dict) or set(changes)-{'name','factors','numerics','execution'}:
            raise ValueError('只允许修改方案名称、四因素、计算设置和设备投入。')
        out=copy.deepcopy(base)
        out.update(preserve_numeric_representation(base,changes))
        out=normalize(out)
        errors=validate(out,self.catalog['sites'])
        if errors:raise ValueError('；'.join(errors))
        return out

    def comparisons(self):
        with self.connect() as db:
            rows=db.execute('SELECT payload FROM comparisons ORDER BY created DESC').fetchall()
        return [loads(row['payload']) for row in rows]

    def add_comparison(self,name,left,right,metric):
        return self.save_comparison(name,left,right,metric)['comparison']

    def save_comparison(self,name,left,right,metric):
        """Reuse exact submissions atomically; existing relationships remain immutable."""
        if not isinstance(name,str) or not 1<=len(name.strip())<=100:
            raise ValueError('请填写有效的比较名称。')
        if metric not in ('total','heating','cooling','temperature'):
            raise ValueError('比较指标不受支持。')
        if not isinstance(left,dict) or not isinstance(right,dict) or set(left)!={'id','revision'} or set(right)!={'id','revision'}:
            raise ValueError('比较双方必须指定方案及版本。')
        a=self.get(left['id'],left['revision']);b=self.get(right['id'],right['revision'])
        if left==right:raise ValueError('请选择两个不同的方案或版本。')
        if metric!='temperature' and any(r['factors']['condition']['operation']['mode']=='natural' for r in (a,b)):
            raise ValueError('自然室温方案不能按空调负荷比较。')
        name=name.strip()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Old duplicate rows are preserved. Reuse the oldest exact match deterministically.
            for saved in db.execute('SELECT payload FROM comparisons ORDER BY created,id'):
                row=loads(saved['payload'])
                if (row['name'],row['left'],row['right'],row['metric'])==(name,left,right,metric):
                    return dict(comparison=row,reused_comparison=True)
            row=dict(id='comparison_'+uuid.uuid4().hex,name=name,left=left,right=right,metric=metric,created=now())
            db.execute('INSERT INTO comparisons VALUES (?,?,?)',(row['id'],canonical(row),row['created']))
        return dict(comparison=row,reused_comparison=False)

    def create(self,source_id,base_revision,changes):
        source=self.get(source_id,base_revision)
        if source['revision']!=base_revision:raise Conflict('来源方案已经更新，请重新读取后另存。')
        out=self.update_payload(source,changes)
        out.update(id='draft_'+uuid.uuid4().hex,revision=1,status='draft',archived=False,saved_at=now())
        out['provenance']['origin_id']=source['provenance'].get('origin_id',source['id'])
        out['provenance']['parent_id']=source['id']
        out['provenance']['parent_revision']=source['revision']
        out['record_sha256']=record_digest(out)
        with self.connect() as db:
            db.execute('INSERT INTO versions VALUES (?,?,?,?)',(out['id'],1,canonical(out),out['saved_at']))
            db.execute('INSERT INTO events(at,action,record_id,revision) VALUES (?,?,?,?)',(out['saved_at'],'create',out['id'],1))
        return out

    def save(self,ident,expected_revision,changes):
        if ident in self.member_owners():raise ValueError('这是对比集内成员，请从本组预览并保存；来源方案不会被修改。')
        if ident in self.catalog['records']:raise ValueError('来源方案只读，请另存为新方案。')
        if type(expected_revision) is not int:raise ValueError('必须提供当前方案版本。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision,payload FROM versions WHERE id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
            if row is None:raise KeyError('没有该草案。')
            if row['revision']!=expected_revision:raise Conflict('方案已在另一处更新；当前修改未覆盖已保存内容。')
            out=self.update_payload(loads(row['payload']),changes)
            out.update(revision=expected_revision+1,saved_at=now())
            out['record_sha256']=record_digest(out)
            db.execute('INSERT INTO versions VALUES (?,?,?,?)',(ident,out['revision'],canonical(out),out['saved_at']))
            db.execute('INSERT INTO events(at,action,record_id,revision) VALUES (?,?,?,?)',(out['saved_at'],'save',ident,out['revision']))
        return out
