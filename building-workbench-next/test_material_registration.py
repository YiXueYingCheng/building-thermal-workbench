import copy,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from material_registration import inventory,describe,resistance_template,check_adoption
from material_types import template
from component_library import Library
from material_catalog import adoption_preview
from contracts import normalize,validate_definitions

class MaterialRegistrationTests(unittest.TestCase):
 def test_fixed_scope_preserves_assignments_and_insulation_method(self):
  from drawing_wall_scope import select,fixed_partial
  from surface_materials import apply_fixed
  from test_reference_materials import model,record
  d=resistance_template()
  for s,r in zip(d['states'],(.3,.06)):s['resistance_m2K_W']=r
  for k,o in d['optics'].items():o.update(solar_absorptance=.08 if k[0]=='A' else .82,emissivity=.66)
  ids=['north','south','east']
  r=record(d,ids);r['factors']['building']={'wall_ids':ids}
  app=r['factors']['materials']['applications'][0];app.update(placement_basis='legacy_outer_equivalent_model',component='wall')
  thermal,face=r['factors']['condition']['controls'];thermal['target_ids']=['north']
  r['factors']['condition']['controls'] += [{**thermal,'target_ids':['south','east'],'state_id':'C'}]
  face.update(face_id='B')
  selected=select(r,ids,['east','north'],[])
  m=model();walls=m['BuildingSurface:Detailed']
  for ident in ids:walls[ident]=copy.deepcopy(walls['wall'])
  self.assertEqual(selected['factors']['materials']['applications'][0]['placement_basis'],app['placement_basis'])
  apply_fixed(m,fixed_partial(selected))
  found={}
  for x in m['SurfaceControl:MovableInsulation'].values():
   mat=m['Material:NoMass'][x['material_name']]
   found[x['surface_name']]=mat['thermal_resistance']*m['Schedule:Constant'][x['schedule_name']]['hourly_value']
   self.assertEqual(mat['solar_absorptance'],.82)
  self.assertEqual(found,{'north':.3,'east':.06})
  self.assertEqual(walls['south']['construction_name'],'shared')
  self.assertEqual(m['Material']['base']['solar_absorptance'],.6)
 def test_legacy_feedback_uses_only_explicit_control_selection(self):
  from material_catalog import legacy_feedback_options
  app=dict(id='layer',placement_basis='legacy_outer_equivalent_model',target_ids=['west','east','north'])
  control=dict(application_id='layer',channel='thermal',mode='fixed',target_ids=app['target_ids'])
  record=dict(factors=dict(materials=dict(applications=[app]),condition=dict(controls=[control])))
  catalog=dict(dynamic_registry=dict(walls=[dict(surface=w,eligible=w!='east',zone='room',area_m2=10.) for w in ('west','east','uncovered')]))
  def selected():
   options=legacy_feedback_options(record,catalog)
   self.assertEqual([r['id'] for r in options],app['target_ids'])
   self.assertEqual([r['id'] for r in options if r['supported']],['west','east'])
   return [r['id'] for r in options if r['selected']]
  self.assertEqual(selected(),[])
  record['factors']['condition']['controls']=[dict(control,target_ids=['east'],mode='feedback'),
                                              dict(control,target_ids=['west','north'])]
  self.assertEqual(selected(),['east'])
  app['placement_basis']='fixed_surface_material_v1'
  with self.assertRaises(ValueError):legacy_feedback_options(record,catalog)
 def test_browser_can_adopt_new_material_without_weakening_snapshot_check(self):
  import json
  from record_store import Store
  from component_library import verify
  base={'factors':{'materials':{'definitions':[], 'applications':[]}}}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store=Store({},root)
   content={'name':'宽带面','measured':1.0}
   ref=Library(root).save('material','宽带面',content)
   changes={'factors':{'materials':{'definitions':[content],'definition_reference':ref}}}
   wire=json.loads(json.dumps(changes),parse_float=lambda s:int(float(s)))
   adopted=store.draft_payload(base,wire)['factors']['materials']
   self.assertEqual(verify(adopted['definition_reference'],'material'),ref)
   self.assertIs(type(adopted['definitions'][0]['measured']),float)
   for changed in (0,True,'1'):
    wrong=copy.deepcopy(wire)
    wrong['factors']['materials']['definition_reference']['content']['measured']=changed
    with self.assertRaises(ValueError):
     verify(store.draft_payload(base,wrong)['factors']['materials']['definition_reference'])
 def test_registration_modes_and_no_implied_dynamic_support(self):
  data=inventory();self.assertEqual({m['id'] for m in data['modes']},{'optical','storage','resistance','pcm','spectral','stack'})
  for d in (template('film'),resistance_template()):
   self.assertFalse(describe(d)['storage']);self.assertIn('不能用于新版可调热阻',describe(d)['capability'])
  self.assertTrue(describe(template('solid'))['storage']);self.assertIn('可在工况中启用统一热阻反馈',describe(template('variable'))['capability'])
 def test_blank_resistance_registration_roundtrips_without_physical_fields(self):
  d=resistance_template();d['name']='隔离验证热阻'
  d['states'][0]['resistance_m2K_W']=.3;d['states'][1]['resistance_m2K_W']=.06
  for o in d['optics'].values():o.update(solar_absorptance=.1,reflectance=.9,emissivity=.9)
  before=copy.deepcopy(d);normalized=normalize({'factors':{'materials':{'definitions':[d]}}})['factors']['materials']['definitions'][0]
  self.assertEqual(validate_definitions([normalized])[1],[]);self.assertEqual(d,before)
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp));r=lib.save('material',d['name'],normalized);self.assertEqual(lib.all('material')[0]['content'],normalized)
  self.assertNotIn('density_kg_m3',r['content']['states'][0]);self.assertNotIn('category',r['content'])
 def test_legacy_measurements_roundtrip_without_scheme_settings(self):
  from material_catalog import import_definition, normalize_library_material
  material=resistance_template()
  material['name']='旧材料物性'
  material['states'][0].update(density_kg_m3=3.07, specific_heat_J_kgK=1200, areal_mass_kg_m2=.0307, areal_capacity_J_m2K=36.84)
  checked=normalize_library_material(material)
  self.assertEqual(import_definition(dict(schema='workbench-material/v1',source_revision=1,material=checked)),checked)
  self.assertEqual(checked['states'][0]['areal_capacity_J_m2K'],36.84)
  material['states'][0]['areal_mass_kg_m2']={'scheme_id':'other'}
  with self.assertRaises(ValueError):normalize_library_material(material)
 def test_nonstorage_adoption_rejects_feedback_before_any_adapter(self):
  record={'factors':{'condition':{'controls':[{'channel':'thermal','mode':'feedback'}]}}}
  for d in (template('film'),resistance_template()):
   before=copy.deepcopy(record)
   with self.assertRaisesRegex(ValueError,'不计入新增材料层蓄热'):check_adoption(record,d)
   self.assertEqual(record,before)
  check_adoption(record,template('solid')) # Its fixed-only adapter still applies its own restrictions.
 def test_api_adoption_guard_rejects_no_storage_and_keeps_history(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);lib=Library(root);d=resistance_template();r=lib.save('material','热阻',d)
   record={'factors':{'condition':{'controls':[{'channel':'thermal','mode':'feedback'}]}}};before=copy.deepcopy(record)
   with self.assertRaisesRegex(ValueError,'可调热阻'):adoption_preview(record,{k:r[k] for k in ('id','revision','sha256')},{},root)
   self.assertEqual(record,before);self.assertEqual(lib.all('material')[0],r)
 def test_fixed_and_calendar_not_mistaken_for_thermal_feedback(self):
  for controls in ([],[dict(channel='thermal',mode='fixed'),dict(channel='orientation',mode='calendar')]):
   check_adoption(dict(factors=dict(condition=dict(controls=controls))),resistance_template())
 def test_unknown_model_has_no_advertised_capability(self):self.assertIsNone(describe({'model':'unknown'}))

if __name__=='__main__':unittest.main()
