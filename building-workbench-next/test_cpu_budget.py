import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import cpu_budget as cpu
import resources
from execution_queue import Queue


def machine(percent=30, average=None, ready=True):
    return dict(available_gib=16, commit_available_gib=32, disk_free_gib=100, logical_cpus=4,
                cpu=dict(ready=ready, percent=percent, average_percent=percent if average is None else average))


def policy(enabled=True, **extra):
    return resources.settings(dict(profile='custom', max_parallel=4, reserve_gib=2,
                                   cpu_limit_enabled=enabled, cpu_limit_percent=80, **extra))


class CpuTests(unittest.TestCase):
    def test_counter_subtracts_idle_once_and_whole_machine_percent(self):
        s = cpu.Samples()
        s.update(0, 100, 400)
        s.update(1, 180, 500)
        self.assertFalse(s.read(1)['ready'])
        s.update(2, 260, 600)
        self.assertAlmostEqual(s.read(2)['percent'], 20)
        self.assertAlmostEqual(s.read(2)['average_percent'], 20)

    def test_stale_restart_and_invalid_counters_not_zero_load(self):
        s = cpu.Samples()
        s.update(0, 100, 400); s.update(2, 200, 600)
        self.assertTrue(s.read(2)['ready'])
        self.assertFalse(s.read(6)['ready'])
        s.update(8, 240, 700)
        self.assertFalse(s.read(8)['ready'])
        s.update(10, 500, 710)
        self.assertFalse(s.read(10)['ready'])

    def test_recent_high_load_cannot_be_hidden_by_one_low_sample(self):
        p = policy()
        self.assertFalse(resources.dispatch_budget(p, machine(5, 75), [])['allowed'])
        self.assertTrue(resources.dispatch_budget(p, machine(5, 25), [])['allowed'])

    def test_disabled_control_keeps_old_dispatch_even_when_cpu_unknown(self):
        for m in (machine(100), machine(None, ready=False)):
            self.assertTrue(resources.dispatch_budget(policy(False), m, [])['allowed'])

    def test_enabled_unknown_waits_instead_of_assuming_idle(self):
        b = resources.dispatch_budget(policy(), machine(None, ready=False), [])
        self.assertFalse(b['allowed']); self.assertIn('CPU', b['reason'])

    def test_predicts_new_case_before_saturation_on_four_cpu_machine(self):
        b = resources.dispatch_budget(policy(), machine(60), [{'working_gib':.1, 'commit_gib':.1}])
        self.assertFalse(b['allowed'])
        self.assertEqual(b['cpu']['next_job_percent'], 25)
        self.assertEqual(b['cpu']['projected_percent'], 85)

    def test_observed_peak_increases_reservation_and_startup_waits(self):
        b = resources.dispatch_budget(policy(), machine(30), [{'cpu_peak_percent':55}])
        self.assertFalse(b['allowed']); self.assertEqual(b['cpu']['next_job_percent'], 55)
        b = resources.dispatch_budget(policy(), machine(5), [{'cpu_settling_seconds':8}])
        self.assertFalse(b['allowed']); self.assertIn('启动观察', b['reason'])
        self.assertTrue(resources.dispatch_budget(policy(False), machine(5), [{'cpu_settling_seconds':8}])['allowed'])

    def test_memory_commit_disk_and_parallel_constraints_stay_mandatory(self):
        for enabled in (False, True):
            p = policy(enabled)
            for field in ('available_gib', 'commit_available_gib', 'disk_free_gib'):
                m = machine(0); m[field] = 0
                self.assertFalse(resources.dispatch_budget(p, m, [])['allowed'])
            self.assertFalse(resources.dispatch_budget(p, machine(0), [{}] * 4)['allowed'])

    def test_settings_optional_and_validated(self):
        self.assertFalse(resources.settings({'profile':'light'})['cpu_limit_enabled'])
        self.assertTrue(resources.settings({'profile':'light','cpu_limit_enabled':True})['cpu_limit_enabled'])
        for value in (None, True, '80', 0, 101, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                resources.settings({'profile':'light','cpu_limit_percent':value})
        for value in (0, 1, 'true', None):
            with self.assertRaises(ValueError):
                resources.settings({'profile':'light','cpu_limit_enabled':value})

    def test_old_workspace_policy_default_and_new_policy_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            q = Queue(Path(temp))
            old = {'profile':'custom','max_parallel':1,'reserve_gib':2,'disk_reserve_gib':5,'priority':'below_normal'}
            with q.db() as db:
                db.execute("UPDATE settings SET value=? WHERE key='resources'", (json.dumps(old),))
            self.assertFalse(q.policy()['cpu_limit_enabled'])
            q.set_policy(dict(old,cpu_limit_enabled=True,cpu_limit_percent=70))
            self.assertEqual(Queue(Path(temp)).policy()['cpu_limit_percent'],70)

    @unittest.skipUnless(os.name == 'nt', 'Windows worker')
    def test_real_worker_loop_waits_then_dispatches_when_cpu_headroom_returns(self):
        import execution_worker as worker
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            q = MagicMock(folder=root)
            q.policy.return_value = policy()
            q.next_pending.return_value = {'batch':'test', 'idx':0}
            q.claim.return_value = None  # Assert claim timing without starting a simulation.
            q.state.side_effect = [dict(batches=[dict(mode='run',counts={'pending':1})]), dict(batches=[])]
            history = MagicMock()
            history.estimate.return_value = dict(reserved_gib=.75,configuration_samples=0,family_samples=0,basis='test',observed_family_peak_gib=0)
            with patch.object(worker,'Queue',return_value=q), patch.object(worker,'ProcessGroup'), \
                 patch.object(worker,'ResourceHistory',return_value=history), \
                 patch.object(worker.resources,'snapshot',side_effect=[machine(99),machine(5)]), \
                 patch.object(worker,'engine_pids',return_value=[]), \
                 patch.object(worker.output_storage,'dispatch_capacity',return_value={'reason':None}), \
                 patch.object(worker,'publish_status'), patch.object(worker.time,'sleep'):
                worker.run(root,idle_exit=True)
            self.assertEqual(q.next_pending.call_count,2)
            q.claim.assert_called_once_with(expected={'batch':'test','idx':0})


if __name__ == '__main__':
    unittest.main()
