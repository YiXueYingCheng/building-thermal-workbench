from pathlib import Path
from unittest.mock import patch
import unittest,json,sqlite3,os
from foundation import digest,sha,write_json,read_json
from record_store import Store,Conflict
from component_library import Library
import test_version_notes as fixture
from execution_queue import Queue
import version_notes as notes
import plan_deletion as pd

class PlanDeletionTests(unittest.TestCase):
 def setUp(self):
  f=fixture.VersionNotesTests();f.setUp();self.addCleanup(f.doCleanups);self.root=f.root;self.store=f.store;self.catalog=f.catalog;self.source=f.source
  self.r=f.draft();self.ident=self.r['id']
 def preview(self,revision=None):return pd.preview(self.root,self.catalog,self.ident,'record' if revision is None else 'version',revision)
 def execute(self,p):return pd.execute(self.root,self.catalog,p['id'],p['sha256'],True)
 def revisions(self):return [r['revision'] for r in self.store.history(self.ident)]
 def test_preview_and_cancel_read_only(self):
  before=sha(self.store.path);p=self.preview();self.assertFalse(p['inspection']['blocked']);self.assertEqual(before,sha(self.store.path));self.assertEqual(pd.history(self.root),[])
  with self.assertRaises(ValueError):pd.execute(self.root,self.catalog,p['id'],p['sha256'],False)
  self.assertEqual(self.revisions(),[1]);self.assertEqual(before,sha(self.store.path))
 def test_preview_identifies_referring_versions_and_historical_files(self):
  child=self.store.create(self.ident,1,{'name':'后续研究'})
  self.store.save(self.ident,1,{'name':'第二版'})
  library=Library(self.root)
  calendar=library.save('calendar','日历',{'reference_record':{'id':self.ident,'revision':1}})
  library.save('calendar','日历',{'reference_record':{'id':self.ident,'revision':2}},parent=calendar)
  archive=self.root/'data/history-locations/files/aa/snapshot.json'
  write_json(archive,child,self.root)
  for cleanup in (False,True):
   preview=pd.preview(self.root,self.catalog,self.ident,'record',cleanup=cleanup)['inspection']
   self.assertTrue(preview['blocked'])
   refs=preview['references']
   objects={(obj['id'],obj['revision']):(obj['kind'],ref['relations']) for ref in refs if (obj:=ref.get('source_object'))}
   self.assertEqual(objects[(child['id'],1)],('方案',['另存／来源追溯 · v1']))
   for rev in (1,2):
    self.assertEqual(objects[(calendar['id'],rev)],('日历',['方案引用 · v'+str(rev)]))
   self.assertEqual([Path(ref['history_file']) for ref in refs if ref.get('history_file')],[archive])
 def test_delete_whole_plan_notes_and_atomic_receipt_no_file_removal(self):
  self.store.save(self.ident,1,{'name':'第二版'});other=self.store.create(self.source['id'],self.source['revision'],{'name':'其他方案'})
  notes.save(self.store,self.ident,1,'第一版备注',0);notes.save(self.store,self.ident,2,'第二版备注',0)
  files=[self.root/'runs/keep/result.json',self.root/'data/model-inputs/keep/input.epJSON',self.root/'backups/keep.zip']
  for p in files:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
  before={p:sha(p) for p in files};p=self.preview();r=self.execute(p)
  self.assertEqual((r['removed_versions'],r['removed_current_notes'],r['files_deleted']),(2,2,0));self.assertEqual(self.revisions(),[])
  with self.assertRaises(KeyError):self.store.get(self.ident)
  self.assertEqual(before,{p:sha(p) for p in before});self.assertEqual(self.store.get(other['id']),other)
  self.assertEqual(r,self.execute(p));self.assertEqual(pd.history(self.root),[r]);self.assertEqual(notes.listing(self.store),[])
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM version_note_events').fetchone()[0],2)
 def test_historical_delete_keeps_versions_and_latest_delete_does_not_reuse_number(self):
  v2=self.store.save(self.ident,1,{'name':'二'});v3=self.store.save(self.ident,2,{'name':'三'})
  self.execute(self.preview(2));self.assertEqual(self.revisions(),[3,1]);self.assertEqual(self.store.get(self.ident,3),v3)
  self.execute(self.preview(3));self.assertEqual(self.store.get(self.ident),self.r)
  v4=self.store.save(self.ident,1,{'name':'四'});self.assertEqual(v4['revision'],4)
  with self.assertRaises(Conflict):self.store.save(self.ident,3,{'name':'过期'})
 def test_last_version_removes_plan_and_recreation_is_not_possible(self):
  p=self.preview(1);self.assertIsNone(p['inspection']['target']['latest_after']);self.execute(p)
  with self.assertRaises(KeyError):self.store.save(self.ident,1,{})
  with self.assertRaises(KeyError):self.store.create(self.ident,1,{})
  with self.assertRaises(KeyError):notes.save(self.store,self.ident,1,'孤立备注',0)
 def test_exact_version_references_and_fork_source_protection(self):
  self.store.save(self.ident,1,{'name':'二'});self.store.create(self.ident,1,{'name':'子方案'})
  self.assertTrue(self.preview()['inspection']['blocked']);self.assertTrue(self.preview(1)['inspection']['blocked']);self.assertFalse(self.preview(2)['inspection']['blocked'])
  self.execute(self.preview(2));self.assertEqual(self.revisions(),[1])
 def test_saved_comparisons_block_even_archived_other_plan(self):
  self.store.save(self.ident,1,{'name':'二'})
  self.store.add_comparison('旧关系',dict(id=self.ident,revision=1),dict(id=self.ident,revision=2),'total')
  for rev in (None,1,2):self.assertTrue(self.preview(rev)['inspection']['blocked'])
 def test_set_member_and_historical_set_source_protected(self):
  with self.store.connect() as db:db.execute('INSERT INTO research_set_members VALUES(?,?,?)',(self.ident,'set_'+'1'*32,'baseline'))
  self.assertTrue(self.preview()['inspection']['blocked'])
  with self.store.connect() as db:
   db.execute('DELETE FROM research_set_members')
   db.execute('INSERT INTO research_sets VALUES(?,?,?,?)',('set_'+'1'*32,1,json.dumps({'members':{'baseline':{'source':{'id':self.ident,'revision':1}}}}),'now'))
  self.assertTrue(self.preview(1)['inspection']['references'])
 def test_input_export_calendar_and_unknown_metadata_block(self):
  for name in ('data/model-inputs/record.json','data/calendar/check.json','data/comparison-exports/receipt.json','verification/evidence.json','runs/legacy/extra.json'):
   p=self.root/name;write_json(p,dict(record_id=self.ident,revision=1),self.root)
   self.assertTrue(self.preview()['inspection']['blocked'],name);p.unlink()
  p=self.root/'data/unknown.json';write_json(p,{'file':'somewhere/'+self.ident+'/out'},self.root);self.assertTrue(self.preview(1)['inspection']['blocked'])
 def test_queue_and_secondary_sqlite_references_block(self):
  q=Queue(self.root)
  with q.db() as db:db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',('batch_'+'a'*32,'review',json.dumps(dict(record_id=self.ident,revision=1,record_name='record')),'sha','pause','now'))
  self.assertTrue(self.preview(1)['inspection']['blocked'])
  with q.db() as db:db.execute('DELETE FROM batches')
  p=self.root/'verification/nested/queue.sqlite';p.parent.mkdir(parents=True)
  with sqlite3.connect(p) as db:db.execute('CREATE TABLE evidence (payload TEXT)');db.execute('INSERT INTO evidence VALUES(?)',(json.dumps(dict(id=self.ident,revision=1)),))
  self.assertTrue(self.preview()['inspection']['blocked'])
 def test_invalid_metadata_and_shared_database_block(self):
  p=self.root/'data/broken.json';p.write_text('{bad');self.assertTrue(self.preview()['inspection']['blocked']);p.unlink()
  p=self.root/'linked.sqlite';os.link(self.store.path,p)
  with self.assertRaises(ValueError):self.preview()
  p.unlink()
 def test_concurrent_new_version_note_or_reference_refuses_stale_preview(self):
  p=self.preview();self.store.save(self.ident,1,{'name':'新版本'})
  with self.assertRaises(ValueError):self.execute(p)
  p=self.preview(1);notes.save(self.store,self.ident,1,'新备注',0)
  with self.assertRaises(ValueError):self.execute(p)
  p=self.preview(1);write_json(self.root/'data/new-reference.json',{'record_id':self.ident},self.root)
  with self.assertRaises(ValueError):self.execute(p)
  self.assertEqual(self.revisions(),[2,1])
 def test_source_invalid_expired_and_tampered_preview_rejected(self):
  source=pd.preview(self.root,self.catalog,self.source['id'],'record');self.assertTrue(source['inspection']['blocked'])
  with self.assertRaises(ValueError):pd.execute(self.root,self.catalog,source['id'],source['sha256'],True)
  p=self.preview()
  with patch.object(pd.time,'time',return_value=p['expires_epoch']+1):
   with self.assertRaises(ValueError):self.execute(p)
  file=self.root/'data/storage-management/previews'/(p['id']+'.json');v=read_json(file);v['inspection']['target']['versions'][0]['revision']=999;write_json(file,v,self.root)
  with self.assertRaises(ValueError):pd.execute(self.root,self.catalog,p['id'],digest(v),True)
  self.assertEqual(self.revisions(),[1])
 def test_running_backup_and_database_writer_block(self):
  p=self.preview()
  with self.assertRaises(ValueError):pd.execute(self.root,self.catalog,p['id'],p['sha256'],True,True)
  backup=self.root/'backups/x.incomplete';backup.parent.mkdir();backup.write_text('in progress')
  with self.assertRaises(ValueError):self.execute(p)
  backup.unlink()
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   with self.assertRaises(sqlite3.OperationalError):self.execute(p)
  self.assertEqual(self.revisions(),[1])
 def test_transaction_failure_rolls_back_every_version_note_and_receipt(self):
  self.store.save(self.ident,1,{'name':'two'});notes.save(self.store,self.ident,1,'note',0)
  p=self.preview()
  # Abort the second deletion after the first has run within the same transaction.
  with self.store.connect() as db:db.execute("CREATE TRIGGER test_abort BEFORE DELETE ON versions WHEN OLD.revision=2 BEGIN SELECT RAISE(ABORT,'test failure'); END")
  before=sha(self.store.path)
  with self.assertRaises(sqlite3.IntegrityError):self.execute(p)
  self.assertEqual(self.revisions(),[2,1]);self.assertEqual(notes.get(self.store,self.ident,1)['note'],'note');self.assertEqual(pd.history(self.root),[]);self.assertEqual(before,sha(self.store.path))
 def test_directional_dependencies_and_historical_inventory(self):
  self.store.save(self.ident,1,{'name':'二'})
  manifest=self.root/'data/integration-sources/8796/manifest/entity-keys.json'
  write_json(manifest,{'tables':[{'record_id':self.ident,'revision':1}],'peer_roots':[]},self.root)
  write_json(manifest.parent.parent/'RECEIPT.json',dict(origin='source',snapshot_cut='date',sealed=True,files=[dict(file='manifest/entity-keys.json',sha256=sha(manifest))]),self.root)
  v=self.preview(1)['inspection']
  self.assertFalse(v['blocked']);self.assertEqual(len(v['historical_mentions']),1)
  self.assertIn(self.source['id'],[r['id'] for r in v['target']['versions'][0]['outgoing']])
  loc=self.root/'data/model-inputs/inputs_example'
  for name in ('manifest','record'):
   write_json(loc/(name+'.json'),{'record_id':self.ident,'revision':2},self.root)
  v=self.preview(2)['inspection']
  self.assertEqual({r['owner'] for r in v['references']},{'inputs_example'})
  self.assertTrue(v['blocked']);self.assertFalse(self.preview(1)['inspection']['blocked'])
 def test_index_refresh_and_escaped_ids_in_large_metadata(self):
  path=self.root/'data/large.json'
  path.write_bytes(b'{"padding":"'+b' '*(17*2**20)+b'"}')
  self.assertFalse(self.preview()['inspection']['blocked'])
  path.write_text('{"record_id":"\\u0064'+self.ident[1:]+'","revision":1}')
  self.assertTrue(self.preview()['inspection']['references'])
  path.write_text('{invalid')
  info=self.preview()['inspection']
  self.assertTrue(info['blocked']);self.assertIn(str(path),info['issues'][0])
 def test_unknown_revision_reference_is_conservative(self):
  self.store.save(self.ident,1,{'name':'two'})
  write_json(self.root/'data/ref.json',{'id':self.ident,'revision':'unknown'},self.root)
  self.assertTrue(self.preview(2)['inspection']['blocked'])

if __name__=='__main__':unittest.main()
