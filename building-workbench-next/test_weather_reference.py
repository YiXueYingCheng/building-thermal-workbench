from pathlib import Path
import tempfile
import unittest

from foundation import sha
from model_adapter import VerifiedReader
from test_weather_quality import sample, encoded
from weather_import import inventory, merge, register, register_folder_item


class WeatherReferenceTests(unittest.TestCase):
    def test_two_workspaces_share_source_and_legacy_copy_is_independent(self):
        catalog = {'sites': {}, 'global_bundle': {'classes': []}}
        with tempfile.TemporaryDirectory() as folder:
            shared = Path(folder) / 'station.epw'
            raw = encoded(*sample())
            shared.write_bytes(raw)
            checksum = sha(shared)
            opts = dict(name='站点', reviewed=True)
            for name in ('first', 'second'):
                root = Path(folder) / name
                root.mkdir()
                register(root, str(shared), checksum, dict(opts,storage_mode='reference'), catalog)
                row, = inventory(root,catalog)
                self.assertEqual((row['storage_mode'],row['status'],Path(row['path'])),('reference','present',shared))
                self.assertFalse((root/'data/weather-files').exists())
                self.assertTrue(register_folder_item(root,str(shared),checksum,dict(opts,storage_mode='reference'),catalog)['reused'])
            ref_id = row['id']
            copied = register_folder_item(root,str(shared),checksum,opts,catalog)['registration']
            self.assertNotEqual(copied['id'],ref_id)
            sites = merge(catalog,root)['sites']
            self.assertEqual(VerifiedReader(catalog).check(sites[ref_id]['weather']),shared)
            self.assertEqual(inventory(root,catalog,ref_id)[0]['status'],'matches')
            shared.write_bytes(raw.replace(b'Fixture',b'Changed'))
            self.assertEqual(inventory(root,catalog,ref_id)[0]['status'],'mismatch')
            with self.assertRaises(ValueError):
                VerifiedReader(catalog).check(sites[ref_id]['weather'])
            shared.unlink()
            self.assertEqual(inventory(root,catalog,ref_id)[0]['status'],'missing')
            legacy, = inventory(root,catalog,copied['id'])
            self.assertEqual((legacy['storage_mode'],legacy['status']),('copy','matches'))
