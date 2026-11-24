"""Preview and remove saved comparison relationships independently of simulation results."""
from contextlib import closing
import sqlite3

from foundation import digest, loads, now, read_json
from storage_management import safe_child
from result_storage import maintenance

KINDS = {
    'comparison': ('comparisons', '两两比较', '删除比较'),
    'reading': ('reading_groups', '阅读对比集', '解散对比集'),
    'set': ('research_sets', '计算型对比集', '解散对比集'),
    'design': ('comparison_designs', '对照设计', '删除设计'),
}
LABELS = {'comparisons':'已保存比较', 'comparison_inputs':'比较双方保存的输入快照', 'reading_groups':'阅读对比集', 'research_sets':'计算型对比集版本',
          'comparison_designs':'设计版本', 'reading_links':'收录的比较', 'reading_hidden':'收录隐藏记录',
          'theme_versions':'成员清单版本', 'research_set_members':'成员归属', 'queue.comparison_step_choices':'地点步长选择'}


def action_for(table, row):
    for kind, (main, _, _) in KINDS.items():
        if table == main:
            return action(kind, row['id'])
    if table == 'comparison_inputs':
        return action('comparison', row['comparison_id'])
    if table == 'research_set_members':
        return action('set', row['set_id'])
    if table in ('theme_versions', 'reading_links'):
        group = row['group_id']
        return action('set' if group.startswith('set_') else 'reading', group)
    if table == 'comparison_step_choices':
        return action('comparison', row['comparison'])
    return None


def action(kind, ident):
    return dict(kind=kind, id=ident, label=KINDS[kind][2])


def exists(db, table):
    schema, _, name = table.rpartition('.')
    if schema and schema not in {r[1] for r in db.execute('PRAGMA database_list')}:
        return False
    return db.execute('SELECT 1 FROM '+(schema or 'main')+'.sqlite_master WHERE type=? AND name=?',
                      ('table', name)).fetchone() is not None


def name_relations(root, refs):
    actionable = [r for r in refs if r.get('action')]
    if not actionable:
        return
    names = {(r['kind'], r['id']): r for r in listing(root)}
    for ref in actionable:
        a = ref['action']
        item = names.get((a['kind'], a['id']))
        if item:
            ref.update(kind=item['title'], label=item['name'], owner=a['id'], owner_key=a['kind']+'/'+a['id'])


def inspect(db, root, kind, ident):
    if kind not in KINDS or not isinstance(ident, str) or not ident:
        raise ValueError('请选择已保存的比较、对比集或设计。')
    primary, title, verb = KINDS[kind]
    rows = {}
    def collect(table, where, args):
        if not exists(db, table):
            return []
        found = [dict(r) for r in db.execute('SELECT rowid AS _key,* FROM '+table+' WHERE '+where+' ORDER BY rowid', args)]
        if found:
            rows.setdefault(table, []).extend(found)
        return found

    heads = collect(primary, 'id=?', (ident,))
    if not heads:
        raise ValueError('这项关系已经移除，请刷新列表。')
    last = max(heads, key=lambda r:r.get('revision', 0))
    name = last['name'] if kind == 'reading' else loads(last['payload'])['name']
    if kind == 'comparison':
        collect('comparison_inputs', 'comparison_id=?', (ident,))
        links = collect('reading_links', "json_extract(payload,'$.comparison')=?", (ident,))
        for link in links:
            collect('reading_hidden', 'group_id=? AND signature=?', (link['group_id'], link['signature']))
        collect('queue.comparison_step_choices', 'comparison=?', (ident,))
    elif kind in ('reading', 'set'):
        for table in ('reading_links', 'reading_hidden', 'theme_versions'):
            collect(table, 'group_id=?', (ident,))
        if kind == 'set':
            collect('research_set_members', 'set_id=?', (ident,))

    # Historical readers of group exports and preparation records use an exact frozen revision.
    retained = set()
    runs = []
    if kind == 'set':
        for path in sorted((root/'data/research-set-exports').glob('set_export_*/receipt.json')):
            receipt = read_json(safe_child(root, path))
            if receipt['set_id'] == ident:
                retained.add(receipt['revision'])
        for path in sorted((root/'data/research-set-preparations').glob('setprep_*/state.json')):
            state = read_json(safe_child(root, path))
            if state['plan']['id'] == ident:
                if state['state']=='preparing':
                    from research_execution import owner_alive
                    if owner_alive(state.get('owner_pid')):
                        raise ValueError('本集正在准备计算。请先暂停该组准备，待当前任务停下再解散。')
                retained.add(state['plan']['revision'])
                runs.append((state['id'], state['state']))
        if retained.difference(r['revision'] for r in heads):
            raise ValueError('组导出或准备记录绑定的版本缺失，请先核查该记录。')
    snapshot = digest([kind, ident, rows, sorted(retained), runs])
    counts = [dict(label=LABELS[t], count=len(items)) for t, items in rows.items()]
    group_names = []
    if kind == 'comparison':
        hidden={(r['group_id'],r['signature']) for r in rows.get('reading_hidden', [])}
        for gid in sorted({r['group_id'] for r in rows.get('reading_links', []) if (r['group_id'],r['signature']) not in hidden}):
            group = db.execute('SELECT name FROM reading_groups WHERE id=?',(gid,)).fetchone() if exists(db,'reading_groups') else None
            if group is None and exists(db,'research_sets'):
                group = db.execute("SELECT json_extract(payload,'$.name') FROM research_sets WHERE id=? ORDER BY revision DESC LIMIT 1",(gid,)).fetchone()
            group_names.append(group[0] if group else gid)
    result = dict(kind=kind, id=ident, title=title, name=name, verb=verb, counts=counts, collection_names=group_names,
                  sha256=snapshot, archived_revisions=sorted(retained), preparations=len(runs))
    return result, rows


