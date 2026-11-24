import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import plan_cleanup as cleanup
import plan_deletion as deletion
from execution_queue import Queue
from foundation import canonical, digest, write_json
import test_version_notes as fixture


class PlanCleanupTests(unittest.TestCase):
    def setUp(self):
        f=fixture.VersionNotesTests();f.setUp();self.addCleanup(f.doCleanups)
        self.root,self.catalog,self.store=f.root,f.catalog,f.store
        self.record=f.draft();self.id=self.record['id'];self.queue=Queue(self.root)
        self.bundle='inputs_'+'1'*32;self.review='review_'+'2'*32;self.batch='batch_'+'3'*32
        self.attempt='attempt_'+'4'*32
        self.folder=self.root/'data/model-inputs'/self.bundle
        self.run=self.root/'runs'/self.attempt[8:]
        meta=dict(record_id=self.id,revision=1)
        self.file(self.folder/'manifest.json',meta)
        self.file(self.root/'data/execution/reviews'/self.review/'plan.json',meta)
        self.file(self.run/'launch.json',dict(batch=self.batch))
        self.file(self.run/'result.json',dict(attempt=self.attempt))
        with self.queue.db() as db:
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(self.batch,self.review,canonical(meta),'sha','run','now'))
            db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,result,updated) VALUES(?,?,?,?,?,?,?)',(self.batch,0,'passed','identity',self.attempt,str(self.run/'result.json'),'now'))
            db.execute('INSERT INTO cache VALUES(?,?,?)',('identity',str(self.run/'result.json'),'sha'))
        self.prep=self.root/'data/execution/preparations.sqlite'
        with sqlite3.connect(self.prep) as db:
            db.execute('CREATE TABLE preparations(key TEXT PRIMARY KEY,bundle_id TEXT,review TEXT)')
            db.execute('INSERT INTO preparations VALUES(?,?,?)',('prep',self.bundle,self.review))

    def file(self,path,value):write_json(path,value,self.root)
    def preview(self):return deletion.preview(self.root,self.catalog,self.id,'version',1,cleanup=True)
    def execute(self,p):return deletion.execute(self.root,self.catalog,p['id'],p['sha256'],True)

    def test_exclusive_cleanup_and_retry(self):
        self.store.save(self.id,1,{'name':'另一个版本'})
        p=self.preview();self.assertFalse(p['inspection']['blocked']);self.assertTrue(self.run.exists())
        r=self.execute(p);self.assertEqual(r,self.execute(p));self.assertEqual(r['files_deleted'],4)
        self.assertFalse(self.run.exists());self.assertFalse(self.folder.exists())
        self.assertEqual([v['revision'] for v in self.store.history(self.id)],[2])
        with self.queue.db() as db:
            for table in ('cache','batches','jobs'):self.assertFalse(db.execute('SELECT * FROM '+table).fetchall())
        with sqlite3.connect(self.prep) as db:self.assertFalse(db.execute('SELECT * FROM preparations').fetchall())

    def test_changed_scope_dependency_and_interruption(self):
        p=self.preview()
        foreign=self.root/'data/export.json';self.file(foreign,dict(source_batch=self.batch))
        with self.assertRaises(ValueError):self.execute(p)
        self.assertTrue(self.preview()['inspection']['references']);foreign.unlink()
        self.file(self.folder/'new.json',{})
        with self.assertRaises(ValueError):self.execute(p)
        p=self.preview();rename=cleanup.os.replace
        def second_fails(src,dst):
            if Path(dst).name=='1':raise PermissionError('test lock')
            return rename(src,dst)
        with patch.object(cleanup.os,'replace',side_effect=second_fails),self.assertRaises(PermissionError):self.execute(p)
        self.assertTrue((self.folder/'new.json').exists())
        self.assertTrue((self.run/'launch.json').exists())
        self.assertEqual(self.store.get(self.id)['id'],self.id)
        with self.queue.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_registered_evidence_survives_and_shared_run_blocks(self):
        relative=(self.run/'result.json').relative_to(self.root).as_posix()
        data=dict(schema=1,inputs={'x':dict(kind='workspace_file',path=relative)})
        self.file(self.root/'data/history-locations/index.json',dict(data=data,sha256=digest(data)))
        other='batch_'+'a'*32
        with self.queue.db() as db:
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(other,'other','{}','x','run','now'))
            db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,result,updated) VALUES(?,?,?,?,?,?,?)',(other,0,'reused','identity',None,str(self.run/'result.json'),'now'))
        self.assertTrue(self.preview()['inspection']['blocked'])
        with self.queue.db() as db:db.execute('DELETE FROM jobs WHERE batch=?',(other,))
        p=self.preview();self.assertFalse(p['inspection']['blocked']);self.execute(p)
        self.assertTrue((self.run/'result.json').exists())

    def test_changed_reference_even_with_same_size_and_timestamp(self):
        import os
        path=self.root/'data/dependency.json'
        other='draft_'+'0'*32
        self.file(path,{'record_id':other})
        p=self.preview()
        self.assertFalse(p['inspection']['blocked'])
        before=path.stat()
        raw=path.read_bytes().replace(other.encode(),self.id.encode())
        path.write_bytes(raw)
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaises(ValueError):self.execute(p)
        self.assertEqual(self.store.get(self.id)['id'],self.id)

    def test_recover_precommit_staging(self):
        p=self.preview();rows=p['inspection']['cleanup']['files']
        cleanup.stage(self.root,p['id'],rows)
        cleanup.recover(self.root)
        for relative,*_ in rows:self.assertTrue((self.root/relative).is_file())
