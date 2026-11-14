import copy,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from material_registration import inventory,describe,resistance_template,check_adoption
from material_types import template
from component_library import Library
from material_catalog import adoption_preview
from contracts import normalize,validate_definitions

class MaterialRegistrationTests(unittest.TestCase):
 def test_three_modes_and_no_implied_dynamic_support(self):
  data=inventory();self.assertEqual(len(data['modes']),3)
  for d in (template('film'),resistance_template()):
   self.assertFalse(describe(d)['storage']);self.assertIn('不能用于新版可调热阻',describe(d)['capability'])
  self.assertTrue(describe(template('solid'))['storage']);self.assertIn('不自动获得',describe(template('variable'))['capability'])
 def test_blank_resistance_registration_roundtrips_without_physical_fields(self):
  d=resistance_template();d['name']='隔离验证热阻'
  d['states'][0]['resistance_m2K_W']=.3;d['states'][1]['resistance_m2K_W']=.06
  for o in d['optics'].values():o.update(solar_absorptance=.1,reflectance=.9,emissivity=.9)
  before=copy.deepcopy(d);normalized=normalize({'factors':{'materials':{'definitions':[d]}}})['factors']['materials']['definitions'][0]
  self.assertEqual(validate_definitions([normalized])[1],[]);self.assertEqual(d,before)
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp));r=lib.save('material',d['name'],normalized);self.assertEqual(lib.all('material')[0]['content'],normalized)
  self.assertNotIn('density_kg_m3',r['content']['states'][0]);self.assertNotIn('category',r['content'])
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
