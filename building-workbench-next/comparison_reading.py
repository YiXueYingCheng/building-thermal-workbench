"""Interpret a pinned pair and point to separate, accepted comparisons in saved exports."""
from pathlib import Path
import re

from comparison_results import finite, pair_reason
from calendar_library import active_references
from foundation import digest, owned, read_json, sha
from planner import compare
from research_exports import selected
from research_sets import Sets, require


def except_keys(value, *keys):
    return {k: v for k, v in value.items() if k not in keys}


def installation(record):
    factors = record['factors']
    apps = factors['materials']['applications']
    if len(apps) != 1:
        return None
    app = apps[0]
    definitions = factors['materials']['definitions']
    controls = factors['condition']['controls']
    if len(definitions) != 1 or definitions[0]['id'] != app['material_id'] or len(controls) != 2:
        return None
    by_channel = {c['channel']: c for c in controls}
    if set(by_channel) != {'orientation', 'thermal'} or not app['target_ids']:
        return None
    if any(c['application_id'] != app['id'] or set(c['target_ids']) != set(app['target_ids']) for c in controls):
        return None
    definition = definitions[0]
    thermal, optical = by_channel['thermal'], by_channel['orientation']
    state = next((s['name'] for s in definition['states'] if s['id'] == thermal.get('state_id')), '')
    return dict(material=definition.get('name') or definition['id'], thermal=thermal, optical=optical,
                state=state, count=len(app['target_ids']), component=app.get('component'))


