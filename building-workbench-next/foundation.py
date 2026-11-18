"""Small, independent I/O layer. No legacy modules are imported."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parent

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()

def reject_constant(value):
    raise ValueError('JSON 不允许非有限数值：' + value)

def loads(text):
    return json.loads(text, parse_constant=reject_constant)

def read_json(path):
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('JSON 文件超出读取上限。')
    from inspection_io import current
    scope=current();loader=lambda:loads(path.read_text(encoding='utf-8-sig'))
    return scope.json(path,loader) if scope else loader()

def sha(path):
    from inspection_io import current
    if current():return current().sha(path)
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def owned(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('写入目标必须位于重构工作区内。')
    return path

def replace_with_retry(source, target):
    """Windows readers may briefly deny delete-sharing; retain atomic publication."""
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if os.name != 'nt' or getattr(error,'winerror',None) not in (5,32,33) or attempt==5:
                raise
            time.sleep(.05 * 2**attempt)

def write_json(path, value, root=ROOT):
    path = owned(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    # A long destination name must not be repeated in its atomic temporary name.
    # mkstemp reserves the short random name exclusively in the same directory.
    handle, temporary = tempfile.mkstemp(prefix='t-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()

def config(root=ROOT):
    root = Path(root).resolve()
    from runtime_settings import normalize_config
    value = normalize_config(read_json(root / 'config.json'), root)
    old = Path(value['legacy_root'])
    if root == old or root.is_relative_to(old) or old.is_relative_to(root):
        raise ValueError('新旧平台目录必须相互独立。')
    return value

class Sources:
    """Hash each source once; expected historical hashes remain separate."""
    def __init__(self):
        self.observed = {}

    def ref(self, path, expected=None):
        path = Path(path).resolve()
        key = str(path)
        if key not in self.observed:
            try:
                before = path.stat()
                checksum = sha(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('读取期间来源发生变化。')
                self.observed[key] = dict(path=key, sha256=checksum, bytes=after.st_size, status='verified')
            except (OSError, ValueError) as error:
                self.observed[key] = dict(path=key, sha256=None, bytes=None, status='unavailable', error=str(error))
        result = dict(self.observed[key])
        if expected:
            result['expected_sha256'] = expected
            if result['sha256'] and result['sha256'] != expected:
                result['status'] = 'changed'
        return result

    def json(self, path, expected=None):
        ref = self.ref(path, expected)
        if ref['status'] != 'verified':
            raise ValueError('来源无法按记录核实：' + str(path))
        result = read_json(path)
        if sha(path) != ref['sha256']:
            raise ValueError('读取期间来源发生变化：' + str(path))
        return result, ref

    def check_unchanged(self):
        changed = []
        for path, row in self.observed.items():
            if row['sha256']:
                try:
                    if sha(path) != row['sha256']:
                        changed.append(path)
                except OSError:
                    changed.append(path)
        return dict(checked=sum(bool(r['sha256']) for r in self.observed.values()), changed=changed, passed=not changed)
