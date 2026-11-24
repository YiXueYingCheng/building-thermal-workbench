import copy, json, tempfile, unittest, urllib.error
from pathlib import Path
from unittest.mock import patch
import weather_downloads as wd
from foundation import sha, read_json


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.alts=wd.weather_fetch.alternatives()['weather']
        self.ids=[r['original_id'] for r in self.alts[:3]]
        self.china=wd.catalog()['china34'][0]

    def wait(self):
        thread=wd.ACTIVE[str(self.root.resolve())]['thread'];thread.join(10)
        self.assertFalse(thread.is_alive())

    def good(self,ident,output):
        file=Path(output)/(ident+'.epw');file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(b'fake for controlled network test')
        return dict(path=str(file),sha256=sha(file))

    def failed_parent(self,ids=None):
        with patch.object(wd.weather_fetch,'fetch',side_effect=ValueError('controlled failure')):
            job=wd.start(self.root,ids or self.ids,str(self.root/'epw'));self.wait()
        return wd.status(self.root,job['id'])

    def test_primary_defaults_stay_original_and_approved_coverage(self):
        catalog=wd.catalog();self.assertEqual(len(catalog['global30']),29)
        self.assertTrue(all(not x.startswith('pvgis_') for x in catalog['global30']))
        self.assertEqual(len(self.alts),25)
        self.assertEqual(len(wd.weather_fetch.alternatives()['unavailable']),2)
        self.assertTrue(any(r['timezone']!=r['original_timezone'] for r in self.alts))

    def test_preview_is_readonly_and_excludes_success(self):
        parent=self.failed_parent();parent['items'][0]['state']='ready';wd.save(self.root,parent)
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        preview=wd.fallback_preview(self.root,parent['id'])
        self.assertEqual([r['id'] for r in preview['rows']],self.ids[1:])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_confirmation_and_selected_ids_required(self):
        parent=self.failed_parent();preview=wd.fallback_preview(self.root,parent['id'])
        for ids,stamp,reviewed in [(self.ids,preview['stamp'],False),([],preview['stamp'],True),(['injected'],preview['stamp'],True),(self.ids,'stale',True)]:
            with self.assertRaises(ValueError):wd.fallback_start(self.root,parent['id'],ids,stamp,reviewed)
        self.assertEqual(len(wd.listing(self.root)),1)

    def test_stale_source_or_parent_rejected(self):
        parent=self.failed_parent();preview=wd.fallback_preview(self.root,parent['id'])
        parent['items'][0]['attempts']+=1;wd.save(self.root,parent)
        with self.assertRaises(ValueError):wd.fallback_start(self.root,parent['id'],self.ids,preview['stamp'],True)
        preview=wd.fallback_preview(self.root,parent['id']);manifest=copy.deepcopy(wd.weather_fetch.alternatives());manifest['weather'][0]['period']='changed'
        with patch.object(wd.weather_fetch,'alternatives',return_value=manifest):
            with self.assertRaises(ValueError):wd.fallback_start(self.root,parent['id'],self.ids,preview['stamp'],True)

    def test_child_preserves_parent_and_repeat_confirmation_reuses_child(self):
        parent=self.failed_parent();before=wd.path(self.root,parent['id']).read_bytes();p=wd.fallback_preview(self.root,parent['id'])
        with patch.object(wd.weather_fetch,'fetch',side_effect=self.good),patch.object(wd.weather_quality,'inspect',return_value={'status':'notes'}):
            child=wd.fallback_start(self.root,parent['id'],self.ids[:1],p['stamp'],True);self.wait()
            again=wd.fallback_start(self.root,parent['id'],self.ids[:1],p['stamp'],True)
        self.assertEqual(child['id'],again['id']);self.assertEqual(before,wd.path(self.root,parent['id']).read_bytes())
        self.assertEqual(again['state'],'completed');self.assertEqual(again['parent_batch_id'],parent['id'])
        self.assertIn('JRC 备用',again['items'][0]['name']);self.assertFalse((self.root/'data/weather-registry').exists())
        with self.assertRaises(ValueError):wd.fallback_preview(self.root,child['id'])

    def test_unavailable_sites_cannot_be_submitted(self):
        ids=[r['original_id'] for r in wd.weather_fetch.alternatives()['unavailable']]
        parent=self.failed_parent(ids);preview=wd.fallback_preview(self.root,parent['id'])
        self.assertTrue(all(not r['alternative'] and r['unavailable_reason'] for r in preview['rows']))
        with self.assertRaises(ValueError):wd.fallback_start(self.root,parent['id'],ids,preview['stamp'],True)

    def test_timeout_retried_once_then_host_paused_other_host_continues(self):
        calls=[]
        def fetch(i,o):
            calls.append(i)
            if i!=self.china:raise wd.weather_fetch.WeatherNetworkError('timeout','climate.onebuilding.org','timeout')
            return self.good(i,o)
        with patch.object(wd.weather_fetch,'fetch',side_effect=fetch),patch.object(wd.weather_quality,'inspect',return_value={'status':'notes'}):
            job=wd.start(self.root,self.ids+[self.china],str(self.root/'epw'));self.wait()
        state=wd.status(self.root,job['id']);self.assertEqual(state['state'],'connection_blocked')
        self.assertEqual(calls,[self.ids[0],self.ids[0],self.ids[1],self.ids[1],self.china])
        self.assertEqual([i['state'] for i in state['items']],['failed','failed','pending','ready'])

    def test_hash_or_http_404_not_retried(self):
        error=wd.weather_fetch.network_error(urllib.error.HTTPError('https://example',404,'missing',{},None),'climate.onebuilding.org')
        self.assertFalse(error.retryable)
        with patch.object(wd.weather_fetch,'fetch',side_effect=ValueError('EPW checksum changed')) as fetch:
            job=wd.start(self.root,self.ids[:1],str(self.root/'epw'));self.wait()
        self.assertEqual(fetch.call_count,1)

    def test_old_batch_without_snapshot_still_resumes(self):
        parent=self.failed_parent(self.ids[:1]);del parent['kind'];del parent['items'][0]['source'];wd.save(self.root,parent)
        with patch.object(wd.weather_fetch,'fetch',side_effect=self.good),patch.object(wd.weather_quality,'inspect',return_value={'status':'notes'}):
            wd.resume(self.root,parent['id']);self.wait()
        self.assertEqual(wd.status(self.root,parent['id'])['state'],'completed')

    def test_register_records_alternative_source_and_rejects_changed_bytes(self):
        parent=self.failed_parent(self.ids[:1]);p=wd.fallback_preview(self.root,parent['id'])
        with patch.object(wd.weather_fetch,'fetch',side_effect=self.good),patch.object(wd.weather_quality,'inspect',return_value={'status':'notes'}):
            child=wd.fallback_start(self.root,parent['id'],self.ids[:1],p['stamp'],True);self.wait()
        item=wd.status(self.root,child['id'])['items'][0]
        with patch('weather_import.register',return_value={'registration':{'id':'fixture'},'reused':False}) as register:
            with self.assertRaises(ValueError):wd.register(self.root,child['id'],[item['id']],{},False)
            result=wd.register(self.root,child['id'],[item['id']],{},True)
            metadata=register.call_args.args[3]
            self.assertEqual(metadata['storage_mode'],'copy')
            wd.register(self.root,child['id'],[item['id']],{},True,storage_mode='reference')
            self.assertEqual(register.call_args.args[3]['storage_mode'],'reference')
            self.assertIn('JRC 备用',metadata['name']);self.assertIn('非原 TMYx',metadata['note'])
            self.assertNotIn('supersedes',metadata);self.assertEqual(result['items'][0]['status'],'registered')
        Path(item['result']['path']).write_bytes(b'changed')
        result=wd.register(self.root,child['id'],[item['id']],{},True)
        self.assertEqual(result['items'][0]['status'],'failed')


if __name__=='__main__':unittest.main()
