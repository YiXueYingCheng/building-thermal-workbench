"""Recent verified views. Decisions and exports always use the original readers."""
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

import batch_results
import comparison_results
from foundation import digest, now
from inspection_io import reading
import output_storage
from summary_retention import notices


def registry(root, ids, comparison=None):
    path = root / 'data/execution/queue.sqlite'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        from site_recalculation import links
        from comparison_steps import selections
        state = []
        jobs = []
        children = set()
        for ident in dict.fromkeys(ids):
            followups = links(db, ident)
            state.append(followups)
            children.update(row['child'] for row in followups)
        for ident in sorted(set(ids) | children):
            batch = db.execute('SELECT checksum,plan FROM batches WHERE id=?', (ident,)).fetchone()
            if batch is None:
                raise ValueError('未找到批次。')
            state.append(list(batch))
            jobs.extend(dict(row) for row in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx', (ident,)))
        if comparison:
            state.append(selections(db, comparison))
    return digest([state,jobs]), jobs


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
    token: str

    def matches(self, key):
        try:
            return (key == self.registry_key and self.files == file_marks(self.files)
                    and all(get() == expected for get, expected, _ in self.bindings))
        except (OSError, sqlite3.Error, ValueError):
            return False


class RecentViews:
    watch_failure_logs = False

    def __init__(self, root, limit=3, max_bytes=16*1024*1024):
        self.root = Path(root).resolve()
        self.limit = limit
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.catalog = None
        self.lock = threading.Lock()
        self.readers = [threading.Lock() for _ in range(16)]

    def get(self, ident, catalog, force=False, known=None):
        # Concurrent opens share one completed verification.
        with self.readers[hash(ident) % len(self.readers)]:
            key, jobs = self.registry(ident)
            with self.lock:
                if self.catalog is not catalog:
                    self.entries.clear()
                    self.catalog = catalog
                entry = self.entries.pop(ident, None)
            if entry and not force and entry.matches(key):
                # A waiver or completed job may be registered while a result disk is being checked.
                key, jobs = self.registry(ident)
                if entry.registry_key == key:
                    self.remember(ident, catalog, entry)
                    response = dict(verified=entry.verified, reused=True, view_token=entry.token)
                    if known != entry.token:
                        response['summary'] = json.loads(entry.payload)
                    return response

            data = self.root / 'data'
            optional = [data / name for name in ('drafts.sqlite', 'drafts.sqlite-wal', 'output-storage.json',
                                                'current.json', 'coverage-results/index.json')]
            cacheable = True
            with reading() as reads:
                for job in jobs:
                    if job['attempt']:
                        optional.append(data / 'storage-management/retention' / (job['attempt']+'.json'))
                    if job['status'] == 'failed' and self.watch_failure_logs:
                        try:
                            folder = output_storage.attempt_folder(self.root, job['attempt'])
                            optional.extend(folder / name for name in ('run/eplusout.err', 'run/eplusout.end',
                                                                       'warmup.jsonl', 'launch.json'))
                        except (ValueError, OSError):
                            cacheable = False
                before = file_marks(optional)
                summary = self.build(ident, catalog)
                paths = set(reads.hashes).union(optional)
                removed = {p for record in notices(summary) for p in record['removed_artifacts']}
                paths.update(removed)
                marks = file_marks(paths)
                bindings = tuple(reads.values.values())
            verified = now()
            if self.registry(ident)[0] != key:
                raise ValueError('读取期间批次登记或文件发生变化，请重新打开。')
            if before is not None and marks is not None:
                if before != file_marks(optional) or marks != file_marks(paths):
                    raise ValueError('读取期间来源文件发生变化，请重新打开。')
                cacheable = cacheable and all(marks[p] is None for p in removed)
            else:
                cacheable = False
            token = None
            if cacheable:
                payload = json.dumps(summary, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
                if len(payload) <= self.max_bytes:
                    token = uuid.uuid4().hex
                    self.remember(ident, catalog, Entry(key, marks, bindings, payload, verified, token))
            return dict(summary=summary, verified=verified, reused=False, view_token=token)

    def remember(self, ident, catalog, entry):
        with self.lock:
            if self.catalog is not catalog or len(entry.payload) > self.max_bytes:
                return
            self.entries[ident] = entry
            while len(self.entries) > self.limit or sum(len(e.payload) for e in self.entries.values()) > self.max_bytes:
                self.entries.popitem(last=False)


class RecentBatches(RecentViews):
    watch_failure_logs = True

    def registry(self, ident):
        return registry(self.root, [ident])

    def build(self, ident, catalog):
        return batch_results.build(ident, catalog, self.root)


class RecentComparisons(RecentViews):
    def registry(self, scope):
        _, left, right, _ = scope
        batches = [s for s in (left, right) if s != 'historical' and not s.startswith('observed_')]
        return registry(self.root, batches, comparison=scope)

    def build(self, scope, catalog):
        return comparison_results.build(*scope, catalog, self.root, with_controls=True)