def question(left, right, check=None):
    if check is None:
        check = compare(left, right)
    changed = [x['label'] for x in check['rows'] if not x['equal']]
    same_origin = all(left['provenance'].get(k) == right['provenance'].get(k) for k in ('adapter', 'snapshot_id'))
    if check.get('contrast_factor')=='room_usage':
        return dict(kind='room_usage', text='同一建筑更换房间使用配置后，{metric}怎样变化？', basis=check['note'])
    if not changed and same_origin:
        return dict(kind='same', text='两侧保存的研究输入相同。', basis='当前版本之间没有可用来解释结果变化的输入差异。')
    generic = dict(kind='combined', text='两套已保存方案的{metric}有何差异？',
                   basis='请结合下方差异解释两套配置的整体表现。涉及的项目有'+ '、'.join(changed or ['建筑来源'])+'。')
    if not check['shared_conditions'] or not same_origin:
        return generic
    a, b = left['factors'], right['factors']
    left_app, right_app = installation(left), installation(right)
    # The active calendar and its reference are part of the optical strategy.
    if (left_app and right_app and a['materials'] == b['materials']
            and except_keys(a['condition'], 'controls', 'reference_runs') == except_keys(b['condition'], 'controls', 'reference_runs')):
        apps = (left_app, right_app)
        optics = [app['optical'] for app in apps]
        modes = [opt['mode'] for opt in optics]
        if (set(modes) == {'fixed','calendar'} and left_app['thermal'] == right_app['thermal']
                and left_app['thermal']['mode'] == 'fixed'
                and except_keys(optics[0], 'mode','reference_id') == except_keys(optics[1], 'mode','reference_id')):
            cal = (left, right)[modes.index('calendar')]
            refs = active_references(cal)
            if (len(refs) == 1 and cal['factors']['condition']['reference_runs'] == refs
                    and not (left,right)[modes.index('fixed')]['factors']['condition']['reference_runs']):
                fixed_face = optics[modes.index('fixed')]['face_id']
                fixed_label = f'固定 {fixed_face} 组光学参数'
                rule = refs[0].get('snapshot',{}).get('content',{}).get('rule') or {}
                calendar_label = ('季节光学切换' if {'dominant_share','persistence_days','window_days'}.issubset(rule)
                                  else '按日历切换表面光学参数')
                change = f'由{fixed_label}改为{calendar_label}' if modes[0]=='fixed' else f'由{calendar_label}改为{fixed_label}'
                return dict(kind='orientation', text=f"材料保持{left_app['state']}态，外表面{change}后，{{metric}}怎样变化？",
                            basis=f"两侧的材料、铺设的 {left_app['count']} 个构件和热阻设置一致。")
    if except_keys(a['condition'], 'controls') != except_keys(b['condition'], 'controls'):
        return generic
    if left_app and right_app and a['materials'] == b['materials'] and left_app['optical'] == right_app['optical']:
        modes = [x['thermal']['mode'] for x in (left_app, right_app)]
        optical = left_app['optical']
        calendar = optical['mode'] == 'calendar' and len(active_references(left)) == 1
        if modes == ['fixed','fixed'] and (optical['mode'] == 'fixed' or calendar):
            start, end = left_app['thermal'], right_app['thermal']
            if (start.get('state_id') != end.get('state_id') and left_app['state'] and right_app['state']
                    and except_keys(start, 'state_id') == except_keys(end, 'state_id')):
                premise = '使用同一光学切换日历时' if calendar else f"外表面固定采用 {optical['face_id']} 组光学参数时"
                return dict(kind='fixed_thermal_state',
                            text=f"{premise}，材料由固定{left_app['state']}改为固定{right_app['state']}，{{metric}}怎样变化？",
                            basis=f"两侧覆盖相同的 {left_app['count']} 个构件，全年各保持一种材料状态。")
        if set(modes) == {'fixed','feedback'} and (optical['mode'] == 'fixed' or calendar):
            fixed = (left_app, right_app)[modes.index('fixed')]
            transition = '由固定'+fixed['state']+'态改为按反馈调节热阻' if modes[0]=='fixed' else '由按反馈调节热阻改为固定'+fixed['state']
            premise = '使用同一光学切换日历时' if calendar else f"外表面固定采用 {optical['face_id']} 组光学参数时"
            return dict(kind='calendar_feedback' if calendar else 'feedback', text=f"{premise}，{transition}，{{metric}}怎样变化？",
                        basis=f"两侧使用相同材料和相同的 {fixed['count']} 个构件，建筑运行、气象范围和求解设置一致。")
    for base, study, app, add in ((a, b, right_app, True), (b, a, left_app, False)):
        if not app or base['materials']['applications'] or base['materials']['definitions'] or base['condition']['controls']:
            continue
        if except_keys(base['materials'], 'applications','definitions','definition_reference') != except_keys(study['materials'], 'applications','definitions','definition_reference'):
            continue
        if app['thermal']['mode'] == app['optical']['mode'] == 'fixed':
            target = f"{app['count']} 面墙" if app['component']=='wall' else f"{app['count']} 个构件"
            label = 'ECA' if app['material']=='OLD_ECA' else app['material']
            verb = '加装' if add else '移除'
            state=app['state'] or '固定'
            if not state.endswith(('态','状态')):state+='态'
            return dict(kind='application', text=f"在 {target}上{verb} {label} 后，{{metric}}怎样变化？",
                        basis=f"材料热学设置为{state}，表面光学参数固定为 {app['optical']['face_id']} 组。这里比较整套铺设方案的效果。")
    return generic


PAIRS = {
    'application': ('baseline','fixed','原构造与固定材料的需求差多少？'),
    'feedback': ('flip','feedback','按日历切换表面光学参数时，按反馈调节热阻会怎样？'),
    'orientation': ('fixed','flip','热阻固定时，季节光学切换会怎样影响负荷？'),
}

def material_family(record):
    definitions = record['factors']['materials']['definitions']
    if len(definitions) != 1:
        return None
    key = (definitions[0]['id'], definitions[0].get('model'))
    # The archived Beijing studies store the same ECA family under these two model-specific IDs.
    if key in {('OLD_ECA', 'equivalent_resistance_no_layer_storage'), ('eca_solid_conserved', 'solid_conserved_mass_v1')}:
        return 'ECA'
    return key


