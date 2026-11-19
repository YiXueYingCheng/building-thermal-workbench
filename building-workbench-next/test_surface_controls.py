import copy
import unittest

from contracts import normalize
from material_catalog import import_definition
from surface_controls import apply, fixed
from surface_materials import baseline
from test_reference_materials import definition, model, record


def fixture():
    material = definition('variable')
    material['faces'] = ['A', 'B']
    material['optics']['B_R'] = dict(material['optics']['A_R'], solar_absorptance=.8)
    scheme = record(material, ['roof'])
    scheme['numerics'] = {'step_minutes': 1}
    thermal, orientation = scheme['factors']['condition']['controls']
    thermal.update(mode='feedback', rule='UNIFIED', reference_step_minutes=5,
                   policy=dict(cold_C=18, hot_C=26, flux_deadband_W_m2=1, minimum_hold_minutes=60),
                   update=dict(kind='minutes', minutes=5))
    orientation.update(mode='calendar', reference_id='local')
    scheme['factors']['condition']['reference_runs'] = [dict(id='local', kind='workspace_daily_calendar_v1')]
    geometry = model()
    geometry['Zone'] = {'Room': {'multiplier': 2}}
    geometry['Timestep'] = {'Time step': {'number_of_timesteps_per_hour': 12}}
    geometry['BuildingSurface:Detailed']['roof']['vertices'] = [
        dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=3)
        for x, y in [(0, 0), (2, 0), (2, 2), (0, 2)]]
    return scheme, geometry


