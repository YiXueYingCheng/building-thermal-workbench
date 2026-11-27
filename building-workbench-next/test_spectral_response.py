import datetime
import sqlite3
import unittest
from spectral_response import read_values, room_series, TEMP, SOLAR, INSIDE


class SpectralWallReadTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE Time(TimeIndex,Month,Day,Hour,Minute,Interval,EnvironmentPeriodIndex,IntervalType,WarmupFlag);
          CREATE TABLE ReportDataDictionary(ReportDataDictionaryIndex,ReportingFrequency,KeyValue,Name,Units);
          CREATE TABLE ReportData(ReportDataDictionaryIndex,TimeIndex,Value);
        """)
        wall='wall-X'
        fields=[(wall,TEMP,'C',25.),('EMS','WB Window Sky Loss '+wall,'W/m2',14.),
                (wall,INSIDE,'W/m2',-3.),(wall,SOLAR,'W/m2',150.),
                ('EMS','WB Incident Solar '+wall,'W/m2',150.),('EMS','WB Cover Temperature '+wall,'C',27.),
                ('EMS','WB Cover Balance '+wall,'W/m2',0.)]
        for i,(key,name,unit,value) in enumerate(fields):
            self.db.execute("INSERT INTO ReportDataDictionary VALUES(?,'Zone Timestep',?,?,?)",(i,key,name,unit))
            self.db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(i,k,value) for k in range(1,25)])
        self.db.executemany('INSERT INTO Time VALUES(?,7,20,?,0,60,1,-1,0)',[(k,k) for k in range(1,25)])

    def read(self,kind):
        return read_values(self.db,1,'wall-X',kind,[datetime.date(2025,7,20)],60)

    def test_covered_and_broadband_sign_and_fields(self):
        self.assertEqual(self.read('covered')['cover'],[27.]*24)
        broad=self.read('broadband')
        self.assertNotIn('cover',broad)
        self.assertEqual(broad['inward'],[-3.]*24)

    def test_missing_interval_is_not_interpolated(self):
        self.db.execute('DELETE FROM ReportData WHERE ReportDataDictionaryIndex=5 AND TimeIndex=12')
        with self.assertRaisesRegex(ValueError,'有缺项'):self.read('covered')

    def test_duplicate_interval_at_equal_count_is_rejected(self):
        self.db.execute('UPDATE Time SET Hour=11 WHERE Hour=12')
        with self.assertRaisesRegex(ValueError,'重复'):self.read('broadband')

    def test_wrong_wall_solar_is_rejected(self):
        self.db.execute('UPDATE ReportData SET Value=0 WHERE ReportDataDictionaryIndex=4 AND TimeIndex=12')
        with self.assertRaisesRegex(ValueError,'日照'):self.read('covered')

    def test_room_links_and_missing_signals(self):
        fields=[('Study','Zone Mean Air Temperature','C',25.),('EMS','Study Control Mode','',2.),
                ('unitB','Zone Ideal Loads Zone Sensible Cooling Energy','J',3.6e6),
                ('another','Zone Ideal Loads Zone Sensible Cooling Energy','J',9e6)]
        for i,(key,name,unit,value) in enumerate(fields,20):
            self.db.execute("INSERT INTO ReportDataDictionary VALUES(?,'Zone Timestep',?,?,?)",(i,key,name,unit))
            self.db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(i,t,value) for t in range(1,25)])
        model={'EnergyManagementSystem:OutputVariable':{'Study Control Mode':{}},
               'ZoneHVAC:EquipmentConnections':{'conn':{'zone_name':'STUDY','zone_conditioning_equipment_list_name':'L'}},
               'ZoneHVAC:EquipmentList':{'l':{'equipment':[{'zone_equipment_object_type':'ZoneHVAC:IdealLoadsAirSystem','zone_equipment_name':'UnitB'}]}}}
        def read(operation):
            return room_series(self.db,1,[datetime.date(2025,7,20)],60,{'zone':'Study'},model,operation)
        data,notes=read('controlled')
        self.assertEqual(data,dict(air=[25.]*24,state=[2]*24,cooling=[1.]*24))
        self.assertTrue(notes)
        self.db.execute('UPDATE ReportData SET Value=1.5 WHERE ReportDataDictionaryIndex=21 AND TimeIndex=3')
        self.assertNotIn('state',read('controlled')[0])
        self.assertEqual(read('natural')[0],{'air':[25.]*24})
