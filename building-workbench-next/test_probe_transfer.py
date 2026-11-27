import copy
import unittest
from unittest.mock import patch

from probe_transfer import handle, merge
import test_version_notes as fixture


class ProbeTransferTests(unittest.TestCase):
    def setUp(self):
        self.target={'factors':{'building':{'id':'building'},'scope':{'period':[5,1,5,6]}},'execution':{}}
        self.req=dict(wall='wall A',fields=['inward','air'],layers=[],frequency='Timestep')
        self.p=dict(id='material',revision=2,name='layer',sha256='sha',layer=1)

    def test_merge_keeps_target_observations_and_shared_frequency(self):
        old=dict(frequency='Hourly',building_id='building',points=[
            dict(wall='wall A',zone='room',fields=['inside','air']),
            dict(wall='wall B',zone='other',fields=['outside'])])
        self.target['execution']['wall_observations']=copy.deepcopy(old)
        ex,info=merge({},self.target,self.req,'room')
        points=ex['wall_observations']['points']
        self.assertEqual(points[0]['fields'],['inside','air','inward'])
        self.assertEqual(points[1],old['points'][1])
        self.assertEqual(info['frequency'],'Hourly')
        self.assertEqual(self.target['execution']['wall_observations'],old)

    def test_match_unique_version_even_if_layer_moves(self):
        self.req.update(fields=[],layers=[{'layer':1,'sha256':'sha'}])
        with patch('probe_transfer.installed_layers',side_effect=[[self.p],[dict(self.p,layer=3)]]):
            ex,info=merge({},self.target,self.req,'room')
        self.assertEqual(ex,{'stack_response':[dict(wall='wall A',layer=3,sha256='sha')]})
        self.assertFalse(info['skipped'])

    def test_missing_different_and_ambiguous_layers_do_not_create_points(self):
        self.req.update(fields=[],layers=[dict(layer=1,sha256='sha')])
        for layers,reason in [([], '无此材料层'),([dict(self.p,sha256='other')],'材料版本不同'),
                              ([self.p,dict(self.p,layer=2)],'层位无法唯一对应')]:
            with self.subTest(reason=reason),patch('probe_transfer.installed_layers',side_effect=[[self.p],layers]):
                ex,info=merge({},self.target,self.req,'room')
                self.assertEqual(ex,{})
                self.assertIn(reason,info['skipped'][0]['reason'])


class BatchTransferTests(unittest.TestCase):
    def setUp(self):
        f = fixture.VersionNotesTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.store, self.catalog, self.root = f.store, f.catalog, f.root
        draft = f.draft()
        self.target = dict(id=draft['id'], revision=draft['revision'])
        self.source = dict(id=f.source['id'], revision=f.source['revision'])
        geometry = patch('probe_transfer.geometry', return_value=dict(supported=True, walls=[
            dict(id='west', zone='room A', exterior=True), dict(id='east', zone='room B', exterior=True)]))
        self.geometry = geometry.start()
        self.addCleanup(geometry.stop)
        self.request = dict(source=self.source, target=self.target, frequency='Hourly', walls=[
            dict(wall='west', fields=['inward','air'], layers=[]),
            dict(wall='east', fields=['outside'], layers=[])])

    def transfer(self, action='preview', **changes):
        return handle(self.root, self.catalog, self.store, dict(self.request, action=action, **changes))

    def test_two_walls_one_version_and_repeat_no_new_version(self):
        p = self.transfer()
        self.assertEqual(self.geometry.call_count, 2)
        self.assertEqual(len(self.store.history(self.target['id'])), 1)
        result = self.transfer('apply', signature=p['signature'])
        saved = result['saved']
        self.assertEqual(saved, dict(self.target, revision=2))
        self.assertEqual(self.transfer('apply', signature=p['signature'])['saved'], saved)
        unchanged = self.transfer(target=saved)
        self.assertFalse(unchanged['changed'])
        self.transfer('apply', target=saved, signature=unchanged['signature'])
        self.assertEqual(len(self.store.history(saved['id'])), 2)
        points = self.store.get(saved['id'])['execution']['wall_observations']['points']
        self.assertEqual([(p['wall'], p['fields']) for p in points], [('west',['inward','air']), ('east',['outside'])])

    def test_subset_invalid_wall_and_stale_save_do_not_write(self):
        p = self.transfer()
        with self.assertRaises(ValueError):
            self.transfer('apply', walls=self.request['walls'][:1], signature=p['signature'])
        invalid = [self.request['walls'][0], dict(self.request['walls'][1], wall='missing')]
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.transfer('apply', walls=invalid, signature=p['signature'])
        self.assertEqual(len(self.store.history(self.target['id'])), 1)
        self.store.save(self.target['id'], 1, dict(name='new name'))
        with self.assertRaises(ValueError):
            self.transfer('apply', signature=p['signature'])
        self.assertEqual(len(self.store.history(self.target['id'])), 2)

    def test_batch_to_frozen_target_creates_one_copy(self):
        args = dict(source=self.target, target=self.source)
        p = self.transfer(**args)
        self.assertTrue(p['clone'])
        first = self.transfer('apply', signature=p['signature'], **args)['saved']
        self.assertEqual(first['revision'], 1)
        self.assertNotEqual(first['id'], self.source['id'])
        self.assertEqual(self.transfer('apply', signature=p['signature'], **args)['saved'], first)
        self.assertEqual(len(self.store.get(first['id'])['execution']['wall_observations']['points']), 2)
