import datetime as dt
import sqlite3
import unittest

from wall_switches import controlled_walls, control_names, observations, scan


class WallSwitchTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE Time(TimeIndex,SimulationDays,Month,Day,Hour,Minute,Interval,EnvironmentPeriodIndex,IntervalType,WarmupFlag);
            CREATE TABLE ReportData(ReportDataDictionaryIndex,TimeIndex,Value);
            CREATE TABLE ReportDataDictionary(ReportDataDictionaryIndex,ReportingFrequency,Units,Type,KeyValue,Name,IsMeter);
        ''')
        for i in range(48):
            day=1+i//24
            self.db.execute('INSERT INTO Time VALUES(?,?,5,?,?,0,60,1,-1,0)',(i,day,day,i%24+1))
            self.db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(1,i,int(i>=24)),(2,i,int(i>=24))])
        self.ids={'thermal':{'Zone Timestep':1},'orientation':{'Zone Timestep':2}}

    def scan(self):
        return scan(self.db,1,dt.date(2025,5,1),2,60,self.ids)

    def test_midnight_and_simultaneous_changes(self):
        events,_=self.scan()
        self.assertEqual(events,[(1440,{'thermal':[0,1],'orientation':[0,1]})])

    def test_no_transition_inferred_across_gap(self):
        self.db.execute('DELETE FROM ReportData WHERE TimeIndex=23')
        with self.assertRaises(ValueError):self.scan()

    def test_summary_only_does_not_create_transitions(self):
        self.db.execute('INSERT INTO Time VALUES(50,1,5,1,24,0,1440,1,2,0)')
        self.db.execute('INSERT INTO ReportData VALUES(3,50,0.25)')
        self.ids={'thermal':{'Daily':3}}
        events,summaries=self.scan()
        self.assertEqual(events,[])
        self.assertEqual(summaries['thermal']['values'],{'05-01':.25})

    def test_only_bound_walls_and_their_own_states(self):
        record={'factors':{'materials':{'applications':[{'id':'a','target_ids':['wall-a','wall-b']}]},
                           'condition':{'controls':[{'channel':'thermal','mode':'feedback','application_id':'a','target_ids':['wall-a']},
                                                    {'channel':'thermal','mode':'fixed','application_id':'a','target_ids':['wall-b']}]}}}
        self.assertEqual(controlled_walls(record),{'wall-a':{'thermal'}})
        model={'EnergyManagementSystem:OutputVariable':{'NX wall-a State':{},'NX wall-b State':{},'NX_SC_StateOutput':{}}}
        self.assertEqual(control_names(model,'wall-a',{'thermal'}),{'thermal':'NX wall-a State'})

    def test_room_energy_uses_bound_systems_and_exact_intervals(self):
        model={'ZoneHVAC:EquipmentConnections':{'link':{'zone_name':'Bedroom','zone_conditioning_equipment_list_name':'items'}},
               'ZoneHVAC:EquipmentList':{'items':{'equipment':[{'zone_equipment_object_type':'ZoneHVAC:IdealLoadsAirSystem','zone_equipment_name':'unit-A'}]}}}
        fields=[('wall','Surface Inside Face Conduction Heat Transfer Rate per Area','W/m2','Avg',-2.0),
                ('Bedroom','Zone Mean Air Temperature','C','Avg',24),
                ('unit-A','Zone Ideal Loads Zone Sensible Cooling Energy','J','Sum',3.6e6),
                ('other-system','Zone Ideal Loads Zone Sensible Cooling Energy','J','Sum',18e6)]
        for i,(key,name,unit,typ,val) in enumerate(fields,100):
            self.db.execute("INSERT INTO ReportDataDictionary VALUES(?,'Zone Timestep',?,?,?,?,0)",(i,unit,typ,key,name))
            self.db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(i,t,val*(t-22)) for t in (23,24)])
        rows=observations(self.db,[[23],[24]],model,'wall','Bedroom',{'mode':'controlled'},60,None)
        self.assertEqual([r.get('values') for r in rows[:3]],[[-2,-4],[24,48],None])
        for value,expected in zip(rows[3]['values'],[1,2],strict=True):
            self.assertAlmostEqual(value,expected)
