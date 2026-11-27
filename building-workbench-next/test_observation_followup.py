import contextlib
import unittest
from unittest.mock import patch

import observation_followup as replay


class FollowupTests(unittest.TestCase):
    def test_existing_output_wildcards_are_respected(self):
        model={'Output:Variable':{'room temperature':dict(key_value='*',variable_name='Temperature',reporting_frequency='Monthly')}}
        specs={'air':(['room A'],'Temperature','C','Avg')}
        replay.add_outputs(model,['air'],specs)
        replay.add_outputs(model,['air'],specs)
        outputs=list(model['Output:Variable'].values())
        self.assertEqual(len(outputs),2)
        self.assertEqual(outputs[1],dict(key_value='room A',variable_name='Temperature',reporting_frequency='Timestep'))

    def test_reuse_across_batches_and_only_prepare_missing_fields(self):
        refs=[dict(batch=b,index=0,sha256=b) for b in ('air','different-switch','inward')]
        fields=['air','inward','heating']
        request=dict(action='prepare',result=refs[0],fields=fields,wall='w',offset=60)
        case=dict(mode='controlled',city='city',period=[1,1,1,1],step_minutes=5)
        def read(root,body):
            batch=body['result']['batch']
            return dict(offset=60,wall='w',zone='z',states={'thermal':[1,0] if batch=='different-switch' else [0,1]},
                        rows=[dict(field=f,requestable=True,values=[1,2]) for f in fields],source_token=batch)
        @contextlib.contextmanager
        def source(root,batch,index):
            yield batch,None,1,dict(summary_sha256=batch,view_token=batch)
        def coverage(db,env,chosen,*_):
            return chosen[0]==('heating' if db=='different-switch' else db)
        with contextlib.ExitStack() as stack:
            def replace(name,**kwargs):
                return stack.enter_context(patch.object(replay,name,**kwargs))
            stack.enter_context(patch.object(replay.wall_switches,'read',side_effect=read))
            replace('registered_input',return_value=(None,case,{}, {},dict(status='passed'),None,'air'))
            replace('frozen_model',return_value={})
            replace('candidates',return_value=refs)
            replace('source',side_effect=source)
            replace('verify_series',side_effect=coverage)
            prepare=replace('prepare',return_value={'id':'review'})
            result=replay.resolve(None,request)
            self.assertEqual(result['reused'],{'air':refs[0],'inward':refs[2]})
            self.assertEqual(result['missing'],['heating'])
            self.assertEqual(result['issues'][0]['batch'],'different-switch')
            self.assertEqual(prepare.call_args.args[-2],['heating'])
            result=replay.resolve(None,dict(request,fields=['air','inward']))
            self.assertEqual(result['missing'],[])
            self.assertEqual(result['detail']['states'],{'thermal':[0,1]})
            prepare.assert_called_once()
