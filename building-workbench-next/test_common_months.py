import copy
import unittest

from comparison_results import assemble, common_month_results
from foundation import ROOT, read_json
from output_resolution import days


class CommonMonthTests(unittest.TestCase):
    def setUp(self):
        self.annual = [1, 1, 12, 31]
        self.winter = [1, 15, 3, 10]

    def row(self, period, amount):
        monthly = [dict(month=m, heating_kWh=amount, cooling_kWh=0, total_kWh=amount)
                   for m in range(period[0], period[2] + 1)]
        return dict(status='passed', mode='controlled', step_minutes=5, weather_sha256='w',
                    period=period, days=days(period), monthly=monthly, loads=dict(total_kWh=99999))

    def compare(self, left, right, eligible=True):
        return common_month_results([left['period'], right['period']],
            [dict(cases={'s':row}) for row in (left,right)], [dict(id='s',name='站点',eligible=eligible)], 25)['months']

    def test_only_complete_month_and_no_period_totals(self):
        a, b = self.row(self.annual, 12), self.row(self.winter, 11)
        b['status'] = 'reused'
        for left,right,sign in ((a,b,1),(b,a,-1)):
            months = self.compare(left,right)
            self.assertEqual([(m['month'],m['days'],m['paired_sites']) for m in months], [(2,28,1)])
            site = months[0]['sites'][0]
            self.assertEqual(site['total_saved_kWh'],sign)
            self.assertAlmostEqual(site['total_saved_MJ_m2'],sign*3.6/25)
            self.assertIsNone(site['cooling_saved_percent'])
        self.assertEqual(self.compare(a,self.row([1,2,1,31],2)), [])

    def test_other_pairing_requirements(self):
        a, b = self.row(self.annual, 12), self.row(self.winter, 11)
        month = b['monthly'][1]
        for change in (dict(days=1),dict(mode='natural'),dict(weather_sha256='other'),
                       dict(status='review'),dict(status='failed'),dict(step_minutes=1),dict(choice_error='已变化'),
                       dict(monthly=[]),dict(monthly=[month,month]),dict(monthly=[dict(month,heating_kWh=None)]),
                       dict(monthly=[dict(month,cooling_kWh=float('nan'))])):
            with self.subTest(change=change):
                m, = self.compare(a,dict(b,**change))
                self.assertEqual(m['paired_sites'],0)
                self.assertTrue(m['sites'][0]['reason'])
                self.assertNotIn('total_saved_kWh',m['sites'][0])
        self.assertEqual(self.compare(a,b,False)[0]['paired_sites'],0)

    def test_month_comparison_keeps_original_pair_blocked(self):
        a = read_json(ROOT.parent/'examples/drawing26/template/records.json')['global_w00']
        a['factors']['scope'].update(period=self.annual,site_ids=['s'])
        b = copy.deepcopy(a)
        b['factors']['scope']['period'] = self.winter
        catalog = dict(sites={'s':dict(id='s',name='站点')},global_bundle={'classes':[]})
        def report():
            sources = [dict(id=side, cases={'s':self.row(record['factors']['scope']['period'], amount)})
                       for side,record,amount in [('left',a,12),('right',b,11)]]
            return assemble(dict(metric='total'),a,b,*sources,catalog,'controlled')
        result = report()
        self.assertEqual(result['common_months']['months'][0]['paired_sites'],1)
        self.assertEqual((result['paired_sites'],result['monthly']), (0,[]))
        b['numerics']['engine'] = 'other'
        self.assertNotIn('common_months',report())


if __name__ == '__main__':
    unittest.main()
