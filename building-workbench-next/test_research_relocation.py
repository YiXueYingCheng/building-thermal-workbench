import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from execution_results import verify_artifacts
from foundation import digest, sha
from history_locations import engine_location, input_path
from starter_library import eca_preset
from material_catalog import import_definition, inventory
from component_library import Library


class ResearchRelocationTests(unittest.TestCase):
    def test_saved_material_carries_example_license_after_withdrawal(self):
        example = eca_preset()
        origin = dict(id=example['id'],name=example['name'],revision=example['revision'],
                      license=example['license'],sha256=example['source_sha256'])
        with tempfile.TemporaryDirectory() as temp:
            library = Library(Path(temp))
            first = library.save('material','自己的材料',example['content'], example_origin=origin)
            with patch('starter_library.eca_preset', side_effect=FileNotFoundError):
                second = library.save('material','新名称',example['content'],parent=first)
                self.assertEqual(library.version('material',second['id'],2)['example_origin'],origin)
                data = dict(schema='workbench-material/v1',source_revision=2,material=second['content'],example_origin=origin)
                self.assertEqual(import_definition(data), second['content'])
                with self.assertRaises(ValueError):
                    import_definition(dict(data,example_origin=dict(origin,sha256='broken')))

    def test_relocated_engine_requires_all_registered_files(self):
        with tempfile.TemporaryDirectory() as temp:
            old, new = (Path(temp)/d for d in ('old','new'))
            def files(folder):
                return {str(folder/name):hashvalue for name,hashvalue in [('energyplus.exe','a'*64),('Energy+.idd','b'*64)]}
            runtime = dict(executable=str(new/'energyplus.exe'),engine_files=files(new))
            plan = dict(engine=str(old/'energyplus.exe'),engine_files=files(old))
            with patch('history_locations.locations',return_value={'schema':1}), patch('workspace_setup.registration',return_value=runtime):
                self.assertEqual(engine_location(new,plan),(runtime['executable'],files(new)))
                del runtime['engine_files'][str(new/'Energy+.idd')]
                with self.assertRaises(ValueError):
                    engine_location(new,plan)

    def test_missing_or_invalid_eca_keeps_saved_material(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            definition = eca_preset()['content']
            saved = Library(root).save('material', definition['name'], definition)
            for problem in (FileNotFoundError('ECA.json'), ValueError('invalid ECA')):
                with self.subTest(problem=type(problem)), patch('starter_library.eca_preset', side_effect=problem):
                    catalog = inventory({'records': {}}, root)
                    self.assertIn(saved['sha256'], {row['sha256'] for row in catalog['versions']})
                    self.assertNotIn('builtin_eca', {row['id'] for row in catalog['presets']})
                    self.assertEqual(len(catalog['preset_issues']), 1)

    def test_relocated_result_uses_its_copy_and_checks_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'destination'
            source = Path(temp) / 'offline'
            output = root / 'runs' / 'case' / 'eplusout.err'
            output.parent.mkdir(parents=True)
            output.write_bytes(b'original')
            original = source / output.relative_to(root)
            raw = {'artifacts': {str(original): sha(output)}}
            registry = root / 'data/history-locations/index.json'
            registry.parent.mkdir(parents=True)
            table = {'schema': 1, 'origins': [str(source)], 'inputs': {}}
            registry.write_text(json.dumps({'data': table, 'sha256': digest(table)}), 'utf8')
            self.assertIs(verify_artifacts(raw, root), raw)
            output.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verify_artifacts(raw, root)
            with self.assertRaises(ValueError):
                input_path(root, original, 'not-a-checksum')
