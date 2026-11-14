"""Guard against false reuse, hidden input changes and stale reference evidence."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from foundation import digest, sha
from model_adapter import VerifiedReader
import reference_readiness as rr


def record():
    return dict(id='r',revision=1,name='研究',provenance=dict(adapter='ordinary_building_v1'),numerics=dict(step_minutes=5,engine_files={'engine':'abc'}),
        factors=dict(building=dict(id='b',name='建筑',usage_profile={'rooms':['original']},envelope_overrides={'wall':'kept'}),
            materials=dict(definitions=[{'id':'eca'}],applications=[{'id':'outside'}],definition_reference={'id':'lib'}),
            condition=dict(operation=dict(mode='controlled',settings='ordinary_usage',overrides={'room':{'available':[0,1]}}),controls=[{'id':'c'}],reference_runs=[]),
            scope=dict(site_ids=['site'],period=[1,1,12,31],aggregation={'weighting':'equal_sites'})))


class ReferenceReadiness(unittest.TestCase):
    def test_baseline_preserves_all_other_inputs_and_original(self):
        r=record();before=copy.deepcopy(r);b=rr.baseline(r)
        self.assertEqual(r,before)
        self.assertEqual(b['factors']['building'],r['factors']['building'])
        self.assertEqual(b['factors']['condition']['operation'],r['factors']['condition']['operation'])
        self.assertEqual(b['factors']['scope'],r['factors']['scope'])
        self.assertEqual(b['numerics'],r['numerics'])
        self.assertEqual(b['factors']['materials'],dict(definitions=[],applications=[]))
        self.assertEqual(b['factors']['condition']['controls'],[])

    def test_both_uses_explicit_controlled_branch(self):
        r=record();r['factors']['condition']['operation']['mode']='both'
        self.assertEqual(rr.baseline(r)['factors']['condition']['operation']['mode'],'controlled')

    def test_natural_and_legacy_need_explicit_definition(self):
        for field,value in [('mode','natural'),('adapter','legacy_plan_v011')]:
            r=record()
            if field=='mode':r['factors']['condition']['operation']['mode']=value
            else:r['provenance'][field]=value
            with self.assertRaises(ValueError):rr.baseline(r)

    def test_unknown_material_overrides_not_silently_removed(self):
        r=record();r['factors']['materials']['legacy_construction_overrides']={'x':'y'}
        self.assertEqual(rr.baseline(r)['factors']['materials']['legacy_construction_overrides'],{'x':'y'})

    def test_schedule_paths_match_by_verified_content(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=[Path(temp)/n for n in ('old.txt','new.txt')]
            a.write_text('0,1\n');b.write_bytes(a.read_bytes());h=sha(a)
            def model(p):return {'Schedule:File':{'x':{'file_name':str(p),'column_number':1}},'Wall':{'R':1}}
            self.assertEqual(rr.physical(model(a),{str(a):h},VerifiedReader()),rr.physical(model(b),{str(b):h},VerifiedReader()))
            b.write_text('1,1\n')
            with self.assertRaises(ValueError):rr.physical(model(b),{str(b):h},VerifiedReader())
            with self.assertRaises(ValueError):rr.physical(model(a),{},VerifiedReader())

    def test_output_names_ignored_physics_kept(self):
        a={'Wall':{'R':1},'Output:Variable':{'x':{'reporting_frequency':'Monthly'}}}
        b=copy.deepcopy(a);b['Output:Variable']['x']['reporting_frequency']='Daily'
        self.assertEqual(rr.physical(a,{},VerifiedReader()),rr.physical(b,{},VerifiedReader()))
        b['Wall']['R']=2
        self.assertNotEqual(rr.physical(a,{},VerifiedReader()),rr.physical(b,{},VerifiedReader()))

    def test_candidate_discovery_ignores_scheme_labels_but_not_material(self):
        r=rr.baseline(record());ref=copy.deepcopy(r);ref['name']='renamed';ref['revision']=99
        self.assertTrue(rr.candidate(r,ref,{'site_id':'site'},'site'))
        r['factors']['materials']['applications']=[{'id':'eca'}]
        self.assertFalse(rr.candidate(r,ref,{'site_id':'site'},'site'))

    def test_candidate_must_be_same_building_and_site(self):
        r=rr.baseline(record());ref=copy.deepcopy(r)
        self.assertFalse(rr.candidate(r,ref,{'site_id':'other'},'site'))
        r['factors']['building']['id']='other'
        self.assertFalse(rr.candidate(r,ref,{'site_id':'site'},'site'))

    def case(self):
        r=rr.baseline(record());m={'Wall':{'R':1}};p={'engine_files':r['numerics']['engine_files']}
        c=dict(mode='controlled',period=[1,1,12,31],step_minutes=5,dependencies={'weather':'h'},weather='weather',physical_digest=digest(m))
        return r,m,p,c

    def test_each_reference_dependency_blocks_reuse(self):
        r,m,p,c=self.case();ph=rr.physical(m,{},VerifiedReader())
        self.assertEqual(rr.match_case(r,c,p,m,ph,'h',VerifiedReader()),[])
        for key,value in [('mode','natural'),('period',[7,1,7,7]),('step_minutes',15),('dependencies',{'weather':'changed'})]:
            changed={**c,key:value};self.assertTrue(rr.match_case(r,changed,p,m,ph,'h',VerifiedReader()))
        self.assertTrue(rr.match_case(r,c,{'engine_files':{'engine':'new'}},m,ph,'h',VerifiedReader()))
        self.assertTrue(rr.match_case(r,c,p,m,digest({'Wall':{'R':2}}),'h',VerifiedReader()))

    def test_physical_digest_tamper_blocks(self):
        r,m,p,c=self.case();c['physical_digest']='bad'
        with self.assertRaises(ValueError):rr.match_case(r,c,p,m,'irrelevant','h',VerifiedReader())

    def test_equal_envelope_numeric_representation_only(self):
        r=record();r['factors']['building']['envelope_overrides']={'S':{'layers':[
            {'kind':'Material','values':{'density':2500,'solar_absorptance':.55}},
            {'kind':'Material','values':{'density':1800,'solar_absorptance':.55}}]}}
        old=copy.deepcopy(r);old['factors']['building']['envelope_overrides']['S']['layers'][0]['values']['density']=2500.0
        old['factors']['condition']['operation']['settings']='never_borrow_this'
        before=copy.deepcopy(r);equivalent=rr.numeric_representation_reference(r,old)
        self.assertIsNotNone(equivalent);self.assertEqual(r,before)
        self.assertEqual(equivalent,r)
        self.assertIs(type(equivalent['factors']['building']['envelope_overrides']['S']['layers'][0]['values']['density']),float)
        self.assertEqual(equivalent['factors']['condition'],r['factors']['condition'])
        self.assertIsNone(rr.numeric_representation_reference(r,r))
        for change in ('value','order','bool','missing'):
            bad=copy.deepcopy(old);layers=bad['factors']['building']['envelope_overrides']['S']['layers']
            if change=='value':layers[0]['values']['solar_absorptance']=.551
            elif change=='order':layers.reverse()
            elif change=='bool':layers[0]['values']['density']=True
            else:layers[0]['values'].pop('solar_absorptance')
            self.assertIsNone(rr.numeric_representation_reference(r,bad),change)

    def test_equivalent_recompiled_model_still_checks_every_input(self):
        r,m,p,c=self.case();exact=rr.physical(m,{},VerifiedReader());other='different_generated_names'
        self.assertEqual(rr.match_case(r,c,p,m,other,'h',VerifiedReader(),equivalent_physical=exact),[])
        self.assertTrue(rr.match_case(r,c,p,m,other,'changed',VerifiedReader(),equivalent_physical=exact))
        changed=copy.deepcopy(m);changed['Wall']['R']=2;c=dict(c,physical_digest=digest(changed))
        self.assertTrue(rr.match_case(r,c,p,changed,other,'h',VerifiedReader(),equivalent_physical=exact))
        c['physical_digest']='tampered'
        with self.assertRaises(ValueError):rr.match_case(r,c,p,changed,other,'h',VerifiedReader(),equivalent_physical=exact)

    def test_monthly_is_not_daily_and_unknown_never_ready(self):
        m={'Output:Variable':{'x':{'reporting_frequency':'Monthly'}}}
        self.assertEqual(rr.daily_coverage(m,'monthly_period_v1')['status'],'not_retained')
        for contract in ('daily_future','monthly_period_v1'):
            result=rr.daily_coverage({'Output:Variable':{'x':{'reporting_frequency':'Daily'}}},contract)
            self.assertFalse(result['usable']);self.assertEqual(result['status'],'unverified')

    def test_unaccepted_result_not_promoted(self):
        for status in ('pending','running','review','failed','cancelled'):
            r=rr.result_evidence({'identity':'x','status':status},{'identity':'x'},Path('.'))
            self.assertFalse(r['accepted'])

    def test_result_identity_hash_artifacts_and_review_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'result.json';c=dict(identity='i',site_id='s',mode='controlled',period=[1,1,12,31],step_minutes=5)
            result={**c,'status':'passed','days':365};p.write_text(json.dumps(result))
            job=dict(identity='i',status='passed',result=str(p),result_sha256=sha(p))
            with patch.object(rr,'verify_artifacts') as va,patch.object(rr,'reviewed') as rev:
                rev.return_value=None;self.assertTrue(rr.result_evidence(job,c,root)['accepted']);va.assert_called_once();rev.assert_called_once()
                va.side_effect=ValueError('artifact changed')
                with self.assertRaises(ValueError):rr.result_evidence(job,c,root)
                va.side_effect=None;rev.side_effect=ValueError('review changed')
                with self.assertRaises(ValueError):rr.result_evidence(job,c,root)
            p.write_text(json.dumps({**result,'identity':'wrong'}))
            with self.assertRaises(ValueError):rr.result_evidence(job,c,root)
            job['result_sha256']=sha(p)
            with self.assertRaises(ValueError):rr.result_evidence(job,c,root)

    def test_no_queue_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(rr.queue_snapshot(temp),([],{}));self.assertEqual(list(Path(temp).rglob('*')),[])

    def test_bound_calendar_is_not_recertified(self):
        r=record();ref=dict(id='calendar',calendar=['A']*365,calendar_sha256=digest(['A']*365))
        r['factors']['condition']['reference_runs']=[ref]
        c={'dynamic_registry':{'records':{'r':{'reference':copy.deepcopy(ref),'site_id':'site'}}}}
        b=rr.bindings(r,c)[0];self.assertTrue(b['registered_reference_match']);self.assertTrue(b['calendar_intact'])
        ref['calendar'][0]='B';b=rr.bindings(r,c)[0];self.assertFalse(b['calendar_intact']);self.assertFalse(b['registered_reference_match'])

    def test_missing_and_short_period_do_not_expand_or_compile(self):
        r=record();r['factors']['scope']['period']=[7,1,7,7];before=copy.deepcopy(r)
        with tempfile.TemporaryDirectory() as temp,patch.object(rr,'compile_case') as compile:
            out=rr.build(r,{'sites':{'site':{'name':'地点'}}},temp)
            compile.assert_not_called();self.assertFalse(out['can_generate_calendar']);self.assertEqual(out['rows'][0]['status'],'missing')
            self.assertTrue(any('局部时段' in x for x in out['issues']));self.assertEqual(r,before)


if __name__=='__main__':unittest.main()
