"""Questions and the next missing comparison for one selected set or reading collection."""
from collections import defaultdict, OrderedDict
from threading import Lock
from pathlib import Path
from uuid import uuid4
import sqlite3
from copy import deepcopy

import pair_archives
from comparison_reading import verified_export
from comparison_results import choice_index, compatible, finite, pair_reason
from foundation import canonical, digest, loads, now, owned, read_json
from pair_evidence import archive_alternative, building_key, fixed_optics_candidate, needs_pair_archive, pin, read
from research_sets import require

STEPS = [('baseline','fixed'), ('fixed','flip'), ('flip','feedback')]
SINGLE = {'application','orientation','feedback','calendar_feedback','fixed_thermal_state','room_usage'}


class CandidateReceipts:
    """Bounded metadata receipts for reading. Submission and collection always verify afresh."""
    def __init__(self,root):
        self.root=Path(root)
        self.entries=OrderedDict()
        self.lock=Lock()

    def sources(self):
        from navigation_lists import database_files
        paths=database_files(self.root,'drafts.sqlite','components.sqlite','execution/preparations.sqlite','execution/queue.sqlite')
        data=self.root/'data'
        return paths+[data/n for n in ('current.json','coverage-results','coverage-results/index.json',
                                       'research-set-exports','execution/reviews','model-inputs','history-locations/index.json','output-storage.json')]

    def read(self,loader):
        from inspection_io import reading
        from recent_batch_views import file_marks
        before=file_marks(self.sources())
        with reading() as reads:
            result=loader()
            files=file_marks(set(reads.hashes)|set(reads.paths))
            bindings=tuple(reads.values.values())
        if before is None or files is None or before!=file_marks(before) or files!=file_marks(files):
            return dict(result,read_receipt=None)
        token=uuid4().hex
        with self.lock:
            self.entries[token]=(before|files,bindings)
            if len(self.entries)>64:self.entries.popitem(last=False)
        return dict(result,read_receipt=token)

    def valid(self,token):
        from recent_batch_views import file_marks
        with self.lock:entry=self.entries.get(token)
        if not entry:return False
        marks,bindings=entry
        try:
            return marks==file_marks(marks) and all(get()==expected for get,expected,_ in bindings)
        except (OSError,sqlite3.Error,ValueError):
            return False



def key(ref):
    return ref['id'],ref['revision']


def exports_for(group, root, notices):
    picks = {}
    for path in sorted((root/'data/research-set-exports').glob('set_export_*')):
        try:
            folder = owned(path,root)
            receipt = read_json(owned(folder/'receipt.json',folder))
            if (receipt['set_id'],receipt['revision']) != (group['id'],group['revision']):
                continue
            rows = verified_export(folder,receipt,group)
            picks.setdefault(digest(rows),(folder.name,rows))
        except (OSError, ValueError, KeyError, TypeError):
            notices.append('一份结果导出未通过核对，已跳过。')
    if len(picks)>1:
        notices.append('该组版本有多份取值不同的导出，请在本组结果中选定批次。')
    return next(iter(picks.values())) if len(picks)==1 else None


def export_pair(observation, export, roles, records, catalog):
    """Both sides of a pair must come from the same export, even if one live side exists."""
    ident, selected = export
    a,b = records
    if compatible(a,b,'controlled','total') or building_key(a)!=building_key(b):
        return observation
    current = deepcopy(observation)
    current.update(sites=[],excluded=[],export=ident)
    for side,role in zip(current['sides'],roles):
        side.update(source=ident,accepted=sorted(selected[role]),note='组版本导出')
    for sid in a['factors']['scope']['site_ids']:
        site = catalog['sites'][sid]
        pair = [selected[role].get(sid) for role in roles]
        reason = pair_reason(*pair)
        if not site.get('eligible',True):
            reason = '地点暂缓接受'
        if not reason and (pair[0]['mode']!='controlled' or not pair[0]['weather_sha256']
                or pair[0]['period']!=a['factors']['scope']['period'] or pair[0]['step_minutes']!=a['numerics']['step_minutes']):
            reason = '运行条件与所选版本不一致'
        row = dict(site=sid,city=site['name'])
        if reason:
            current['excluded'].append(dict(row,reason=reason))
        else:
            current['sites'].append(dict(row, keys=[digest([ident,item['batch_id'],sid,item]) for item in pair],
                values=[[finite(item['loads'][k+'_kWh']) for k in ('heating','cooling','total')] for item in pair]))
    return current if current['sites'] else observation


