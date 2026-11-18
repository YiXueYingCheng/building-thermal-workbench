"""Confirmed opaque door mappings shared by inspection and conversion.

The 10 mm single aluminium door was checked against the source DeST door and
material dialogs on 2026-11-17. Its displayed properties are preserved, not
replaced with handbook values. This does not interpret arbitrary GAP_LENGTH
fields or unreviewed composite/glazed doors.
"""
import collections
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def index(rows, key):
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('门构造或材料编号重复：' + key)
    return result


def matches(row, fields):
    return all(type(row.get(k)) in (int, float) and math.isfinite(row[k])
               and row[k] == v for k, v in fields.items())


def inspect_doors(data, reference_doors, reference_materials):
    doors = index(data['SYS_DOOR'], 'DOOR_ID')
    materials = index(data['SYS_MATERIAL'], 'MATERIAL_ID')
    checked_doors = index(reference_doors, 'DOOR_ID')
    checked_materials = index(reference_materials, 'MATERIAL_ID')
    counts = collections.Counter(r['DOOR_CONSTRUCTION'] for r in data['DOOR'])
    models, errors = [], []
    for ident, count in sorted(counts.items(), key=lambda item: str(item[0])):
        row = doors.get(ident, {})
        material = materials.get(row.get('MATERIAL_ID'), {})
        label = f"门类型 {ident}（{row.get('CNAME') or '未命名'}，{count} 扇）"
        opaque = matches(row, dict(GLASS_RAT=0, APP_ID=0, APP_FLAG=0))
        wood = (bool(row) and row == checked_doors.get(ident)
                and bool(material) and material == checked_materials.get(row.get('MATERIAL_ID'))
                and matches(row, dict(GAP_LENGTH=25.3, MATERIAL_ID=62))
                and type(row.get('CONDUCT_CO')) in (int, float) and row['CONDUCT_CO'] > 0)
        aluminium = (row.get('CNAME') == '单层阳台金属外门'
                and row.get('GROUP_ID') == '阳台外门' and material.get('CNAME') == '铝'
                and material.get('GROUP_ID') == '金属'
                and matches(row, dict(GAP_LENGTH=10, CONDUCT_CO=0, FLAG=0, ERASEFLAG=0))
                and matches(material, dict(CONDUCTIVITY=220.97, DENSITY=2600, SPECIFIC_HEAT=482)))
        if not opaque or not (wood or aluminium):
            errors.append(label + '尚无匹配的已核对转换规则。当前支持已核对的 25.3 mm 木门及 10 mm 单层铝门；请提供该门的构造、厚度和材料参数，不会自动替换成木门。')
            continue
        props = {k: float(material[field]) for k, field in (
            ('conductivity', 'CONDUCTIVITY'), ('density', 'DENSITY'), ('specific_heat', 'SPECIFIC_HEAT'))}
        if any(not math.isfinite(v) or v <= 0 for v in props.values()):
            errors.append(label + '的材料物性必须是有限正数。')
            continue
        thickness_mm = float(row['GAP_LENGTH'])
        model = dict(type_id=str(ident), name=row['CNAME'], count=count,
            material_id=row['MATERIAL_ID'], material_name=material['CNAME'],
            mapping='confirmed_wood_25_3' if wood else 'confirmed_single_aluminium_10',
            thickness_mm=thickness_mm, **props,
            thermal_resistance_m2K_W=thickness_mm / 1000 / props['conductivity'],
            areal_heat_capacity_J_m2K=thickness_mm / 1000 * props['density'] * props['specific_heat'],
            source_CONDUCT_CO=row['CONDUCT_CO'], thermal_mass=True,
            roughness='MediumSmooth', thermal_absorptance=.85, solar_absorptance=.55,
            visible_absorptance=.55,
            surface_assumption='表面热吸收率 0.85、太阳/可见光吸收率 0.55、表面粗糙度采用转换近似；不是该门表面实测值。',
            thickness_basis='已对照 DeST 门库界面的厚度 mm 字段；仅适用于匹配的已核对门构造。',
            source_door_sha256=digest(row), source_material_sha256=digest(material))
        model['confirmation_sha256'] = digest(model)
        models.append(model)
    return models, errors


def validate_confirmation(request, models):
    """A previous all-wood request is compatible; mixed doors need each type."""
    expected = {m['type_id']: m['confirmation_sha256'] for m in models}
    confirmations = request.get('door_confirmations')
    legacy = request.get('door_mm')
    if confirmations is not None:
        if not isinstance(confirmations, dict) or confirmations != expected:
            raise ValueError('请逐项确认本次门构造、厚度、材料物性和表面近似；参数变化后需重新核对。')
        if legacy is not None and (type(legacy) not in (int, float) or legacy != 25.3
                or any(m['mapping'] != 'confirmed_wood_25_3' for m in models)):
            raise ValueError('旧的统一木门厚度选择不能用于本次门构造。')
    elif models and (type(legacy) not in (int, float) or legacy != 25.3
            or any(m['mapping'] != 'confirmed_wood_25_3' for m in models)):
        raise ValueError('请逐项确认本次门构造；不能把全部门统一替换为 25.3 mm 木门。')


def material_properties(model):
    return dict(thickness=model['thickness_mm'] / 1000,
        **{key: model[key] for key in ('conductivity', 'density', 'specific_heat',
            'roughness', 'thermal_absorptance', 'solar_absorptance', 'visible_absorptance')})
