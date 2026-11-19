import copy
from pathlib import Path
import unittest

from schedule_sharing import share_files


class ScheduleSharingTests(unittest.TestCase):
    def setUp(self):
        self.paths = [str(Path(f'room{i}.csv').resolve()) for i in range(6)]
        self.dependencies = {path:'a'*64 for path in self.paths}
        self.model = {'Schedule:File':{name:{'file_name':path,'column_number':1} for name,path in zip('ABCDEF',self.paths)},
                      'People':{'Room B':{'number_of_people_schedule_name':'b'}},
                      'EnergyManagementSystem:Sensor':{'independent_sensor':{
                          'output_variable_or_output_meter_name':'Schedule Value',
                          'output_variable_or_output_meter_index_key_name':'B'}}}

    def test_only_identical_read_only_inputs_share(self):
        m = self.model
        m['EnergyManagementSystem:Actuator'] = {'own_control':{'actuated_component_unique_name':'C'}}
        m['Schedule:File']['D']['column_number'] = 2
        self.dependencies[self.paths[4]] = 'e'*64
        m['Other:Object'] = {'uncertain':{'entries':[{'unrecognized_name':'F'}]}}
        sharing = share_files(m,self.dependencies)
        self.assertEqual(sharing['aliases'],{'B':'A'})
        self.assertEqual(m['People']['Room B']['number_of_people_schedule_name'],'A')
        self.assertEqual(m['EnergyManagementSystem:Sensor']['independent_sensor']['output_variable_or_output_meter_index_key_name'],'A')
        self.assertEqual(m['EnergyManagementSystem:Actuator']['own_control']['actuated_component_unique_name'],'C')
        self.assertIsNone(share_files(m,self.dependencies))

    def test_protected_schedule_never_becomes_shared_source(self):
        self.model['Output:Variable']={'specific':{'variable_name':'Schedule Value','key_value':'A'}}
        aliases=share_files(self.model,self.dependencies)['aliases']
        self.assertNotIn('A',aliases)
        self.assertNotIn('A',aliases.values())

    def test_opaque_consumers_leave_execution_model_as_supplied(self):
        for kind, obj in [('PythonPlugin:Instance',{'plugin_class_name':'Unknown'}),
                          ('ExternalInterface:Schedule',{}),
                          ('Output:Variable',{'variable_name':'Schedule Value','key_value':'[AB].*'})]:
            with self.subTest(kind=kind):
                model=dict(copy.deepcopy(self.model),**{kind:{'example':obj}})
                initial=copy.deepcopy(model)
                self.assertIsNone(share_files(model,self.dependencies))
                self.assertEqual(model,initial)
