"""Regressions for latent-heat accounting and split exterior optics."""
import unittest
from research_materials import errors,example,latent,pcm_layer,solar_split
from material_types import validate

class MaterialPhysicsTests(unittest.TestCase):
    def test_fraction_scales_only_latent_heat(self):
        d=example('pcm')
        d['phase_change'].update(basis='fraction',mass_fraction=.2)
        self.assertEqual(validate(d,True),[])
        self.assertAlmostEqual(latent(d),48400)
        model={}
        pcm_layer(model,'sample','wall',d['states'][0],d)
        rows=model['MaterialProperty:PhaseChange']['sample']['values']
        delta_T=rows[2]['temperature']-rows[1]['temperature']
        self.assertAlmostEqual(rows[2]['enthalpy']-rows[1]['enthalpy'],2200*delta_T+48400)
        d['phase_change']['latent_kJ_kg']=0
        other={}
        pcm_layer(other,'sample','wall',d['states'][0],d)
        self.assertNotIn('MaterialProperty:PhaseChange',other)
        self.assertEqual(other['SurfaceProperty:HeatTransferAlgorithm:Construction'],model['SurfaceProperty:HeatTransferAlgorithm:Construction'])

    def test_multiple_reflection_solar_closure(self):
        p=example('spectral')['spectral']
        absorptions=solar_split(p)
        expected=p['sw_reflectance']+p['sw_transmittance']**2*p['emitter_sw_reflectance']/(1-p['sw_reflectance']*p['emitter_sw_reflectance'])
        self.assertAlmostEqual(sum(absorptions)+expected,1)
        self.assertTrue(all(v>=0 for v in absorptions))
        self.assertEqual(solar_split(dict(p,sw_reflectance=1,sw_transmittance=0,emitter_sw_reflectance=1)),(0,0))

    def test_physical_parameters(self):
        d=example('spectral')
        d['spectral']['window_absorptance']=.9
        self.assertTrue(errors(d,True))
        d=example('pcm')
        d['phase_change'].update(basis='fraction',mass_fraction=None)
        self.assertTrue(errors(d,True))
        self.assertEqual(errors(d,False),[])
        d['phase_change'].update(mass_fraction=1.,liquidus_C=25)
        self.assertTrue(errors(d,True))
