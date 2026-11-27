"""Immutable draft snapshots; unreferenced deletions have separate atomic receipts."""
import copy
from contextlib import contextmanager
import sqlite3
from pathlib import Path
import uuid
from foundation import ROOT, canonical, digest, loads, now, owned
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
            db.execute('CREATE TABLE IF NOT EXISTS comparison_inputs (comparison_id TEXT, side TEXT, payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(comparison_id,side))')
            db.execute('CREATE TRIGGER IF NOT EXISTS drop_comparison_inputs AFTER DELETE ON comparisons BEGIN DELETE FROM comparison_inputs WHERE comparison_id=OLD.id; END')
            missing = "SELECT c.payload FROM comparisons c WHERE NOT EXISTS (SELECT 1 FROM comparison_inputs i WHERE i.comparison_id=c.id AND i.side='left') OR NOT EXISTS (SELECT 1 FROM comparison_inputs i WHERE i.comparison_id=c.id AND i.side='right')"
            if db.execute(missing+' LIMIT 1').fetchone():
                db.execute('BEGIN IMMEDIATE')
                for entry in db.execute(missing).fetchall():
                    self._pin_members(db, loads(entry['payload']))

    @staticmethod
    def _verified_input(row, ref):
        value=loads(row['payload'])
        record=value['record']
        if digest(value)!=row['sha256'] or (record['id'],record['revision'])!=(ref['id'],ref['revision']):
            raise ValueError('对照成员的保存版本校验不一致。')
        return value

    def _saved_input(self, db, ref):
        # Use only snapshots owned by a saved comparison with this exact member.
        for side in ('left','right'):
            row=db.execute("SELECT i.payload,i.sha256 FROM comparisons c JOIN comparison_inputs i ON i.comparison_id=c.id AND i.side=? "
                           "WHERE json_extract(c.payload,?)=? AND json_extract(c.payload,?)=? LIMIT 1",
                           (side,'$.'+side+'.id',ref['id'],'$.'+side+'.revision',ref['revision'])).fetchone()
            if row:
                return self._verified_input(row,ref)

    def study_record(self, ref):
        try:
            return self.get(ref['id'],ref['revision'])
        except KeyError:
            with self.connect() as db:
                saved=self._saved_input(db,ref)
            if not saved:raise
            return saved['record']

    def _pin_members(self, db, comparison):
        for side in ('left','right'):
            ref = comparison[side]
            record = self.catalog['records'].get(ref['id'])
            historical = None
            if record is not None and record['revision'] == ref['revision']:
                # These two original imports identify the signed historical dataset.
                if record['id'] in ('global_w00','global_fixed'):
                    source = self.catalog.get('global_bundle',{}).get('historical') or {}
                    historical = source.get('source',{}).get('sha256')
            else:
                row = db.execute('SELECT payload FROM versions WHERE id=? AND revision=?',
                                 (ref['id'],ref['revision'])).fetchone()
                if row is None:
                    saved=self._saved_input(db,ref)
                    if not saved:continue
                    record,historical=saved['record'],saved.get('historical_sha256')
                else:
                    record = loads(row['payload'])
            value = dict(record=record, historical_sha256=historical)
            db.execute('INSERT OR IGNORE INTO comparison_inputs VALUES (?,?,?,?)',
                       (comparison['id'], side, canonical(value), digest(value)))

    def comparison_input(self, comparison, side):
        ref = comparison[side]
        with self.connect() as db:
            query = 'SELECT payload,sha256 FROM comparison_inputs WHERE comparison_id=? AND side=?'
            key = (comparison['id'],side)
            row = db.execute(query, key).fetchone()
            if row is None:
                saved = db.execute('SELECT payload FROM comparisons WHERE id=?',(comparison['id'],)).fetchone()
                if saved:
                    self._pin_members(db,loads(saved['payload']))
                    row = db.execute(query,key).fetchone()
        if row is None:
            return self.get(ref['id'],ref['revision']), False
        value = self._verified_input(row,ref)
        record = value['record']
        historical = self.catalog.get('global_bundle',{}).get('historical') or {}
        source_hash = value.get('historical_sha256')
        return record, bool(source_hash and source_hash==historical.get('source',{}).get('sha256'))

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

    def draft_payload(self,base,changes):
        if not isinstance(changes,dict) or set(changes)-{'name','factors','numerics','execution'}:
            raise ValueError('只允许修改方案名称、四因素、计算设置和设备投入。')
        out=copy.deepcopy(base)
        out.update(preserve_numeric_representation(base,changes))
        materials=out.get('factors',{}).get('materials',{})
        supplied=changes.get('factors',{}).get('materials',{}).get('definition_reference')
        if isinstance(supplied,dict):
            from component_library import Library,payload_hash
            ref=materials['definition_reference']
            if payload_hash(ref)!=supplied.get('sha256'):
                # A newly selected version has no matching numeric types in the old draft.
                # Restore only a byte-verifiable round trip of the exact library revision.
                trusted=None
                if isinstance(supplied.get('id'),str) and type(supplied.get('revision')) is int:
                    trusted=Library(self.root).version('material',supplied['id'],supplied['revision'])
                if trusted and trusted['sha256']==supplied.get('sha256'):
                    restored=preserve_numeric_representation(trusted,supplied)
                    if payload_hash(restored)==trusted['sha256']:
                        materials['definition_reference']=trusted
                        materials['definitions']=preserve_numeric_representation(
                            [trusted['content']],changes['factors']['materials'].get('definitions',[]))
        return out

    def update_payload(self,base,changes):
        out=self.draft_payload(base,changes)
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
        a=self.study_record(left);b=self.study_record(right)
        if left==right:raise ValueError('请选择两个不同的方案或版本。')
        if metric!='temperature' and any(r['factors']['condition']['operation']['mode']=='natural' for r in (a,b)):
            raise ValueError('自然室温方案不能按空调负荷比较。')
        name=name.strip()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Revalidate under the write lock, after any concurrent controlled deletion.
            self.study_record(left);self.study_record(right)
            # Old duplicate rows are preserved. Reuse the oldest exact match deterministically.
            for saved in db.execute('SELECT payload FROM comparisons ORDER BY created,id'):
                row=loads(saved['payload'])
                if (row['name'],row['left'],row['right'],row['metric'])==(name,left,right,metric):
                    self._pin_members(db,row)
                    return dict(comparison=row,reused_comparison=True)
            row=dict(id='comparison_'+uuid.uuid4().hex,name=name,left=left,right=right,metric=metric,created=now())
            db.execute('INSERT INTO comparisons VALUES (?,?,?)',(row['id'],canonical(row),row['created']))
            self._pin_members(db,row)
        return dict(comparison=row,reused_comparison=False)

    def create(self,source_id,base_revision,changes):
        source=self.get(source_id,base_revision)
        if source['revision']!=base_revision:raise Conflict('来源方案已经更新，请重新读取后另存。')
        out=self.update_payload(source,changes)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.get(source_id,base_revision)
            return self.insert_draft(db,source,out)

    def insert_draft(self,db,source,out):
        """Insert a validated copy inside the caller's transaction."""
        source_id,base_revision=source['id'],source['revision']
        out.update(id='draft_'+uuid.uuid4().hex,revision=1,status='draft',archived=False,saved_at=now())
        out['provenance']['origin_id']=source['provenance'].get('origin_id',source['id'])
        out['provenance']['parent_id']=source['id']
        out['provenance']['parent_revision']=source['revision']
        out['record_sha256']=record_digest(out)
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
            return self.insert_revision(db,out,expected_revision)

    def insert_revision(self,db,out,head):
        """Append a validated snapshot after checking the head in the caller's write transaction."""
        ident=out['id']
        highwater=head
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='plan_deleted_versions'").fetchone():
            highwater=max(highwater,db.execute('SELECT COALESCE(MAX(revision),0) FROM plan_deleted_versions WHERE record_id=?',(ident,)).fetchone()[0])
        out.update(revision=highwater+1,saved_at=now())
        out['record_sha256']=record_digest(out)
        db.execute('INSERT INTO versions VALUES (?,?,?,?)',(ident,out['revision'],canonical(out),out['saved_at']))
        db.execute('INSERT INTO events(at,action,record_id,revision) VALUES (?,?,?,?)',(out['saved_at'],'save',ident,out['revision']))
        return out
