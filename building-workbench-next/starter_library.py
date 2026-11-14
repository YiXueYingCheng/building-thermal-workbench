"""Bundled, read-only examples; selecting one never changes existing schemes."""
import copy
from pathlib import Path
from foundation import read_json, sha
from usage_schedules import validate_load, validate_gains

PACKAGE = Path(__file__).resolve().parents[1]
def bundled_file(relative):
    external = PACKAGE / relative
    return external if external.is_file() else Path(__file__).resolve().parent / 'assets/reference-library' / relative

UNITS = {'people': '人/间', 'people/m2': '人/m²', 'W': 'W/间', 'W/m2': 'W/m²'}
CHANNELS = {'people': '人数', 'lighting': '照明', 'equipment': '设备'}


def describe_choice(ident, label, donor, kind='building'):
    channels = []
    for key, title in CHANNELS.items():
        rule = donor['rules'][key]
        scaled = rule.get('kind') == 'scaled'
        values = rule['weekday'] + rule['weekend']
        lo, hi = (rule['minimum'], rule['maximum']) if scaled else (min(values), max(values))
        unit = UNITS[rule['unit']] if scaled else ('人/间' if key == 'people' else 'W/间')
        channels.append(dict(key=key, name=title, minimum=lo, maximum=hi, unit=unit,
                             mode='上下限 × 比例' if scaled else '逐小时实际值',
                             weekday=copy.deepcopy(rule['weekday']), weekend=copy.deepcopy(rule['weekend'])))
    summary = '；'.join(f"{c['name']} {c['minimum']:g}–{c['maximum']:g} {c['unit']}" for c in channels)
    return dict(id=ident, label=label, kind=kind, summary=summary, channels=channels,
                gains=copy.deepcopy(donor['gains']), source=copy.deepcopy(donor.get('reference_source')),
                note=donor.get('note', '已核对建筑的原房间配置；逐小时实际值按每间保留，密度值按目标面积换算。'))


def usage_templates():
    path = bundled_file('resources/starter-library/usage-profiles.json')
    data = read_json(path)
    if data.get('schema') != 1:
        raise ValueError('公用演示配置库版本不受支持。')
    choices, donors = [], {}
    for item in data['profiles']:
        for channel in CHANNELS:
            validate_load(item['rules'][channel], channel, 1)
        validate_gains(item['gains'])
        ident = 'demo:' + item['id']
        if ident in donors:
            raise ValueError('公用演示配置编号重复。')
        donor = dict(rules=copy.deepcopy(item['rules']), gains=copy.deepcopy(item['gains']),
                     source_building='public_demo_v1', source_room=item['id'],
                     baseline_sha256=sha(path), source_label=item['name'], note=data['scope'],
                     reference_source=dict(name=data['source'], version=data['version'], license=data['license'], sha256=sha(path)))
        donors[ident] = donor
        choices.append(describe_choice(ident, item['name'], donor, 'demo'))
    from reference_library import room_templates
    extra, more = room_templates()
    return choices + extra, {**donors, **more}


def material_presets():
    path = bundled_file('examples/materials/ECA.json')
    content = read_json(path)
    return [dict(id='builtin_eca', revision=1, name=content['name'], builtin=True,
                 content=content, license='CC BY 4.0', source='随包已授权 ECA 示例', source_sha256=sha(path))]
