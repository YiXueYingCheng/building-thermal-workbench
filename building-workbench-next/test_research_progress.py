import json,sqlite3,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
from research_sets import ref
from foundation import digest
import research_progress as p

class FakeSets:
    def __init__(self,root):
        self.root=root;self.catalog={};self.store=self
        self.r={k:dict(id=k,revision=2,recipe='same',factors={'scope':{'site_ids':['a','b']}}) for k in ('baseline','fixed','flip')}
        self.source=dict(id='source',revision=1,recipe='same',factors={'scope':{'site_ids':['a','b']}})
        self.s=dict(id='set_test',revision=4,members={k:dict(record=ref(r),results=[]) for k,r in self.r.items()});self.s['sha256']=digest(self.s)
    def get(self,ident,revision=None):return self.source if ident=='source' else self.s
    def records(self,snapshot):return self.r

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'data/execution').mkdir(parents=True)
        self.db=sqlite3.connect(self.root/'data/execution/queue.sqlite')
        self.db.executescript('create table batches(id text,review text,checksum text,mode text,created text,plan text);create table jobs(batch text,idx int,status text,pid int,attempt text,error text,updated text);')
        self.sets=FakeSets(self.root);self.patcher=patch.object(p,'recipe',lambda r:r['recipe']);self.patcher.start()
    def tearDown(self):self.patcher.stop();self.db.close();self.temp.cleanup()
    def batch(self,name,record=None,status='passed',site='a',bad_hash=False):
        r=record or self.sets.r['flip'];plan=dict(record_id=r['id'],revision=r['revision'],record_sha256='bad' if bad_hash else ref(r)['sha256'],cases=[{'site_id':site}]);self.db.execute('insert into batches values(?,?,?,?,?,?)',(name,'review',name,'run','2026-11-13',json.dumps(plan)));self.db.execute('insert into jobs values(?,?,?,NULL,?,NULL,?)',(name,0,status,'attempt','now'));self.db.commit()
    def build(self,preparations=None):return p.build(self.sets,'set_test',4,preparations or [])
    def test_member_submission_without_group_preparation(self):
        self.batch('one');r=self.build();self.assertEqual((r['submitted'],r['counts']), (1,{'passed':1}));self.assertEqual(r['cases'][0]['origin'],'member')
    def test_group_and_member_are_deduplicated(self):
        self.batch('one');r=self.build([dict(id='prep',created='now',state='submitted',cases=[dict(role='flip',site_id='a',batch_id='one')])]);self.assertEqual(r['submitted'],1);self.assertEqual(r['cases'][0]['origin'],'group')
    def test_other_versions_and_wrong_digest_excluded(self):
        self.batch('old',dict(self.sets.r['flip'],revision=1));self.batch('wrong',bad_hash=True);self.assertEqual(self.build()['case_count'],0)
    def test_bound_source_requires_recipe_and_plan_checksum(self):
        self.batch('source_batch',self.sets.source);c=dict(source=ref(self.sets.source),recipe='same',batch_id='source_batch',plan_sha256='source_batch');self.sets.s['members']['flip']['results']=[c];self.assertEqual(self.build()['cases'][0]['origin'],'source')
        self.sets.s['sha256']='changed';c['plan_sha256']='wrong';self.assertEqual(self.build()['submitted'],0)
    def test_changed_research_excludes_old_source(self):
        self.batch('source_batch',self.sets.source);self.sets.s['members']['flip']['results']=[dict(source=ref(self.sets.source),recipe='different',batch_id='source_batch',plan_sha256='source_batch')];self.assertEqual(self.build()['submitted'],0)
    def test_live_status_updates_without_rebuilding_bindings(self):
        self.batch('one',status='running');self.assertEqual(self.build()['counts'],{'running':1});self.db.execute("update jobs set status='passed'");self.db.commit()
        with patch.object(p,'projection',side_effect=AssertionError('should reuse binding cache')):self.assertEqual(self.build()['counts'],{'passed':1})
    def test_new_batch_invalidates_binding_cache(self):
        self.batch('one');self.build();self.batch('two',status='review',site='b');self.assertEqual(self.build()['counts'],{'passed':1,'review':1})
    def test_multiple_attempts_retained_not_silently_chosen(self):
        self.batch('one');self.batch('two',status='running');self.assertEqual(self.build()['submitted'],2)
    def test_prepared_unsubmitted_and_missing_are_distinct(self):
        r=self.build([dict(id='prep',created='now',state='prepared',cases=[dict(role='fixed',site_id='a',batch_id=None,review_id='review')])]);self.assertEqual(r['counts'],{'prepared':1});self.assertEqual(r['submitted'],0)
    def test_snapshot_and_queue_are_read_only(self):
        self.batch('one');before=self.db.execute('select * from jobs').fetchall();snapshot=copy.deepcopy(self.sets.s);self.build();self.assertEqual(snapshot,self.sets.s);self.assertEqual(before,self.db.execute('select * from jobs').fetchall())

if __name__=='__main__':unittest.main()
