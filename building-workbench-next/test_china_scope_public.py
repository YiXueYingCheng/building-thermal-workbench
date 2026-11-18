import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import china_scope
from foundation import write_json

class PublicScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.catalog={'sites':{}}

    def test_empty_workspace_needs_no_development_file(self):
        result=china_scope.describe(self.catalog,self.root)
        self.assertEqual(len(result['regions']),34);self.assertEqual(result['available_regions'],0)
        self.assertEqual(result['kind'],'public_download_catalog');self.assertEqual(list(self.root.iterdir()),[])

    def test_registration_matches_bytes_not_names_or_predefined_ids(self):
        r=china_scope.describe(self.catalog,self.root)['regions'][0];c=r['candidates'][0]
        self.catalog['sites']['local_custom']={'id':'local_custom','name':'用户自命名','eligible':True,'source_kind':'imported_epw_v1','weather':{'sha256':c['sha256']},'climate':None}
        result=china_scope.describe(self.catalog,self.root)
        self.assertEqual(result['available_regions'],1)
        selected=result['regions'][0]['candidates'][0];self.assertEqual(selected['site_id'],'local_custom');self.assertIsNone(selected['climate'])
        self.catalog['sites']['local_custom']['weather']['sha256']='different'
        self.assertEqual(china_scope.describe(self.catalog,self.root)['available_regions'],0)

    def test_full_registered_set_can_preview_without_changing_scope(self):
        initial=china_scope.describe(self.catalog,self.root)
        for index,r in enumerate(initial['regions']):
            c=r['candidates'][0];ident='local_'+str(index)
            self.catalog['sites'][ident]={'id':ident,'eligible':True,'source_kind':'imported_epw_v1','weather':{'sha256':c['sha256']},'climate':None}
        data=china_scope.describe(self.catalog,self.root)
        selection={r['id']:r['candidates'][0]['site_id'] for r in data['regions']}
        current={'site_ids':['local_0'],'period':[1,1,1,31]};before=copy.deepcopy(current)
        def detail(i,catalog):return dict(status='matches',actual_sha256=catalog['sites'][i]['weather']['sha256'])
        with patch.object(china_scope,'weather_detail',side_effect=detail):
            preview=china_scope.preview(current,selection,data['checksum'],self.catalog,self.root)
        self.assertEqual(len(preview['scope']['site_ids']),34);self.assertEqual(preview['scope']['period'],current['period']);self.assertEqual(current,before)
        self.catalog['sites']['local_0']['weather']['sha256']='changed'
        with self.assertRaises(ValueError):china_scope.preview(current,selection,data['checksum'],self.catalog,self.root)

    def test_existing_legacy_preset_remains_strict(self):
        write_json(self.root/'data/china34-preset.json',{'data':{'regions':[]},'sha256':'bad'},self.root)
        with self.assertRaisesRegex(ValueError,'校验失败'):china_scope.describe(self.catalog,self.root)

if __name__=='__main__':unittest.main()