def scoped_gap(data, scope):
    """Count new work only for a missing source and a verified opposite side at that site."""
    if not data or len(set(data['steps']))!=1 or any(s['ambiguous'] for s in data['sides']):
        return None
    left,right = data['sides']
    for i,(ready,missing) in enumerate(((left,right),(right,left))):
        if missing['source'] or missing['note']!='尚无结果来源':
            continue
        target_sites=set(missing.get('scope_sites',()))
        sites = [s for s in data['excluded'] if s['site'] in scope and s['site'] in target_sites and s['site'] in ready['accepted']
                 and s['reason']=='缺少一侧结果或未在该侧范围内']
        if sites:
            return dict(side='研究侧' if i==0 else '参考侧',sites=[r['site'] for r in sites],places=[r['city'] for r in sites],count=len(sites))
    return None


def proposal(data, relation, gap, gain, basis, title=None):
    return dict(question=title or data['question']['text'],metric=data['metric'],period=data['periods'][0],
                sides=data['sides'],relation=relation,gap=gap,gain=gain,basis=basis,
                scope=sorted({r['site'] for r in data['sites']+data['excluded']}),mode=data['mode'],steps=data['steps'])


def member_answers(reader, group, relations, index, notices):
    catalog,root = reader.store.catalog,reader.store.root
    answers,pending=[],[]
    members = reader.sets.records(group)
    archive = None
    checked = False
    for src,dst in STEPS:
        if dst not in members:
            continue
        a,b = members[src],members[dst]
        rel = next((r for r in relations if r['left']==pin(a) and r['right']==pin(b) and r['metric']=='total'),None)
        relation = rel['id'] if rel else None
        data = read(a,b,dict(comparison=relation),catalog,root,index=index)
        if not data['sites'] and any(s['note']=='尚无结果来源' for s in data['sides']) and not any(s['ambiguous'] for s in data['sides']):
            if not checked:
                archive=exports_for(group,root,notices)
                checked=True
            if archive:
                data=export_pair(data,archive,(src,dst),(a,b),catalog)
        entry=dict(data=data,relation=relation,origin='组内成员')
        (answers if data['sites'] else pending).append(entry)
    return answers,pending


def collection_answers(reader, ident, info, relations, index, notices):
    catalog,root=reader.store.catalog,reader.store.root
    answers,pending=[],[]
    for section in reader.detail(ident)['sections']:
        for row in section:
            rel = next((r for r in relations if r['id']==row['comparison']),None)
            if not rel:
                notices.append('一条收录对照的版本关系已不可用。')
                continue
            a,b=reader.records(rel)
            request=dict(comparison=rel['id'],metric=row['metric'],mode=row['mode'],
                         left_source=row['sides'][0]['source'],right_source=row['sides'][1]['source'])
            try:
                data = read(a,b,request,catalog,root,index=index,store=reader.store)
            except (OSError, ValueError):
                notices.append('一条收录对照的结果来源需重新核对。')
                continue
            current = {s['site']:s['keys'] for s in data['sites']}
            if any(current.get(s['site'])!=s['keys'] for s in row['sites']):
                notices.append('一条已收录结果的依据已变化，请回阅读汇总核对。')
                continue
            entry=dict(data=data,relation=rel['id'],origin='已收录')
            (answers if data['sites'] else pending).append(entry)
    return answers,pending


