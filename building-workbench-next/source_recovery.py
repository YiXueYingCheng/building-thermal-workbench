"""Recover missing, pinned source bytes without changing references or overwriting files."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid
from foundation import digest, now, read_json, sha, write_json
from source_updates import references

LOCK = threading.Lock()
MAX_BYTES = 512 * 1024 * 1024


def target_reference(record, catalog, target):
    if not isinstance(target, str) or not Path(target).is_absolute():
        raise ValueError('请选择当前方案核对记录中的缺失引用。')
    path = str(Path(target).resolve())
    rows = [r for r in references(record, catalog) if r['path'] == path]
    hashes = {r['expected_sha256'] for r in rows}
    if not rows or len(hashes) != 1 or not re.fullmatch('[0-9a-f]{64}', next(iter(hashes)) or ''):
        raise ValueError('引用缺少唯一的原内容校验值，不能恢复。')
    if any('计算引擎' in r['roles'] for r in rows):
        raise ValueError('计算引擎请通过原安装包修复，不在来源恢复中替换。')
    # lexists also rejects dangling links; never follow one to create another file.
    if os.path.lexists(target) or os.path.lexists(path):
        raise ValueError('原路径已有文件或链接；来源恢复不会覆盖，请重新核对来源。')
    if not Path(path).parent.is_dir():
        raise ValueError('原目录不可用。请先恢复磁盘或目录；本功能不批量创建目录或改写引用。')
    return rows[0]


def candidate_identity(candidate):
    if not isinstance(candidate, str) or not Path(candidate).is_absolute():
        raise ValueError('请选择本机原文件副本的完整路径。')
    p = Path(candidate).resolve(strict=True)
    a = p.stat()
    if not p.is_file() or not 0 < a.st_size <= MAX_BYTES:
        raise ValueError('请选择不超过 512 MiB 的非空文件；大文件需单独安排恢复。')
    checksum = sha(p)
    b = p.stat()
    if (a.st_size, a.st_mtime_ns, a.st_ino) != (b.st_size, b.st_mtime_ns, b.st_ino):
        raise ValueError('副本在读取期间改变，请重新检查。')
    return dict(path=str(p), sha256=checksum, bytes=b.st_size)


def preview(record, catalog, target, candidate):
    ref = target_reference(record, catalog, target)
    source = candidate_identity(candidate)
    if source['sha256'] != ref['expected_sha256']:
        raise ValueError('副本内容与原引用不一致，不能作为原文件恢复；内容更新需另行导入。')
    plan = dict(record_sha256=digest(record), record=dict(id=record['id'], revision=record['revision']),
                target=ref, candidate=source)
    return dict(**plan, plan_sha256=digest(plan), checked_at=now(),
                note='恢复共享原路径，引用同一文件的其他方案也会恢复访问。文件内容、方案版本和队列设置不变；本操作不提交或重试计算。')


def restore(root, record, catalog, target, candidate, expected_plan):
    # Single-file publication is atomic and fails if another writer created the target.
    if (Path(root) / '.recovery-copy.json').exists():
        raise ValueError('隔离恢复工作区仅供核对，不恢复外置来源。')
    with LOCK:
        plan = preview(record, catalog, target, candidate)
        if plan['plan_sha256'] != expected_plan:
            raise ValueError('方案或恢复预览已变化，请重新检查副本。')
        dest = Path(plan['target']['path'])
        if shutil.disk_usage(dest.parent).free < plan['candidate']['bytes'] + 50 * 1024 * 1024:
            raise ValueError('原目录磁盘空间不足，恢复后需至少留出 50 MiB。')
        ident = 'recovery_' + uuid.uuid4().hex
        receipt_path = Path(root) / 'data/source-recovery' / (ident + '.json')
        receipt = dict(id=ident, created=now(), status='prepared', plan=plan)
        write_json(receipt_path, receipt, root)
        temporary = None
        published = False
        try:
            fd, temporary = tempfile.mkstemp(prefix='.source-recovery-', suffix='.tmp', dir=dest.parent)
            copied = 0
            checksum = hashlib.sha256()
            with os.fdopen(fd, 'wb') as output, open(plan['candidate']['path'], 'rb') as source:
                while block := source.read(1024 * 1024):
                    copied += len(block)
                    if copied > plan['candidate']['bytes']:
                        raise ValueError('副本在恢复期间改变，请重新检查。')
                    output.write(block)
                    checksum.update(block)
                output.flush()
                os.fsync(output.fileno())
            if copied != plan['candidate']['bytes'] or checksum.hexdigest() != plan['target']['expected_sha256']:
                raise ValueError('实际复制的内容与原引用不一致，未恢复文件。')
            target_reference(record, catalog, target)
            # Same-directory hard link: no partial target, no replace, no cross-volume move.
            os.link(temporary, dest)
            published = True
            receipt.update(status='restored', completed=now(), restored_sha256=sha(dest))
            if receipt['restored_sha256'] != plan['target']['expected_sha256']:
                receipt.update(status='needs_review', error='恢复后的文件被其他程序改变，请重新核对。')
            write_json(receipt_path, receipt, root)
            return receipt
        except Exception as error:
            receipt.update(status='needs_review' if published else 'failed', completed=now(), error=str(error))
            try:
                write_json(receipt_path, receipt, root)
            except OSError:
                pass  # The durable prepared receipt still identifies the intended operation.
            if published:
                raise ValueError('文件已发布，但最终核对或回执未完成；请重新核对来源并查看恢复记录。') from error
            raise ValueError('未恢复文件：' + str(error)) from error
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def history(root, paths):
    """Show persisted intent even if a process stopped between publication and receipt update."""
    rows = []
    for p in (Path(root) / 'data/source-recovery').glob('recovery_*.json'):
        row = read_json(p)
        if row['plan']['target']['path'] in paths:
            rows.append(row)
    return sorted(rows, key=lambda r: (r['created'], r['id']), reverse=True)
