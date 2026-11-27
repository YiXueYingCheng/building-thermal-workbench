import copy, importlib.util, json, shutil, sqlite3, tempfile, unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch
import upgrade_workbench as u

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wb-upgrade-test-');self.root=Path(self.temp.name)
        self.old=self.root/'旧平台 with spaces';self.new=self.root/'新包';self.out=self.root/'外置结果';self.saved=self.root/'备份'
        for r,version in ((self.old,'0.72.2'),(self.new,'0.73.12')):
            (r/'building-workbench-next').mkdir(parents=True)
            (r/'building-workbench-next/VERSION').write_text(version)
            (r/'building-workbench-next/server.py').write_text('program '+version)
            (r/'requirements-lock.txt').write_text('same requirements')
            (r/'building-workbench-next/config.json').write_text('{"port":18799}')
            self.make_manifest(r)
        (self.old/'building-workbench-next/config.json').write_text('{"port":18800,"custom":"keep"}')
        data=self.old/'building-workbench-next/data';data.mkdir();(data/'research.json').write_text('old data')
        self.out.mkdir();(self.out/'result.txt').write_text('old result')
        (data/'output-storage.json').write_text(json.dumps({'roots':[{'path':str(self.out)}]}))
        (self.old/'.venv').mkdir();(self.old/'.venv/environment.txt').write_text('original environment')
        self.ps=patch.object(u,'processes',return_value=[]);self.ps.start()
        self.h=patch.object(u,'health',return_value=None);self.h.start()
    def tearDown(self):self.ps.stop();self.h.stop();self.temp.cleanup()
    def make_manifest(self,r):
        (r/'MANIFEST.sha256').write_text(''.join(u.sha(p)+'  '+p.relative_to(r).as_posix()+'\n' for p in sorted(r.rglob('*')) if p.is_file() and p.name!='MANIFEST.sha256'))
    def test_upgrade_and_restore_preserve_old_and_new_research(self):
        before=u.scan(self.old);results=u.scan(self.out)
        receipt=u.apply(self.new,self.old,self.saved);self.assertEqual(receipt['state'],'complete')
        self.assertEqual((self.old/'building-workbench-next/data/research.json').read_text(),'old data')
        self.assertIn('custom',(self.old/'building-workbench-next/config.json').read_text())
        self.assertEqual(u.scan(self.out),results)
        (self.old/'building-workbench-next/data/research.json').write_text('new research after upgrade')
        (self.old/'building-workbench-next/data/new-plan.json').write_text('new plan')
        (self.out/'result.txt').write_text('new result');(self.out/'added.txt').write_text('new extra')
        result=u.restore(self.saved);self.assertEqual(result['state'],'complete')
        self.assertEqual(u.scan(self.old),before);self.assertEqual(u.scan(self.out),results)
        retained=Path(result['locations'][0]['preserved']);ext=Path(result['locations'][1]['preserved'])
        self.assertEqual((retained/'building-workbench-next/data/research.json').read_text(),'new research after upgrade')
        self.assertTrue((retained/'building-workbench-next/data/new-plan.json').is_file())
        self.assertEqual((ext/'result.txt').read_text(),'new result');self.assertTrue((ext/'added.txt').is_file())
        self.assertEqual((self.old/'.venv/environment.txt').read_text(),'original environment')
    def test_modified_program_refused_without_changes(self):
        (self.old/'building-workbench-next/server.py').write_text('user changes');before=u.scan(self.old)
        with self.assertRaisesRegex(u.UpgradeError,'自行修改'):u.apply(self.new,self.old,self.saved)
        self.assertEqual(u.scan(self.old),before);self.assertFalse(self.saved.exists())

    def test_classic_path_boundary_counts_utf16_and_directory_limit(self):
        folder=PureWindowsPath('C:/b')
        prefix=u.path_units(folder)+1
        name='房'*(259-prefix-2)+'😀'
        u.check_backup_length(folder,[(name,259,'文件')])
        with self.assertRaisesRegex(u.UpgradeError,'260 .*259') as caught:
            u.check_backup_length(folder,[(name+'x',259,'文件')])
        self.assertIn(str(folder/(name+'x')),str(caught.exception))
        with self.assertRaisesRegex(u.UpgradeError,'249 .*248'):
            u.check_backup_length(folder,[('d'*(249-prefix),248,'目录')])

    def test_backup_length_includes_external_files_and_checks_before_copy(self):
        rel='wx-'+'r'*75+'.bin'
        (self.out/rel).write_bytes(b'preserve')
        too_long=self.saved/('b'*max(1,261-u.path_units(self.saved/'external-1'/rel)-1))
        with patch.object(u,'legacy_windows_paths',return_value=True):
            with self.assertRaisesRegex(u.UpgradeError,'备份文件路径过长') as caught:
                u.backup(self.old,too_long)
        self.assertIn(str(too_long.resolve()/'external-1'/rel),str(caught.exception))
        self.assertFalse(too_long.exists())

    def test_wizard_offers_short_persistent_location_and_reprompts(self):
        default=self.old.with_name(self.old.name+'-upgrade-backups')/'fixed'
        # Independent of the machine running the test, straddle the same file boundary.
        allowed=u.path_units(default)
        def check(path,limits):
            if u.path_units(path)>=allowed:
                raise u.UpgradeError('备份文件路径过长')
        with patch.object(u,'legacy_windows_paths',return_value=True),patch.object(u,'stamp',return_value='fixed'),patch.object(Path,'home',return_value=self.root),patch.object(u,'check_backup_length',side_effect=check):
            with patch('builtins.input',return_value=''):
                chosen=u.choose_backup(self.old,[self.out],self.new)
                self.assertEqual(chosen.parent,self.root/'wbup')
                self.assertFalse(chosen.exists())
            with patch('builtins.input',side_effect=[str(default),str(self.root/'short')]):
                self.assertEqual(u.choose_backup(self.old,[self.out],self.new),self.root/'short')
    def test_tampered_source_and_protected_paths_refused(self):
        (self.new/'building-workbench-next/server.py').write_text('tampered')
        with self.assertRaisesRegex(u.UpgradeError,'新包校验'):u.plan(self.new,self.old)
        self.make_manifest(self.new)
        (self.new/'building-workbench-next/data').mkdir();(self.new/'building-workbench-next/data/research.json').write_text('bad')
        self.make_manifest(self.new)
        with self.assertRaisesRegex(u.UpgradeError,'研究资料'):u.plan(self.new,self.old)
    def test_traversal_duplicate_and_nested_paths_refused(self):
        original=(self.new/'MANIFEST.sha256').read_text()
        for value in ('0'*64+'  ../escaped.txt\n',original+original.splitlines()[0]+'\n'):
            (self.new/'MANIFEST.sha256').write_text(value)
            with self.assertRaises(u.UpgradeError):u.plan(self.new,self.old)
        (self.new/'MANIFEST.sha256').write_text(original)
        with self.assertRaises(u.UpgradeError):u.plan(self.old,self.old)
        with self.assertRaises(u.UpgradeError):u.apply(self.new,self.old,self.old/'backup')
    def test_missing_external_and_pending_jobs_refused(self):
        self.out.rename(self.root/'not-connected')
        with self.assertRaisesRegex(u.UpgradeError,'接通'):u.apply(self.new,self.old,self.saved)
        (self.root/'not-connected').rename(self.out)
        db=self.old/'building-workbench-next/data/execution/queue.sqlite';db.parent.mkdir()
        with sqlite3.connect(db) as c:c.execute('CREATE TABLE jobs(status TEXT)');c.execute("INSERT INTO jobs VALUES('pending')")
        c.close()
        with self.assertRaisesRegex(u.UpgradeError,'计算'):u.apply(self.new,self.old,self.saved)
        self.assertFalse(self.saved.exists())
    def test_corrupt_backup_refused_before_restore_moves(self):
        u.apply(self.new,self.old,self.saved);before=u.scan(self.old)
        (self.saved/'workspace/building-workbench-next/data/research.json').write_text('corrupt')
        with self.assertRaisesRegex(u.UpgradeError,'校验不通过'):u.restore(self.saved)
        self.assertEqual(u.scan(self.old),before)
        self.assertFalse(list(self.root.glob('*before-restore*')))
    def test_mid_update_failure_has_recoverable_backup(self):
        before=u.scan(self.old);real=u.os.replace
        def interrupted(a,b):
            if Path(b)==self.old/'building-workbench-next/server.py':raise OSError('injected write failure')
            return real(a,b)
        with patch.object(u.os,'replace',side_effect=interrupted):
            with self.assertRaisesRegex(u.UpgradeError,'更新未完成'):u.apply(self.new,self.old,self.saved)
        self.assertEqual(u.read(self.saved/'UPGRADE.json')['state'],'incomplete')
        self.assertEqual(u.restore(self.saved)['state'],'complete');self.assertEqual(u.scan(self.old),before)
    def test_not_enough_space_refused_before_backup(self):
        disk=shutil.disk_usage(self.root)
        with patch.object(u.shutil,'disk_usage',return_value=type(disk)(disk.total,disk.used,0)):
            with self.assertRaisesRegex(u.UpgradeError,'空间不足'):u.apply(self.new,self.old,self.saved)
        self.assertFalse(self.saved.exists())
    def test_concurrent_mutations_refused(self):
        with u.exclusive(self.old):
            with self.assertRaisesRegex(u.UpgradeError,'已有升级'):u.apply(self.new,self.old,self.saved)
        self.assertFalse(self.saved.exists())

    def public_7311(self):
        app=self.old/'building-workbench-next';newapp=self.new/'building-workbench-next'
        (app/'VERSION').write_text('v0.73.11')
        for n in u.EXECUTORS:
            (app/n).write_text('old executor '+n);(newapp/n).write_text('new executor '+n)
        u.dump(self.new/'EXECUTOR_COMPATIBILITY.json',dict(from_code_hashes={n:u.sha(app/n) for n in u.EXECUTORS},to_code_hashes={n:u.sha(newapp/n) for n in u.EXECUTORS}))
        self.make_manifest(self.new)
        # The old release manifest must not include user's data.
        lines=(self.old/'MANIFEST.sha256').read_text().splitlines()
        lines=[line for line in lines if not line.endswith('building-workbench-next/VERSION')]
        lines += [u.sha(app/n)+'  building-workbench-next/'+n for n in ('VERSION',*u.EXECUTORS)]
        (self.old/'MANIFEST.sha256').write_text('\n'.join(lines)+'\n')
        return app.resolve(),newapp.resolve()

    def test_7311_exact_compatibility_backup_and_restore(self):
        app,newapp=self.public_7311();path=self.old/u.COMPATIBILITY;path.parent.mkdir(parents=True)
        existing={'upgrades':[{'id':'prior','from_code_hashes':{},'to_code_hashes':{}}]};u.dump(path,existing)
        before=u.scan(self.old);receipt=u.apply(self.new,self.old,self.saved)
        current=u.read(path);self.assertEqual(current['upgrades'][0],existing['upgrades'][0])
        entry=current['upgrades'][-1];self.assertEqual(set(entry['from_code_hashes']),{str(app/n) for n in u.EXECUTORS})
        self.assertEqual(entry['to_code_hashes'],{str(app/n):u.sha(app/n) for n in u.EXECUTORS})
        self.assertIn(u.COMPATIBILITY,receipt['updated'])
        self.assertEqual(u.restore(self.saved)['state'],'complete');self.assertEqual(u.scan(self.old),before)

    def test_7311_unknown_executor_refused_even_if_old_manifest_changed(self):
        app,_=self.public_7311();(app/'execution_results.py').write_text('unverified changes')
        lines=(self.old/'MANIFEST.sha256').read_text().splitlines()
        lines=[(u.sha(app/'execution_results.py')+'  building-workbench-next/execution_results.py') if line.endswith('building-workbench-next/execution_results.py') else line for line in lines]
        (self.old/'MANIFEST.sha256').write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(u.UpgradeError,'基线不一致'):u.plan(self.new,self.old)
        self.assertFalse(self.saved.exists())

    def test_stop_rejects_unverified_or_busy_worker(self):
        app=self.old/'building-workbench-next';marker=app/'data/execution/worker.json';marker.parent.mkdir(parents=True)
        row=dict(ProcessId=123,CommandLine=str(app/'execution_worker.py'))
        with patch.object(u,'processes',return_value=[row]):
            for state in ({},dict(active=1,root=str(app),pid=123),dict(active=0,root=str(app),pid=999)):
                u.dump(marker,state)
                with self.assertRaisesRegex(u.UpgradeError,'空闲状态'):u.stop(self.old)

    def test_transient_windows_status_lock_retries(self):
        real=u.os.replace;attempts=[]
        error=PermissionError('temporary sharing violation');error.winerror=32
        def flaky(a,b):
            if Path(b).name=='UPGRADE.json' and len(attempts)<2:
                attempts.append(str(b));raise error
            return real(a,b)
        with patch.object(u.os,'replace',side_effect=flaky),patch.object(u.time,'sleep'):
            result=u.apply(self.new,self.old,self.saved)
        self.assertEqual(result['state'],'complete');self.assertEqual(len(attempts),2)

    def test_receipt_failure_is_distinguished_and_original_error_visible(self):
        real=u.dump
        def fail_receipt(p,v):
            if Path(p).name=='UPGRADE_RECEIPT.json':raise PermissionError('persistent permission denial at receipt')
            return real(p,v)
        with patch.object(u,'dump',side_effect=fail_receipt):
            with self.assertRaisesRegex(u.UpgradeError,'persistent permission denial') as caught:u.apply(self.new,self.old,self.saved)
        self.assertIn('程序文件及保留资料已校验通过',str(caught.exception))
        self.assertEqual(u.read(self.saved/'UPGRADE.json')['state'],'status_pending')
        self.assertEqual(u.restore(self.saved)['state'],'complete')

    def test_persistent_status_failure_keeps_original_error(self):
        real=u.dump
        def fail_status(p,v):
            if Path(p).name=='UPGRADE.json' and v.get('updated'):raise PermissionError('status-file-denied')
            return real(p,v)
        with patch.object(u,'dump',side_effect=fail_status):
            with self.assertRaisesRegex(u.UpgradeError,'status-file-denied'):u.apply(self.new,self.old,self.saved)
        self.assertEqual(u.read(self.saved/'BACKUP.json')['state'],'verified')

if __name__=='__main__':unittest.main()
