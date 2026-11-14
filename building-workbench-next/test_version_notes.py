import copy
from pathlib import Path
import tempfile
import unittest
from foundation import ROOT,read_json,digest
from record_store import Store,Conflict
import version_notes as notes


class VersionNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        records=read_json(__import__('starter_library').bundled_file('examples/drawing26/template/records.json'))
        self.catalog=dict(records=records,created='fixture',sites={s:{} for r in records.values() for s in r['factors']['scope']['site_ids']})
        self.store=Store(self.catalog,self.root);self.source=records['global_fixed']

    def draft(self,name='另存时的名称'):
        return self.store.create(self.source['id'],self.source['revision'],{'name':name})

    def test_save_as_has_one_named_version_and_preserves_source(self):
        before=copy.deepcopy(self.source);r=self.draft()
        self.assertEqual(r['name'],'另存时的名称');self.assertEqual(r['revision'],1)
        self.assertEqual(len(self.store.history(r['id'])),1)
        self.assertEqual(self.store.get(self.source['id']),before)

    def test_notes_do_not_change_any_snapshot_or_comparison_binding(self):
        a=self.draft();b=self.store.save(a['id'],1,{'name':'later name'})
        comp=self.store.add_comparison('同方案两个版本',{'id':a['id'],'revision':1},{'id':a['id'],'revision':2},'total')
        before=[digest(self.store.get(a['id'],n)) for n in (1,2)]
        notes.save(self.store,a['id'],1,'固定蓬松',0);notes.save(self.store,a['id'],2,'参数调整',0)
        self.assertEqual(notes.get(self.store,a['id'],1)['note'],'固定蓬松')
        self.assertEqual(notes.get(self.store,a['id'],2)['note'],'参数调整')
        self.assertEqual(before,[digest(self.store.get(a['id'],n)) for n in (1,2)])
        self.assertEqual(self.store.comparisons(),[comp]);self.assertEqual(len(self.store.history(a['id'])),2)

    def test_edit_conflict_and_idempotency_preserve_text(self):
        r=self.draft();first=notes.save(self.store,r['id'],1,'first',0)
        with self.assertRaises(Conflict):notes.save(self.store,r['id'],1,'stale',0)
        self.assertEqual(notes.get(self.store,r['id'],1),first)
        self.assertEqual(notes.save(self.store,r['id'],1,'first',1),first)
        saved=notes.save(self.store,r['id'],1,'second',1);self.assertEqual(saved['generation'],2)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM version_note_events').fetchone()[0],2)

    def test_source_annotation_is_local_and_does_not_leak_to_copy(self):
        before=copy.deepcopy(self.catalog)
        notes.save(self.store,self.source['id'],self.source['revision'],'来源说明',0)
        r=self.draft();self.assertEqual(notes.get(self.store,r['id'],1)['note'],'')
        self.assertEqual(self.catalog,before)
        reopened=Store(self.catalog,self.root);self.assertEqual(notes.get(reopened,self.source['id'],self.source['revision'])['note'],'来源说明')

    def test_invalid_and_missing_versions_do_not_write_notes(self):
        r=self.draft()
        with self.assertRaises(ValueError):notes.save(self.store,r['id'],1,'x'*2001,0)
        with self.assertRaises(KeyError):notes.save(self.store,r['id'],999,'unknown',0)
        self.assertEqual(notes.listing(self.store),[])

if __name__=='__main__':unittest.main()
