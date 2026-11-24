"""Exercise the real queue, input proofs and worker loop with a stand-in solver."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import execution_worker as worker
from foundation import read_json
from resource_history import ResourceHistory
from test_site_recalculation import fixture


class DispatchInputTests(unittest.TestCase):
    def test_damaged_first_model_isolated_and_unclassified_second_case_finishes(self):
        with TemporaryDirectory() as tmp, ExitStack() as mocks:
            root=Path(tmp).resolve()
            q,_,_,batch,_=fixture(root, pending=True, include_model_snapshot=False)
            with q.db() as db:
                review=db.execute('select review from batches where id=?',(batch,)).fetchone()[0]
            folder=q.folder/'reviews'/review
            plan=read_json(folder/'plan.json')
            (folder/plan['cases'][0]['model_file']).write_bytes(b'{}')
            engine=Mock(pid=1234)
            engine.poll.return_value=0
            launch=mocks.enter_context(patch.object(worker.subprocess,'Popen',return_value=engine))
            mocks.enter_context(patch.object(worker,'ProcessGroup'))
            mocks.enter_context(patch.object(worker,'engine_pids',return_value=[]))
            mocks.enter_context(patch.object(worker,'publish_status'))
            mocks.enter_context(patch.object(worker.cpu_budget,'ProcessSamples'))
            mocks.enter_context(patch.object(worker.resources,'process_memory',
                return_value=dict(peak_gib=.4,peak_working_gib=.3,peak_commit_gib=.4)))
            mocks.enter_context(patch.object(worker.resources,'snapshot',
                return_value=dict(available_gib=8,commit_available_gib=8,disk_free_gib=30)))
            mocks.enter_context(patch.object(worker.output_storage,'dispatch_capacity',return_value={'reason':None}))
            mocks.enter_context(patch('resource_history.fingerprint',side_effect=KeyError('new_shape')))
            mocks.enter_context(patch.object(worker,'verify',return_value={'status':'passed'}))
            mocks.enter_context(patch.object(worker.time,'sleep',side_effect=[None]*5+[AssertionError('stalled queue')]))

            worker.run(root,idle_exit=True)
            first,second=q.state()['batches'][0]['jobs']
            self.assertEqual(first['status'],'failed')
            self.assertIn('输入需核查',first['error'])
            self.assertIn(plan['cases'][0]['model_file'],first['error'])
            self.assertEqual(read_json(q.folder/'attempt-errors'/(first['attempt']+'.json'))['phase'],'input')
            self.assertEqual(second['status'],'passed')
            launch.assert_called_once()
            receipt=read_json(worker.output_storage.attempt_folder(root,second['attempt'])/'execution.json')
            self.assertEqual(receipt['resource_estimate']['reserved_gib'],.75)
            self.assertIn('new_shape',receipt['resource_estimate']['budget_note'])
            estimate=ResourceHistory(root).estimate(dict(batch=batch,idx=1))
            self.assertEqual((estimate['basis'],estimate['used_samples']),('exact',1))

    def test_history_lookup_failure_keeps_initial_budget(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            _,_,_,batch,_=fixture(root,1,pending=True,include_model_snapshot=False)
            history=ResourceHistory(root)
            with patch.object(history.history,'estimate',side_effect=ValueError('sample unavailable')):
                result=history.estimate(dict(batch=batch,idx=0))
                self.assertEqual(result['reserved_gib'],.75)
                self.assertTrue(result['unseen_configuration'])
                self.assertIn('sample unavailable',result['budget_note'])
