"""Versioned reference data, never applied to saved schemes implicitly."""
import copy, gzip, json
from functools import lru_cache
from pathlib import Path
from foundation import digest, sha, ROOT
from component_library import Library, payload_hash
from starter_library import bundled_file, describe_choice


def source_path():
    return bundled_file('resources/reference-library/catalog.json')


@lru_cache(maxsize=4)
def _read(path, stamp):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def catalog():
    p = source_path()
    return copy.deepcopy(_read(str(p), p.stat().st_mtime_ns))


def get(kind, ident):
    if kind not in ('materials', 'constructions', 'daily_profiles', 'annual_schedules', 'room_templates'):
        raise ValueError('参考库类别不受支持。')
    row = next((r for r in catalog()[kind] if r['id'] == ident), None)
    if row is None:
        raise ValueError('参考条目不存在，请刷新。')
    return row


def listing(root=ROOT):
    data = catalog()
    data['construction_versions'] = Library(root).all('construction')
    return data


def annual(ident):
    row = get('annual_schedules', ident)
    with gzip.open(source_path().with_name('annual.json.gz'), 'rt', encoding='utf-8') as stream:
        values = json.load(stream)[ident]
    if len(values) != 8760:
        raise ValueError('全年参考序列不完整。')
    return dict(**row, values=values, calendar=catalog()['calendar'])


def daily_profiles():
    data = catalog(); rows = []
    for item in data['daily_profiles']:
        values = item['values']
        if len(values) != 24 or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in values):
            continue
        content = dict(schema_version=1, unit='fraction', values=values,
            notes='早期 Excel 参考；需按项目核对。' + item.get('notes', ''),
            provenance=dict(reference_id=item['id'], origins=item['origins'],
                workbook_sha256=data['source_workbook_sha256'], version=data['version']))
        row = dict(kind='daily', id='component_'+digest([item['id'], content])[:32],
            revision=1, name=item['name'], created='2026-11-14T00:00:00+08:00', content=content)
        row['sha256'] = payload_hash(row)
        rows.append(dict(snapshot=row, origin='内置 Excel 参考作息', aliases=[], binary=all(v in (0, 1) for v in values)))
    return rows


def room_templates():
    data = catalog(); daily = {r['id']:r for r in data['daily_profiles']}
    years = {r['id']:r for r in data['annual_schedules']}; choices, donors = [], {}
    mapping = [('people', 'O_SCHEDULE'), ('lighting', 'L_SCHEDULE'), ('equipment', 'E_SCHEDULE')]
    units = {'人/间':'people', '人/m²':'people/m2', 'W/间':'W', 'W/m²':'W/m2'}
    from usage_schedules import validate_load, validate_gains
    for item in data['room_templates']:
        rules = {}
        for channel, key in mapping:
            year = years.get(item.get(key), {})
            if year.get('current_excel_compatible') != '可精确按工作日/周末还原':
                break
            a, b = year.get('weekday_daily_id'), year.get('weekend_daily_id')
            if a not in daily or b not in daily or item[channel+'_mode'] not in units:
                break
            rules[channel] = dict(kind='scaled', unit=units[item[channel+'_mode']],
                minimum=item[channel+'_min'], maximum=item[channel+'_max'],
                weekday=daily[a]['values'], weekend=daily[b]['values'],
                basis='Excel 参考 ' + item['id'] + '；全年比例序列可精确还原为工作日/周末')
        if len(rules) != 3:
            continue  # A seasonal curve is never flattened into a daily pair.
        gains = dict(sensible_W_person=item['people_sensible_W_person'], lighting_heat_fraction=item['additional']['L_HEAT_RATE'])
        for channel in rules: validate_load(rules[channel], channel, 1)
        validate_gains(gains)
        ident = 'reference:'+item['id']
        donor = dict(rules=rules, gains=gains, source_building='excel_reference_v1', source_room=item['id'],
            baseline_sha256=digest(item), source_label='Excel 参考 · '+item['name'],
            note='来源参考，非现行规范值；只采用人数、照明、设备作息及显热设置，保留目标建筑空调与温控配置。',
            reference_source=dict(name=data['source_workbook'], version=data['version'],
                origins=item['origins'], distribution=data['distribution'], sha256=data['source_workbook_sha256']))
        donors[ident] = donor
        choices.append(describe_choice(ident, donor['source_label']+' · '+item['id'][-6:], donor, 'reference'))
    return choices, donors


def construction(ident):
    item = get('constructions', ident); mats = {m['id']:m for m in catalog()['materials']}
    layers = []
    for layer in item['layers']:
        material = copy.deepcopy(mats[layer['material_id']])
        layers.append(dict(sequence=layer['sequence'], thickness_mm=layer['thickness_mm'], material=material))
    return dict(schema_version=1, reference_id=ident, name=item['name'], category=item['category'],
        orientation=item['orientation'], layers=layers, origins=item['origins'],
        source_workbook_sha256=catalog()['source_workbook_sha256'],
        note='保留原层号顺序；应用前需明确室外到室内方向、表面光学和适用构件。')


def copy_construction(root, ident, name):
    return Library(root).save('construction', name, construction(ident))


def material_draft(ident):
    from material_types import template
    item = get('materials', ident); out = template('solid')
    out['name'] = item['name']
    state = out['states'][0]
    for key in ('conductivity_W_mK', 'density_kg_m3', 'specific_heat_J_kgK'):
        state[key] = item.get(key)
    state['thickness_mm'] = item.get('default_thickness_mm')
    # Reflectance alone cannot establish opacity or effective surface absorption.
    out['optics']['A_R']['emissivity'] = item.get('longwave_emissivity')
    out['source_note'] = '早期 Excel 参考 '+ident+'；'+item.get('notes', '')+' 原太阳反射率：'+str(item.get('solar_reflectance'))+'。采用前补全厚度和有效表面光学参数。'
    out['property_source'] = dict(method='source_reference', note=ident+' / '+catalog()['source_workbook_sha256'])
    return out
