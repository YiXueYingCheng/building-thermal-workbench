from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import closing
import unittest,json,os,sqlite3
import storage_management as sm
from foundation import digest

class StorageManagementTests(unittest.TestCase):
 def setUp(self):self.temp=TemporaryDirectory();self.root=Path(self.temp.name)/'workspace';self.root.mkdir()
 def tearDown(self):self.temp.cleanup()
 def file(self,name,data=b'abc'):
  path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path
 def cache(self,key='a'):
  value={'value':{'kept':'source input'},'key':'cache-key','created':'now'};value['sha256']=digest(value['value'])
  return self.file('data/navigation-cache/view-'+key*64+'.json',json.dumps(value).encode())
 def queue(self,status='running'):
  path=self.root/'data/execution/queue.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
  with closing(sqlite3.connect(path)) as db,db:
   db.executescript('CREATE TABLE batches(id TEXT,review TEXT,created TEXT,plan TEXT);CREATE TABLE jobs(batch TEXT,idx INT,status TEXT,attempt TEXT,result TEXT);')
   db.execute('INSERT INTO batches VALUES(?,?,?,?)',('batch_1','review_1','now',json.dumps(dict(record_id='draft_1',revision=2,record_name='方案甲'))))
   db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',('batch_1',0,status,'attempt_'+'a'*32,None))
 def test_inventory_groups_results_by_attempt_and_shared_bytes_once(self):
  self.queue('passed');self.file('runs/'+'a'*32+'/result.json',b'12345');source=self.file('data/weather-files/shared.epw',b'123456789')
  duplicate=self.root/'data/weather-files/shared-copy.epw';os.link(source,duplicate)
  report=sm.inventory(self.root);g=next(g for g in report['groups'] if g['category']=='results')
  self.assertEqual(g['references'][0]['record_id'],'draft_1');self.assertEqual(g['references'][0]['revision'],2)
  weather=next(g for g in report['groups'] if g['category']=='public');self.assertEqual(weather['bytes'],18);self.assertEqual(weather['unique_bytes'],9)
 def test_external_unreadable_is_unknown_not_zero(self):
  item=dict(id='external',label='离线盘',path=str(Path(self.temp.name)/'offline'))
  with patch.object(sm.output_storage,'entries',return_value=[{'id':'local'},item]),patch.object(sm.output_storage,'inspect',side_effect=PermissionError('拒绝访问')):
   data=sm.inventory(self.root)
  loc=data['locations'][-1];self.assertEqual(loc['status'],'unknown');self.assertIsNone(loc['bytes']);self.assertFalse(data['complete'])
 def test_link_boundaries_not_followed(self):
  directory=self.root/'linked';directory.mkdir();self.file('linked/do-not-read.txt');inode=directory.stat().st_ino;original=sm.link
  with patch.object(sm,'link',side_effect=lambda s:original(s) or s.st_ino==inode):
   report=sm.inventory(self.root);self.assertEqual(report['files'],0);self.assertEqual(len(report['links_not_followed']),1)
   with self.assertRaises(ValueError):sm.safe_child(self.root,directory/'do-not-read.txt')
  self.assertTrue(sm.link(SimpleNamespace(st_mode=0,st_file_attributes=0x400)))
  with self.assertRaises(ValueError):sm.safe_child(self.root,Path(self.temp.name)/'outside')
 def test_cache_whitelist_preserves_shared_corrupt_and_other_files(self):
  self.cache();shared=self.cache('b');os.link(shared,self.root/'shared-copy.json');self.file('data/navigation-cache/view-'+'c'*64+'.json',b'{}');self.file('data/navigation-cache/user-data.txt')
  rows,retained=sm.cache_files(self.root);self.assertEqual(len(rows),1);self.assertEqual(len(retained),3)
 def test_explicit_confirmation_and_preview_identity(self):
  cache=self.cache();p=sm.preview(self.root)
  with self.assertRaises(ValueError):sm.execute(self.root,p['id'],p['sha256'],False)
  with self.assertRaises(ValueError):sm.execute(self.root,p['id'],'wrong',True)
  self.assertTrue(cache.exists())
 def test_cleanup_removes_only_frozen_cache_and_is_idempotent(self):
  cache=self.cache();source=self.file('data/model-inputs/source.epJSON');result=self.file('runs/result.json');backup=self.file('backups/keep.zip')
  p=sm.preview(self.root);r=sm.execute(self.root,p['id'],p['sha256'],True)
  self.assertEqual(r['removed'],1);self.assertFalse(cache.exists());self.assertTrue(all(p.exists() for p in (source,result,backup)))
  self.assertEqual(sm.execute(self.root,p['id'],p['sha256'],True),r);self.assertEqual(sm.history(self.root)[0],r)
 def test_changed_cache_retained_and_new_cache_not_included(self):
  changed=self.cache();p=sm.preview(self.root);changed.write_text('updated');new=self.cache('b');r=sm.execute(self.root,p['id'],p['sha256'],True)
  self.assertEqual(r['removed'],0);self.assertEqual(r['retained'],1);self.assertTrue(changed.exists() and new.exists())
 def test_partial_failure_is_reported_without_touching_source(self):
  a=self.cache();b=self.cache('b');p=sm.preview(self.root);unlink=Path.unlink
  def reject(path,*args,**kw):
   if path==b:raise PermissionError('file in use')
   return unlink(path,*args,**kw)
  with patch.object(Path,'unlink',reject):r=sm.execute(self.root,p['id'],p['sha256'],True)
  self.assertEqual((r['removed'],r['retained']),(1,1));self.assertFalse(a.exists());self.assertTrue(b.exists())
 def test_activity_is_rechecked_after_preview(self):
  cache=self.cache();p=sm.preview(self.root);self.queue()
  with self.assertRaises(ValueError):sm.execute(self.root,p['id'],p['sha256'],True)
  self.assertTrue(cache.exists())
 def test_background_and_backup_protection(self):
  self.cache();p=sm.preview(self.root,active=True);self.assertTrue(p['blocked'])
  with self.assertRaises(ValueError):sm.execute(self.root,p['id'],p['sha256'],True,active=True)
  self.file('backups/in-progress.incomplete');self.assertTrue(sm.preview(self.root)['blocked'])
 def test_expiration_requires_new_preview(self):
  self.cache();p=sm.preview(self.root)
  with patch.object(sm.time,'time',return_value=p['expires_epoch']+1):
   with self.assertRaises(ValueError):sm.execute(self.root,p['id'],p['sha256'],True)
 def test_tampered_target_cannot_escape_cache_directory(self):
  cache=self.cache();source=self.file('data/keep.json');p=sm.preview(self.root);path=self.root/'data/storage-management/previews'/(p['id']+'.json');value=json.loads(path.read_text());value['files'][0]['relative']='data/keep.json';path.write_text(json.dumps(value))
  r=sm.execute(self.root,p['id'],digest(value),True);self.assertEqual(r['removed'],0);self.assertTrue(source.exists() and cache.exists())

if __name__=='__main__':unittest.main()
