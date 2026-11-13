"""Isolated first-use and binding checks, including real local HTTP routes."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from foundation import ROOT, config, digest, read_json, write_json
import workspace_setup as setup
from manage import current

class WorkspaceSetupTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/'空 工作区';self.root.mkdir()
        cfg=config(ROOT);cfg.update(initialization='new_workspace',port=8779)
        write_json(self.root/'config.json',cfg,self.root)
        (self.root/'VERSION').write_text('test-workspace','utf-8')

    def test_empty_initialization_is_concurrent_and_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:setup.initialize(self.root),range(4)))
        self.assertEqual(results.count(True),1)
        before=read_json(self.root/'data/current.json');catalog=current(self.root)
        self.assertEqual(catalog['records'],{});self.assertEqual(catalog['sites'],{})
        self.assertIsNone(catalog['global_bundle']['historical'])
        self.assertFalse(setup.initialize(self.root))
        self.assertEqual(read_json(self.root/'data/current.json'),before)

    def test_corrupt_existing_catalog_is_never_overwritten(self):
        setup.initialize(self.root)
        pointer=read_json(self.root/'data/current.json')
        path=self.root/pointer['catalog'];path.write_text('{}','utf-8')
        with self.assertRaisesRegex(ValueError,'校验'):setup.initialize(self.root)
        self.assertEqual(path.read_text('utf-8'),'{}')

    def test_simultaneous_processes_create_only_one_catalog(self):
        def start(_):
            run=subprocess.run([sys.executable,'-B','-X','utf8','-c',
                'import sys;from workspace_setup import initialize;print(initialize(sys.argv[1]))',str(self.root)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
            return run.stdout.strip()
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(start,range(4)))
        self.assertEqual(results.count('True'),1);self.assertEqual(results.count('False'),3)
        self.assertEqual(current(self.root)['records'],{})

    def test_existing_mode_cannot_implicitly_initialize(self):
        cfg=config(self.root);cfg['initialization']='existing_catalog';write_json(self.root/'config.json',cfg,self.root)
        with self.assertRaisesRegex(ValueError,'已有来源'):setup.initialize(self.root)
        self.assertFalse((self.root/'data/current.json').exists())

    def test_preflight_reports_first_use_without_writing(self):
        from runtime_check import check
        result=check(self.root);self.assertTrue(result['startup_ready'])
        self.assertFalse((self.root/'data').exists())

    def fake_engine(self):
        folder=self.root/'安装 引擎';folder.mkdir()
        for name in ('energyplus.exe','Energy+.idd','Energy+.schema.epJSON','runtime.dll'):(folder/name).write_text('fixture '+name)
        return folder/'energyplus.exe'

    def test_engine_registration_rejects_version_and_detects_tampering(self):
        setup.initialize(self.root);exe=self.fake_engine()
        with patch.object(setup.subprocess,'run') as run:
            run.return_value.stdout='EnergyPlus, Version 0.0'
            with self.assertRaisesRegex(ValueError,'需要 EnergyPlus'):setup.register_engine(self.root,str(exe))
            self.assertIsNone(setup.registration(self.root))
            run.return_value.stdout='EnergyPlus, Version '+setup.policy(self.root).BUILD
            registered=setup.register_engine(self.root,str(exe))
        self.assertEqual(len(registered['engine_files']),4)
        catalog=current(self.root);numerics=setup.import_numerics(catalog)
        self.assertEqual(numerics['engine_files'],registered['engine_files'])
        record={'numerics':copy.deepcopy(numerics)};catalog['workspace_runtime']['engine_files']={'new': 'hash'}
        self.assertEqual(setup.engine_files(record,catalog),registered['engine_files'])
        value=read_json(self.root/'data/runtime-registration.json');value['data']['version']='changed'
        write_json(self.root/'data/runtime-registration.json',value,self.root)
        with self.assertRaisesRegex(ValueError,'校验'):current(self.root)

    def test_no_engine_does_not_borrow_private_research(self):
        setup.initialize(self.root)
        with self.assertRaisesRegex(ValueError,'先在工作区'):setup.import_numerics(current(self.root))

    def test_existing_record_keeps_frozen_engine(self):
        catalog={'records':{'global_fixed':{'numerics':{'engine_files':{'old':'old-hash'}}}}}
        self.assertEqual(setup.engine_files({'numerics':{}},catalog),{'old':'old-hash'})
        self.assertEqual(setup.engine_files({'numerics':{'engine_files':{'bound':'hash'}}},catalog),{'bound':'hash'})

    def test_http_empty_catalog_material_weather_and_restart(self):
        from server import make_server
        from test_weather_quality import sample,encoded
        server=make_server(self.root,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        address='http://127.0.0.1:'+str(server.server_port)
        token=None
        def call(route,body=None,authorized=True):
            headers={'Content-Type':'application/json'}
            if authorized and token:headers['X-Workbench-Token']=token
            request=Request(address+route,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            with urlopen(request,timeout=30) as response:return json.load(response)
        boot=call('/api/bootstrap');token=boot['token'];self.assertEqual(boot['records'],[])
        self.assertTrue(boot['workspace']['standalone'])
        self.assertEqual(call('/api/building-import-options')['choices'],[])
        self.assertEqual(call('/api/material-library/source-materials')['rows'],[])
        template=call('/api/material-library')['template']
        self.assertTrue(all(s['resistance_m2K_W'] is None for s in template['states']))
        template['name']='测试材料';template['states'][0]['resistance_m2K_W']=2
        saved=call('/api/components',{'kind':'material','name':'测试材料','content':template})
        self.assertEqual(saved['revision'],1)
        invalid=copy.deepcopy(template);invalid['states'][0]['resistance_m2K_W']=-1
        with self.assertRaises(HTTPError) as error:call('/api/components',{'kind':'material','name':'错误','content':invalid})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(HTTPError) as error:call('/api/workspace/engine',{'path':''},False)
        self.assertEqual(error.exception.code,403)
        weather=self.root/'test.epw';weather.write_bytes(encoded(*sample()))
        checked=call('/api/weather-import/inspect',{'path':str(weather)})
        self.assertTrue(checked['can_register'])
        registered=call('/api/weather-import/register',dict(path=str(weather),expected_sha256=checked['sha256'],metadata=dict(name='合成验证气象',climate='',climate_basis='',note='测试用',supersedes='',reviewed=True)))
        self.assertEqual(call('/api/bootstrap')['workspace']['weather_count'],1)
        self.assertEqual(len(call('/api/building-import-options')['weather']),1)
        setup.initialize(self.root)
        self.assertEqual(len(current(self.root)['sites']),1)
        self.assertEqual(len(call('/api/material-library')['versions']),1)

if __name__=='__main__':unittest.main()
