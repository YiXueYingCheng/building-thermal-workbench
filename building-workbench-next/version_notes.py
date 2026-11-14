"""Editable annotations beside immutable calculation snapshots, never inside them."""
from foundation import now
from record_store import Conflict


def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS version_notes (record_id TEXT NOT NULL, revision TEXT NOT NULL, note TEXT NOT NULL, generation INTEGER NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(record_id,revision))')
    db.execute('CREATE TABLE IF NOT EXISTS version_note_events (event_id INTEGER PRIMARY KEY, record_id TEXT NOT NULL, revision TEXT NOT NULL, note TEXT NOT NULL, generation INTEGER NOT NULL, updated_at TEXT NOT NULL)')


def listing(store):
    with store.connect() as db:
        ensure(db)
        return [dict(r) for r in db.execute('SELECT * FROM version_notes ORDER BY record_id,revision')]


def get(store,ident,revision):
    record=store.get(ident,revision)
    with store.connect() as db:
        ensure(db)
        row=db.execute('SELECT * FROM version_notes WHERE record_id=? AND revision=?',(ident,str(record['revision']))).fetchone()
    return dict(row) if row else dict(record_id=ident,revision=str(record['revision']),note='',generation=0,updated_at=None)


def save(store,ident,revision,note,expected_generation):
    record=store.get(ident,revision)
    if not isinstance(note,str) or len(note)>2000:raise ValueError('版本备注最多 2000 字。')
    if type(expected_generation) is not int or expected_generation<0:raise ValueError('请先读取版本备注。')
    note=note.strip();key=(ident,str(record['revision']))
    with store.connect() as db:
        ensure(db);db.execute('BEGIN IMMEDIATE')
        store.get(ident,revision)
        old=db.execute('SELECT * FROM version_notes WHERE record_id=? AND revision=?',key).fetchone()
        generation=old['generation'] if old else 0
        if expected_generation!=generation:raise Conflict('该版本备注已在另一处更新，请重新打开后核对；本次文字尚未覆盖。')
        if note==(old['note'] if old else ''):
            return dict(old) if old else dict(record_id=ident,revision=key[1],note='',generation=0,updated_at=None)
        values=(*key,note,generation+1,now())
        db.execute('INSERT INTO version_notes VALUES(?,?,?,?,?) ON CONFLICT(record_id,revision) DO UPDATE SET note=excluded.note,generation=excluded.generation,updated_at=excluded.updated_at',values)
        db.execute('INSERT INTO version_note_events(record_id,revision,note,generation,updated_at) VALUES(?,?,?,?,?)',values)
    return dict(zip(('record_id','revision','note','generation','updated_at'),values))
