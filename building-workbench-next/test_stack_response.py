import copy
import unittest

from stack_response import attach, change_step, configure, signals


class StackResponseTest(unittest.TestCase):
    def setUp(self):
        self.wall=dict(surface='test-wall',construction='assembly',inserted_layers=['pcm','solid'],
                       layers_after=['base','pcm','solid'],thermal_mode='fixed')
        self.audit=dict(model='layer_stack_v1',position='between',surfaces=[self.wall],layers=[
            dict(name='PCM',sha256='pcm-v1',model='phase_change_layer_v1',state='R',revision=1),
            dict(name='Solid',sha256='solid-v1',model='solid_layer_v1',state='R',revision=1)])
        self.model={'Material':{key:dict(thickness=.1,conductivity=1,density=1000,specific_heat=1000)
                                for key in ('base','pcm','solid')},
                    'Timestep':{'steps':{'number_of_timesteps_per_hour':60}},
                    'SurfaceProperty:HeatTransferAlgorithm:Construction':{'fd':dict(construction_name='assembly',algorithm='ConductionFiniteDifference')}}
        self.choice=dict(wall='test-wall',layer=1,sha256='pcm-v1')

    def test_only_selected_boundaries_and_shared_neighbour(self):
        rows=configure(self.model,self.audit,[self.choice,dict(wall='test-wall',layer=2,sha256='solid-v1')],'monthly_period_v1')
        self.assertEqual([(r['outside'],r['inside']) for r in rows],[(8,15),(15,22)])
        self.assertEqual(len(self.model['Output:Variable']),3)
        self.assertIsNone(rows[0]['face'])
        self.assertEqual([field for field,*_ in signals(rows[1])],['outside','inside'])
        self.model['Timestep']['steps']['number_of_timesteps_per_hour']=30
        change_step(self.model,{'stack_response':rows},'monthly_period_v1')
        self.assertEqual([(r['outside'],r['inside']) for r in rows],[(6,11),(11,16)])
        self.assertEqual(len(self.model['Output:Variable']),3)

    def test_reject_stale_version_and_no_internal_solver(self):
        with self.assertRaisesRegex(ValueError,'版本'):
            configure(self.model,self.audit,[{**self.choice,'sha256':'other-version'}],'monthly_period_v1')
        self.model.pop('SurfaceProperty:HeatTransferAlgorithm:Construction')
        with self.assertRaisesRegex(ValueError,'内部节点'):
            configure(self.model,self.audit,[self.choice],'monthly_period_v1')

    def test_old_input_untouched(self):
        original=copy.deepcopy(self.model)
        self.assertEqual(attach(self.model,None,None,{},'monthly_period_v1'),[])
        self.assertEqual(self.model,original)
