"""Inventory, consistent local backups and isolated recovery; never run simulations."""
from contextlib import closing
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from foundation import ROOT, read_json, write_json, sha, digest, owned, now
import output_storage

EXCLUDED_DIRS = {'backups','__pycache__','.git','node_modules'}
EPHEMERAL = {'data/service.json','data/session-token.json','data/server.stdout.log',
    'data/server.stderr.log','data/execution/worker.json','data/execution/worker.lock',
    'data/execution/worker.log','data/execution/disk-sampler.lock','data/output-storage.lock','data/.building-import.lock','.recovery-copy.json'}


def walk_files(root):
    root=Path(root);files=[];links=[]
    for base,dirs,names in os.walk(root,followlinks=False):
        for name in dirs[:]:
            p=Path(base)/name
            if p.is_symlink() or p.is_junction(): links.append(str(p));dirs.remove(name)
            elif name in EXCLUDED_DIRS: dirs.remove(name)
        for name in names:
            p=Path(base)/name
            if p.is_symlink(): links.append(str(p));continue
            if p.relative_to(root).as_posix() in EPHEMERAL or name.endswith(('-wal','-shm','-journal','.tmp')): continue
            files.append(p)
    return sorted(files),sorted(links)


def references(root):
    from manage import current
    refs={}
    def add(path,expected=None):
        if not isinstance(path,str) or not Path(path).is_absolute():return
        p=Path(path)
        # Keep the registered spelling (a junction may resolve to another volume).
        if p.is_relative_to(root):return
        row=refs.setdefault(str(p),dict(path=str(p),expected_sha256=[]))
        if isinstance(expected,str) and re.fullmatch('[a-f0-9]{64}',expected) and expected not in row['expected_sha256']:row['expected_sha256'].append(expected)
    def visit(value):
        if isinstance(value,dict):
            add(value.get('path'),value.get('sha256'))
            for k,v in value.items():
                add(k,v if isinstance(v,str) else None)
                if k in ('path','engine','weather','legacy_root','material_root','material_batch','python','source_root'):add(v)
                visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(current(root));visit(read_json(root/'config.json'))
    for pattern in ('data/model-inputs/*/manifest.json','data/execution/reviews/*/plan.json'):
        for p in root.glob(pattern):visit(read_json(p))
    # Registered component/plan content may contain dependencies not used by a bundle yet.
    for file in ('data/drafts.sqlite','data/components.sqlite','data/scope-library.sqlite'):
        p=root/file
        if not p.exists():continue
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                for row in db.execute('SELECT * FROM "'+table.replace('"','""')+'"'):
                    for v in row:
                        if isinstance(v,str) and v.startswith(('{','[')):
                            try:visit(json.loads(v))
                            except ValueError:pass
    visit(output_storage.config(root))
    queue=root/'data/execution/queue.sqlite'
    if queue.exists():
        with closing(sqlite3.connect(queue.as_uri()+'?mode=ro',uri=True)) as db:
            jobs=db.execute('SELECT result,result_sha256,attempt FROM jobs').fetchall()
        for path,checksum,attempt in jobs:
            if path:
                add(path,checksum)
                try:
                    actual=output_storage.checked_path(path,root)
                    if sha(actual)==checksum:visit(read_json(actual))
                except (OSError,ValueError,KeyError):pass
            if attempt:
                try:add(str(output_storage.attempt_folder(root,attempt)))
                except (OSError,ValueError):pass
    return sorted(refs.values(),key=lambda r:r['path'].casefold())


def inventory(root=ROOT,verify=False):
    root=Path(root).resolve();files,links=walk_files(root);groups={}
    for p in files:
        rel=p.relative_to(root);key=rel.parts[0] if len(rel.parts)>1 else '程序与根目录文件'
        g=groups.setdefault(key,dict(files=0,bytes=0));g['files']+=1;g['bytes']+=p.stat().st_size
    deps=references(root)
    for r in deps:
        p=Path(r['path']);r.update(status='unavailable',bytes=None,resolved_path=None)
        try:
            r['resolved_path']=str(p.resolve(strict=True));r['volume']=Path(r['resolved_path']).anchor
            if p.is_dir():r['status']='directory_unexpanded';continue
            before=p.stat();r['bytes']=before.st_size
            r['status']='available_unverified'
            if verify:
                h=sha(p);after=p.stat();r['observed_sha256']=h
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):r['status']='changed_during_read'
                elif not r['expected_sha256']:r['status']='observed_only'
                elif all(h==e for e in r['expected_sha256']):r['status']='matches'
                else:r['status']='historical_hash_differs'
        except OSError as e:r['error']=str(e)
    return dict(created=now(),root=str(root),hashes_checked=verify,groups=groups,
        local_files=len(files),local_bytes=sum(g['bytes'] for g in groups.values()),
        disk_free_bytes=shutil.disk_usage(root).free,links_not_followed=links,dependencies=deps,
        dependency_status={s:sum(r['status']==s for r in deps) for s in sorted({r['status'] for r in deps})},
        exclusions=sorted(EXCLUDED_DIRS|EPHEMERAL),
        coverage='备份范围为当前工作区内的程序、方案/版本库、来源快照、输入、清单、原始运行成果、导出、分析与核验证据。外置文件仅登记，不随本地备份复制；目录与链接不递归。')


