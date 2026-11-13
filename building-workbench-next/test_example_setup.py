"""Standalone example sources must not invent historical results or overwrite records."""
import copy
from pathlib import Path
import tempfile
import unittest
from foundation import digest,write_json
from example_setup import merge,REGISTRY
from comparison_results import choices

class ExampleSourcesTests(unittest.TestCase):
    def test_fresh_template_has_no_historical_choice(self):
        record={'id':'global_fixed'}
        catalog={'records':{'global_fixed':record},'global_bundle':{'historical':None}}
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(choices(record,catalog,Path(folder)),[])

    def test_existing_historical_choice_is_preserved(self):
        record={'id':'global_fixed'}
        catalog={'records':{'global_fixed':record},'global_bundle':{'historical':{'source':'existing result'}}}
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(choices(record,catalog,Path(folder))[0]['id'],'historical')

    def test_corrupt_example_registration_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            write_json(root/REGISTRY,{'data':{'kind':'drawing26_public_example_v1'},'sha256':'invalid'},root)
            with self.assertRaises(ValueError):merge({},root)

    def test_existing_source_is_never_overwritten(self):
        data={'kind':'drawing26_public_example_v1','records':{'global_fixed':{'name':'sample'}},'global_bundle':{}}
        catalog={'catalog_kind':'standalone_v1','records':{'global_fixed':{'name':'existing'}},'global_bundle':{'jobs':{}}}
        original=copy.deepcopy(catalog)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);write_json(root/REGISTRY,{'data':data,'sha256':digest(data)},root)
            with self.assertRaises(ValueError):merge(catalog,root)
        self.assertEqual(catalog,original)

if __name__=='__main__':unittest.main()
