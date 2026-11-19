import copy,json,tempfile,unittest
from pathlib import Path
from foundation import write_json,digest,sha
from example_controls import merge,REGISTRY
from capability_summary import guide,factors

class PublicControlsTests(unittest.TestCase):
    def test_empty_dynamic_placeholder_can_load_but_existing_source_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'controls.json'
            write_json(source,dict(kind='drawing26_controls_v1',policy={'cold_C':18},walls=[{'surface':'S1'}]),root)
            data={'source':{'path':str(source),'sha256':sha(source)}}
            write_json(root/REGISTRY,{'data':data,'sha256':digest(data)},root)
            c=dict(example_bundle={'id':'example'},dynamic_registry={'records':{},'walls':[],'policy':{},'source_refs':[]})
            loaded=merge(copy.deepcopy(c),root);self.assertEqual(loaded['dynamic_registry']['walls'],[{'surface':'S1'}])
            c['dynamic_registry']['walls']=[{'surface':'existing'}];before=copy.deepcopy(c)
            with self.assertRaisesRegex(ValueError,'未覆盖'):merge(c,root)
            self.assertEqual(c,before)

    def test_changed_control_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'controls.json';source.write_text('{}')
            data={'source':{'path':str(source),'sha256':sha(source)}}
            write_json(root/REGISTRY,{'data':data,'sha256':digest(data)},root);source.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'已变化'):merge({'example_bundle':True},root)

    def test_guide_separates_examples_from_unavailable_development_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            c={'catalog_kind':'standalone_v1'};d=guide('test',c,Path(tmp));content=json.dumps(d,ensure_ascii=False)
            self.assertEqual(d['kind'],'public_preparation');self.assertEqual(len(d['examples']),3)
            self.assertEqual([x['key'] for x in factors(c)],['building','materials','condition','scope'])
            for phrase in ('T05','14.18%','北京示例','维护与回归'):self.assertNotIn(phrase,content)
            example_text=json.dumps(d['examples'],ensure_ascii=False)
            self.assertNotIn('五层',example_text)
            research=next(x for x in d['material_support'] if x['id']=='development_solid_eca')
            self.assertIn('历史验证',research['status'])
            general=next(x for x in d['material_support'] if x['id']=='solid_variable_v1')
            self.assertIn('反馈',general['control'])
            self.assertIn('不推广为任意材料算法',research['control'])
            self.assertTrue(all(not x['records'] for x in d['examples']))

    def test_public_guide_uses_saved_dates_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_json(root/'data/examples/orientation-example.json',dict(period=[4,20,5,20],records={'orientation':{'id':'draft_example','revision':3}}),root)
            d=guide('test',{'catalog_kind':'standalone_v1'},root)
            self.assertIn('4 月 20 日—5 月 20 日',d['examples'][2]['period'])
            self.assertEqual(d['examples'][2]['records'][0]['revision'],3)

if __name__=='__main__':unittest.main()
