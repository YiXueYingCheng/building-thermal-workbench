from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import unittest, tempfile, sqlite3, json
import csv
import batch_timeseries as details
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

    def test_shared_schedule_lookup_and_export_by_original_name(self):
        self.raw['schedule_sharing'] = dict(version=1,original_count=2,retained_count=1,aliases={'Room B':'Room A'})
        self.raw['period'] = [1,1,1,31]
        with closing(sqlite3.connect(self.sql)) as db, db:
            for i,freq in enumerate(('Daily','Monthly','Run Period'),4):
                db.execute('INSERT INTO ReportDataDictionary VALUES(?,0,?,?,?,?,?)',(i,'Avg','ROOM A','Schedule Value',freq,''))
            db.execute('INSERT INTO ReportData SELECT TimeIndex,4,0.5 FROM Time WHERE WarmupFlag IS NULL')
            for ident,interval in ((5,3),(6,4)):
                db.execute('INSERT INTO Time VALUES(?,2007,1,31,24,0,0,44640,?,31,1,NULL)',(100+ident,interval))
                db.execute('INSERT INTO ReportData VALUES(?,?,0.5)',(100+ident,ident))
        self.save()
        inventory=rt.inventory(self.root,self.batch,0)
        aliases=[r for r in inventory['dictionary'] if r.get('SharedSchedule')]
        self.assertEqual(len(aliases),3)
        for row in aliases:
            key=row['ReportDataDictionaryIndex']
            values=rt.series(self.root,self.batch,0,key,'01-01','01-31')
            physical=rt.series(self.root,self.batch,0,row['SourceDictionaryIndex'],'01-01','01-31')
            self.assertEqual(values['variable']['KeyValue'],'ROOM B')
            self.assertEqual(values['rows'],physical['rows'])
        path=self.root/'names.csv'
        variables={4:('schedules',dict(KeyValue='ROOM A'))}
        details.write_schedule_names(self.raw,variables,path)
        with path.open(encoding='utf-8-sig',newline='') as f:self.assertEqual(list(csv.reader(f))[1:],[['ROOM B','ROOM A']])

    def test_inventory_distinguishes_solver_step_and_actual_frequency(self):
        r=rt.inventory(self.root,self.batch,0)
        self.assertEqual(r['step_minutes'],5);self.assertFalse(r['has_subdaily_time_records'])
        self.assertEqual(r['frequencies'][0]['records'],31);self.assertEqual(r['systems'],['SYSTEM A'])

    def test_reopening_inventory_reuses_only_verified_unchanged_sql(self):
        token=rt.inventory(self.root,self.batch,0)['view_token']
        with patch.object(rt,'source',side_effect=AssertionError('SQL reader reopened')):
            self.assertEqual(rt.inventory(self.root,self.batch,0,token),dict(view_token=token,unchanged=True))
        with self.q.db() as db:db.execute("UPDATE jobs SET status='reused'")
        changed=rt.inventory(self.root,self.batch,0,token)
        self.assertNotEqual(changed['view_token'],token)
        self.assertEqual(changed['registered_status'],'reused')
        self.sql.write_bytes(b'broken result')
        with self.assertRaisesRegex(ValueError,'SQL'):rt.inventory(self.root,self.batch,0,changed['view_token'])

    def test_building_daily_sums_include_every_system_and_match_monthly(self):
        self.raw.update(period=[1,1,1,31], rooms=[dict(system=s) for s in ('SYSTEM A','SYSTEM B')],
                        monthly=[dict(month=1,heating_kWh=527,cooling_kWh=992)])
        with closing(sqlite3.connect(self.sql)) as db, db:
            for idx,name,value in ((4,rt.HEAT,3.6e6),(5,rt.COOL,0)):
                db.execute("INSERT INTO ReportDataDictionary VALUES(?,0,'Sum','SYSTEM B',?,'Daily','J')",(idx,name))
                db.execute('INSERT INTO ReportData SELECT TimeIndex,?,? FROM Time WHERE WarmupFlag IS NULL',(idx,value))
        self.save()
        def building():
            return rt.daily(self.root,self.batch,0,'','01-01','01-31','building')
        self.assertEqual(rt.inventory(self.root,self.batch,0)['building_daily_issue'],'')
        actual=building()
        self.assertEqual(actual['system_count'],2)
        self.assertEqual(actual['rows'][0]['total_kWh'],4)
        self.assertEqual(actual['sums'],dict(heating_kWh=527,cooling_kWh=992,total_kWh=1519))
        self.raw['monthly'][0]['cooling_kWh']=993
        self.save()
        with self.assertRaisesRegex(ValueError,'月度汇总'):building()
        self.mutate('DELETE FROM ReportData WHERE TimeIndex=2 AND ReportDataDictionaryIndex=5')
        with self.assertRaisesRegex(ValueError,'缺失'):building()
        self.mutate("DELETE FROM ReportDataDictionary WHERE KeyValue='SYSTEM B'")
        with self.assertRaisesRegex(ValueError,'全部系统'):building()
        self.assertEqual(self.daily(end='01-01')['rows'][0]['total_kWh'],3)

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

    def test_export_native_material_states_separately_and_keep_fixed_channels_out(self):
        self.raw['period']=[1,1,1,31]
        with closing(sqlite3.connect(self.sql)) as db, db:
            for ident,name in ((7,'NX_SC_StateOutput'),(8,'NX_SC_FaceOutput')):
                db.execute("INSERT INTO ReportDataDictionary VALUES(?,0,'Avg','EMS',?,'Daily','')",(ident,name))
                db.executemany("INSERT INTO ReportData VALUES(?,?,?)",
                    [(day,ident,0.25 if ident==7 else int(day<=12)) for day in range(1,32)])
                db.execute("INSERT INTO ReportData VALUES(100,?,6)",(ident,))
        self.save()
        controls=[dict(channel='thermal',mode='feedback',target_ids=['S_10']),
                  dict(channel='orientation',mode='calendar',target_ids=['S_10'])]
        record={'factors':{'condition':{'controls':controls}}}
        case=dict(index=2,city='Fixture',mode='controlled',status='passed',status_label='通过',
                  evidence=dict(batch_id=self.batch,index=0,result_sha256=sha(self.summary),identity='same'))
        data=dict(record_id='scheme',revision=1,record_sha256=details.digest(record),results=[case])
        with patch.object(details,'current'),patch.object(details,'Store') as store:
            store.return_value.get.return_value=record
            options=details.inspect(data,self.root)
            self.assertEqual(options['choices'],[dict(group=g,frequency='Daily',cases=1) for g in ('loads','optical','thermal')])
            for group,expected in [('thermal',[25]*31),('optical',[100]*12+[0]*19)]:
                response=details.inspect(data,self.root,[(group,'Daily')],self.root)
                self.assertEqual(response['inventory_sha256'],options['inventory_sha256'])
                entry=response['cases'][0]
                self.assertEqual((entry['source_index'],entry['rows']),(0,31))
                with (self.root/entry['file']).open(encoding='utf-8-sig') as f:
                    rows=list(csv.DictReader(f))
                self.assertEqual([float(r['状态占比_%']) for r in rows],expected)
                self.assertEqual({r['算例'] for r in rows},{'3'})
                self.assertEqual(rows[-1]['区间结束日期'],'01-31')
            controls[1]['mode']='fixed';data['record_sha256']=details.digest(record)
            options=details.inspect(data,self.root)
            self.assertNotIn('optical',options['groups'])
            self.assertFalse(any(r['group']=='optical' for r in options['choices']))
            self.sql.unlink()
            missing=details.inspect(data,self.root)
            self.assertEqual(missing['choices'],[])
            self.assertIn('SQL',missing['cases'][0]['note'])

    def test_month_output_is_read_as_a_complete_simulated_period(self):
        self.raw['period']=[1,8,1,12]
        with closing(sqlite3.connect(self.sql)) as db, db:
            db.execute("INSERT INTO Time VALUES(200,2007,1,12,24,0,0,44640,3,5,1,0)")
            db.execute("INSERT INTO ReportData VALUES(200,3,19.25)")
            db.execute("INSERT INTO ReportDataDictionary VALUES(4,0,'Avg','EMS','NX_Fb_StateOutput','Monthly','')")
            db.execute("INSERT INTO ReportData VALUES(200,4,0.25)")
        self.save()
        d=rt.series(self.root,self.batch,0,3,'01-08','01-12')
        self.assertEqual((d['rows'][0]['label'],d['rows'][0]['Value']),('01-08 至 01-12',19.25))
        self.assertEqual(rt.inventory(self.root,self.batch,0)['monthly_controls']['compressed']['months'],{1:0.25})
        with self.assertRaises(ValueError):rt.series(self.root,self.batch,0,3,'01-09','01-12')
        self.mutate("INSERT INTO ReportData VALUES(200,4,0.25)")
        self.assertIn('error',rt.inventory(self.root,self.batch,0)['monthly_controls']['compressed'])
        self.mutate("UPDATE ReportDataDictionary SET KeyValue='OTHER' WHERE ReportDataDictionaryIndex=4")
        self.assertFalse(rt.inventory(self.root,self.batch,0)['monthly_controls'])


if __name__=='__main__':unittest.main()
