import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from verify_manifest import main, verify


class ManifestVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = '示例 数据/参数.json'
        path = self.root / self.name
        path.parent.mkdir()
        path.write_bytes('热阻：0.3\r\n'.encode('utf-8'))
        self.line = hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + self.name + '\n'
        self.manifest = self.root / 'MANIFEST.sha256'
        self.manifest.write_text(self.line, encoding='utf-8')

    def test_unicode_space_and_bom(self):
        self.manifest.write_text(self.line, encoding='utf-8-sig')
        self.assertEqual(verify(self.root), (1, []))

    def test_changed_file_fails(self):
        (self.root / self.name).write_text('changed', encoding='utf-8')
        self.assertIn('内容不一致', verify(self.root)[1][0])

    def test_missing_file_fails(self):
        (self.root / self.name).unlink()
        self.assertIn('文件缺失', verify(self.root)[1][0])

    def test_invalid_line_is_not_silently_skipped(self):
        self.manifest.write_text(self.line + 'not a checksum\n', encoding='utf-8')
        self.assertIn('格式错误', verify(self.root)[1][0])

    def test_duplicate_file_fails(self):
        self.manifest.write_text(self.line * 2, encoding='utf-8')
        self.assertIn('重复', verify(self.root)[1][0])

    def test_paths_outside_package_are_rejected(self):
        for name in ['../outside.txt', '/outside.txt', 'C:/outside.txt', 'C:outside.txt', '..\\outside.txt']:
            with self.subTest(name=name):
                self.manifest.write_text('0' * 64 + '  ' + name + '\n', encoding='utf-8')
                checked, errors = verify(self.root)
                self.assertEqual(checked, 0)
                self.assertIn('路径无效', errors[0])

    def test_empty_manifest_fails(self):
        self.manifest.write_text('', encoding='utf-8')
        self.assertIn('没有可核对', verify(self.root)[1][0])

    def test_cli_exit_status(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root)]), 0)
            (self.root / self.name).write_bytes(b'changed')
            self.assertEqual(main(['--root', str(self.root)]), 1)


if __name__ == '__main__':
    unittest.main()
