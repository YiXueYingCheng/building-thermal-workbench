import copy,tempfile,unittest,zipfile
from pathlib import Path
from research_exports import tables,export,load_export
from foundation import digest

class SetExportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.cat={'sites':{'one':{'name':'代表城市','eligible':True},'two':{'name':'未计算城市','eligible':True}}}
  def batch(role,total):
   return dict(batch_id=role,usable=True,source={'id':role,'revision':1},results=[dict(site_id='one',accepted=True,acceptance='passed',status='passed',period=[1,1,12,31],mode='controlled',step_minutes=5,days=365,weather_sha256='w',loads=dict(heating_kWh=total/2,cooling_kWh=total/2,total_kWh=total))])
  self.d=dict(id='set_test',revision=1,name='三组',scope={'site_ids':['one','two']},members={k:[batch(k,v)] for k,v in [('baseline',100),('fixed',80),('flip',75)]},audit={'consistent':True,'issues':[]});self.d['dataset_sha256']=digest(self.d)
 def test_pairing_missing_and_negative(self):
  self.d['members']['fixed'][0]['results'][0]['loads']['total_kWh']=110
  rows,evidence=tables(self.d,self.cat,{})
  self.assertEqual(rows[0]['fixed_total_saved_percent'],-10)
  self.assertEqual(rows[0]['flip_total_saved_percent'],25)
  self.assertIsNone(rows[1]['baseline_total_kWh']);self.assertEqual(rows[1]['fixed_pair_status'],'excluded')
  self.assertEqual(len(evidence),3)
 def test_four_conditions_and_incremental_contributions(self):
  from research_figures import coverage,plot_rows
  b=copy.deepcopy(self.d['members']['flip'][0]);b['batch_id']='feedback';b['results'][0]['loads']=dict(heating_kWh=30,cooling_kWh=30,total_kWh=60)
  self.d['members']['feedback']=[b]
  rows,evidence=tables(self.d,self.cat,{})
  self.assertEqual(rows[0]['orientation_increment_total_saved_kWh'],5)
  self.assertEqual(rows[0]['feedback_increment_total_saved_kWh'],15)
  self.assertEqual(coverage(rows)['complete'],1);self.assertEqual(coverage(rows)['paired']['feedback'],1)
  self.assertEqual({r['role'] for r in plot_rows(rows)},{'baseline','fixed','flip','feedback'})
  self.assertIsNone(rows[1]['feedback_increment_total_saved_kWh'])
  self.d['dataset_sha256']=digest(self.d)
  receipt=export(self.d,self.cat,{},self.root);self.assertEqual(receipt['paired']['feedback'],1)
 def test_mismatched_actual_weather_never_paired(self):
  self.d['members']['fixed'][0]['results'][0]['weather_sha256']='other'
  rows,_=tables(self.d,self.cat,{})
  self.assertIsNone(rows[0]['fixed_total_saved_percent']);self.assertEqual(rows[0]['fixed_pair_reason'],'气象不一致')
 def test_unaccepted_and_ambiguous_not_selected(self):
  self.d['members']['fixed'][0]['results'][0].update(accepted=False,status='review')
  rows,_=tables(self.d,self.cat,{});self.assertIsNone(rows[0]['fixed_total_kWh'])
  self.d['members']['baseline'].append(copy.deepcopy(self.d['members']['baseline'][0]));self.d['members']['baseline'][1]['batch_id']='other'
  with self.assertRaisesRegex(ValueError,'多个可用结果'):tables(self.d,self.cat,{})
  rows,_=tables(self.d,self.cat,{'baseline':'other'});self.assertEqual(rows[0]['baseline_batch'],'other')
 def test_zero_baseline_and_inconsistent_common_conditions(self):
  self.d['members']['baseline'][0]['results'][0]['loads']['total_kWh']=0
  rows,_=tables(self.d,self.cat,{});self.assertIsNone(rows[0]['fixed_total_saved_percent']);self.assertEqual(rows[0]['fixed_total_saved_kWh'],-80)
  self.d['audit']={'consistent':False,'issues':['房间设置不一致']}
  rows,_=tables(self.d,self.cat,{});self.assertIsNone(rows[0]['flip_total_saved_kWh'])
 def test_export_repeated_and_tamper_detected(self):
  receipt=export(self.d,self.cat,{},self.root);self.assertEqual(receipt,export(self.d,self.cat,{},self.root))
  folder,_=load_export(receipt['id'],self.root)
  with zipfile.ZipFile(folder/'comparison.zip') as z:self.assertIsNone(z.testzip());self.assertIn('result-evidence.json',z.namelist())
  (folder/'comparison.csv').write_text('changed')
  with self.assertRaisesRegex(ValueError,'内容变化'):load_export(receipt['id'],self.root)

if __name__=='__main__':unittest.main()