def db_digest(path):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败：'+str(path))
        h=hashlib.sha256()
        for line in db.iterdump():h.update(line.encode('utf-8'));h.update(b'\n')
        tables={n:db.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0]
                for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        return dict(logical_sha256=h.hexdigest(),tables=tables)


def idle(root):
    from accdb_import import locked
    with locked(root):pass
    from calculation_budget import queue_snapshot
    state=queue_snapshot(root)
    running_batches={b['id'] for b in state['batches'] if b['mode']=='run'}
    if any(j['status']=='running' or (j['status']=='pending' and j['batch'] in running_batches) for j in state['jobs']):
        raise ValueError('请等运行任务结束并暂停排队项，再创建一致备份。')


def create_backup(root=ROOT):
    from result_storage import maintenance
    with maintenance(root):return _create_backup(root)

def _create_backup(root=ROOT):
    root=Path(root).resolve();idle(root)
    folder=owned(root/'backups',root);folder.mkdir(exist_ok=True)
    token='backup_'+uuid.uuid4().hex
    report=inventory(root,verify=True)
    if report['disk_free_bytes']<report['local_bytes']*2+2*2**30:raise ValueError('空间不足，未创建备份；需留出临时包和恢复核验余量。')
    files,_=walk_files(root);entries={};databases={}
    for p in files:
        rel=p.relative_to(root).as_posix()
        entries[rel]=dict(bytes=p.stat().st_size,sha256=sha(p))
        if p.suffix=='.sqlite':databases[rel]=db_digest(p)
    target=owned(folder/(token+'.zip'),root);partial=target.with_suffix('.incomplete')
    # Keep all staging inside the excluded backups directory; never recurse into it.
    with tempfile.TemporaryDirectory(prefix='staging-',dir=folder) as tmp:
        staged={}
        for rel,expected in databases.items():
            dest=Path(tmp)/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect((root/rel).as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(dest)) as dst:src.backup(dst)
            if db_digest(dest)!=expected:raise ValueError('数据库在备份期间变化，请重试。')
            staged[rel]=dest;entries[rel]=dict(bytes=dest.stat().st_size,sha256=sha(dest))
        manifest=dict(schema=1,id=token,created=now(),source_root=str(root),version=(root/'VERSION').read_text('utf-8').strip(),
            files=entries,databases=databases,inventory=report,external_files_included=False,
            restore_mode='isolated_read_only',absolute_paths_rebound=False)
        with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            for rel in entries:z.write(staged.get(rel,root/rel),'workspace/'+rel)
            z.writestr('backup-manifest.json',json.dumps(manifest,ensure_ascii=False,allow_nan=False))
        idle(root)
        after,_=walk_files(root)
        if {p.relative_to(root).as_posix() for p in after}!=set(entries):raise ValueError('备份期间文件清单变化，未发布完成包。')
        for rel,e in entries.items():
            if rel in databases:
                if db_digest(root/rel)!=databases[rel]:raise ValueError('备份期间数据库变化，未发布完成包。')
            elif sha(root/rel)!=e['sha256']:raise ValueError('备份期间文件变化：'+rel)
        verify_archive(partial)
        partial.rename(target)
    receipt=dict(id=token,created=now(),archive=str(target),sha256=sha(target),bytes=target.stat().st_size,
        source_bytes=sum(e['bytes'] for e in entries.values()),files=len(entries),databases=databases,
        version=manifest['version'],external_files_included=False,absolute_paths_rebound=False,
        dependency_status=report['dependency_status'],verified=True)
    write_json(folder/(token+'.json'),receipt,root)
    return receipt


def verify_archive(archive):
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(n.casefold() for n in names)):raise ValueError('备份存在重复路径。')
        if z.getinfo('backup-manifest.json').file_size>32*1024**2:raise ValueError('备份清单过大。')
        m=json.loads(z.read('backup-manifest.json'))
        if m.get('schema')!=1:raise ValueError('备份格式不受支持。')
        for rel in m['files']:
            p=PurePosixPath(rel)
            if p.is_absolute() or '..' in p.parts or '\\' in rel or ':' in rel or str(p)!=rel or rel=='.recovery-copy.json':raise ValueError('备份路径不安全。')
        expected={'workspace/'+rel for rel in m['files']}|{'backup-manifest.json'}
        if set(names)!=expected:raise ValueError('备份条目与清单不一致。')
        for rel,e in m['files'].items():
            name='workspace/'+rel
            if z.getinfo(name).file_size!=e['bytes']:raise ValueError('备份大小不一致。')
            with z.open(name) as stream:h=hashlib.file_digest(stream,'sha256').hexdigest()
            if h!=e['sha256']:raise ValueError('备份文件校验失败：'+rel)
    return m