def open_db(root, kind, writing):
    from plan_deletion import dbpath
    mode = 'rw' if writing else 'ro'
    db = sqlite3.connect(dbpath(root).as_uri()+'?mode='+mode, uri=True, timeout=4)
    try:
        db.row_factory = sqlite3.Row
        queue = safe_child(root, root/'data/execution/queue.sqlite')
        schemas = ['main']
        if kind == 'comparison' and queue.exists():
            if writing and queue.stat().st_nlink != 1:
                raise ValueError('队列数据库与其他工作区共享，请先解除文件共享。')
            db.execute('ATTACH DATABASE ? AS queue', (queue.as_uri()+'?mode='+mode,))
            schemas.append('queue')
        if writing and len(schemas) > 1:
            for schema in schemas:
                if db.execute('PRAGMA '+schema+'.journal_mode').fetchone()[0] not in ('delete','truncate','persist'):
                    raise ValueError('当前日志模式无法同时更新比较和地点步长选择。')
                db.execute('PRAGMA '+schema+'.synchronous=FULL')
        db.execute('BEGIN IMMEDIATE' if writing else 'BEGIN')
        return db
    except BaseException:
        db.close()
        raise


def listing(root):
    with closing(open_db(root, None, False)) as db:
        result = []
        for kind, (table, title, _) in KINDS.items():
            if not exists(db, table):
                continue
            if kind == 'reading':
                query = 'SELECT id,name FROM reading_groups ORDER BY name,id'
            else:
                query = "SELECT id,json_extract(payload,'$.name') FROM "+table
                if kind in ('set', 'design'):
                    query += ' AS x WHERE revision=(SELECT MAX(revision) FROM '+table+' WHERE id=x.id)'
                query += ' ORDER BY 2,1'
            result.extend(dict(action(kind, ident), title=title, name=name) for ident, name in db.execute(query))
        return result


def preview(root, kind, ident):
    with closing(open_db(root, kind, False)) as db:
        return inspect(db, root, kind, ident)[0]


def remove(root, kind, ident, checksum, confirmed):
    if confirmed is not True:
        raise ValueError('请确认本次解除关系的范围。')
    with maintenance(root), closing(open_db(root, kind, True)) as db, db:
        result, rows = inspect(db, root, kind, ident)
        if result['sha256'] != checksum:
            raise ValueError('关系或收录范围已变化，请重新预览。')
        if result['archived_revisions']:
            db.execute('CREATE TABLE IF NOT EXISTS dissolved_set_snapshots (id TEXT, revision INTEGER, payload TEXT NOT NULL, PRIMARY KEY(id,revision))')
            db.executemany('INSERT INTO dissolved_set_snapshots VALUES(?,?,?)',
                           [(ident, r['revision'], r['payload']) for r in rows['research_sets']
                            if r['revision'] in result['archived_revisions']])
        for table, entries in reversed(list(rows.items())):
            db.executemany('DELETE FROM '+table+' WHERE rowid=?', [(r['_key'],) for r in entries])
        db.execute('INSERT INTO events(at,action,record_id,revision) VALUES(?,?,?,?)',
                   (now(), 'remove_'+kind, ident, 0))
        return result
