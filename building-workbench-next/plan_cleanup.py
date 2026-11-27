"""Collect a saved study's exclusive artifacts. Only confirmed, recomputed paths are moved."""
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from collections import OrderedDict
from threading import Lock
import hashlib

import history_locations
import output_storage
import plan_deletion as pd
from foundation import canonical, digest, loads, read_json, write_json
from result_storage import documents
from storage_management import blockers, queue_metadata, safe_child

HEX = r'[a-f0-9]{32}'
ROOTS = {
    '模型输入': ('data/model-inputs', 'inputs_'+HEX),
    '提交前核对': ('data/execution/reviews', 'review_'+HEX),
    '输入准备任务': ('data/input-preparations', 'job_'+HEX+r'\.json'),
    '计算结果': ('runs', HEX),
    '结果复核': ('verification/result-reviews', 'review_'+HEX),
    '已采用的复核结果': ('data/execution/scientific-reviews', 'review_'+HEX),
    '磁盘采样': ('data/execution/disk-observations', 'attempt_'+HEX+r'\.json'),
}
NOTE = '清理列出的保存版本、当前备注、计算批次和专属文件。恢复这些数据需要已有备份。'
KEPT = ['建筑、材料、作息、气象和日历库', '备份、交接清单和操作记录']

def paths(root, relative):
    p = safe_child(root, root / relative)
    for prefix, rule in ROOTS.values():
        parts = Path(relative).parts
        base = Path(prefix).parts
        if parts[:len(base)] == base and len(parts)>len(base) and re.fullmatch(rule, parts[len(base)]):
            return p
    raise ValueError('清理路径超出专属资料目录：'+str(relative))

class Candidates:
    """Only exact contents validated against the same search can skip parsing."""
    negatives = OrderedDict()
    lock = Lock()

    def __init__(self, tokens):
        self.tokens = tuple(sorted(tokens))
        self.needles = [t.encode('ascii').lower() for t in self.tokens]
        self.scope = digest(self.tokens)

    def row_matches(self, row):
        for value in (*row.keys(), *row.values()):
            if isinstance(value, str):
                raw = value.lower()
                if '\\u00' in raw or any(t in raw for t in self.tokens):
                    return True
        return False

    def read(self, path, st):
        if st.st_size > pd.MAX_METADATA:
            raise ValueError('资料超过核对上限')
        with path.open('rb') as stream:
            raw = stream.read(st.st_size + 1)
        if len(raw) != st.st_size:
            raise ValueError('核对期间文件发生变化')
        key = self.scope, hashlib.sha256(raw).digest()
        with self.lock:
            if key in self.negatives:
                self.negatives.move_to_end(key)
                return None
        value = loads(raw.decode('utf-8-sig'))
        if b'\\u00' in raw:
            raw = canonical(value).encode('utf-8')
        lower = raw.lower()
        if any(n in lower for n in self.needles):
            return value
        with self.lock:
            self.negatives[key] = None
            if len(self.negatives) > 32768:
                self.negatives.popitem(last=False)
        return None