def restore_drill(archive,checksum,root=ROOT):
    root=Path(root).resolve();archive=owned(archive,root/'backups')
    if sha(archive)!=checksum:raise ValueError('备份包整体校验不符。')
    m=verify_archive(archive)
    size=sum(e['bytes'] for e in m['files'].values())
    if shutil.disk_usage(root).free<size+2*2**30:raise ValueError('恢复副本空间不足。')
    target=owned(root/'backups'/('restore_'+uuid.uuid4().hex),root);target.mkdir(exist_ok=False)
    write_json(target/'.recovery-copy.json',dict(created=now(),source_root=m['source_root'],archive=str(archive),
        isolated=True,workers_disabled=True,absolute_paths_rebound=False),target)
    with zipfile.ZipFile(archive) as z:
        for rel,e in m['files'].items():
            p=owned(target/rel,target);p.parent.mkdir(parents=True,exist_ok=True)
            with z.open('workspace/'+rel) as src,p.open('xb') as dst:shutil.copyfileobj(src,dst)
            if sha(p)!=e['sha256']:raise ValueError('恢复文件校验失败：'+rel)
    databases={rel:db_digest(target/rel) for rel in m['databases']}
    if databases!=m['databases']:raise ValueError('恢复数据库逻辑内容不一致。')
    from manage import current
    catalog=current(target)
    result=dict(created=now(),archive=str(archive),archive_sha256=checksum,target=str(target),passed=True,
        restored_files=len(m['files']),restored_bytes=size,databases=databases,catalog_verified=True,
        source_records=len(catalog['records']),workers_started=0,external_files_included=False,
        absolute_paths_rebound=False,scope='工作区文件及数据库恢复核验；原路径之外运行和外置资料灾备仍需另行完成。')
    write_json(root/'backups'/(target.name+'.json'),result,root)
    return result


def status(root=ROOT):
    root=Path(root).resolve();report=inventory(root)
    receipts=[]
    for p in (root/'backups').glob('backup_*.json'):
        r=read_json(p);archive=owned(r['archive'],root/'backups')
        receipts.append(dict(**r,archive_available=archive.is_file()))
    report['backups']=sorted(receipts,key=lambda r:r['created'],reverse=True)
    report['drills']=[read_json(p) for p in (root/'backups').glob('restore_*.json')]
    return report


def check_backup(ident,root=ROOT):
    """Revalidate an existing registered archive; no extraction or disk writes."""
    if not re.fullmatch(r'backup_[a-f0-9]{32}',str(ident)):raise ValueError('备份编号不正确。')
    root=Path(root).resolve();folder=owned(root/'backups',root)
    receipt=owned(folder/(ident+'.json'),folder);archive=owned(folder/(ident+'.zip'),folder)
    result=dict(id=ident,checked_at=now(),passed=False,extracted_files=0,external_files_checked=False)
    try:
        receipt_hash=sha(receipt);r=read_json(receipt)
        if r['id']!=ident or owned(r['archive'],folder)!=archive:raise ValueError('登记回执与备份包不对应。')
        actual=sha(archive);result.update(archive=str(archive),expected_sha256=r['sha256'],observed_sha256=actual)
        if actual!=r['sha256']:raise ValueError('备份包整体 SHA-256 与登记回执不符。')
        m=verify_archive(archive)
        if m['id']!=ident or len(m['files'])!=r['files'] or sum(e['bytes'] for e in m['files'].values())!=r['source_bytes']:
            raise ValueError('备份内容清单与登记回执不符。')
        if sha(archive)!=actual or sha(receipt)!=receipt_hash:raise ValueError('校验期间备份或回执变化，请重试。')
        result.update(passed=True,verified_files=len(m['files']),source_bytes=r['source_bytes'],
            archive_bytes=archive.stat().st_size,version=m['version'],backup_created=m['created'],
            message='整体 SHA-256、成员清单、文件大小及逐文件哈希一致；未解压或复制文件。')
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as e:result['message']='校验未通过：'+str(e)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['inventory','backup','restore-drill']);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--verify',action='store_true');p.add_argument('--archive');p.add_argument('--sha256');a=p.parse_args()
    if a.command=='inventory':r=inventory(a.root,a.verify)
    elif a.command=='backup':r=create_backup(a.root)
    else:
        if not a.archive or not a.sha256:p.error('恢复演练需要 --archive 和 --sha256')
        r=restore_drill(a.archive,a.sha256,a.root)
    print(json.dumps(r,ensure_ascii=False,indent=2))