class SurfaceControlTests(unittest.TestCase):
    def test_combined_controls_on_selected_roof_only(self):
        scheme, geometry = fixture()
        original = copy.deepcopy(scheme)
        audit = apply(geometry, scheme, [1] + [0] * 364)
        self.assertEqual(audit['feedback_area_m2'], 8)
        self.assertEqual(geometry['BuildingSurface:Detailed']['wall']['construction_name'], 'shared')
        self.assertEqual(geometry['Timestep']['Time step']['number_of_timesteps_per_hour'], 60)
        layer = geometry['Material'][audit['surfaces'][0]['layers_after'][0]]
        self.assertAlmostEqual(layer['thickness'] * layer['density'], .2)
        self.assertAlmostEqual(layer['thickness'] / layer['conductivity'], .25)
        lines = [r['program_line'] for r in geometry['EnergyManagementSystem:Program']['NX_SC_Control']['lines']]
        for line in ('SET NX_SC_K0 = 0.02', 'SET NX_SC_K0 = 0.04',
                     'SET NX_SC_S0 = 0.2', 'SET NX_SC_S0 = 0.8', 'IF DayOfYear >= 2'):
            self.assertIn(line, lines)
        self.assertEqual(baseline(scheme)['numerics']['step_minutes'], 5)
        self.assertEqual(fixed(scheme)['factors']['condition']['reference_runs'], [])
        self.assertEqual(scheme, original)

    def test_missing_calendar_and_incompatible_mass(self):
        scheme, geometry = fixture()
        with self.assertRaisesRegex(ValueError, '365'):
            apply(geometry, scheme, [1])
        scheme['factors']['materials']['definitions'][0]['states'][1]['density_kg_m3'] *= 2
        with self.assertRaisesRegex(ValueError, '面质量'):
            apply(geometry, scheme, [1] * 365)

    def test_passive_wall_uses_its_own_state_and_the_shared_calendar(self):
        scheme, geometry = fixture()
        factors = scheme['factors']
        material = factors['materials']['definitions'][0]
        material['optics_depend_on_state'] = True
        for face, solar in [('A', .3), ('B', .6)]:
            material['optics'][face + '_C'] = dict(material['optics'][face + '_R'], solar_absorptance=solar)
        targets = ['roof', 'wall']
        app = factors['materials']['applications'][0]
        feedback, optical = factors['condition']['controls']
        app['target_ids'] = targets
        optical['target_ids'] = targets.copy()
        passive = dict(channel='thermal', application_id=app['id'], mode='fixed', state_id='C', target_ids=['wall'])
        factors['condition']['controls'].append(passive)
        overlap = copy.deepcopy(scheme)
        overlap['factors']['condition']['controls'][-1]['target_ids'].append('roof')
        with self.assertRaisesRegex(ValueError, '恰好属于一个热学分组'):
            apply(copy.deepcopy(geometry), overlap, [1] * 365)
        audit = apply(geometry, scheme, [1] + [0] * 364)
        self.assertEqual(feedback['target_ids'], ['roof'])
        self.assertEqual(audit['feedback_area_m2'], 8)
        self.assertEqual([w['thermal_mode'] for w in audit['surfaces']], ['feedback', 'fixed'])
        actuators = geometry['EnergyManagementSystem:Actuator']
        self.assertIn('NX_SC_K0', actuators)
        self.assertNotIn('NX_SC_K1', actuators)
        lines = [x['program_line'] for x in geometry['EnergyManagementSystem:Program']['NX_SC_Control']['lines']]
        passive_solar = [line for line in lines if line.startswith('SET NX_SC_S1 =')]
        self.assertCountEqual(passive_solar, ['SET NX_SC_S1 = 0.3', 'SET NX_SC_S1 = 0.6'] * 2)

    def test_imported_wall_selection_uses_model_geometry(self):
        from drawing_wall_scope import available, exterior_walls, generated, select
        scheme, geometry = fixture()
        geometry['BuildingSurface:Detailed'].pop('wall')
        template = geometry['BuildingSurface:Detailed']['roof']
        for label in ['West 310', 'East 470', 'North 982']:
            wall = copy.deepcopy(template)
            wall['surface_type'] = 'Wall'
            geometry['BuildingSurface:Detailed'][label] = wall
        opening = dict(template, building_surface_name='North 982', multiplier=2)
        opening['vertices'] = [dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=3)
                               for x,y in [(0,0),(1,0),(1,1),(0,1)]]
        geometry['FenestrationSurface:Detailed'] = {'glass':opening}
        scheme['provenance'] = {'adapter':'ordinary_building_v1'}
        scheme['factors']['building'] = {'id':'newly_imported'}
        names = ['West 310','East 470','North 982']
        for row in [*scheme['factors']['materials']['applications'], *scheme['factors']['condition']['controls']]:
            row['target_ids'] = names.copy()
        self.assertTrue(available(scheme))
        inventory = exterior_walls(geometry, {'Room':True})
        self.assertEqual([w['id'] for w in inventory],names)
        self.assertEqual(inventory[-1]['net_m2'],2)
        with self.assertRaises(ValueError):
            select(scheme,names,names[:1],names)
        chosen = select(scheme,names,names[:2],names[:1])
        model = copy.deepcopy(geometry)
        audit = apply(model,chosen,[0]*365)
        result = generated(chosen,geometry,model,audit,{'Room':True})
        self.assertEqual((result['covered_m2'],result['feedback_m2']),(8,4))
        self.assertEqual([w['thermal'] for w in result['rows']],['feedback','fixed',None])
        self.assertEqual(geometry['BuildingSurface:Detailed']['North 982'],model['BuildingSurface:Detailed']['North 982'])
        self.assertEqual(model['Construction']['shared'],geometry['Construction']['shared'])

    def test_portable_material_roundtrip(self):
        scheme, _ = fixture()
        material = normalize(scheme)['factors']['materials']['definitions'][0]
        portable = dict(schema='workbench-material/v1', source_revision=3, material=material)
        self.assertEqual(import_definition(portable), material)
        corrupt = copy.deepcopy(portable)
        corrupt['material']['states'][0]['resistance_m2K_W'] = 123
        with self.assertRaises(ValueError):
            import_definition(corrupt)
