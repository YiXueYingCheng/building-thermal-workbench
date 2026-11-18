import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import execution_inputs as e

class HistoricalResultsTests(unittest.TestCase):
    def test_read_only_compatibility_never_allows_submission(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'data/execution/runtime-compatibility.json';p.parent.mkdir(parents=True)
            old={'old.py':'a'};new={'new.py':'b'}
            p.write_text(json.dumps({'upgrades':[dict(id='fixture',historical_only=True,from_code_hashes=old,to_code_hashes=new)]}))
            with patch.object(e,'code_hashes',return_value=new):
                self.assertEqual(e.execution_revision(old,root,historical=True)['id'],'fixture')
                with self.assertRaisesRegex(ValueError,'重新准备'):e.execution_revision(old,root)
                with self.assertRaises(ValueError):e.execution_revision({'old.py':'changed'},root,historical=True)
                self.assertEqual(e.execution_revision(new,root)['kind'],'frozen')
            with patch.object(e,'code_hashes',return_value={'new.py':'changed'}):
                with self.assertRaises(ValueError):e.execution_revision(old,root,historical=True)

if __name__=='__main__':unittest.main()
