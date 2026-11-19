import copy
import unittest
from unittest.mock import patch

import coverage_results


def record(ids, calendar):
    controls=[dict(channel='thermal',mode='feedback',target_ids=['N'],state_id='R'),
              dict(channel='orientation',mode='calendar',target_ids=ids)]
    if len(ids)>1:
        controls.append(dict(channel='thermal',mode='fixed',target_ids=ids[1:],state_id='R'))
    return dict(provenance=dict(adapter='global_frozen_v011',snapshot_id='test'),numerics=dict(step_minutes=1),
                factors=dict(building=dict(id='drawing26_global_frozen',wall_ids=['N','W']),
                    materials=dict(definitions=[dict(model='solid_variable_v1')],applications=[
                        dict(target_ids=ids,placement_basis='fixed_surface_material_v1')]),
                    condition=dict(controls=controls,reference_runs=[dict(snapshot=dict(content=dict(
                        sites=[dict(site_id='X',calendar=calendar)])))])))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.a=record(['N'],[0]*365)
        self.b=record(['N','W'],[0]*365)
    def site(self, records, status='paired', annual=True):
        site=dict(status=status,site_id='X',pairing_basis='严格配对',heating_saved_kWh=8,
                  cooling_saved_kWh=-2,total_saved_kWh=6)
        d=dict(metric='total',annual=annual,sites=[site])
        with patch('coverage_results.rows',return_value=[dict(id='N',net_m2=30),dict(id='W',net_m2=2)]):
            coverage_results.annotate(d,records,[dict(cases={'X':{}})]*2,{})
        return site
    def test_signed_savings_and_no_evidence(self):
        s=self.site([self.a,self.b])
        self.assertEqual(s['savings_per_added_m2'],dict(heating=4,cooling=-1,total=3))
        self.assertIsNone(s['feedback_timing'])
    def test_only_strict_annual_expansion_with_common_controls(self):
        for r in (self.site([self.b,self.a]),self.site([self.a,self.a]),
                  self.site([self.a,self.b],status='excluded'),self.site([self.a,self.b],annual=False)):
            self.assertNotIn('savings_per_added_m2',r)
        other=copy.deepcopy(self.b)
        other['factors']['condition']['reference_runs'][0]['snapshot']['content']['sites'][0]['calendar'][1]=1
        self.assertIs(self.site([self.a,other])['coverage_calendar_same'],False)
        self.assertNotIn('savings_per_added_m2',self.site([self.a,other]))
        self.b['factors']['condition']['controls'][0]['state_id']='C'
        self.assertNotIn('savings_per_added_m2',self.site([self.a,self.b]))
    def test_ordinary_building_without_legacy_snapshot_or_direction(self):
        for record in (self.a,self.b):
            record['provenance'] = {'adapter':'ordinary_building_v1'}
        self.assertEqual(self.site([self.a,self.b])['savings_per_added_m2']['total'],3)

    def test_different_switch_times_with_equal_counts(self):
        a=dict(minutes=20,step=1,initial=1,events=[[4,0],[12,1]])
        b=dict(minutes=20,step=1,initial=1,events=[[8,0],[12,1]])
        t=coverage_results.switches(a,b)
        self.assertEqual((t['coincident'],t['different_minutes'],len(t['unmatched'])),(1,4,2))
        self.assertIsNone(coverage_results.switches(a,{**b,'step':60}))
