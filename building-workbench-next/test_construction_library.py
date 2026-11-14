import copy,tempfile,unittest
from pathlib import Path
from component_library import Library
from test_reference_materials import model,definition,record as material_record
import construction_library as cl
import surface_materials as sm

class ConstructionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.lib=Library(Path(self.temp.name))
  layers=[dict(sequence=i,thickness_mm=d,material=dict(name=n,conductivity_W_mK=k,density_kg_m3=r,specific_heat_J_kgK=900)) for i,d,n,k,r in [(1,20,'外层',.04,50),(2,180,'内层',1.4,2300)]]
  self.row=self.lib.save('construction','试验构造',dict(schema_version=1,layers=layers))
  self.r=dict(factors=dict(building={cl.KEY:[dict(reference=self.row,target_ids=['wall'],order='original',optics_basis='retain_target_surface_optics')]},materials=dict(definitions=[])))

 def test_layers_order_properties_and_unselected_geometry_preserved(self):
  m=model();old=copy.deepcopy(m);a=cl.apply(m,self.r)[0]
  self.assertEqual(a['material_names'],['外层','内层'])
  self.assertEqual(m['Material'][a['layers_after'][0]]['thickness'],.02)
  self.assertEqual(m['Material'][a['layers_after'][1]]['density'],2300)
  self.assertEqual(m['Material']['base'],old['Material']['base'])
  for k in ('roof','interior'):self.assertEqual(m['BuildingSurface:Detailed'][k],old['BuildingSurface:Detailed'][k])
  self.assertEqual({k:v for k,v in m['BuildingSurface:Detailed']['wall'].items() if k!='construction_name'},{k:v for k,v in old['BuildingSurface:Detailed']['wall'].items() if k!='construction_name'})
  self.r['factors']['building'][cl.KEY][0]['order']='reversed'
  self.assertEqual(cl.apply(model(),self.r)[0]['material_names'],['内层','外层'])

 def test_original_inner_outer_optics_are_preserved(self):
  m=model();m['Material']['inner']=dict(m['Material']['base'],solar_absorptance=.3)
  m['Construction']['shared']['layer_2']='inner'
  a=cl.apply(m,self.r)[0]
  self.assertEqual(m['Material'][a['layers_after'][0]]['solar_absorptance'],.6)
  self.assertEqual(m['Material'][a['layers_after'][1]]['solar_absorptance'],.3)

 def test_fixed_material_applies_after_new_construction(self):
  r=material_record(definition('solid'));r['factors']['building']=self.r['factors']['building']
  m=model();a=cl.apply(m,r)[0];sm.apply(m,r)
  c=m['Construction'][m['BuildingSurface:Detailed']['wall']['construction_name']]
  self.assertEqual(c['layer_2'],a['layers_after'][0]);self.assertEqual(c['layer_3'],a['layers_after'][1])

 def test_pinned_old_version_remains_unchanged_and_tampering_rejected(self):
  content=copy.deepcopy(self.row['content']);content['layers'][0]['thickness_mm']=30
  self.lib.save('construction','更新构造',content,self.row)
  a=cl.apply(model(),self.r)[0];self.assertEqual(a['revision'],1)
  self.r['factors']['building'][cl.KEY][0]['reference']['content']['layers'][0]['thickness_mm']=99
  with self.assertRaisesRegex(ValueError,'快照'):cl.apply(model(),self.r)

 def test_invalid_state_and_overlapping_edits_are_rejected(self):
  for patch in ({'envelope_overrides':{'wall':{}}},):
   r=copy.deepcopy(self.r);r['factors']['building'].update(patch)
   with self.assertRaises(ValueError):cl.apply(model(),r)
  r=copy.deepcopy(self.r);r['factors']['materials']['definitions']=[dict(model='eca_legacy')]
  with self.assertRaises(ValueError):cl.apply(model(),r)
  m=model();m['SurfaceControl:MovableInsulation']={'m':dict(surface_name='wall')}
  with self.assertRaises(ValueError):cl.apply(m,self.r)
  for key,value in [('density_kg_m3',None),('specific_heat_J_kgK',50)]:
   c=copy.deepcopy(self.row['content']);c['layers'][0]['material'][key]=value
   with self.assertRaises(ValueError):cl.validate_content(c)

if __name__=='__main__':unittest.main()
