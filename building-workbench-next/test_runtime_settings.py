"""Release-path regressions using isolated folders and explicit runtime probes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foundation import ROOT, config, digest, write_json
import launch
import runtime_check
import runtime_settings as settings


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / '含 空格的副本' / 'app'
        self.root.mkdir(parents=True)
        self.value = json.loads((ROOT / 'config.example.json').read_text('utf-8'))
        self.value.update(initialization='existing_catalog', import_reference_tables=None)
        self.save()

    def save(self):
        write_json(self.root / 'config.json', self.value, self.root)

    def test_paths_follow_configuration_directory_after_relocation(self):
        actual = config(self.root)
        self.assertEqual(Path(actual['conversion_root']), self.root.parent / 'dependencies/dest_compatibility')
        moved = self.root.parent / '另一个目录' / 'app'
        moved.mkdir(parents=True)
        shutil.copy2(self.root / 'config.json', moved / 'config.json')
        self.assertEqual(Path(config(moved)['conversion_root']), moved.parent / 'dependencies/dest_compatibility')

    def test_explicit_absolute_config_survives_nested_validation_copy(self):
        resolved = config(self.root)
        stage = self.root / 'data/import/input-validation'
        write_json(stage / 'config.json', resolved, stage)
        staged = config(stage)
        for key in ('legacy_root', 'material_root', 'conversion_root', 'python', 'plot_python'):
            self.assertEqual(staged[key], resolved[key])

    def test_previous_configuration_preserves_paths_and_initialization(self):
        legacy = self.root.parent / 'old/outputs/run/building-workbench'
        self.value = dict(legacy_root=str(legacy), material_root=str(self.root.parent / 'material'),
                          material_batch=str(self.root.parent / 'batch.json'), python=sys.executable, port=8766)
        self.save()
        result = config(self.root)
        self.assertEqual(result['initialization'], 'legacy_import')
        self.assertEqual(Path(result['conversion_root']), legacy.parents[1] / 'building-energy/dest_compatibility')
        self.assertEqual(Path(result['import_reference_tables']), legacy.parents[2] / 'work/dest-model-only/tables/TEST.accdb')
        self.assertEqual(result['python'], str(Path(sys.executable).resolve()))

    def test_converter_interface_survives_resolved_config(self):
        portable = config(self.root)
        self.assertEqual(portable['converter_interface'], 'portable')
        old = dict(legacy_root=str(self.root.parent / 'legacy'), python=sys.executable)
        resolved = settings.normalize_config(old, self.root)
        self.assertEqual(resolved['converter_interface'], 'legacy')
        self.assertEqual(settings.normalize_config(resolved, self.root)['converter_interface'], 'legacy')

    def test_explicit_optional_nulls_do_not_guess_external_data(self):
        result = config(self.root)
        for key in ('material_batch', 'import_reference_tables', 'public_material_catalog'):
            self.assertIsNone(result[key])

    def test_invalid_port_and_overlapping_roots_are_rejected(self):
        for port in (True, 0, 65536, '8776'):
            self.value['port'] = port
            self.save()
            with self.assertRaisesRegex(ValueError, 'port'):
                config(self.root)
        self.value['port'] = 8776
        self.value['legacy_root'] = '.'
        self.save()
        with self.assertRaisesRegex(ValueError, '相互独立'):
            config(self.root)

    def test_missing_python_dependency_has_actionable_message(self):
        with self.assertRaisesRegex(ValueError, 'requirements.txt'):
            settings.python_environment(sys.executable, ('workbench_missing_dependency_fixture',))

    def test_plotting_uses_configured_interpreter(self):
        self.value['plot_python'] = './plot environment/python.exe'
        self.save()
        with patch.object(settings, 'python_environment') as probe:
            selected = settings.plotting_python(self.root)
        self.assertEqual(selected, self.root / 'plot environment/python.exe')
        probe.assert_called_once_with(str(selected), ('numpy', 'matplotlib'))

    def test_origin_probes_the_workspace_module_dir_and_reports_dll_errors(self):
        self.value['plot_python']=sys.executable
        self.save()
        modules=self.root/'data/origin-python'
        modules.mkdir(parents=True)
        (modules/'originpro.py').write_text("import OriginExt",encoding='utf8')
        (modules/'OriginExt.py').write_text("raise ImportError('incompatible test DLL')",encoding='utf8')
        with self.assertRaisesRegex(ValueError,'incompatible test DLL') as error:
            settings.origin_environment(self.root)
        self.assertIn(str(Path(sys.executable).resolve()),str(error.exception))
        self.assertIn('plot_python',str(error.exception))
        (modules/'OriginExt.py').write_text("__version__='test'",encoding='utf8')
        result=settings.origin_environment(self.root)
        self.assertEqual(Path(result['executable']),Path(sys.executable))
        self.assertEqual(set(result['modules']),{'numpy','OriginExt','originpro'})

    def test_import_converter_uses_explicit_bundled_path(self):
        from accdb_import import backend
        self.assertEqual(backend(self.root), self.root.parent / 'dependencies/dest_compatibility')

    def test_font_config_survives_subprocess_argument_boundaries(self):
        self.value['plot_font'] = 'fonts/中文 字体.ttf'
        self.save()
        font = self.root / self.value['plot_font']
        font.parent.mkdir()
        font.write_bytes(b'path selection fixture')
        self.assertEqual(settings.figure_font(self.root), font)

    def test_dependency_check_is_read_only_and_reports_missing_catalog(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))
        report = runtime_check.check(self.root)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))
        self.assertEqual(before, after)
        self.assertFalse(report['startup_ready'])
        missing = {r['name'] for r in report['checks'] if not r['available']}
        self.assertIn('建筑与材料来源目录', missing)
        self.assertIn('门窗与材料参考表', missing)

    def test_optional_import_gaps_do_not_block_an_existing_catalog(self):
        catalog = dict(records={}, sites={}, global_bundle={})
        write_json(self.root / 'data/catalog.json', catalog, self.root)
        write_json(self.root / 'data/current.json', dict(catalog='data/catalog.json', sha256=digest(catalog)), self.root)
        report = runtime_check.check(self.root)
        self.assertTrue(report['startup_ready'])
        self.assertTrue(any(not r['available'] for r in report['checks'] if r['feature'] == 'database_import'))

    def test_launch_of_uninitialized_release_never_imports_history_or_spawns(self):
        with patch.object(launch, 'ROOT', self.root), patch.object(launch, 'config', lambda: config(self.root)), \
             patch.object(launch, 'health', return_value=None), patch('manage.import_sources') as migrate, \
             patch('runtime_settings.python_environment'), patch.object(launch.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, '尚未建立'):
                launch.launch(False)
        migrate.assert_not_called()
        spawn.assert_not_called()
        self.assertFalse((self.root / 'data').exists())

    def test_cli_check_and_normal_launch_return_clear_failure_without_data(self):
        # Probe the isolated copy even when the user's normal service is online.
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.value['port'] = listener.getsockname()[1]
        self.save()
        # Actual entry points in a copy also exercise imports and CWD independence.
        for name in ('launch.py', 'foundation.py', 'inspection_io.py', 'runtime_settings.py', 'runtime_check.py'):
            shutil.copy2(ROOT / name, self.root / name)
        for arguments in (['--check', '--json'], ['--no-browser']):
            run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(self.root / 'launch.py'), *arguments],
                                 cwd=self.root.parent, capture_output=True, text=True, encoding='utf-8', timeout=40)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertNotIn('Traceback', run.stderr)
            if '--json' in arguments:
                self.assertFalse(json.loads(run.stdout)['startup_ready'])
            else:
                self.assertIn('尚未建立', run.stderr)
        self.assertFalse((self.root / 'data').exists())


if __name__ == '__main__':
    unittest.main()
