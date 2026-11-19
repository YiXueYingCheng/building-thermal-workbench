import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from execution_failure_view import describe
from warmup_trends import classify, screen


class WarmupTrendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.trace = self.folder/'warmup.jsonl'
        case = dict(step_minutes=5, warmup_observer=dict(tolerance=.4, environment='Annual'))
        (self.folder/'launch.json').write_text(json.dumps(dict(case=case)))
        self.check = dict(zone='Room', measure='Min Temp', value=.7, tolerance=.4,
                          environment_kind='RunPeriod', environment='ANNUAL', days=24)

    def record(self, sequence, ended=True):
        with self.trace.open('w') as f:
            for i, v in enumerate(sequence, 1):
                row = dict(env=1, day=i, steps=12, rooms={'ROOM':[v,22],'OTHER':[16,20]})
                f.write(json.dumps(row)+'\n')
            if ended:
                f.write('{"ended":1}\n')

    def test_period_two_and_missing_or_non_temperature_evidence(self):
        self.record([15.2,14.5]*12)
        view = screen(self.folder,[self.check])
        r, = view['rows']
        self.assertEqual((view['first'],view['last'],view['ended']),(5,24,True))
        self.assertEqual((r['zone'],r['label'],r['kind']),('Room','最低温','period_two'))
        self.assertAlmostEqual(r['delta'],.7)
        self.assertEqual(r['max_two_day_delta'],0)
        for changed in (dict(value=.8),dict(days=22),dict(environment='Other'),
                        dict(environment_kind='SizingPeriod'),dict(measure='Max Heat Load'),
                        dict(zone='UNKNOWN'),dict(tolerance=.2)):
            self.assertFalse(screen(self.folder,[dict(self.check,**changed)])['rows'])

    def test_shrinking_damped_irregular_and_short_histories(self):
        for values in ([100*.95**i for i in range(20)],
                       [20+(-1)**i*2*.95**i for i in range(20)]):
            self.assertEqual(classify(values,.4)['kind'],'shrinking')
        for values in ([15,14]*4, [15,14,15,13]*5, list(range(20)), [15,14.9]*10):
            self.assertEqual(classify(values,.4)['kind'],'unclear')

    def test_live_skips_unfinished_day_and_requires_contiguous_days(self):
        self.record([15.2,14.5]*12,ended=False)
        with self.trace.open('a') as f:
            f.write('{"day":25')
        t=screen(self.folder)
        self.assertFalse(t['ended'])
        self.assertEqual(len(t['rows']),1)
        self.assertEqual(t['rows'][0]['kind'],'period_two')
        text=self.trace.read_text().replace('"day": 23,','"day": 20,')
        self.trace.write_text(text)
        self.assertFalse(screen(self.folder)['rows'])

    def test_old_attempt_and_bad_trace_leave_failure_unchanged(self):
        self.assertFalse(screen(self.folder,[self.check])['rows'])
        self.trace.write_text('this is not a trace\n')
        self.assertFalse(screen(self.folder,[self.check])['rows'])

    def test_engine_log_and_warmup_only_criterion(self):
        self.record([15.2,14.5]*12)
        run=self.folder/'run'
        run.mkdir()
        err=run/'eplusout.err'
        err.write_text('   ** Severe  ** CheckWarmupConvergence: Loads Initialization, Zone="Room" did not converge after 24 warmup days.\n'
                       '   **   ~~~   ** ...Environment(RunPeriod)="ANNUAL"\n'
                       '   **   ~~~   ** ..Min Temp Comparison = 0.7 vs Temperature Convergence Tolerance=0.4 - Fail Convergence\n')
        with patch('output_storage.attempt_folder',return_value=self.folder):
            job=dict(status='failed',attempt='attempt_'+'b'*32)
            view=describe(job,self.folder)
            self.assertEqual(view['warmup_trend']['rows'][0]['kind'],'period_two')
            self.assertFalse(view['acceptance_changed'])
            with err.open('a') as f:
                f.write('   ** Fatal ** Additional error\n')
            view=describe(job,self.folder)
            self.assertEqual(view['kind'],'engine_error')
            self.assertTrue(view['warmup_trend']['rows'])
            err.write_text('  ** Warning ** Temperature out of range [-100. to 200.] (PsyPsatFnTemp)\n')
            self.assertIsNone(describe(job,self.folder)['warmup_trend'])
