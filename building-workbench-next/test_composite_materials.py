import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from component_library import Library
from composite_materials import template, resolve, install, validate
from material_catalog import normalize_library_material, import_definition
from material_types import template as single_layer
from research_materials import example


def sample_sources(library):
    film = single_layer('film')
    variable = single_layer('variable')
    film['name'], variable['name'] = '表面涂层', '两态实体'
    for d in (film, variable):
        d['property_source']['note'] = '组合功能核验'
        d['optics']['A_R'].update(solar_absorptance=.17, emissivity=.93)
    for s, thickness, conductivity in zip(variable['states'], (18., 9.), (.06, .09)):
        s.update(thickness_mm=thickness, conductivity_W_mK=conductivity,
                 density_kg_m3=1800/thickness, specific_heat_J_kgK=1300.)
    variable['faces'] = ['A','B']
    variable['optics']['B_R'] = dict(variable['optics']['A_R'], solar_absorptance=.52,emissivity=.82)
    return [library.save('material',d['name'],normalize_library_material(d)) for d in (film, example('pcm'), variable)]


def compose(library, rows):
    d=template()
    d['name']='层序核验'
    d['layers']=[dict(reference={k:r[k] for k in ('id','revision','sha256')},
                      state='C' if r['content']['category']=='variable' else 'R', face='A') for r in rows]
    return normalize_library_material(resolve(d,library))


class CompositeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lib=Library(Path(tmp.name))
        self.rows=sample_sources(self.lib)
        self.model={'BuildingSurface:Detailed':{k:{'construction_name':'base'} for k in ('Wall','Other')},
                    'Material':{'out':{'visible_absorptance':.43},'in':{'visible_absorptance_inside_face':.62}},
                    'Construction':{'base':{'outside_layer':'out','layer_2':'in'}}}

    def apply(self,rows,position,**kwargs):
        d=compose(self.lib,rows)
        return install(self.model,{'definition':d,'targets':['Wall']},dict(position=position,**kwargs))['surfaces'][0]

    def test_outside_coating_and_pcm(self):
        row=self.apply(self.rows,'exterior')
        pcm,solid=row['inserted_layers']
        self.assertEqual(row['layers_after'],[pcm,solid,'out','in'])
        self.assertEqual(self.model['Material'][pcm]['solar_absorptance'],.17)
        self.assertEqual(self.model['Material'][pcm]['visible_absorptance'],.43)
        self.assertEqual(self.model['Material'][solid]['thickness'],.009)
        self.assertIn(pcm,self.model['MaterialProperty:PhaseChange'])
        self.assertEqual(self.model['BuildingSurface:Detailed']['Other']['construction_name'],'base')

    def test_inner_face_and_between_preserve_baseline(self):
        row=self.apply(self.rows[1:],'interior')
        solid=self.model['Material'][row['inserted_layers'][-1]]
        self.assertEqual(row['layers_after'][:2],['out','in'])
        self.assertEqual(solid['solar_absorptance_inside_face'],.52)
        self.assertEqual(solid['visible_absorptance_inside_face'],.62)
        self.model['BuildingSurface:Detailed']['Wall']['construction_name']='base'
        row=self.apply(self.rows[1:],'between',after_layer=1)
        self.assertEqual(row['layers_after'],['out',*row['inserted_layers'],'in'])

    def test_inspection_uses_actual_layer_slots_and_actuator_targets(self):
        from input_inspection import stack_readback
        definition=compose(self.lib,self.rows)
        audit=install(self.model,{'definition':definition,'targets':['Wall','Other']},{'position':'exterior'})
        first_solid,variable=audit['surfaces'][0]['inserted_layers']
        self.model['EnergyManagementSystem:Actuator']={'only-one':dict(
            actuated_component_type='CondFD Surface Material Layer',actuated_component_control_type='Thermal Conductivity',
            actuated_component_unique_name='Wall:'+variable)}
        result=stack_readback(self.model,audit)
        coating,pcm,solid=result['layers']
        self.assertEqual(result['surface_count'],2)
        self.assertEqual(coating['groups'][0]['slot'],1)
        self.assertEqual(coating['groups'][0]['solar_absorptance'],.17)
        self.assertEqual(pcm['groups'][0]['slot'],1)
        self.assertEqual(pcm['groups'][0]['enthalpy_points'],len(self.model['MaterialProperty:PhaseChange'][first_solid]['values']))
        self.assertEqual([(g['slot'],g['feedback'],g['surfaces']) for g in solid['groups']],
                         [(2,True,['Wall']),(2,False,['Other'])])

    def test_frozen_version_and_portable_copy(self):
        d=compose(self.lib,self.rows)
        document=dict(schema='workbench-material/v1',source_revision=1,material=d)
        self.lib.path.unlink()
        self.assertEqual(import_definition(document),d)
        self.assertEqual(resolve(copy.deepcopy(d),self.lib),d)
        d['layers'][0]['version']=d['layers'][0]['version'].replace('0.17','0.71')
        self.assertTrue(validate(d))

    def test_exposed_group_overrides_only_exterior_optics_and_roundtrips_to_inherited_b(self):
        from input_inspection import stack_readback
        from surface_materials import specification
        from test_reference_materials import record
        for top in (self.rows[2],self.lib.save('material','双面涂层',normalize_library_material(
                dict(self.rows[0]['content'],faces=['A','B'],optics={k:self.rows[2]['content']['optics'][k] for k in ('A_R','B_R')})))):
            d=compose(self.lib,[top,self.rows[1]])
            d['layers'][0]['face']='B'
            d['optics']['A_R']=copy.deepcopy(top['content']['optics']['B_R'])
            plan=record(d,['Wall'])
            app=plan['factors']['materials']['applications'][0]
            app['placement_basis']='layer_stack_v1'
            original=copy.deepcopy(d)
            oc=plan['factors']['condition']['controls'][1]
            for face,solar,emissivity in ((None,.52,.82),('A',.17,.93),('B',.52,.82)):
                if face:oc.update(face_basis='exposed_layer',face_id=face)
                model=copy.deepcopy(self.model)
                audit=install(model,specification(plan),app)
                outer=audit['surfaces'][0]['inserted_layers'][0]
                props=model['Material'][outer]
                self.assertEqual((props['solar_absorptance'],props['thermal_absorptance'],props['visible_absorptance']),(solar,emissivity,.43))
                self.assertEqual(stack_readback(model,audit)['layers'][0]['groups'][0]['emissivity'],emissivity)
                self.assertEqual(model['BuildingSurface:Detailed']['Other']['construction_name'],'base')
                if face is None:inherited=props
                else:self.assertEqual({k:v for k,v in props.items() if k not in ('solar_absorptance','thermal_absorptance')},
                                      {k:v for k,v in inherited.items() if k not in ('solar_absorptance','thermal_absorptance')})
            self.assertEqual(d,original)
            app['position']='interior'
            with self.assertRaisesRegex(ValueError,'原构造外侧'): specification(plan)

    def test_feedback_validates_optics_of_the_selected_group(self):
        from composite_materials import feedback_layer
        leaf=copy.deepcopy(self.rows[2]['content'])
        leaf['optics_depend_on_state']=True
        for face in leaf['faces']:leaf['optics'][face+'_C']=dict(leaf['optics'][face+'_R'])
        leaf['optics']['B_C']['emissivity']=.89
        row=self.lib.save('material','分组随状态变化',normalize_library_material(leaf))
        d=compose(self.lib,[row,self.rows[1]])
        feedback_layer(d,{'position':'exterior'},1,'A')
        with self.assertRaisesRegex(ValueError,'暴露面'): feedback_layer(d,{'position':'exterior'},1,'B')

    def test_calendar_switches_exposed_coating_independently_of_buried_feedback(self):
        from test_reference_materials import record
        from test_surface_controls import fixture
        from composite_materials import configure_feedback
        from surface_controls import apply
        from calendar_library import with_reference
        film=copy.deepcopy(self.rows[0]['content'])
        film['faces']=['A','B']
        film['optics']['A_R']['visible_absorptance']=.21
        film['optics']['B_R']=dict(film['optics']['A_R'],solar_absorptance=.87,visible_absorptance=None)
        dual=self.lib.save('material','双组涂层',normalize_library_material(film))
        d=compose(self.lib,[dual,self.rows[1],self.rows[2]])
        fixed=record(d,['wall','roof'])
        fixed.update(provenance={'adapter':'ordinary_building_v1'},numerics={'step_minutes':2})
        app=fixed['factors']['materials']['applications'][0]
        app['placement_basis']='layer_stack_v1'
        snap=dict(id='ref',content={'schema_version':1})
        saved=with_reference(fixed,snap)
        for feedback in (False,True):
            scheme=configure_feedback(saved,3,['roof']) if feedback else saved
            _,geometry=fixture()
            audit=apply(geometry,scheme,[0]*120+[1]*245)
            actuators=geometry['EnergyManagementSystem:Actuator']
            for i,s in enumerate(audit['surfaces']):
                pcm,solid=s['inserted_layers']
                self.assertEqual(actuators['NX_SC_S'+str(i)]['actuated_component_unique_name'],pcm)
                self.assertIn(pcm,geometry['MaterialProperty:PhaseChange'])
                self.assertEqual('NX_SC_K'+str(i) in actuators,feedback and s['surface']=='roof')
                if feedback and s['surface']=='roof':self.assertEqual(actuators['NX_SC_K'+str(i)]['actuated_component_unique_name'],'roof:'+solid)
            self.assertIn('NX_SC_FaceOutput',geometry['EnergyManagementSystem:OutputVariable'])
            self.assertEqual(scheme['numerics']['step_minutes'],1 if feedback else 2)
        app['position']='interior'
        with self.assertRaisesRegex(ValueError,'外侧'):apply(fixture()[1],with_reference(fixed,snap),[1]*365)

    def test_feedback_addresses_one_frozen_layer_and_preserves_other_walls(self):
        from composite_materials import configure_feedback
        from surface_controls import controls
        from drawing_wall_scope import select
        from test_reference_materials import record
        d=compose(self.lib,[*self.rows,self.rows[-1]])
        scheme=record(d,['north','west','east'])
        scheme['provenance']={'adapter':'ordinary_building_v1'}
        scheme['numerics']={'step_minutes':2}
        scheme['factors']['materials']['applications'][0]['placement_basis']='layer_stack_v1'
        for layer,expected_index in ((3,1),(4,2)):
            result=configure_feedback(scheme,layer,['west'])
            spec,tc,_=controls(result)
            self.assertEqual(spec['controlled_index'],expected_index)
            self.assertEqual(result['numerics']['step_minutes'],1)
            self.assertEqual(tc['target_ids'],['west'])
            self.assertEqual(result['factors']['materials'],scheme['factors']['materials'])
            reduced=select(result,['north','west','east'],['west','east'],['west'])
            self.assertEqual(controls(reduced)[1]['layer_number'],layer)
            restored=configure_feedback(reduced,None,[])
            self.assertEqual(restored['numerics']['step_minutes'],2)
            self.assertTrue(all(c['mode']=='fixed' for c in restored['factors']['condition']['controls']))
        for bad in (1,2,5,None,True):
            with self.assertRaises(ValueError): configure_feedback(scheme,bad,['west'])
        with self.assertRaises(ValueError):configure_feedback(scheme,3,['not-covered'])
        with self.assertRaises(ValueError):configure_feedback(scheme,3,['west','west'])

    def test_invalid_interfaces_and_versions(self):
        with self.assertRaises(ValueError): self.apply(self.rows,'interior')
        with self.assertRaises(ValueError): self.apply(self.rows[::-1],'exterior')
        with self.assertRaises(ValueError): self.apply(self.rows[1:],'between',after_layer=2)
        d=compose(self.lib,self.rows)
        d['layers'][0]['face']='B'
        self.assertTrue(validate(d))

    def test_case_preview_checks_the_resistance_expected_by_the_material_model(self):
        from composite_materials import configure_feedback
        from planner import preview
        from test_reference_materials import record

        d=compose(self.lib,[self.rows[2],self.rows[1]])
        fixed=record(d,['wall'])
        fixed.update(schema_version=1,id='plan',name='逐层计算',numerics={'step_minutes':2},
                     execution={'max_parallel':1},provenance={'adapter':'ordinary_building_v1','snapshot_id':'source'})
        f=fixed['factors']
        f.update(building={'id':'building','name':'建筑'},scope={'site_ids':['site'],'period':[1,1,1,31]})
        f['condition']['operation']={'mode':'controlled'}
        f['materials']['applications'][0]['placement_basis']='layer_stack_v1'
        catalog={'records':{},'created':'test','sites':{'site':{'name':'站点'}}}
        feedback=configure_feedback(fixed,1,['wall'])
        with patch('model_adapter.capability', return_value={'supported':True,'reasons':[]}):
            for scheme in (fixed,feedback):
                with self.subTest(control=scheme['factors']['condition']['controls'][0]['mode']):
                    result=preview(scheme,catalog)
                    self.assertTrue(result['valid'],result['errors'])
                    self.assertEqual(result['requirements'],[])
            legacy=copy.deepcopy(fixed)
            state={'id':'R','name':'初始态','resistance_m2K_W':None}
            legacy['factors']['materials']['definitions']=[dict(id=d['id'],name='等效层',kind='single_layer',
                model='equivalent_resistance_no_layer_storage',states=[state],optics=d['optics'])]
            self.assertTrue(any('缺少本模型使用的热阻' in x for x in preview(legacy,catalog)['requirements']))
            state['resistance_m2K_W']=0.3
            self.assertEqual(preview(legacy,catalog)['requirements'],[])
