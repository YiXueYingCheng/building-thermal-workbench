"""Recognize inventory documents declared by a workspace transfer."""
from pathlib import Path
import re

from foundation import read_json, sha
from storage_management import safe_child


class HandoffInventory:
    def __init__(self, root):
        self.roots = set()
        self.entries = {}
        base = root / 'data/integration-sources'
        for manifest in base.glob('*/*.json'):
            info = read_json(safe_child(root, manifest))
            if not isinstance(info, dict):
                continue
            files = info.get('files')
            if isinstance(files, dict) and info.get('format') and info.get('source') and info.get('signed_at'):
                entries = files.items()
            elif isinstance(files, list) and info.get('origin') and info.get('snapshot_cut') and info.get('sealed'):
                entries = ((row.get('file'), row) for row in files if isinstance(row, dict))
            else:
                continue
            self.roots.add(manifest)
            for name, meta in entries:
                if not isinstance(name, str) or not isinstance(meta, dict):
                    continue
                parts = Path(name).parts
                checksum = meta.get('sha256', '')
                if (len(parts) >= 2 and parts[0] in ('inventory', 'manifest')
                        and '..' not in parts and name.endswith('.json')
                        and isinstance(checksum, str) and re.fullmatch('[0-9a-f]{64}', checksum)):
                    self.entries[manifest.parent / name] = checksum

    def contains(self, path):
        if path in self.roots:
            return True
        expected = self.entries.get(path)
        return bool(expected and sha(path) == expected)
