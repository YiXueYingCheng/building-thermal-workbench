"""Build and verify a source release from the Git-tracked publication files."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def build(root, output):
    metadata = json.loads((root / 'RELEASE.json').read_text(encoding='utf-8'))
    version = metadata['version']
    stem = f'building-workbench-v{version}'
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').strip('\0').split('\0')
    payload = {}
    for name in names:
        if name == 'MANIFEST.sha256':
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Expected a regular publication file: {name}')
        payload[name] = path.read_bytes()
    # Runtime configuration is intentionally ignored by Git; ship a clean copy only.
    payload['building-workbench-next/config.json'] = payload['building-workbench-next/config.example.json']
    digest = lambda data: hashlib.sha256(data).hexdigest()
    payload['MANIFEST.sha256'] = ''.join(digest(data) + '  ' + name + '\n' for name, data in sorted(payload.items())).encode('utf-8')
    day = datetime.date.fromisoformat(metadata['prepared_on'])
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (stem + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(stem + '/' + name, (day.year, day.month, day.day, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for line in payload['MANIFEST.sha256'].decode('utf-8').splitlines():
            expected, name = line.split('  ', 1)
            assert digest(z.read(stem + '/' + name)) == expected, name
    checksum = digest(archive.read_bytes())
    archive.with_suffix('.zip.sha256').write_bytes((checksum + '  ' + archive.name + '\n').encode('ascii'))
    return dict(version=version, archive=archive.name, files=len(payload), sha256=checksum)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.output), indent=2))
