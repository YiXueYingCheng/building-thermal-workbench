import sqlite3
import unittest
from pathlib import Path

from foundation import canonical, digest, sha, write_json
from execution_queue import Queue
import plan_deletion as plans
from reading_collections import Readings
from research_sets import Sets
import study_relations as relations
import test_version_notes as fixture


class StudyRelationsTests(unittest.TestCase):
    def setUp(self):
        f = fixture.VersionNotesTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.root, self.catalog, self.store = f.root, f.catalog, f.store
        self.draft = f.draft()
        self.ident = self.draft['id']
        self.pin = dict(id=self.ident, revision=1)
        self.other = dict(id=f.source['id'], revision=f.source['revision'])
        Readings(self.catalog, self.root)
        self.queue = Queue(self.root)

    def remove(self, kind, ident):
        p = relations.preview(self.root, kind, ident)
        return relations.remove(self.root, kind, ident, p['sha256'], True)

    def plan(self, cascade=True):
        return plans.preview(self.root, self.catalog, self.ident, 'version', 1, cleanup=cascade)['inspection']

    def test_missing_example_retains_comparison_and_owns_its_snapshots(self):
        from record_store import Store
        rel=self.store.add_comparison('参考比较',self.other,self.pin,'total')
        expected=self.store.get(self.other['id'],self.other['revision'])
        with self.store.connect() as db:
            db.execute("DELETE FROM comparison_inputs WHERE comparison_id=? AND side='left'",(rel['id'],))
        Store(self.catalog,self.root)
        del self.catalog['records'][self.other['id']]
        reopened=Store(self.catalog,self.root)
        self.assertEqual(reopened.comparison_input(rel,'left')[0],expected)
        self.assertEqual(reopened.study_record(self.other),expected)
        with self.assertRaises(KeyError):
            reopened.get(self.other['id'])
        copy=reopened.add_comparison('同版本另一指标',self.other,self.pin,'heating')
        self.remove('comparison',rel['id'])
        self.assertEqual(reopened.comparison_input(copy,'left')[0],expected)
        self.remove('comparison',copy['id'])
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM comparison_inputs').fetchone()[0],0)

    def test_unlink_comparison_and_dissolve_group(self):
        c = self.store.add_comparison('选中的比较', self.other, self.pin, 'total')['id']
        untouched = self.store.add_comparison('保留的比较', self.other, self.pin, 'heating')['id']
        grp = 'reading_'+'1'*32
        with self.store.connect() as db:
            db.execute('INSERT INTO reading_groups VALUES(?,?,?)', (grp, '集', '*'))
            db.execute('INSERT INTO theme_versions VALUES(?,?,?)', (grp, 1, canonical(dict(members=[self.pin]))))
            for ident in (c, untouched):
                db.execute('INSERT INTO reading_links VALUES(?,?,?)', (grp, ident, canonical(dict(comparison=ident,sides=[self.pin]))))
        with self.queue.db() as db:
            for ident in (c, untouched):
                db.execute('INSERT INTO comparison_step_choices VALUES(?,?,?,?,?,?)', (ident, 'a', 'b', 'm', 'city', '{}'))
        p = relations.preview(self.root, 'comparison', c)
        with self.store.connect() as db:
            db.execute('INSERT INTO reading_hidden VALUES(?,?,?)', (grp, c, 'token'))
        with self.assertRaisesRegex(ValueError,'变化'):
            relations.remove(self.root,'comparison',c,p['sha256'],True)
        with self.assertRaises(ValueError):
            relations.remove(self.root,'comparison',c,p['sha256'],False)
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail BEFORE DELETE ON comparisons BEGIN SELECT RAISE(ABORT,'rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.remove('comparison', c)
        with self.queue.db() as db:
            self.assertEqual(2, db.execute('SELECT count(*) FROM comparison_step_choices').fetchone()[0])
        with self.store.connect() as db:
            db.execute('DROP TRIGGER fail')
        self.remove('comparison', c)
        with self.queue.db() as db:
            self.assertEqual([untouched], [r[0] for r in db.execute('SELECT comparison FROM comparison_step_choices')])
        with self.store.connect() as db:
            self.assertEqual(0, db.execute('SELECT count(*) FROM reading_hidden').fetchone()[0])
            self.assertEqual(1, db.execute('SELECT count(*) FROM reading_links').fetchone()[0])
        self.assertEqual({r['action']['id'] for r in self.plan()['references']}, {untouched,grp})
        self.remove('reading', grp)
        self.assertEqual({r['action']['id'] for r in self.plan()['references']}, {untouched})
        self.remove('comparison', untouched)
        self.assertFalse(self.plan()['blocked'])
        self.assertEqual(self.draft,self.store.get(self.ident))

    def test_removing_one_membership_releases_only_its_plan_reference(self):
        ident = self.store.add_comparison('工况对照', self.other, self.pin, 'total')['id']
        groups = ['reading_' + digit * 32 for digit in ('1', '2')]
        with self.store.connect() as db:
            for group in groups:
                db.execute('INSERT INTO reading_groups VALUES(?,?,?)', (group, group, '*'))
                db.execute('INSERT INTO reading_links VALUES(?,?,?)',
                           (group, ident, canonical(dict(comparison=ident, sides=[self.pin]))))
        readings = Readings(self.catalog, self.root)
        membership = dict(group=groups[0], entry=ident)
        removed = readings.visibility(membership, False)
        for cascade in (False, True):
            actions = {r['action']['id'] for r in self.plan(cascade)['references'] if r['action']}
            self.assertEqual(actions, {ident, groups[1]})
        self.assertEqual(relations.preview(self.root, 'comparison', ident)['collection_names'], [groups[1]])
        readings.visibility(dict(**membership, token=removed['token']), True)
        actions = {r['action']['id'] for r in self.plan()['references'] if r['action']}
        self.assertEqual(actions, {ident, *groups})

    def test_set_preserves_existing_export_revision_and_member(self):
        group = 'set_'+'2'*32
        values = []
        with self.store.connect() as db:
            for revision in (1,2):
                v = dict(id=group,name='组',revision=revision,members={'baseline':dict(record=self.pin)})
                v['sha256']=digest(v)
                values.append(v)
                db.execute('INSERT INTO research_sets VALUES(?,?,?,?)',(group,revision,canonical(v),'now'))
            db.execute('INSERT INTO research_set_members VALUES(?,?,?)',(self.ident,group,'baseline'))
        receipt = self.root/'data/research-set-exports'/('set_export_'+'2'*32)/'receipt.json'
        write_json(receipt,dict(set_id=group,revision=1),self.root)
        group_store=Sets(self.catalog,self.root)
        checks=sha(receipt)
        self.assertEqual([1],self.remove('set',group)['archived_revisions'])
        self.assertEqual(values[0],group_store.evidence_version(group,1))
        with self.assertRaises(ValueError):
            group_store.get(group,1)
        self.assertEqual(self.draft,self.store.get(self.ident))
        self.assertFalse(self.plan()['blocked'])
        self.assertEqual(checks,sha(receipt))

    def test_design_versions_are_removed_together(self):
        from comparison_designs import ensure
        ident = 'design_'+'3'*32
        with self.store.connect() as db:
            ensure(db)
            for revision in (1,2):
                db.execute('INSERT INTO comparison_designs VALUES(?,?,?)',
                           (ident,revision,canonical(dict(name='设计',base=self.pin,revision=revision))))
        self.assertEqual([ident], [r['id'] for r in relations.listing(self.root) if r['kind']=='design'])
        for cascade in (True,False):
            refs=self.plan(cascade)['references']
            self.assertTrue(refs)
            self.assertTrue(all(r['action']['id']==ident and r['label']=='设计' for r in refs))
        self.assertEqual(2,self.remove('design',ident)['counts'][0]['count'])
        self.assertFalse(self.plan()['blocked'])
        self.assertEqual(self.draft,self.store.get(self.ident))

    def test_declared_inventories_and_active_lookalikes(self):
        folder = self.root/'data/integration-sources'/'new-origin'
        report = folder/'inventory'/'example.json'
        write_json(report,self.pin,self.root)
        write_json(folder/'snapshot-manifest.json',dict(format='handoff/v1',source='new',signed_at='now',
                   files={'inventory/example.json':dict(sha256=sha(report))}),self.root)
        for cascade in (True,False):
            report_hash = sha(report)
            self.assertFalse(self.plan(cascade)['blocked'])
            self.assertEqual(report,Path(self.plan(cascade)['historical_mentions'][0]['source']))
            real = self.root/'data/uses/example.json'
            write_json(real,self.pin,self.root)
            self.assertTrue(self.plan(cascade)['blocked'])
            real.unlink()
            write_json(report,dict(self.pin,changed=True),self.root)
            self.assertTrue(self.plan(cascade)['blocked'])
            write_json(report,self.pin,self.root)
            self.assertEqual(report_hash,sha(report))