def inspect(root,catalog,ident,scope,revision,active,fresh=False):
    root=Path(root).resolve()
    target=pd.target_snapshot(root,catalog,ident,scope,revision)
    reasons=target['blocked']+blockers(root,active)
    revisions={v['revision'] for v in target['versions']}
    groups={};tokens=set();retained=[];files=[];refs=[];history=[];issues=[]
    def add(kind,name):
        prefix,rule=ROOTS[kind]
        if not re.fullmatch(rule,name):raise ValueError('资料标识异常：'+name)
        rel=(Path(prefix)/name).as_posix()
        groups[rel]=kind
        tokens.add(name.removesuffix('.json'))
    def selected(row):
        return row.get('record_id')==ident and row.get('revision') in revisions
    for kind,manifest in [('模型输入','manifest.json'),('提交前核对','plan.json'),('输入准备任务',None)]:
        prefix,rule=ROOTS[kind];base=safe_child(root,root/prefix)
        for entry in base.iterdir() if base.exists() else ():
            if not re.fullmatch(rule,entry.name):continue
            path=safe_child(root,entry/manifest if manifest else entry)
            if path.is_file() and selected(read_json(path)):add(kind,entry.name)
    batches,attempts,_,errors=queue_metadata(root);issues+=errors
    bids=sorted(b for b,row in batches.items() if selected(row))
    for b in bids:
        if not re.fullmatch('batch_'+HEX,b):raise ValueError('批次编号异常')
    tokens.update(bids)
    for launch in (root/'runs').glob('*/launch.json'):
        if re.fullmatch(HEX,launch.parent.name):
            batch=read_json(safe_child(root,launch)).get('batch')
            if batch in bids:attempts.setdefault('attempt_'+launch.parent.name,[]).append(dict(id=batch))
    for attempt,owners in attempts.items():
        members={x.get('id') for x in owners}
        if not members.intersection(bids):continue
        if members.difference(bids):
            reasons.append('其他批次共用算例 '+attempt+'：'+', '.join(str(i) for i in members.difference(bids)));continue
        folder=output_storage.attempt_folder(root,attempt)
        if folder.parent!=root/'runs':
            retained.append(dict(path=str(folder),reason='外置结果原件'));continue
        if folder.exists():
            launch=folder/'launch.json'
            if not launch.exists() or read_json(safe_child(root,launch)).get('batch') not in bids:
                reasons.append('无法确认计算目录所属批次：'+str(folder));continue
            add('计算结果',folder.name)
        observation=root/ROOTS['磁盘采样'][0]/(attempt+'.json')
        if observation.exists():add('磁盘采样',observation.name)
        tokens.add(attempt)
    for job in (root/'verification/result-reviews').glob('review_*/job.json'):
        row=read_json(safe_child(root,job))
        if row.get('batch') in bids:
            add('结果复核',job.parent.name)
            result=root/ROOTS['已采用的复核结果'][0]/job.parent.name
            if result.exists():add('已采用的复核结果',job.parent.name)
    # The migration registry may also serve unrelated frozen models by content hash.
    registry=history_locations.locations(root)
    pinned={root/row['path'] for row in registry.get('inputs',{}).values() if row['kind']=='workspace_file'}
    pinned.update(root/rel for rel in registry.get('external_paths',{}).values())
    group_rows=[]
    for rel,kind in sorted(groups.items()):
        directory=paths(root,rel);count=total=0
        stack=[directory]
        while stack:
            p=safe_child(root,stack.pop())
            if p.is_dir():
                stack.extend(p.iterdir());continue
            if not p.is_file():raise ValueError('无法核对文件：'+str(p))
            st=p.stat();relative=p.relative_to(root).as_posix()
            if p in pinned or not pinned.isdisjoint(p.parents):
                retained.append(dict(path=relative,reason='历史文件位置登记'));continue
            files.append([relative,st.st_size,st.st_mtime_ns,st.st_ino]);count+=1
            if st.st_nlink==1:total+=st.st_size
        group_rows.append(dict(kind=kind,path=rel,files=count,bytes=total))
    # Some exports and frozen comparisons identify the input or result only by its checksum.
    with closing(pd.connect_read(pd.dbpath(root))) as db:
        for row in db.execute('SELECT revision,payload FROM versions WHERE id=?',(ident,)):
            if row['revision'] in revisions:
                checksum=loads(row['payload']).get('record_sha256')
                if checksum and re.fullmatch('[a-f0-9]{64}',checksum):tokens.add(checksum)
    if bids:
        with closing(pd.connect_read(root/'data/execution/queue.sqlite')) as db:
            for bid in bids:
                for row in db.execute('SELECT * FROM jobs WHERE batch=?',(bid,)):
                    checksum=dict(row).get('result_sha256')
                    if checksum and re.fullmatch('[a-f0-9]{64}',checksum):tokens.add(checksum)
    owned=[root/rel for rel in groups]
    scanner=Candidates(tokens|{ident})
    related_ids=sorted(tokens)
    cache_ids=[];prep_keys=[];queue_rows=[];queue=root/'data/execution/queue.sqlite';drafts=root/'data/drafts.sqlite'
    inventory=pd.HandoffInventory(root)
    for source,value in documents(root,issues,True,scanner):
        path=Path(source);table=value.get('_storage_table','') if isinstance(value,dict) else ''
        if any(path.is_relative_to(directory) for directory in owned):continue
        if source==str(drafts)+'#'+table:
            if table in pd.AUDIT_TABLES or table=='version_notes':continue
            if table=='versions' and value.get('id')==ident and value.get('revision') in revisions:continue
        if source==str(root/'data/execution/preparations.sqlite')+'#preparations':
            if value['bundle_id'] in tokens and value['review'] in tokens:
                prep_keys.append(value['key']);queue_rows.append(digest(value));continue
        if source==str(queue)+'#'+table:
            internal=(table=='batches' and value['id'] in bids
                      or table in ('jobs','events','batch_storage','attempt_storage') and value.get('batch') in bids
                      or table=='site_recalculations' and value['parent'] in bids and value['child'] in bids)
            if internal:
                queue_rows.append(digest(value));continue
            if table=='cache':
                result=history_locations.workspace_path(root,value['path'])
                if any(result.is_relative_to(root/group) for group,kind in groups.items()
                       if kind in ('计算结果','已采用的复核结果')):
                    cache_ids.append(value['identity']);queue_rows.append(digest(value));continue
        if inventory.contains(path) or path==root/'data/history-locations/index.json':
            history.append(source);continue
        encoded=canonical(value).lower()
        hits=pd.match_reference(value,ident,None if scope=='record' else revisions) if ident in encoded else []
        related=next((key for key in related_ids if key in encoded),None)
        if related:hits.append('关联计算资料 '+related)
        if hits:
            name=value.get('id') or value.get('batch') or value.get('name') if isinstance(value,dict) else ''
            action=pd.action_for(table,value) if source in (str(drafts)+'#'+table,str(queue)+'#'+table) else None
            payload=value.get('payload') if isinstance(value,dict) else None
            label=payload.get('name') if isinstance(payload,dict) else None
            refs.append(dict(action=action,kind=action['label'] if action else '外部引用',label=str(label or name or path.name),
                             owner_key=(action['kind']+'/'+action['id']) if action else source,owner=action['id'] if action else str(name or path.name),source=source,relations=hits,
                             **pd.reference_display(root,source,value)))
    pd.name_relations(root,refs)
    if refs:reasons.append('其他资料仍引用所选版本或计算记录，详见关系树。')
    if issues:reasons.append('仍有资料未完成核对。')
    return dict(target=target,blocked=sorted(set(reasons)),issues=sorted(set(issues)),references=sorted(refs,key=canonical),
                historical_mentions=[dict(source=s,relations=['迁入时登记的资料']) for s in sorted(set(history))],kept=KEPT,impact=NOTE,scope_note='检查本工作区、登记的结果位置及引用。独立导出的文件留在原处。',
                cleanup=dict(groups=group_rows,batches=bids,cache_ids=sorted(cache_ids),prep_keys=sorted(prep_keys),files=sorted(files),
                             queue_digest=digest(sorted(queue_rows)),retained=sorted(retained,key=lambda x:x['path']),historical=sorted(set(history)),
                             bytes=sum(g['bytes'] for g in group_rows)))

