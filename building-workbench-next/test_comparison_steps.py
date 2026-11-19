"""An accepted baseline can be paired at a different step in just one comparison."""
import copy
from pathlib import Path
import tempfile
import unittest

from batch_results import build as batch_results
from comparison_results import build
from comparison_steps import can_waive, choose
from record_store import Store
from site_recalculation import adopt, submit
from test_site_recalculation import fixture, finish_fixture


class PairedStepTest(unittest.TestCase):
    def test_only_step_may_differ_for_a_waiver(self):
        a=dict(step_minutes=5,evidence={},weather_sha256='weather',status='passed',days=365,
               mode='controlled',monthly=[dict(month=1)],period=[1,1,12,31])
        b=dict(a,step_minutes=1,evidence={'original_failure':{'step_minutes':5}})
        self.assertTrue(can_waive([a,b]))
        for changes in (dict(status='failed'),dict(status='review'),dict(weather_sha256='other'),
                        dict(days=30),dict(period=[1,1,1,31]),dict(monthly=[]),dict(monthly=[dict(month=2)]),
                        dict(evidence={}),dict(step_minutes=10),dict(step_minutes=5)):
            self.assertFalse(can_waive([a,dict(b,**changes)]),changes)

    def test_one_of_34_requires_confirmation_and_retains_both_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            q,base,catalog,left,originals=fixture(root,34,fail_last=False)
            study=copy.deepcopy(base)
            study.update(id='global_fixed',name='固定高热阻与表面光学切换')
            _,study,_,right,jobs=fixture(root,34,Path(next(iter(base['numerics']['engine_files']))),
                Path(originals[0]['case']['weather']),frozen_record=study,bundle_id='inputs_'+'2'*32,
                snapshot=base['factors']['building']['model_snapshot'])
            catalog['records'][study['id']]=study
            store=Store(catalog,root)
            def relation(name):
                return store.add_comparison(name,*({k:r[k] for k in ('id','revision')} for r in (base,study)),'total')['id']
            ident=relation('哈尔滨步长配对')
            def report(active=ident,controls=True):
                return build(active,left,right,'controlled',catalog,root,with_controls=controls)
            fixed_child=submit(q,right,33,jobs[-1]['attempt'],1)['id']
            adopt(q,right,33,fixed_child,finish_fixture(q,q.claim()))
            before=report()
            self.assertEqual(before['paired_sites'],33)
            control=before['step_controls']['s33']
            self.assertEqual([(o['side'],o['step']) for o in control['options']],[('left',1)])
            args=(q,left,33,originals[-1]['attempt'],1,'comparison')
            child=submit(*args)['id']
            self.assertEqual(submit(*args)['id'],child)
            job=q.claim()
            self.assertEqual((job['batch'],job['case']['site_id']),(child,'s33'))
            self.assertIsNone(q.claim())
            req=dict(id=ident,left_source=left,right_source=right,mode='controlled',site='s33',action='select',
                     side='left',child=child,expected=control['expected'],result_sha256='')
            with self.assertRaises(ValueError):choose(root,catalog,req)
            req['result_sha256']=finish_fixture(q,job)
            with self.assertRaises(ValueError):adopt(q,left,33,child,req['result_sha256'])
            self.assertEqual(report()['paired_sites'],33)
            for bad in (dict(expected='stale'),dict(site='s0'),dict(child=fixed_child),dict(result_sha256='wrong')):
                with self.assertRaises(ValueError):choose(root,catalog,dict(req,**bad))
            waiver=dict(req,action='waive')
            for bad in (dict(expected='stale'),dict(site='s0')):
                with self.assertRaises(ValueError):choose(root,catalog,dict(waiver,**bad))
            choose(root,catalog,waiver)
            mixed=report()
            self.assertEqual([(s['paired_sites'],s['waived_sites']) for s in mixed['pairing_summaries']],[(33,0),(34,1)])
            self.assertEqual((mixed['strict_classes'][0]['valid_sites'],mixed['classes'][0]['valid_sites']),(33,34))
            self.assertEqual(mixed['monthly'][-1]['pairing_basis'],'跨步长豁免')
            self.assertEqual(report(relation('未确认豁免的对照'))['paired_sites'],33)
            with self.assertRaises(ValueError):choose(root,catalog,req)
            choose(root,catalog,dict(req,expected=mixed['step_controls']['s33']['expected']))
            done=report()
            self.assertEqual(done['paired_sites'],34)
            self.assertEqual(done['sites'][:-1],before['sites'][:-1])
            h=done['sites'][-1]
            self.assertEqual((h['left_step_minutes'],h['right_step_minutes'],h['left_original_step_minutes'],h['right_original_step_minutes']),(1,1,5,5))
            self.assertEqual(h['left_evidence']['comparison_selection']['original']['attempt'],originals[-1]['attempt'])
            self.assertEqual(h['right_evidence']['original_failure']['attempt'],jobs[-1]['attempt'])
            self.assertEqual(done['dataset_sha256'],report(controls=False)['dataset_sha256'])
            self.assertEqual(report(relation('另一组比较'))['paired_sites'],33)
            baseline=batch_results(left,catalog,root)
            self.assertEqual(baseline['counts']['accepted'],34)
            self.assertEqual({r['step_minutes'] for r in baseline['results']},{5})
            clear=dict(req,action='clear',expected=done['step_controls']['s33']['expected'])
            with self.assertRaises(ValueError):choose(root,catalog,dict(clear,expected='stale'))
            # A selected artifact that no longer verifies cannot silently re-enter the aggregate.
            result=root/'runs'/job['attempt'][8:]/'result.json'
            contents=result.read_bytes()
            result.write_bytes(contents+b' ')
            self.assertEqual(report()['paired_sites'],33)
            result.write_bytes(contents)
            choose(root,catalog,clear)
            self.assertEqual(report()['dataset_sha256'],before['dataset_sha256'])
