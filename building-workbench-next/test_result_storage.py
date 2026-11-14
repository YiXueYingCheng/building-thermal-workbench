from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import unittest,tempfile,json,sqlite3,os
from foundation import write_json,read_json,digest,sha
import result_storage as rs

class ResultStorageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.attempt='attempt_'+'a'*32
  from execution_queue import Queue
  self.queue=Queue(self.root)
  with self.queue.db() as db:
   db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',('batch_a','review_a',json.dumps(dict(record_id='draft_a',revision=1,record_name='测试方案')),'hash','pause','now'))
   db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,error,updated) VALUES(?,?,?,?,?,?,?)',('batch_a',0,'failed','identity_a',self.attempt,'original failure','now'))
  self.folder=self.root/'runs'/('a'*32)
  self.sql=self.file('run/eplusout.sql',b'failed SQL')
  self.csv=self.file('run/eplusout.csv',b'failed CSV')
  self.log=self.file('run/eplusout.err',b'important diagnostic log')
  self.model=self.file('model.epJSON',b'{}')
 def file(self,name,data):
  p=self.folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
 def doc(self,name,value):
  p=self.root/'data'/name;write_json(p,value,self.root);return p
 def preview(self):return rs.preview(self.root,self.attempt)
 def execute(self,p):return rs.execute(self.root,p['id'],p['sha256'],True)
 def test_failed_bulk_cleanup_keeps_diagnostics_registration_and_inputs(self):
  before=sha(self.queue.path);p=self.preview();self.assertFalse(p['blocked'],p['blocked']);self.assertEqual(len(p['files']),2)
  result=self.execute(p);self.assertEqual(result['removed'],2);self.assertFalse(self.sql.exists());self.assertTrue(self.log.exists() and self.model.exists());self.assertEqual(before,sha(self.queue.path));self.assertEqual(self.execute(p),result)
 def test_confirm_and_checksum_required(self):
  p=self.preview()
  with self.assertRaises(ValueError):rs.execute(self.root,p['id'],p['sha256'],False)
  with self.assertRaises(ValueError):rs.execute(self.root,p['id'],'wrong',True)
  self.assertTrue(self.sql.exists())
 def test_accepted_review_reused_interrupted_and_unknown_protected(self):
  for status in ('passed','review','reused','interrupted','new_status'):
   with self.queue.db() as db:db.execute('UPDATE jobs SET status=?',(status,))
   p=self.preview();self.assertTrue(p['blocked']);self.assertEqual(p['estimated_file_bytes'],0)
   with self.assertRaises(ValueError):self.execute(p)
 def test_direct_reference_calendar_and_review_protected(self):
  for name,value in [('calendar-inspections/a.json',{'batch_id':'batch_a'}),('execution/scientific-reviews/a.json',{'artifacts':{str(self.sql):sha(self.sql)}}),('exports/list.json',[{'batch_id':'batch_a'}])]:
   p=self.doc(name,value);d=rs.inspect(self.root,self.attempt);self.assertTrue(d['references']);self.assertTrue(d['blocked']);p.unlink()
 def test_comparison_and_set_plan_bindings_protected(self):
  p=self.root/'data/drafts.sqlite'
  with closing(sqlite3.connect(p)) as db,db:
   db.execute('CREATE TABLE comparisons(id,payload)');db.execute('CREATE TABLE research_sets(id,revision,payload)')
   db.execute('INSERT INTO comparisons VALUES(?,?)',('compare_a',json.dumps({'name':'对比','left':{'id':'draft_a','revision':1}})))
   db.execute('INSERT INTO research_sets VALUES(?,?,?)',('set_a',1,json.dumps({'name':'四工况','results':{'batch_id':'batch_a'}})))
  d=rs.inspect(self.root,self.attempt);self.assertEqual({r['kind'] for r in d['references']},{'保存的两两比较','对比集及结果绑定'})
 def test_reuse_index_and_history_protected(self):
  with self.queue.db() as db:
   db.execute('INSERT INTO cache VALUES(?,?,?)',('reused_identity',str(self.folder/'result.json'),'checksum'))
   db.execute('INSERT INTO events(created,batch,action,details) VALUES(?,?,?,?)',('now','batch_a','review',json.dumps({'attempt':self.attempt})))
  d=rs.inspect(self.root,self.attempt);self.assertEqual(len(d['references']),2)
 def test_new_reference_after_preview_blocks_execution(self):
  p=self.preview();self.doc('model-inputs/new/manifest.json',{'evidence':{'path':str(self.sql)}})
  with self.assertRaises(ValueError):self.execute(p)
  self.assertTrue(self.sql.exists())
 def test_retry_or_background_after_preview_blocks(self):
  p=self.preview()
  with self.assertRaises(ValueError):rs.execute(self.root,p['id'],p['sha256'],True,True)
  with self.queue.db() as db:db.execute("UPDATE jobs SET status='pending'")
  with self.assertRaises(ValueError):self.execute(p)
 def test_changed_and_new_files_retained(self):
  p=self.preview();self.sql.write_bytes(b'new content');new=self.file('run/eplusout.eso',b'created after preview')
  result=self.execute(p);self.assertEqual((result['removed'],result['retained']),(1,1));self.assertTrue(self.sql.exists() and new.exists())
 def test_shared_file_never_deleted(self):
  os.link(self.sql,self.root/'shared-sql');p=self.preview();self.assertEqual(len(p['files']),1);self.execute(p);self.assertTrue(self.sql.exists())
 def test_partial_failure_receipt(self):
  p=self.preview();unlink=Path.unlink
  def fail(path,*a,**kw):
   if path==self.sql:raise PermissionError('test file in use')
   return unlink(path,*a,**kw)
  with patch.object(Path,'unlink',fail):r=self.execute(p)
  self.assertEqual((r['removed'],r['retained']),(1,1));self.assertTrue(self.sql.exists());self.assertTrue(self.log.exists())
 def test_tampered_target_cannot_delete_logs_or_outside(self):
  p=self.preview();path=self.root/'data/storage-management/previews'/(p['id']+'.json');v=read_json(path)
  v['files'][0]['relative']='runs/'+'a'*32+'/run/eplusout.err';write_json(path,v,self.root)
  r=rs.execute(self.root,p['id'],digest(v),True);self.assertTrue(self.log.exists());self.assertGreater(r['retained'],0)
 def test_unknown_metadata_external_and_links_protected(self):
  p=self.doc('bad.json',{});p.write_text('{')
  self.assertTrue(self.preview()['blocked']);p.unlink()
  with patch.object(rs.output_storage,'entries',return_value=[{},dict(path='Z:/offline',id='offline')]),patch.object(rs.output_storage,'inspect',side_effect=OSError('offline')):
   self.assertTrue(self.preview()['blocked'])
  original=rs.link;inode=self.sql.stat().st_ino
  with patch.object(rs,'link',side_effect=lambda s:original(s) or s.st_ino==inode):self.assertTrue(self.preview()['blocked'])
 def test_expired_preview(self):
  p=self.preview()
  with patch.object(rs.time,'time',return_value=p['expires_epoch']+1):
   with self.assertRaises(ValueError):self.execute(p)
 def test_backup_and_request_exclusion(self):
  with rs.maintenance(self.root):
   with self.assertRaises(ValueError):
    with rs.maintenance(self.root):pass
  gate=rs.Requests()
  with gate.enter():
   with gate.enter():pass
   with self.assertRaises(ValueError):
    with gate.enter(True):pass
  with gate.enter(True):
   with self.assertRaises(ValueError):
    with gate.enter():pass
 def test_database_writer_blocks_cleanup(self):
  p=self.preview()
  with closing(sqlite3.connect(self.queue.path)) as db:
   db.execute('BEGIN IMMEDIATE')
   with self.assertRaises(ValueError):self.execute(p)
  self.assertTrue(self.sql.exists())
 def test_external_attempt_never_deleted(self):
  with patch.object(rs.output_storage,'attempt_folder',return_value=self.root.parent/'external'/'a'):
   p=self.preview();self.assertTrue(p['blocked']);self.assertEqual(p['files'],[])
 def test_malformed_plan_and_history_are_unknown_not_safe(self):
  with self.queue.db() as db:
   db.execute("UPDATE batches SET plan='[]'")
   db.execute('INSERT INTO events(created,batch,action,details) VALUES(?,?,?,?)',('now','batch_a','failed','[]'))
  info=rs.inspect(self.root,self.attempt);self.assertTrue(info['issues']);self.assertTrue(info['blocked']);self.assertTrue(self.sql.exists())

if __name__=='__main__':unittest.main()