def theme_member_answers(reader, info, relations, index, answers, pending, notices):
    """Read the user's chosen directions. Membership alone never writes a comparison."""
    store=reader.store
    snap=info['membership']
    records={key(p):store.study_record(p) for p in snap['members']}
    reference=snap['reference']
    # A hidden or stale reading still owns its direction; do not silently replace it.
    with store.connect() as db:
        represented={tuple(row) for row in db.execute(
            "SELECT json_extract(payload,'$.sides[0].ref.id'),json_extract(payload,'$.sides[0].ref.revision'),"
            "json_extract(payload,'$.sides[1].ref.id'),json_extract(payload,'$.sides[1].ref.revision'),"
            "json_extract(payload,'$.metric') FROM reading_links WHERE group_id=?",(info['id'],))}
    saved=defaultdict(list)
    for rel in relations:
        a,b=key(rel['left']),key(rel['right'])
        if a in records and b in records:
            saved[a,b,rel['metric']].append(rel)
    other_buildings=0
    if reference or len(records)==2:
        left=key(reference) if reference else next(iter(records))
        pairs=[]
        for right in records:
            if left==right:
                continue
            if building_key(records[left])!=building_key(records[right]):
                other_buildings+=1
                continue
            natural=any(records[k]['factors']['condition']['operation']['mode']=='natural' for k in (left,right))
            pairs.append((left,right,'temperature' if natural else 'total'))
    else:
        pairs=[p for p in saved if building_key(records[p[0]])==building_key(records[p[1]])]
    prior_sources=defaultdict(set)
    for item in answers:
        d=item['data']
        for side in d['sides']:
            if side['source'] and not side['source'].startswith('set_export_'):
                prior_sources[key(side['ref']),d['mode']].add(side['source'])
    reference_cache={} if reference else None
    unresolved={}
    for item in pending:
        d=item['data']
        a,b=[key(s['ref']) for s in d['sides']]
        if a in records and b in records and needs_pair_archive(d):
            unresolved[a,b,d['metric']]=item
    # An unresolved reading stays in the library until an explicit save. A verified
    # archive may already answer that same question with a different pair of sources.
    covered=defaultdict(set)
    def note_coverage(item):
        d=item['data']
        sig=tuple(key(s['ref']) for s in d['sides'])+(d['metric'],d['mode'])
        covered[sig].update(s['site'] for s in d['sites'])
    for item in answers:note_coverage(item)
    choices=[]
    archives=None
    for left,right,metric in dict.fromkeys([*pairs,*unresolved]):
        previous=unresolved.get((left,right,metric))
        if (*left,*right,metric) in represented and not previous:
            continue
        rels=saved[left,right,metric]
        a,b=records[left],records[right]
        if previous:
            rels=[r for r in rels if r['id']==previous['relation']]
            ready=covered[left,right,metric,previous['data']['mode']]
            if previous['data']['excluded'] and all(s['site'] in ready for s in previous['data']['excluded']):continue
        if len(rels)>1:
            choices.append(dict(sides=[dict(ref=pin(r),name=r['name']) for r in (a,b)],metric=metric))
            continue
        relation=rels[0]['id'] if rels else None
        request=dict(comparison=relation,metric=metric)
        mode='natural' if metric=='temperature' and any(
            r['factors']['condition']['operation']['mode']=='natural' for r in (a,b)) else 'controlled'
        for role,k in (('left',left),('right',right)):
            selected=prior_sources[k,mode]
            if len(selected)==1:
                request[role+'_source']=next(iter(selected))
        try:
            data=previous['data'] if previous else read(a,b,request,store.catalog,store.root,index=index,store=store,reference_cache=reference_cache)
            if needs_pair_archive(data):
                if archives is None:archives=pair_archives.for_members(reader,records.values(),notices)
                issues=[]
                alternative=archive_alternative(reader,a,b,request,archives,issues)
                if alternative:
                    data=alternative
                elif issues or '一份组导出需要重新核对来源。' in notices:
                    for side in data['sides']:
                        if side['note']=='尚无结果来源':side['note']='归档来源待核对'
                notices.extend(issues)
        except (OSError,ValueError) as err:
            notices.append(f"{a['name']} → {b['name']} 需重新核对来源。{err}")
            continue
        if previous and not data['sites']:continue
        item=dict(data=data,relation=relation,origin='成员配对 · 尚未收录')
        (answers if data['sites'] else pending).append(item)
        if data['sites']:note_coverage(item)
    def still_pending(item):
        d=item['data']
        sig=tuple(key(s['ref']) for s in d['sides'])+(d['metric'],d['mode'])
        return not d['excluded'] or any(s['site'] not in covered[sig] for s in d['excluded'])
    pending[:]=[item for item in pending if still_pending(item)]
    return dict(revision=snap['revision'],members=snap['members'],reference=reference,
                reference_name=records[key(reference)]['name'] if reference else None,
                other_buildings=other_buildings,choices=choices)


