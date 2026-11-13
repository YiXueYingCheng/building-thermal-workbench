"""Disposable list projections; opening or adopting an item still verifies it."""
from pathlib import Path
from foundation import digest, read_json, loads, now
from navigation_cache import cached
import result_index, source_overview


def database_files(root, *names):
    return [root / ('data/' + name + suffix) for name in names for suffix in ('', '-wal')]


def catalog_key(catalog):
    return digest([catalog.get('snapshot_id'), catalog.get('records'), catalog.get('sites'), catalog.get('ordinary_buildings')])


def sources(catalog, store, root):
    root = Path(root)
    return cached(root, 'source-overview-v1', catalog_key(catalog),
        lambda: database_files(root, 'drafts.sqlite', 'components.sqlite') +
            [Path(__file__), Path(source_overview.__file__), root/'component_updates.py'],
        lambda: source_overview.build(catalog, store, root))


def results(catalog, store, root):
    root = Path(root)
    def watch():
        return database_files(root, 'drafts.sqlite', 'execution/queue.sqlite') + \
            [Path(__file__), Path(result_index.__file__), root/'research_input_notes.py'] + \
            list(root.glob('data/execution/reviews/review_*/record.json')) + \
            list(root.glob('data/execution/reviews/review_*/plan.json'))
    value = cached(root, 'result-index-v1', catalog_key(catalog), watch,
                   lambda: result_index.build(catalog, store, root))
    return dict(value, read_at=now())


def inputs(root):
    root = Path(root)
    def files():
        return list(root.glob('data/model-inputs/inputs_*/manifest.json'))
    def build():
        rows = []
        for file in files():
            # Only six listing fields are retained. All manifests are already
            # watched before/after; avoid request-local copies of huge payloads.
            # The detail and submission endpoints keep their full verification.
            p = loads(file.read_text('utf-8-sig'))
            rows.append({k:p[k] for k in ('id','created','record_name','revision','case_count','exact_matches')})
        return sorted(rows, key=lambda x:x['created'], reverse=True)
    return cached(root, 'input-list-v1', 'v1', lambda:files()+[Path(__file__)], build)
