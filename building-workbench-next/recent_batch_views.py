"""Bounded memory cache for browsing. Exports and decisions use batch_results.build directly."""
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import threading

import batch_results
from foundation import digest, now
from inspection_io import reading
import output_storage


def registry(root, ident):
    path = root / 'data/execution/queue.sqlite'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        batch = db.execute('SELECT checksum,plan FROM batches WHERE id=?', (ident,)).fetchone()
        if batch is None:
            raise ValueError('未找到批次。')
        jobs = [dict(row) for row in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx', (ident,))]
        from site_recalculation import links
        followups = links(db, ident) if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='site_recalculations'"
        ).fetchone() else []
    return digest([list(batch), jobs, followups]), jobs


def file_marks(paths):
    marks = {}
    for path in paths:
        try:
            s = os.stat(path)
            marks[path] = (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        except FileNotFoundError:
            marks[path] = None
        except OSError:
            # A missing optional failure log on an inaccessible drive must not
            # prevent the normal reader from showing the queue's failure reason.
            return None
    return marks


@dataclass
class Entry:
    registry_key: str
    files: dict
    bindings: tuple
    payload: bytes
    verified: str

    def matches(self, key):
        try:
            return (key == self.registry_key and self.files == file_marks(self.files)
                    and all(get() == expected for get, expected in self.bindings))
        except (OSError, sqlite3.Error, ValueError):
            return False


class RecentBatches:
    def __init__(self, root, limit=3, max_bytes=16*1024*1024):
        self.root = Path(root).resolve()
        self.limit = limit
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.catalog = None
        self.lock = threading.Lock()
        self.readers = [threading.Lock() for _ in range(16)]

    def get(self, ident, catalog, force=False):
        # Double opens of one batch share the first completed verification.
        with self.readers[hash(ident) % len(self.readers)]:
            key, jobs = registry(self.root, ident)
            with self.lock:
                if self.catalog is not catalog:
                    self.entries.clear()
                    self.catalog = catalog
                entry = self.entries.pop(ident, None)
            if entry and not force and entry.matches(key):
                self.remember(ident, catalog, entry)
                return dict(summary=json.loads(entry.payload), verified=entry.verified, reused=True)

            data = self.root / 'data'
            optional = [data / name for name in ('drafts.sqlite', 'drafts.sqlite-wal', 'output-storage.json', 'current.json')]
            cacheable = True
            with reading() as reads:
                for job in jobs:
                    if job['attempt']:
                        optional.append(data / 'storage-management/retention' / (job['attempt']+'.json'))
                    if job['status'] == 'failed':
                        try:
                            folder = output_storage.attempt_folder(self.root, job['attempt'])
                            optional.append(folder / 'run/eplusout.err')
                        except (ValueError, OSError):
                            cacheable = False
                before = file_marks(optional)
                summary = batch_results.build(ident, catalog, self.root)
                paths = set(reads.hashes).union(optional)
                for row in summary['results']:
                    paths.update(row.get('data_retention', {}).get('removed_artifacts', []))
                marks = file_marks(paths)
                bindings = tuple(reads.values.values())
            verified = now()
            if registry(self.root, ident)[0] != key:
                raise ValueError('读取期间批次登记或文件发生变化，请重新打开。')
            if before is not None and marks is not None:
                if before != file_marks(optional) or marks != file_marks(paths):
                    raise ValueError('读取期间来源文件发生变化，请重新打开。')
                cacheable = cacheable and all(marks[p] is None for row in summary['results']
                    for p in row.get('data_retention', {}).get('removed_artifacts', []))
            else:
                cacheable = False
            if cacheable:
                payload = json.dumps(summary, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
                self.remember(ident, catalog, Entry(key, marks, bindings, payload, verified))
            return dict(summary=summary, verified=verified, reused=False)

    def remember(self, ident, catalog, entry):
        with self.lock:
            if self.catalog is not catalog or len(entry.payload) > self.max_bytes:
                return
            self.entries[ident] = entry
            while len(self.entries) > self.limit or sum(len(e.payload) for e in self.entries.values()) > self.max_bytes:
                self.entries.popitem(last=False)