def add_neighbours(reader, info, relations, index, answers, pending):
    catalog,root=reader.store.catalog,reader.store.root
    # Discover only immediate neighbours sharing an actual observation. Avoid chains of suggestions.
    anchors = {(key(side['ref']),s['site'],s['keys'][i],d['condition'],d['metric']) for entry in answers
               for d in [entry['data']] for i,side in enumerate(d['sides']) for s in d['sites']}
    pins = {v[0] for v in anchors}
    ready_sources = {(key(side['ref']),side['source'],s['site'],d['condition'],d['metric']) for entry in answers
                     for d in [entry['data']] for side in d['sides'] for s in d['sites']}
    seen = {(frozenset(key(s['ref']) for s in e['data']['sides']),e['data']['metric']) for e in answers+pending}
    for rel in relations:
        sides=frozenset(key(rel[k]) for k in ('left','right'))
        sig=(sides,rel['metric'])
        if not pins.intersection(sides) or sig in seen:
            continue
        a,b=reader.records(rel)
        if building_key(a)!=building_key(b) or info['building'] not in (building_key(a),'*'):
            continue
        data=read(a,b,dict(comparison=rel['id'],metric=rel['metric']),catalog,root,index=index,store=reader.store)
        matching=[s for s in data['sites'] if any((key(side['ref']),s['site'],s['keys'][i],data['condition'],data['metric']) in anchors
                                                  for i,side in enumerate(data['sides']))]
        if matching:
            data['sites']=matching
            answers.append(dict(data=data,relation=rel['id'],origin='关联的已核验对照'))
            seen.add(sig)
        elif data['question']['kind'] in SINGLE:
            shared = {sid for side in data['sides'] for sid in side['accepted']
                      if (key(side['ref']),side['source'],sid,data['condition'],data['metric']) in ready_sources}
            if scoped_gap(data,shared):
                data['excluded']=[s for s in data['excluded'] if s['site'] in shared]
                pending.append(dict(data=data,relation=rel['id'],origin='关联的已保存方案'))
                seen.add(sig)


