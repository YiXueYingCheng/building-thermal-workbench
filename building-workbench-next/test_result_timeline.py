from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import unittest, tempfile, sqlite3, json
from foundation import sha
from execution_queue import Queue
import result_timeline as rt


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.q=Queue(self.root)
        self.batch='batch_'+'a'*32;folder=self.root/'runs'/('b'*32);folder.mkdir(parents=True)
        self.sql=folder/'eplusout.sql';self.summary=folder/'result.json'
        with closing(sqlite3.connect(self.sql)) as db, db:
            db.executescript('''CREATE TABLE EnvironmentPeriods(EnvironmentPeriodIndex INTEGER,EnvironmentType INTEGER);
            INSERT INTO EnvironmentPeriods VALUES(1,3);
            CREATE TABLE ReportDataDictionary(ReportDataDictionaryIndex INTEGER,IsMeter INTEGER,Type TEXT,KeyValue TEXT,Name TEXT,ReportingFrequency TEXT,Units TEXT);
            CREATE TABLE Time(TimeIndex INTEGER,Year INTEGER,Month INTEGER,Day INTEGER,Hour INTEGER,Minute INTEGER,Dst INTEGER,Interval INTEGER,IntervalType INTEGER,SimulationDays INTEGER,EnvironmentPeriodIndex INTEGER,WarmupFlag INTEGER);
            CREATE TABLE ReportData(TimeIndex INTEGER,ReportDataDictionaryIndex INTEGER,Value REAL);''')
            for i,name in enumerate((rt.HEAT,rt.COOL),1):
                db.execute('INSERT INTO ReportDataDictionary VALUES(?,0,?,?,?,?,?)',(i,'Sum','SYSTEM A',name,'Daily','J'))
            db.execute('INSERT INTO ReportDataDictionary VALUES(3,0,?,?,?,?,?)',('Avg','ROOM A','Zone Mean Air Temperature','Monthly','C'))
            for day in range(1,32):
                db.execute('INSERT INTO Time VALUES(?,2007,1,?,24,0,0,1440,2,?,1,NULL)',(day,day,day))
                db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(day,1,day*3.6e6),(day,2,2*day*3.6e6)])
            # Excluded warmup and different environment values must never contaminate dates.
            db.execute('INSERT INTO Time VALUES(100,2007,1,1,24,0,0,1440,2,1,1,1)')
            db.execute('INSERT INTO ReportData VALUES(100,1,999999999)')
        self.raw=dict(identity='same',status='passed',period=[1,1,12,31],step_minutes=5,city='Fixture')
        with self.q.db() as db:
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(self.batch,'review','{}','hash','pause','now'))
            db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,updated) VALUES(?,?,?,?,?,?)',(self.batch,0,'passed','same','attempt_'+'b'*32,'now'))
        self.save()

    def save(self):
        self.raw['artifacts']={str(self.sql):sha(self.sql)}
        self.summary.write_text(json.dumps(self.raw),encoding='utf8')
        with self.q.db() as db:db.execute('UPDATE jobs SET result=?,result_sha256=?',(str(self.summary),sha(self.summary)))

    def daily(self,start='01-01',end='01-03',system='SYSTEM A'):
        return rt.daily(self.root,self.batch,0,system,start,end)

    def mutate(self,statement):
        with closing(sqlite3.connect(self.sql)) as db, db:db.execute(statement)
        self.save()

    def test_inventory_distinguishes_solver_step_and_actual_frequency(self):
        r=rt.inventory(self.root,self.batch,0)
        self.assertEqual(r['step_minutes'],5);self.assertFalse(r['has_subdaily_time_records'])
        self.assertEqual(r['frequencies'][0]['records'],31);self.assertEqual(r['systems'],['SYSTEM A'])

    def test_daily_closed_values_and_preserved_calendar(self):
        before={p:sha(p) for p in (self.q.path,self.sql,self.summary)}
        r=self.daily();self.assertEqual(r['sums'],dict(heating_kWh=6,cooling_kWh=12,total_kWh=18))
        self.assertEqual(r['rows'][0]['time']['Year'],2007);self.assertEqual(r['rows'][0]['date'],'01-01')
        self.assertEqual(before,{p:sha(p) for p in before});self.assertEqual(len(self.daily(end='01-31')['rows']),31)

    def test_invalid_ranges_not_truncated(self):
        for start,end in [('01-01','02-01'),('01-03','01-01'),('02-29','03-01'),('../01','01-03'),('13-01','13-02')]:
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):self.daily(start,end)
        self.raw['period']=[1,2,1,31];self.save()
        with self.assertRaises(ValueError):self.daily()

    def test_missing_or_duplicate_never_zero_filled(self):
        self.mutate('DELETE FROM ReportData WHERE TimeIndex=2 AND ReportDataDictionaryIndex=2')
        with self.assertRaisesRegex(ValueError,'缺失'):self.daily()
        self.mutate('INSERT INTO ReportData VALUES(2,2,0)');self.mutate('INSERT INTO ReportData VALUES(2,2,0)')
        with self.assertRaisesRegex(ValueError,'重复'):self.daily()

    def test_time_alignment_and_interval_checked(self):
        self.mutate('UPDATE Time SET Day=3 WHERE TimeIndex=2')
        with self.assertRaisesRegex(ValueError,'日期'):self.daily()
        self.mutate('UPDATE Time SET Day=2,Interval=60 WHERE TimeIndex=2')
        with self.assertRaisesRegex(ValueError,'间隔'):self.daily()

    def test_wrong_statistic_units_and_negative_rejected(self):
        self.mutate("UPDATE ReportDataDictionary SET Units='W' WHERE ReportDataDictionaryIndex=1")
        with self.assertRaisesRegex(ValueError,'单位'):self.daily()
        self.mutate("UPDATE ReportDataDictionary SET Units='J',Type='Avg' WHERE ReportDataDictionaryIndex=1")
        with self.assertRaisesRegex(ValueError,'累加'):self.daily()
        self.mutate("UPDATE ReportDataDictionary SET Type='Sum' WHERE ReportDataDictionaryIndex=1")
        self.mutate('UPDATE ReportData SET Value=-1 WHERE TimeIndex=2')
        with self.assertRaisesRegex(ValueError,'无效数值'):self.daily()

    def test_unknown_system_no_room_name_guess(self):
        with self.assertRaises(ValueError):self.daily(system='ROOM A')
        with self.assertRaises(ValueError):self.daily(system="x' OR 1=1")

    def test_source_identity_and_missing_detail(self):
        self.raw['identity']='other';self.save()
        with self.assertRaisesRegex(ValueError,'身份'):self.daily()
        self.raw['identity']='same';self.save();self.sql.unlink()
        with self.assertRaisesRegex(ValueError,'不能还原明细'):rt.inventory(self.root,self.batch,0)

    def test_hash_change_and_writer_journal(self):
        with closing(sqlite3.connect(self.sql)) as db, db:db.execute('UPDATE ReportData SET Value=0')
        with self.assertRaisesRegex(ValueError,'核对'):self.daily()
        self.save();Path(str(self.sql)+'-wal').write_bytes(b'active')
        with self.assertRaisesRegex(ValueError,'写入日志'):self.daily()

    def test_review_display_is_not_acceptance(self):
        self.raw['status']='review';self.save()
        with self.q.db() as db:db.execute("UPDATE jobs SET status='review'")
        self.assertEqual(self.daily()['registered_status'],'review')

    def test_design_day_or_mixed_environments_rejected(self):
        self.mutate('INSERT INTO EnvironmentPeriods VALUES(2,1)')
        with self.assertRaisesRegex(ValueError,'环境'):self.daily()

    def test_registration_concurrency_is_rejected(self):
        original=rt.jobs;calls=[]
        def changed(*args):
            rows=original(*args);calls.append(1)
            if len(calls)>1:rows[0]['updated']='changed'
            return rows
        with patch.object(rt,'jobs',side_effect=changed),self.assertRaisesRegex(ValueError,'任务登记变化'):self.daily()

    def test_missing_half_pair_and_monthly_not_read_as_daily(self):
        self.mutate("UPDATE ReportDataDictionary SET ReportingFrequency='Monthly' WHERE ReportDataDictionaryIndex=2")
        self.assertEqual(rt.inventory(self.root,self.batch,0)['systems'],[])
        with self.assertRaises(ValueError):self.daily()

    def test_read_deadline_stops_verification(self):
        with self.assertRaises(ValueError):
            with rt.source(self.root,self.batch,0,budget=-1):pass


if __name__=='__main__':unittest.main()
