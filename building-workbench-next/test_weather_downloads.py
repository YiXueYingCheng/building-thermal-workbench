import copy, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
from foundation import sha
import weather_downloads as wd


class DownloadsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.ids=[r['id'] for r in wd.catalog()['rows'][:2]]
        self.addCleanup(self.tmp.cleanup)

    def wait(self):
        worker=wd.ACTIVE.get(str(self.root.resolve()))
        if worker:worker['thread'].join(8);self.assertFalse(worker['thread'].is_alive())

    def fetch(self,ident,output):
        p=Path(output);p.mkdir(parents=True,exist_ok=True);f=p/(ident+'.epw');reused=f.exists()
        if not reused:f.write_bytes(b'test EPW')
        return dict(id=ident,path=str(f),sha256=sha(f),reused=reused)

    def test_catalog_preserves_34_regions_and_missing_class(self):
        c=wd.catalog();self.assertEqual(len(c['china34']),34);self.assertEqual(len(c['climates']),30)
        self.assertEqual(len(c['global30']),29)
        self.assertIsNone(next(x for x in c['climates'] if x['climate']=='Csc')['default_id'])

    def test_failed_item_can_resume_without_redownloading_success(self):
        called=[]
        def first(i,o):
            called.append(i)
            if i==self.ids[1]:raise OSError('模拟网络中断')
            return self.fetch(i,o)
        with patch.object(wd.weather_fetch,'fetch',side_effect=first),patch.object(wd.weather_quality,'inspect',return_value={'status':'ok'}):
            job=wd.start(self.root,self.ids,str(self.root/'downloads'));self.wait()
        self.assertEqual(wd.status(self.root,job['id'])['state'],'completed_with_issues')
        with patch.object(wd.weather_fetch,'fetch',side_effect=lambda i,o:(called.append(i) or self.fetch(i,o))),patch.object(wd.weather_quality,'inspect',return_value={'status':'ok'}):
            wd.resume(self.root,job['id']);self.wait()
        self.assertEqual(called.count(self.ids[0]),1)
        self.assertEqual(wd.status(self.root,job['id'])['state'],'completed')
        self.assertFalse((self.root/'data/weather-registry').exists())

    def test_cancel_keeps_current_result_and_stops_next_file(self):
        entered=threading.Event();release=threading.Event()
        def fetch(i,o):entered.set();release.wait(5);return self.fetch(i,o)
        with patch.object(wd.weather_fetch,'fetch',side_effect=fetch),patch.object(wd.weather_quality,'inspect',return_value={'status':'ok'}):
            job=wd.start(self.root,self.ids,str(self.root/'downloads'));self.assertTrue(entered.wait(3))
            with self.assertRaises(ValueError):wd.start(self.root,self.ids,str(self.root/'other'))
            wd.cancel(self.root,job['id']);release.set();self.wait()
        result=wd.status(self.root,job['id']);self.assertEqual(result['state'],'cancelled')
        self.assertEqual([i['state'] for i in result['items']],['ready','pending'])

    def test_quality_issues_are_retained_but_cannot_register(self):
        with patch.object(wd.weather_fetch,'fetch',side_effect=self.fetch),patch.object(wd.weather_quality,'inspect',return_value={'status':'issues'}):
            job=wd.start(self.root,self.ids[:1],str(self.root/'downloads'));self.wait()
        result=wd.status(self.root,job['id']);self.assertEqual(result['items'][0]['state'],'quality_issues')
        self.assertTrue(Path(result['items'][0]['result']['path']).exists())
        with self.assertRaises(ValueError):wd.register(self.root,job['id'],self.ids[:1],{},True)

    def test_source_ids_and_output_location_must_be_explicit(self):
        for ids in ([],['unknown'],[self.ids[0],self.ids[0]]):
            with self.assertRaises(ValueError):wd.start(self.root,ids,str(self.root/'downloads'))
        with self.assertRaises(ValueError):wd.start(self.root,self.ids,'relative')


if __name__=='__main__':unittest.main()