def feedback_followup(reader, group, answers, pending, index, notices):
    store=reader.store
    catalog,root=store.catalog,store.root
    for entry in list(answers):
        data=entry['data']
        if data['question']['kind']!='calendar_feedback' or data['metric']=='temperature':
            continue
        a,b=[store.study_record(s['ref']) for s in data['sides']]
        match=group
        if match is None:
            # Use the two pinned calendar members. Distinct fixed references imply a research choice.
            with store.connect() as db:
                rows=db.execute('SELECT DISTINCT id,revision FROM research_sets ORDER BY revision DESC').fetchall()
            compatible_groups={}
            for row in rows:
                g=reader.sets.get(*row)
                if 'feedback' in g['members'] and {key(g['members'][k]['record']) for k in ('flip','feedback')}=={key(a),key(b)}:
                    compatible_groups.setdefault(key(g['members']['fixed']['record']),g)
            if len(compatible_groups)!=1:
                continue
            match=next(iter(compatible_groups.values()))
        if 'feedback' not in match['members'] or {key(a),key(b)}!={
                key(match['members'][role]['record']) for role in ('flip','feedback')}:
            continue
        special=fixed_optics_candidate(a,b,catalog,root,group=match,index=index)
        if not special:
            continue
        scope={r['site'] for r in data['sites']}
        comp=special.get('evidence')
        title='固定 A 组光学参数时，按反馈调节热阻会怎样改变显热需求？'
        basis='已有对照测出了季节光学切换时的反馈效果。固定 A 的对照可检验这个结论是否也适用于全年固定表面参数。'
        gain='先量出固定 A 时，启用反馈使供暖、制冷和合计各改变多少。再与同地点的季节光学切换结果对照，就能判断哪种光学策略下反馈的作用更大，以及差多少。'
        if comp:
            if comp['condition']!=data['condition']:
                notices.append('固定光学参数与日历工况的结果条件存在差异，请单独核对。')
                continue
            relation=special['relation']
            comp=dict(comp,sites=[s for s in comp['sites'] if s['site'] in scope],
                      excluded=[s for s in comp['excluded'] if s['site'] in scope])
            if relation:
                pending[:]=[e for e in pending if e['relation']!=relation]
            sig=[(key(s['ref']),s['source']) for s in comp['sides']]
            if comp['sites'] and not any([(key(s['ref']),s['source']) for s in e['data']['sides']]==sig and
                                         e['data']['metric']==comp['metric'] for e in answers):
                answers.append(dict(data=comp,relation=relation,origin='匹配到已有方案'))
            gap=scoped_gap(comp,scope)
            if gap:
                return dict(proposal(comp,relation,gap,gain,basis,title),basis_entry=entry)
            if comp['sites']:
                return dict(proposal(comp,relation,None,gain,basis,title),basis_entry=entry,answer=comp)
            if comp['excluded']:
                if not any(e['relation']==relation and relation for e in pending):
                    pending.append(dict(data=comp,relation=relation,origin='匹配到已有方案'))
                return dict(proposal(comp,relation,None,gain,basis,title),basis_entry=entry,waiting=comp['excluded'][0]['reason'])
        else:
            return dict(question=title,gain=gain,basis=basis,gap=None,relation=None,metric='total',period=data['periods'][0],
                          sides=[],draft=True,basis_entry=entry,design_target=dict(left=special['left'],recipe=special['target_recipe'],rules=special['target_rules']),
                          scope=sorted(scope),mode=data['mode'],steps=data['steps'])

    return None


def saved_followup(pending):
    # A saved, single-factor pair with one verified side is more actionable than an unresolved batch.
    possibilities=[]
    for entry in pending:
        data=entry['data']
        if data['question']['kind'] not in SINGLE:
            continue
        gap=scoped_gap(data,{r['site'] for r in data['excluded']})
        if gap:
            possibilities.append((gap['count'],proposal(data,entry['relation'],gap,
                '可以逐间比较所选时段内两种设置的室温差异。' if data['metric']=='temperature' else
                {'application':'可以量化这一铺设方案对供暖和制冷需求的整体影响。',
                 'orientation':'可以量化热阻设置相同时，改变表面光学策略带来的需求变化。',
                 'feedback':'可以量化表面光学参数固定时，调节热阻带来的需求变化。',
                 'calendar_feedback':'可以量化共用光学切换日历时，调节热阻带来的需求变化。',
                 'fixed_thermal_state':'可以量化在同一表面光学策略下，采用两种固定材料状态的需求差异。',
                 'room_usage':'可以比较这两套房间使用配置对选定指标的整体影响。'}[data['question']['kind']],
                '这组只改变一项研究设置，一侧已有核验结果。在满足这两个条件的候选里，这组所缺的地点算例最少。')))
    if possibilities:
        priority=min(possibilities,key=lambda item:item[0])[1]
        pending[:]=[e for e in pending if e['data']['sides']!=priority['sides'] or e['data']['metric']!=priority['metric']]
        return priority
    return None


