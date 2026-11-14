import copy, tempfile, unittest
from pathlib import Path
from component_library import Library
from contracts import normalize, validate_definitions
import material_types as mt
import surface_materials as sm
import reference_library as rl


def definition(kind):
    d=mt.template(kind);d['name']='验证材料';d['property_source']['note']='明确的演示假设'
    for i,s in enumerate(d['states']):
        if kind!='film':s.update(thickness_mm=10/(i+1),conductivity_W_mK=.04,density_kg_m3=20*(i+1),specific_heat_J_kgK=1200)
    d['optics']['A_R'].update(solar_absorptance=.2,emissivity=.9)
    return d


def record(d,targets=None,state='R'):
    targets=targets or ['wall']
    a=dict(id='surface_material',material_id=d['id'],component='opaque_exterior',position='exterior',target_ids=targets,placement_basis='fixed_surface_material_v1')
    c=[dict(application_id=a['id'],channel='thermal',mode='fixed',target_ids=targets,state_id=state),dict(application_id=a['id'],channel='orientation',mode='fixed',target_ids=targets,face_id='A')]
    return dict(factors=dict(materials=dict(definitions=[d],applications=[a]),condition=dict(controls=c,reference_runs=[])))


def model():
    props=dict(thickness=.2,conductivity=1.4,density=2300,specific_heat=900,roughness='MediumRough',solar_absorptance=.6,thermal_absorptance=.9,visible_absorptance=.6)
    return {'Material':{'base':props},'Construction':{'shared':{'outside_layer':'base'}},'BuildingSurface:Detailed':{
        name:dict(surface_type=kind,outside_boundary_condition=boundary,zone_name='Room',construction_name='shared')
        for name,kind,boundary in [('wall','Wall','Outdoors'),('roof','Roof','Outdoors'),('interior','Wall','Surface')]}}


class MaterialTests(unittest.TestCase):
    def test_default_is_one_state_solid_without_eca_values(self):
        d=mt.template();self.assertEqual(d['category'],'solid');self.assertEqual(len(d['states']),1)
        self.assertIsNone(d['states'][0]['density_kg_m3']);self.assertEqual(d['faces'],['A'])

    def test_optical_only_preserves_all_thermal_properties_and_shared_surfaces(self):
        m=model();before=copy.deepcopy(m);audit=sm.apply(m,record(definition('film')))
        c=m['Construction'][m['BuildingSurface:Detailed']['wall']['construction_name']]
        layer=m['Material'][c['outside_layer']]
        for k in ('thickness','conductivity','density','specific_heat'):self.assertEqual(layer[k],before['Material']['base'][k])
        self.assertEqual(layer['solar_absorptance'],.2);self.assertEqual(len(c),1)
        self.assertEqual(m['Material']['base'],before['Material']['base'])
        self.assertEqual(m['BuildingSurface:Detailed']['roof'],before['BuildingSurface:Detailed']['roof'])
        self.assertNotIn('Material:NoMass',m);self.assertEqual(audit['model'],'optical_surface_v1')

    def test_solid_prepends_real_mass_and_preserves_base(self):
        m=model();before=copy.deepcopy(m);audit=sm.apply(m,record(definition('solid'),['roof']))
        c=m['Construction'][m['BuildingSurface:Detailed']['roof']['construction_name']]
        self.assertEqual(c['layer_2'],'base');layer=m['Material'][c['outside_layer']]
        self.assertEqual(layer['density'],20);self.assertEqual(layer['specific_heat'],1200)
        self.assertAlmostEqual(layer['thickness']/layer['conductivity'],.25)
        self.assertAlmostEqual(audit['physical']['areal_capacity_J_m2K'],240)
        self.assertEqual(m['Material']['base'],before['Material']['base'])

    def test_variable_fixed_states_keep_distinct_resistance_and_conserved_mass(self):
        d=definition('variable');a=sm.apply(model(),record(d,state='R'));b=sm.apply(model(),record(d,state='C'))
        self.assertNotEqual(a['physical']['resistance_m2K_W'],b['physical']['resistance_m2K_W'])
        self.assertEqual(a['physical']['areal_capacity_J_m2K'],b['physical']['areal_capacity_J_m2K'])

    def test_dynamic_control_and_unknown_targets_are_rejected(self):
        r=record(definition('variable'));r['factors']['condition']['controls'][0]['mode']='feedback'
        with self.assertRaisesRegex(ValueError,'专项校准'):sm.apply(model(),r)
        with self.assertRaises(ValueError):sm.apply(model(),record(definition('film'),['interior']))

    def test_missing_density_source_and_invalid_cp_cannot_run(self):
        for path,value in [('density_kg_m3',None),('conductivity_W_mK',0),('specific_heat_J_kgK',50)]:
            d=definition('solid');d['states'][0][path]=value
            with self.assertRaises(ValueError):sm.apply(model(),record(d))
        d=definition('solid');d['property_source']['note']=''
        with self.assertRaises(ValueError):sm.apply(model(),record(d))

    def test_unknown_fields_cannot_be_silently_ignored(self):
        d=definition('solid');d['states'][0]['phase_change']=True
        self.assertTrue(validate_definitions([d])[1])
        d=definition('film');d['states'][0]['density_kg_m3']=1
        self.assertTrue(validate_definitions([d])[1])

    def test_single_state_normalization_does_not_invent_second_state(self):
        r=normalize(record(definition('film')))
        self.assertEqual(set(r['factors']['materials']['definitions'][0]['optics']),{'A_R'})


class ReferenceTests(unittest.TestCase):
    def test_all_names_layers_and_annual_values_are_available_without_mutation(self):
        c=rl.catalog();self.assertEqual(len(c['constructions']),47);self.assertEqual(len(c['daily_profiles']),28)
        for row in c['constructions']:
            full=rl.construction(row['id']);self.assertEqual(len(full['layers']),len(row['layers']))
            self.assertTrue(all(l['material']['name'] for l in full['layers']))
        for row in c['annual_schedules']:
            full=rl.annual(row['id']);self.assertEqual(len(full['values']),8760)
            self.assertEqual(min(full['values']),row['min']);self.assertEqual(max(full['values']),row['max'])

    def test_daily_snapshots_and_exact_room_mapping(self):
        from component_library import verify
        from usage_schedules import expanded
        for r in rl.daily_profiles():verify(r['snapshot'],'daily')
        choices,donors=rl.room_templates();self.assertEqual(len(choices),8)
        for item in rl.catalog()['room_templates']:
            donor=donors['reference:'+item['id']]
            for channel,key in [('people','O_SCHEDULE'),('lighting','L_SCHEDULE'),('equipment','E_SCHEDULE')]:
                values=rl.annual(item[key])['values'];rule=donor['rules'][channel]
                expected=[rule['minimum']+v*(rule['maximum']-rule['minimum']) for v in values]
                self.assertEqual(expanded(rule,1),expected)

    def test_copy_and_edit_preserve_old_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);c=rl.catalog()['constructions'][0];a=rl.copy_construction(root,c['id'],'我的墙')
            b=copy.deepcopy(a['content']);b['layers'][0]['thickness_mm']+=1
            newer=Library(root).save('construction','我的墙',b,a)
            self.assertEqual(newer['revision'],2);self.assertIn(a,Library(root).all('construction'))
            self.assertEqual(rl.construction(c['id']),a['content'])


if __name__=='__main__':unittest.main()
