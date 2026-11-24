"""Resolve frozen inputs in a verified workspace copy without modifying their identities."""
from functools import lru_cache
from pathlib import Path
import os, re
from foundation import digest, owned, read_json


@lru_cache(maxsize=8)
def _read(path, modified, size):
    box = read_json(path)
    data = box['data']
    if box['sha256'] != digest(data) or data['schema'] != 1:
        raise ValueError('历史文件位置清单校验失败。')
    return data


def locations(root):
    path = Path(root)/'data/history-locations/index.json'
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    return _read(path, stat.st_mtime_ns, stat.st_size)


def workspace_path(root, original):
    """Match only declared source workspaces, before accessing the old path."""
    path = Path(original)
    table = locations(root)
    relative = table.get('external_paths',{}).get(os.path.normcase(os.path.normpath(path)))
    if relative:
        return owned(Path(root)/relative, Path(root))
    for source in table.get('origins', []):
        if path.is_relative_to(source):
            rel = path.relative_to(source)
            if rel.parts and rel.parts[0] in ('data','assets','verification','runs') and '..' not in rel.parts:
                return owned(Path(root)/rel, root)
    return path


def input_path(root, original, checksum):
    table = locations(root)
    if not table:
        return Path(original)
    if not re.fullmatch('[a-f0-9]{64}', checksum or ''):
        raise ValueError('历史引用缺少有效的文件校验值。')
    entry = table['inputs'].get(checksum)
    if entry:
        if entry['kind']=='workspace_file':
            return owned(Path(root)/entry['path'],root)
        if entry['kind']=='local':
            return owned(Path(root)/entry['path'],Path(root)/'data/history-locations/files')
        if entry['kind']=='shared_epw' and Path(entry['path']).is_absolute() and Path(entry['path']).suffix.lower()=='.epw':
            return Path(entry['path'])
        raise ValueError('历史引用位置类型无效。')
    return workspace_path(root, original)


def engine_location(root, plan):
    """A relocated installation must match the entire pinned installation manifest."""
    executable, files = plan['engine'], plan['engine_files']
    if not locations(root):
        return executable, files
    from workspace_setup import registration
    runtime = registration(root)
    if not runtime or Path(runtime['executable']) == Path(executable):
        return executable, files

    def relative_set(entries, exe):
        base = Path(exe).parent
        if not base.is_absolute() or exe not in entries:
            raise ValueError('冻结引擎清单未绑定其执行程序。')
        relative = {}
        for name, checksum in entries.items():
            path = Path(name)
            if '..' in path.parts or not path.is_relative_to(base):
                raise ValueError('引擎文件位于登记安装目录之外。')
            key = path.relative_to(base)
            if key in relative:
                raise ValueError('引擎文件重复登记。')
            relative[key] = checksum
        return relative
    if (Path(executable).name != Path(runtime['executable']).name
            or relative_set(files, executable) != relative_set(runtime['engine_files'], runtime['executable'])):
        raise ValueError('本工作区的引擎文件与原算例登记的安装不一致。')
    return runtime['executable'], runtime['engine_files']