def thermal_strategy_tables(store, answers):
    """Join three verified pairs only when each shared observation is identical."""
    from comparison_reading import installation
    by_scope = defaultdict(dict)
    for i, entry in enumerate(answers):
        data = entry['data']
        kind = data['question']['kind']
        if (kind not in ('fixed_thermal_state', 'calendar_feedback', 'feedback')
                or data['mode'] != 'controlled' or data['metric'] != 'total'
                or len(set(data['steps'])) != 1 or data['periods'][0] != data['periods'][1]
                or any(side['ambiguous'] for side in data['sides'])):
            continue
        for row in data['sites']:
            # Include version and source explicitly for older export evidence keys.
            nodes = tuple((key(side['ref']), side['source'], fingerprint, tuple(values))
                          for side, fingerprint, values in zip(data['sides'], row['keys'], row['values']))
            scope = row['site'], data['condition'], tuple(data['periods'][0]), data['steps'][0]
            edges = by_scope[scope]
            pair = frozenset(nodes)
            if len(pair) == 2 and (pair not in edges or (entry['relation'] and row.get('monthly_sources'))):
                edges[pair] = (kind, nodes, i, row['city'])

    labels = {}
    tables = []
    for (site, condition, period, step), edges in by_scope.items():
        neighbours = defaultdict(set)
        for kind, (left, right), _, _ in edges.values():
            if kind != 'fixed_thermal_state':
                neighbours[left].add(right)
                neighbours[right].add(left)
        for kind, (left, right), _, city in edges.values():
            if kind != 'fixed_thermal_state':
                continue
            for feedback in sorted(neighbours[left] & neighbours[right]):
                nodes = [left, right, feedback]
                members = []
                for node in nodes:
                    ref = dict(id=node[0][0], revision=node[0][1])
                    if node[0] not in labels:
                        try:
                            record = store.study_record(ref)
                        except KeyError:
                            labels[node[0]] = (None, '')
                        else:
                            labels[node[0]] = (installation(record), record['name'])
                    app, name = labels[node[0]]
                    if not app or app['thermal']['mode'] != ('feedback' if node == feedback else 'fixed'):
                        break
                    label = '按反馈调节热阻' if node == feedback else '固定'+app['state']
                    members.append(dict(ref=ref, name=name, label=label, values=node[3]))
                if len(members) != 3:
                    continue
                pairs = []
                for first, second in ((left,right),(left,feedback),(right,feedback)):
                    _, (a,b), index, _ = edges[frozenset((first,second))]
                    pairs.append(dict(left=nodes.index(a), right=nodes.index(b), answer=index))
                optical = app['optical']
                optics = '同一光学切换日历' if optical['mode']=='calendar' else '固定 '+optical['face_id']+' 面'
                tables.append(dict(id=digest([site,condition,sorted((n[:3] for n in nodes),key=canonical)]), site=site, city=city,
                                   period=period, step=step, optics=optics, material=app['material'],
                                   members=members, pairs=pairs))
    return tables


