import copy,unittest,tempfile
from pathlib import Path
import material_types as mt
import surface_materials as sm
from component_library import Library
from test_reference_materials import definition,record,model
from contracts import normalize

class InputMeaningTests(unittest.TestCase):
 def test_old_absorption_is_not_reinterpreted_or_given_metadata(self):
  d=definition('film');d['optics']['A_R']['solar_absorptance']=.955
  before=copy.deepcopy(d);out=normalize(record(d))['factors']['materials']['definitions'][0]
  self.assertEqual(out,before);self.assertNotIn('solar_input',out['optics']['A_R'])
  a=sm.apply(model(),record(d));self.assertEqual(a['model'],'optical_surface_v1')

 def test_reflection_input_matches_generated_absorption_and_mismatch_fails(self):
  d=definition('film');o=d['optics']['A_R'];o.update(solar_input=dict(quantity='reflectance',value=.955),solar_absorptance=1-.955)
  self.assertEqual(mt.validate(d,True),[])
  m=model();audit=sm.apply(m,record(d));self.assertAlmostEqual(m['Material'][audit['surfaces'][0]['layers_after'][0]]['solar_absorptance'],.045)
  o['solar_absorptance']=.955;self.assertTrue(mt.validate(d,True))

 def test_density_requires_explicit_confirmation_and_preserves_independent_cp_k(self):
  d=definition('variable');d['states'][0].update(thickness_mm=15,density_kg_m3=3.7,specific_heat_J_kgK=1200)
  d['states'][1].update(thickness_mm=3,density_kg_m3=7,specific_heat_J_kgK=1400,conductivity_W_mK=.08)
  with self.assertRaises(ValueError):mt.density_preview(d)
  p=mt.density_preview(d,confirmed=True)
  self.assertAlmostEqual(p['target_after']['density_kg_m3'],18.5)
  self.assertAlmostEqual(p['source_summary']['areal_mass_kg_m2'],.0555)
  self.assertAlmostEqual(p['target_summary']['areal_mass_kg_m2'],.0555)
  self.assertEqual(p['target_after']['specific_heat_J_kgK'],1400);self.assertEqual(p['target_after']['conductivity_W_mK'],.08)
  self.assertEqual(d['states'][1]['density_kg_m3'],7)

 def test_derived_relation_roundtrip_and_dependency_changes_fail_without_overwriting(self):
  d=definition('variable');p=mt.density_preview(d,cp_rule='shared',confirmed=True)
  d['states'][1]=p['target_after'];d['state_relationship']=p['relationship'];self.assertEqual(mt.validate(d,True),[])
  with tempfile.TemporaryDirectory() as temp:
   lib=Library(Path(temp));row=lib.save('material','推算材料',d);self.assertEqual(lib.all('material')[0]['content'],d)
  for key,value in [('thickness_mm',4),('density_kg_m3',99),('specific_heat_J_kgK',500)]:
   changed=copy.deepcopy(d);changed['states'][1][key]=value;before=copy.deepcopy(changed)
   self.assertTrue(mt.validate(changed,True));self.assertEqual(changed,before)
  changed=copy.deepcopy(d);changed['states'][0]['density_kg_m3']+=1;self.assertTrue(mt.validate(changed,True))

 def test_source_direction_is_explicit_and_not_name_dependent(self):
  d=definition('variable');d['states'][0]['name']='任意名称';d['states'][1]['name']='不是高低判据'
  p=mt.density_preview(d,source_state='C',confirmed=True)
  self.assertEqual(p['relationship']['target_state'],'R');self.assertEqual(p['source']['name'],'不是高低判据')
  for value in (0,-1,float('inf'),None):
   d['states'][1]['thickness_mm']=value
   with self.assertRaises(ValueError):mt.density_preview(d,source_state='C',confirmed=True)

 def test_single_layer_inside_optics_preserved_mass_and_nomass(self):
  for kind in ('Material','Material:NoMass'):
   for explicit in (False,True):
    m=model();base=m['Material']['base']
    if kind=='Material:NoMass':
     base={k:v for k,v in base.items() if k not in ('thickness','conductivity','density','specific_heat')};base['thermal_resistance']=.3;m['Material:NoMass']={'base':base};m.pop('Material')
    if explicit:base.update(solar_absorptance_inside_face=.3,thermal_absorptance_inside_face=.8,visible_absorptance_inside_face=.4)
    old=copy.deepcopy(base);d=definition('film');d['optics']['A_R'].update(emissivity=.85,visible_absorptance=.1)
    a=sm.apply(m,record(d));new=m[kind][a['surfaces'][0]['layers_after'][0]]
    for field,default in [('solar_absorptance',.7),('thermal_absorptance',.9),('visible_absorptance',.7)]:self.assertEqual(new[field+'_inside_face'],old.get(field+'_inside_face',old.get(field,default)))
    self.assertEqual(m[kind]['base'],old);self.assertEqual(new['solar_absorptance'],.2)
    self.assertEqual(len(m['Construction'][m['BuildingSurface:Detailed']['wall']['construction_name']]),1)

 def test_multiple_layers_do_not_alter_inner_layer(self):
  m=model();m['Material']['inner']=dict(m['Material']['base'],solar_absorptance=.4);m['Construction']['shared']['layer_2']='inner';old=copy.deepcopy(m['Material']['inner'])
  a=sm.apply(m,record(definition('film')));self.assertEqual(m['Material']['inner'],old)
  self.assertIsNone(a['surfaces'][0]['preserved_inside_optics'])

 def test_visible_inheritance_differences_default_and_override(self):
  m=model();m['Material']['roof_outer']=dict(m['Material']['base'],visible_absorptance=.3);m['Construction']['roof']={'outside_layer':'roof_outer'};m['BuildingSurface:Detailed']['roof']['construction_name']='roof'
  a=sm.apply(m,record(definition('solid'),['wall','roof']))
  self.assertEqual([r['visible_absorptance']['value'] for r in a['surfaces']],[.6,.3])
  self.assertTrue(all(r['visible_absorptance']['source']=='target_outer_layer' for r in a['surfaces']))
  m=model();m['Material']['base'].pop('visible_absorptance');a=sm.apply(m,record(definition('film')))
  self.assertEqual(a['surfaces'][0]['visible_absorptance']['value'],.7);self.assertEqual(a['surfaces'][0]['visible_absorptance']['source'],'engine_default')
  d=definition('film');d['optics']['A_R']['visible_absorptance']=.12;a=sm.apply(model(),record(d))
  self.assertEqual(a['surfaces'][0]['visible_absorptance']['source'],'user_override')

if __name__=='__main__':unittest.main()
