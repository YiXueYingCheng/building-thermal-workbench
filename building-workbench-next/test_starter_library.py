import copy
from pathlib import Path
import tempfile
import unittest

from accdb_import import options
from accdb_conversion import normalise
from component_library import Library
from material_catalog import inventory
from starter_library import describe_choice, material_presets, usage_templates
from usage_schedules import actual_pair


class StarterLibraryTests(unittest.TestCase):
    def test_empty_workspace_has_references_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = dict(records={}, sites={})
            choices, donors = options(catalog, root)
            self.assertEqual(len(choices['choices']), 3)
            self.assertEqual(len(donors), 3)
            materials = inventory(catalog, root)
            self.assertEqual(materials['versions'], [])
            self.assertEqual(materials['presets'][0]['content']['id'], 'ECA_PUBLIC_EXAMPLE')
            self.assertEqual(list(root.iterdir()), [])

    def test_scaled_profiles_and_exact_hour_boundaries(self):
        choices, donors = usage_templates()
        day = donors['demo:daytime']['rules']['people']
        self.assertEqual(actual_pair(day, 100)['weekday'][7:19], [0]+[10]*10+[0])
        self.assertEqual(actual_pair(day, 100)['weekend'], [0]*24)
        night = actual_pair(donors['demo:nighttime']['rules']['lighting'], 50)
        self.assertEqual(night['weekday'][7:19], [400]+[0]*10+[400])
        self.assertEqual(night['weekday'], night['weekend'])
        self.assertEqual(actual_pair(donors['demo:continuous']['rules']['equipment'], 50)['weekday'], [500]*24)
        self.assertTrue(all(c['source']['license'] == 'CC BY 4.0' for c in choices))
        self.assertTrue(all('不是规范值' in c['note'] for c in choices))

    def test_absolute_source_summary_keeps_units_and_values(self):
        donor = dict(rules={k:dict(weekday=[v]*24,weekend=[0]*24) for k,v in [('people',3),('lighting',200),('equipment',400)]},gains=dict(sensible_W_person=90,lighting_heat_fraction=.8))
        result = describe_choice('source:1', '原房间', donor)
        self.assertIn('人数 0–3 人/间', result['summary'])
        self.assertIn('照明 0–200 W/间', result['summary'])
        self.assertEqual(donor['rules']['people']['weekday'], [3]*24)

    def test_explicit_material_copy_preserves_builtin_and_prior_version(self):
        original = material_presets()[0]['content']
        with tempfile.TemporaryDirectory() as directory:
            library = Library(Path(directory))
            row = library.save('material', original['name'], original)
            changed = copy.deepcopy(original)
            changed['states'][0]['resistance_m2K_W'] = .4
            newer = library.save('material', original['name'], changed, row)
            self.assertEqual(newer['revision'], 2)
            self.assertEqual(material_presets()[0]['content'], original)
            self.assertEqual(next(r for r in library.all('material') if r['revision']==1)['content'], original)

    def test_explicit_demo_mapping_reaches_actual_model_schedules(self):
        _, donors = usage_templates()
        donor = donors['demo:daytime']
        source = dict(ROOM=[dict(ID=1,NAME='R1',AREA=100,OF_ROOM_GROUP=1,TYPE=1)],ROOM_GROUP=[dict(ROOM_GROUP_ID=1,IS_AC_ROOM=False)],ROOM_TYPE_DATA=[dict(ID=1,NAME='测试房间')],SCHEDULE_YEAR=[])
        for table in ('OCCUPANT_GAINS','LIGHT_GAINS','EQUIPMENT_GAINS'):
            source[table] = [dict(OF_ROOM=1,GAIN_ID=1)]
        model = {'People':{'OCCUPANT_GAINS_1':dict(number_of_people_schedule_name='Input_R1_people',activity_level_schedule_name='activity',sensible_heat_fraction=.6)},'ElectricEquipment':{'LIGHT_GAINS_1':dict(schedule_name='Input_R1_lighting',fraction_lost=0,fraction_radiant=.3),'EQUIPMENT_GAINS_1':dict(schedule_name='Input_R1_equipment')},'Schedule:Constant':{'activity':dict(hourly_value=150)},'Schedule:File':{}}
        models = {k:copy.deepcopy(model) for k in ('controlled','natural')}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            profiles, sources, checked=normalise(models,source,dict(mapping={'1':'demo:daytime'}),{'1':donor},root)
            people=[float(v) for v in (root/'schedules/Input_R1_people.txt').read_text().splitlines()]
            self.assertEqual(len(people),8760)
            self.assertEqual(people[8],10)
            self.assertEqual(people[5*24+8],0)
            self.assertFalse(profiles[0]['conditioned'])
            self.assertIsNone(profiles[0]['hvac'])
            self.assertIn('日间使用演示',sources['R1']['basis'])
            self.assertEqual(checked,0)  # Explicit replacement, never reported as source preservation.


if __name__=='__main__':
    unittest.main()