def attach_queue(db,root):
    schemas=['main']
    for name,filename in [('queue','queue.sqlite'),('prep','preparations.sqlite')]:
        path=safe_child(root,root/'data/execution'/filename)
        if not path.exists():continue
        if path.stat().st_nlink!=1:raise ValueError('共享数据库无法独立清理：'+filename)
        db.execute('ATTACH DATABASE ? AS '+name,(path.as_uri()+'?mode=rw',))
        schemas.append(name)
    for schema in schemas:
        if db.execute('PRAGMA '+schema+'.journal_mode').fetchone()[0] not in ('delete','truncate','persist'):
            raise ValueError('当前数据库日志模式不支持跨库原子清理。')
        db.execute('PRAGMA '+schema+'.synchronous=FULL')

def remove_queue_rows(db,plan):
    for key in plan['prep_keys']:db.execute('DELETE FROM prep.preparations WHERE key=?',(key,))
    for batch in plan['batches']:
        for table,key in [('site_recalculations','parent'),('attempt_storage','batch'),('batch_storage','batch'),
                          ('jobs','batch'),('batches','id')]:
            if db.execute("SELECT 1 FROM queue.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                db.execute('DELETE FROM queue.'+table+' WHERE '+key+'=?',(batch,))
    for ident in plan['cache_ids']:db.execute('DELETE FROM queue.cache WHERE identity=?',(ident,))

def stage(root,ident,rows):
    trash=safe_child(root,root/'data/storage-management/plan-trash'/ident)
    trash.mkdir(parents=True)
    write_json(trash/'journal.json',dict(paths=[r[0] for r in rows]),root)
    for index,(relative,size,mtime,inode) in enumerate(rows):
        p=paths(root,relative);st=p.stat()
        if (st.st_size,st.st_mtime_ns,st.st_ino)!=(size,mtime,inode):raise ValueError('清理前文件发生变化：'+relative)
        os.replace(p,trash/str(index))

def settle(root,ident,committed):
    trash=safe_child(root,root/'data/storage-management/plan-trash'/ident)
    if not trash.exists():return
    journal=safe_child(root,trash/'journal.json')
    if not journal.exists():
        trash.rmdir();return
    records=read_json(journal)['paths'];parents=set()
    for index,relative in enumerate(records):
        p=paths(root,relative);staged=safe_child(root,trash/str(index))
        if staged.exists():
            if committed:staged.unlink()
            elif not p.exists():os.rename(staged,p)
            else:raise ValueError('恢复路径已被占用：'+str(p))
        if committed:
            for parent in p.parents:
                if parent in [root/prefix for prefix,_ in ROOTS.values()]:break
                parents.add(parent)
    for parent in sorted(parents,key=lambda p:-len(p.parts)):
        if parent.is_dir() and not any(parent.iterdir()):parent.rmdir()
    journal.unlink();trash.rmdir()

def recover(root):
    base=safe_child(root,root/'data/storage-management/plan-trash')
    if not base.exists():return
    from result_storage import maintenance
    with maintenance(root),closing(pd.connect_read(pd.dbpath(root))) as db:
        for folder in base.iterdir():
            if not re.fullmatch('plan_delete_'+HEX,folder.name):raise ValueError('清理日志目录含未知项目。')
            committed=pd.table_exists(db,'plan_deletion_receipts') and db.execute(
                'SELECT 1 FROM plan_deletion_receipts WHERE id=?',(folder.name,)).fetchone()
            settle(root,folder.name,bool(committed))