def report(reader, ident, revision=None, *, context=None):
    info=reader.group(ident)
    store=reader.store
    relations=store.comparisons()
    index=choice_index(store.root)
    notices=[]
    group=None
    historical=False
    require(context in (None,'reading'),'无效的对比集入口。')
    require(context!='reading' or revision is None,'阅读汇总按各条对照的版本查看。')
    use_members=info['kind']=='calculation' and (context!='reading' or not info['count'])
    if use_members:
        group=reader.sets.get(ident,revision)
        if context=='reading':
            notices.append('此阅读汇总尚未收录对照，以下按当前组版本的成员核对。')
        historical=revision is not None and group['revision']!=reader.sets.get(ident)['revision']
        answers,pending=member_answers(reader,group,relations,index,notices)
    else:
        require(revision is None,'阅读汇总按收录的双方版本核对。')
        answers,pending=collection_answers(reader,ident,info,relations,index,notices)
    member_review=None
    if info.get('membership'):
        member_review=theme_member_answers(reader,info,relations,index,answers,pending,notices)
    priority=None
    if historical:
        notices.append('正在查看历史组版本。切换到最新组版本可查看补充建议。')
    else:
        if member_review:
            active=set(map(key,member_review['members']))
            def current_member_pair(item):
                return all(key(s['ref']) in active for s in item['data']['sides'])
            current=[item for item in answers if current_member_pair(item)]
            potential=[item for item in pending if current_member_pair(item)]
            old_answers=len(current)
            retired={key(p) for version in info['member_history'] for p in version['members']}-active
            with store.connect() as db:
                recorded={r[0] for r in db.execute(
                    "SELECT json_extract(payload,'$.comparison') FROM reading_links WHERE group_id=?",(ident,))}
            unresolved={(key(q['sides'][0]['ref']),key(q['sides'][1]['ref']),q['metric']) for q in member_review['choices']}
            neighbours=[r for r in relations if r['id'] not in recorded
                        and (key(r['left']),key(r['right']),r['metric']) not in unresolved
                        and not retired.intersection((key(r['left']),key(r['right'])))]
            add_neighbours(reader,info,neighbours,index,current,potential)
            priority=feedback_followup(reader,group,current,potential,index,notices) or saved_followup(potential)
            answers.extend(current[old_answers:])
            pending=[item for item in pending if not current_member_pair(item)]+potential
        else:
            add_neighbours(reader,info,relations,index,answers,pending)
            priority=feedback_followup(reader,group,answers,pending,index,notices) or saved_followup(pending)
    # Bind the confirmation to the exact direction, coverage and evidence the user read.
    for item in answers:
        evidence=item['data']
        if evidence['sites'] and not evidence.get('export') and not any(s['ambiguous'] for s in evidence['sides']):
            item['collection_token']=digest([ident,revision,context,(info.get('membership') or {}).get('revision'),item['relation'],evidence])
    answered=None
    if priority and priority.get('answer'):
        entry=next((x for x in answers if x.get('collection_token') and
                    [s['ref'] for s in x['data']['sides']]==[s['ref'] for s in priority['sides']] and
                    x['data']['sites']==priority['answer']['sites']),None)
        if entry:
            priority['collection_token']=entry['collection_token']
            priority['collected']=entry['origin']=='已收录'
        answered=priority
        priority=saved_followup(potential if member_review else pending)
    # Point to the exact verified comparison used in this report, including its saved direction.
    for item in (priority,answered):
        if item and 'basis_entry' in item:
            evidence=item.pop('basis_entry')
            item['basis_answer']=next(i for i,row in enumerate(answers) if row is evidence)
    return dict(answered_followup=answered,name=group['name'] if group else info['name'],revision=group['revision'] if group else None,
                answers=answers,thermal_tables=thermal_strategy_tables(store,answers),
                priority=priority,pending=pending,member_review=member_review,notices=list(dict.fromkeys(notices)))


def collect_answer(reader,body):
    """Explicit confirmation of one already-read candidate, including a version outside the set."""
    ident=body['group']
    token=body.get('token')
    require(isinstance(token,str) and len(token)==64,'请重新打开追问并核对结果。')
    revision=body.get('revision')
    result=report(reader,ident,revision,context=body.get('context'))
    entry=next((x for x in result['answers'] if x.get('collection_token')==token),None)
    require(entry is not None,'对照的版本、来源或结果已变化，请重新核对后收录。')
    data=dict(entry['data'])
    left,right=[s['ref'] for s in data['sides']]
    metric=data['metric']
    relation=entry['relation'] or 'comparison_'+digest(['topic-pair',left,right,metric])[:32]
    a,b=[reader.store.study_record(ref) for ref in (left,right)]
    name=data.get('name') or (a['name']+' → '+b['name'])[:100]
    data.update(comparison=relation,name=name,building=a['factors']['building']['name'],building_key=building_key(a))
    sig=digest([left,right,metric,data['mode'],[s['source'] for s in data['sides']]])
    rel=dict(id=relation,name=name,left=left,right=right,metric=metric)
    with reader.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if result['member_review']:
            from theme_groups import latest
            require(latest(db,ident)['revision']==result['member_review']['revision'],'集内成员已变化，请重新核对。')
        row=db.execute('SELECT payload FROM comparisons WHERE id=?',(relation,)).fetchone()
        if row:
            current=loads(row[0])
            require(all(current[k]==rel[k] for k in ('left','right','metric')),'原对照已经变化，请重新核对。')
        else:
            require(not entry['relation'],'原对照已移除，请重新核对。')
            db.execute('INSERT INTO comparisons VALUES(?,?,?)',(relation,canonical(dict(rel,created=now())),now()))
        reader.store._pin_members(db,rel)
        added=reader.save_link(db,ident,sig,data)
    return dict(group=ident,entry=sig,added=added)