def verified_export(folder, receipt, group):
    """Read only the selected results dataset, bound to this immutable group revision."""
    dataset = owned(folder/'dataset.json', folder)
    require(receipt['id'] == folder.name and receipt['set_id'] == group['id']
            and receipt['revision'] == group['revision'] and sha(dataset) == receipt['files']['dataset.json'],
            '导出文件或绑定版本变化。')
    data = read_json(dataset)
    require(data['id'] == group['id'] and data['revision'] == group['revision'] and data['set_sha256'] == group['sha256']
            and data['records'] == {k:m['record'] for k,m in group['members'].items()}
            and digest(except_keys(data,'checked_at','dataset_sha256')) == data['dataset_sha256'] == receipt['dataset_sha256'],
            '结果来源或保存版本不符。')
    require(data['audit']['consistent'], '对比集共同条件不一致。')
    return selected(data, receipt['choices'])


def related(left, right, catalog, root):
    kind = question(left, right)['kind']
    response = dict(items=[], issues=0)
    if kind not in ('feedback','application','calendar_feedback','orientation'):
        return response
    f = left['factors']
    sites = f['scope']['site_ids']
    if len(sites)!=1 or f['condition']['operation']['mode']!='controlled':
        return response
    weather = (catalog['sites'].get(sites[0],{}).get('weather') or {}).get('sha256')
    if not weather:
        return response
    picks = {'feedback': ('orientation','feedback'), 'calendar_feedback': ('orientation',),
             'orientation': ('feedback',), 'application': ('application','orientation')}[kind]
    family = material_family(right) or material_family(left)
    sets = Sets(catalog,root)
    options = []
    for path in (Path(root)/'data/research-set-exports').glob('set_export_*'):
        if not path.is_dir() or not re.fullmatch(r'set_export_[a-f0-9]{32}',path.name):
            continue
        try:
            folder = owned(path, root)
            receipt = read_json(owned(folder/'receipt.json',folder))
            group = sets.evidence_version(receipt['set_id'],receipt['revision'])
            base = group['members']['baseline']['record']
            record = sets.store.get(base['id'],base['revision'])
            if record['factors']['building']['id'] != f['building']['id'] or record['provenance']['snapshot_id'] != left['provenance']['snapshot_id']:
                continue
            fixed = group['members']['fixed']['record']
            if not family or material_family(sets.store.get(fixed['id'], fixed['revision'])) != family:
                continue
            chosen = verified_export(folder,receipt,group)
            refs = [(r['id'], r['revision']) for r in (left,right)]
            found = []
            for topic in picks:
                src,dst,title = PAIRS[topic]
                if dst not in chosen or src not in chosen:
                    continue
                pair_refs = [(group['members'][k]['record']['id'],group['members'][k]['record']['revision']) for k in (src,dst)]
                if set(refs)==set(pair_refs):
                    continue
                for site, first in chosen[src].items():
                    second = chosen[dst].get(site)
                    if first.get('weather_sha256')!=weather or first['period']!=f['scope']['period'] or first['mode']!='controlled':
                        continue
                    if site not in catalog['sites'] or not catalog['sites'][site].get('eligible',True) or pair_reason(first,second) or pair_reason(chosen['baseline'].get(site),second):
                        continue
                    values = [[finite(row['loads'][k+'_kWh']) for k in ('heating','cooling','total')] for row in (first,second)]
                    found.append(dict(topic=topic, title=title, group=group['name'], revision=group['revision'],
                                      export_id=path.name, created=receipt['created'], site_id=site, city=first['city'], step=first['step_minutes'],
                                      names=[row['source']['name'] for row in (first,second)], values=values,
                                      period=first['period'], acceptance=[row['status_label'] for row in (first,second)]))
            options.extend(found)
        except (ValueError, KeyError, OSError, TypeError, IndexError):
            response['issues']+=1
    # One example for each follow-up question, preferring the latest verified export.
    for topic in picks:
        candidates=[x for x in options if x['topic']==topic]
        if candidates:
            response['items'].append(max(candidates,key=lambda x:(x['created'],x['export_id'])))
    return response
