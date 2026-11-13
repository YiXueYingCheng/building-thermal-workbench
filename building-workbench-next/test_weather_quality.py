import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scope_management
import weather_quality as q


def sample():
    head=['LOCATION,测试,Region,Country,TMY,123,30,110,8,23', 'DESIGN CONDITIONS,0',
          'TYPICAL/EXTREME PERIODS,0', 'GROUND TEMPERATURES,0', 'HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0',
          'COMMENTS 1,Fixture', 'COMMENTS 2,Fixture', 'DATA PERIODS,1,1,Data,Monday,1/1,12/31']
    rows=[]
    for i in range(8760):
        day=dt.date(2025,1,1)+dt.timedelta(days=i//24)
        r=['0']*35;r[:6]=[str(2000+day.month),str(day.month),str(day.day),str(i%24+1),'60','?']
        for index,value in ((6,20),(7,10),(8,50),(9,100000),(12,300),(13,100),(14,50),(15,25),(20,180),(21,2),(23,3)):
            r[index]=str(value)
        rows.append(r)
    return head,rows


def encoded(head,rows):return ('\n'.join(head+ [','.join(r) for r in rows])+'\n').encode('utf-8')


class WeatherQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.head,cls.rows=sample()

    def altered(self,changes):
        rows=copy.deepcopy(self.rows)
        for record,index,value in changes:rows[record][index]=str(value)
        return q.inspect(encoded(self.head,rows))

    def test_complete_mixed_tmy_years_and_monthly_units(self):
        r=q.inspect(encoded(self.head,self.rows))
        self.assertEqual(r['status'],'clear');self.assertTrue(r['timeline']['complete'])
        self.assertEqual(r['timeline']['source_years'],list(range(2001,2013)))
        self.assertEqual(r['monthly'][0]['temperature_mean_C'],20)
        self.assertEqual(r['monthly'][0]['solar']['ghi']['energy_kWh_m2'],74.4)
        self.assertEqual(len(r['monthly']),12);json.dumps(r,allow_nan=False)

    def test_duplicate_missing_and_out_of_order_cannot_form_monthly_statistics(self):
        rows=copy.deepcopy(self.rows);rows[50]=rows[49]
        r=q.inspect(encoded(self.head,rows))
        self.assertEqual(r['timeline']['duplicate_hours'],1);self.assertEqual(r['timeline']['missing_hours'],1)
        self.assertEqual(r['monthly'],[]);self.assertEqual(r['status'],'issues')
        rows=copy.deepcopy(self.rows);rows[50],rows[51]=rows[51],rows[50]
        r=q.inspect(encoded(self.head,rows));self.assertEqual(r['timeline']['out_of_sequence'],2)
        self.assertFalse(r['timeline']['complete'])

    def test_minute_markers_are_not_hour_shift_or_repair(self):
        r=self.altered([(0,4,0),(1,4,30)])
        self.assertTrue(r['timeline']['complete']);self.assertEqual(r['timeline']['minute_markers'],[0,30,60])
        self.assertEqual(r['status'],'notes');self.assertEqual(r['timeline']['missing_hours'],0)
        self.assertEqual(r['timeline']['minute_counts'],{'0':1,'30':1,'60':8758})
        r=q.inspect(encoded(self.head,[[*row[:4],'0',*row[5:]] for row in self.rows]))
        self.assertEqual(next(i['count'] for i in r['issues'] if i['code']=='minute_zero'),8760)

    def test_missing_sentinel_excluded_and_no_zero_fill(self):
        r=self.altered([(0,6,99.9),(0,13,9999),(1,14,10000)])
        self.assertEqual(r['monthly'][0]['temperature_hours'],743)
        self.assertEqual(r['monthly'][0]['temperature_mean_C'],20)
        self.assertIsNone(r['monthly'][0]['solar']['ghi']['energy_kWh_m2'])
        self.assertIsNone(r['monthly'][0]['solar']['dni']['energy_kWh_m2'])
        self.assertEqual(r['monthly'][1]['solar']['ghi']['energy_kWh_m2'],67.2)
        self.assertEqual(r['status'],'issues')

    def test_non_finite_blank_and_range_values(self):
        r=self.altered([(0,6,'NaN'),(1,6,''),(2,6,-80),(3,7,'inf'),(4,14,-1),(5,8,101)])
        f={f['key']:f for f in r['fields']}
        self.assertEqual((f['dry_bulb']['invalid'],f['dry_bulb']['missing'],f['dry_bulb']['out_of_range']),(1,1,1))
        self.assertEqual(f['dry_bulb']['minimum'],20);self.assertEqual(f['relative_humidity']['out_of_range'],0)
        json.dumps(r,allow_nan=False)

    def test_ir_fallback_is_row_specific_and_needs_cloud_and_temperature(self):
        r=self.altered([(0,12,9999),(1,12,9999),(1,23,99),(2,23,99),(3,12,9999),(3,7,99.9)])
        self.assertEqual(r['infrared'],dict(fallback_hours=1,unavailable_hours=2))
        r=self.altered([(0,12,9999)]);self.assertEqual(r['status'],'notes')
        r=self.altered([(0,12,'NaN')]);self.assertEqual(r['infrared']['unavailable_hours'],1)

    def test_partial_subhourly_and_leap_data_not_claimed_complete(self):
        r=q.inspect(encoded(self.head,self.rows[:48]));self.assertEqual(r['timeline']['records_scanned'],48);self.assertFalse(r['monthly'])
        h=self.head.copy();h[7]='DATA PERIODS,1,4,Data,Monday,1/1,12/31'
        self.assertFalse(q.inspect(encoded(h,self.rows))['timeline']['complete'])
        r=self.altered([(0,1,2),(0,2,29)])
        self.assertEqual(r['timeline']['invalid_time'],1);self.assertFalse(r['monthly'])

    def test_bad_encoding_headers_column_counts_and_csv(self):
        self.assertEqual(q.inspect(b'\xff')['status'],'issues')
        self.assertEqual(q.inspect(b'LOCATION')['status'],'issues')
        h=self.head.copy();h[1]='BROKEN'
        self.assertFalse(q.inspect(encoded(h,self.rows))['monthly'])
        rows=copy.deepcopy(self.rows);rows[0]=rows[0][:8]
        r=q.inspect(encoded(self.head,rows));self.assertFalse(r['monthly'])
        rows=copy.deepcopy(self.rows);rows[0][6]='"unfinished'
        r=q.inspect(encoded(self.head,rows));self.assertIn('csv',{i['code'] for i in r['issues']})

    def test_bounded_examples_and_record_cap(self):
        rows=copy.deepcopy(self.rows)
        for r in rows:r[6]='99.9'
        report=q.inspect(encoded(self.head,rows));issue=next(i for i in report['issues'] if i['code']=='dry_bulb_missing')
        self.assertEqual(issue['count'],8760);self.assertEqual(len(issue['examples']),3)
        self.assertEqual(issue['examples'][0]['line'],9);self.assertIsNone(report['monthly'][0]['temperature_mean_C'])
        r=q.inspect(encoded(self.head,self.rows+self.rows[:26]));self.assertEqual(r['timeline']['records_scanned'],8785)
        self.assertIn('record_limit',{i['code'] for i in r['issues']})

    def test_location_nan_cannot_be_reported_clear(self):
        h=self.head.copy();h[0]='LOCATION,Test,Region,Country,TMY,123,nan,110,8,23'
        self.assertEqual(q.inspect(encoded(h,self.rows))['status'],'issues')

    def test_bound_bytes_identity_missing_mismatch_and_size(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'weather.epw';raw=encoded(self.head,self.rows);f.write_bytes(raw);checksum=hashlib.sha256(raw).hexdigest()
            meta,got=q.read_snapshot(f,checksum);self.assertEqual(meta['status'],'matches');self.assertEqual(got,raw)
            self.assertIsNone(q.read_snapshot(f,'0'*64)[1])
            with patch.object(q,'MAX_BYTES',10):self.assertEqual(q.read_snapshot(f,checksum)[0]['status'],'too_large')
            f.unlink();self.assertEqual(q.read_snapshot(f,checksum)[0]['status'],'missing')

    def test_mid_read_change_discards_report(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'weather.epw';raw=encoded(self.head,self.rows);f.write_bytes(raw)
            a=f.stat();b=type('Changed',(),dict(st_size=a.st_size,st_ino=a.st_ino,st_mtime_ns=a.st_mtime_ns+1))()
            with patch.object(Path,'stat',side_effect=[a,b]):meta,data=q.read_snapshot(f,hashlib.sha256(raw).hexdigest())
            self.assertEqual(meta['status'],'changed_during_read');self.assertIsNone(data)

    def test_endpoint_keeps_catalog_file_and_review_and_rejects_arbitrary_path(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'weather.epw';raw=encoded(self.head,self.rows);f.write_bytes(raw);checksum=hashlib.sha256(raw).hexdigest()
            c=dict(sites={'test':dict(id='test',source_kind='reviewed_global',eligible=True,review_note='已有时间复核',weather=dict(path=str(f),sha256=checksum)),
                          'held':dict(id='held',source_kind='reviewed_global',eligible=False,weather=None)})
            before=copy.deepcopy(c);r=scope_management.weather_quality_detail('test',c)
            self.assertEqual(r['quality']['sha256'],checksum);self.assertEqual(c,before);self.assertEqual(f.read_bytes(),raw)
            self.assertEqual(r['site']['review_note'],'已有时间复核')
            self.assertIsNone(scope_management.weather_quality_detail('held',c)['quality'])
            f.write_bytes(b'changed');r=scope_management.weather_quality_detail('test',c)
            self.assertEqual(r['status'],'mismatch');self.assertIsNone(r['quality'])
            with self.assertRaises(ValueError):scope_management.weather_quality_detail(str(f),c)


if __name__=='__main__':unittest.main()
