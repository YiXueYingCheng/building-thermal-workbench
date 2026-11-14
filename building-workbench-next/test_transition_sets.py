import copy,tempfile,unittest
from pathlib import Path
from foundation import ROOT,read_json,digest
from record_store import Store
from research_sets import Sets,compatible
from research_execution import baseline_contract,CONTRACT,OUTPUT_CONTRACT
import version_notes

class TransitionSetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  raw=read_json(__import__('starter_library').bundled_file('examples/drawing26/template/records.json'))
  self.c=dict(records=raw,created='test',sites={s:{} for r in raw.values() for s in r['factors']['scope']['site_ids']})
  store=Store(self.c,self.root);self.records={}
  for role in ('baseline','fixed','flip','feedback'):
   origin=raw['global_w00' if role=='baseline' else 'global_fixed'];f=copy.deepcopy(origin['factors'])
   if role in ('flip','feedback'):
    for x in f['condition']['controls']:
     if x['channel']=='orientation':x.update(mode='calendar')
   if role=='feedback':
    ctl=next(x for x in f['condition']['controls'] if x['channel']=='thermal');ctl.update(mode='feedback',rule='UNIFIED',update={'kind':'solver_step'},policy={'cold_C':18.,'hot_C':26.,'flux_deadband_W_m2':1.,'minimum_hold_minutes':60},state_roles={'positive':'R','negative':'C'})
   self.records[role]=store.create(origin['id'],origin['revision'],{'name':role,'factors':f})
  self.sets=Sets(self.c,self.root)
 def refs(self,count):return {k:{'id':r['id'],'revision':r['revision']} for k,r in self.records.items() if count==4 or k!='feedback'}
 def test_three_and_four_create_without_changing_sources(self):
  before=copy.deepcopy(self.records)
  for count in (3,4):
   p=self.sets.create_preview(str(count),self.refs(count));s=self.sets.create(str(count),self.refs(count),p['preview_sha256']);saved=self.sets.get(s['id'])
   self.assertEqual(len(saved['members']),count);self.assertTrue(compatible(self.sets.records(saved))['consistent'])
  self.assertEqual(self.records,before)
  for r in before.values():self.assertEqual(self.sets.store.get(r['id'],r['revision']),r)
 def test_partial_feedback_keeps_unaffected_wall_state(self):
  self.assertTrue(compatible(self.records)['consistent'])
  bad=copy.deepcopy(self.records)
  next(x for x in bad['feedback']['factors']['condition']['controls'] if x['channel']=='thermal' and x['mode']=='fixed')['state_id']='C'
  self.assertFalse(compatible(bad)['consistent'])
 def test_feedback_role_cannot_contain_only_fixed_controls(self):
  bad=copy.deepcopy(self.records);bad['feedback']['factors']['condition']=copy.deepcopy(bad['flip']['factors']['condition'])
  self.assertFalse(compatible(bad)['consistent'])
 def test_member_notes_never_change_set_or_source_snapshots(self):
  p=self.sets.create_preview('four',self.refs(4));s=self.sets.create('four',self.refs(4),p['preview_sha256']);before=self.sets.get(s['id']);member=before['members']['feedback']['record']
  version_notes.save(self.sets.store,member['id'],1,'成员自己的备注',0)
  self.assertEqual(self.sets.get(s['id']),before);self.assertEqual(len(self.sets.records(before)),4)
  source=self.records['feedback'];self.assertEqual(version_notes.get(self.sets.store,source['id'],1)['note'],'')
 def test_short_period_cannot_be_misrepresented_as_annual_reference(self):
  b=copy.deepcopy(self.records['baseline']);b['factors']['scope']['period']=[5,4,5,5]
  self.assertEqual(baseline_contract(b),OUTPUT_CONTRACT)
  b['factors']['scope']['period']=[1,1,12,31];self.assertEqual(baseline_contract(b),CONTRACT)
  b['factors']['condition']['operation']['mode']='natural'
  with self.assertRaises(ValueError):baseline_contract(b)
 def test_four_member_shared_edit_is_atomic_and_old_set_survives(self):
  p=self.sets.create_preview('four',self.refs(4));s=self.sets.create('four',self.refs(4),p['preview_sha256']);old=self.sets.get(s['id'])
  records=self.sets.records(old);f=copy.deepcopy(records['feedback']['factors']);f['scope']['period']=[5,1,5,2]
  request=dict(role='feedback',changes={'factors':f},shared=['scope'])
  preview=self.sets.preview(s['id'],1,request);out=self.sets.save(s['id'],1,request,preview['preview_sha256'])
  self.assertEqual(out['revision'],2);self.assertEqual(self.sets.get(s['id'],1),old)
  self.assertTrue(all(r['revision']==2 and r['factors']['scope']['period']==[5,1,5,2] for r in self.sets.records(self.sets.get(s['id'])).values()))
  with self.assertRaises(ValueError):self.sets.save(s['id'],1,request,preview['preview_sha256'])

if __name__=='__main__':unittest.main()
