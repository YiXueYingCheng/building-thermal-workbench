"""Independent physical-face optics; public thermal layers remain unchanged."""
import copy
import math

SHEET = '墙面光学设置'
DELEGATE = '按墙面光学设置'
MODES = ['沿用DeST', '使用材料参数', '自定义']
HEADERS = ['墙体编号', '表面编号', '位置', '连接环境或房间', '参数来源',
           '自定义太阳反射率 0–1', '自定义全长波发射率 0–1',
           'DeST太阳反射率 0–1', 'DeST全长波发射率 0–1', '备注']
GENERAL_HEADERS = ['构件编号','表面编号','位置','连接环境或房间','参数来源',
                   '自定义太阳反射率 0–1','自定义全长波发射率 0–1',
                   '源太阳反射率 0–1','源全长波发射率 0–1','备注']
KEYS = ('solar_absorptance', 'thermal_absorptance', 'visible_absorptance')


def number(value, label, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'{label}：须填写0–1的数值；0是有效值，自定义模式不能留空。')
    return value


def emissivity(value, label, optional=False):
    value=number(value,label,optional)
    if value is not None and not 0 < value <= .99999:
        raise ValueError(f'{label}：EnergyPlus要求全长波发射率大于0且不超过0.99999。')
    return value


def initial_rows(walls, assignments):
    chosen = {a['id']: a for a in assignments}
    rows = []
    for w in walls:
        a = chosen[w['id']]
        mode = MODES[1] if a['optics'] == '材料优先（不透明）' else MODES[0]
        for f in w['optical_faces']:
            rows.append([w['id'], f['source_id'], f['position'], f['environment'], mode,
                         None, None, 1-f['solar_absorptance'], f['thermal_absorptance'], None])
    return rows


def parse_workbook(book, walls):
    names = [n for n in (SHEET, '表面光学') if n in book.sheetnames]
    if not names:
        return None  # Pre-upgrade workbooks retain their original whole-wall rules.
    if len(names) != 1:
        raise ValueError('表面光学存在两个编辑入口，请保留对应版本的一张输入页。')
    sh = book[names[0]]
    labels=GENERAL_HEADERS if any(c.value==GENERAL_HEADERS[0] for row in sh for c in row) else HEADERS
    header_rows = [c.row for row in sh for c in row if c.value == labels[0]]
    if len(header_rows) != 1:
        raise ValueError('墙面光学设置：表头缺失或重复。')
    hr = header_rows[0]
    columns = [c for c in sh[hr] if c.value in labels]
    positions = {HEADERS[labels.index(c.value)]: c.column for c in columns}
    if set(positions) != set(HEADERS) or len(columns) != len(HEADERS):
        raise ValueError('表面光学：请保留全部表头，不得重复。')
    expected = {(w['id'], f['source_id']): f for w in walls for f in w['optical_faces']}
    result = {}
    for rr in range(hr+1, sh.max_row+1):
        row = tuple(sh.cell(rr,positions[h]).value for h in HEADERS)
        if all(v is None for v in row):
            continue
        key = (row[0], row[1])
        if key not in expected or key in result:
            raise ValueError(f'墙面光学设置：表面编号未知或重复 {key}。')
        f = expected[key]
        if row[2:4] != (f['position'], f['environment']):
            raise ValueError(f'{key}：表面位置或相邻环境被修改。')
        for actual, source in zip(row[7:9], (1-f['solar_absorptance'], f['thermal_absorptance'])):
            number(actual, str(key)+' DeST原值')
            if not math.isclose(actual, source, abs_tol=1e-12):
                raise ValueError(f'{key}：DeST原值列被修改，请在自定义列输入。')
        mode = row[4]
        if mode not in MODES:
            raise ValueError(f'{key}：请选择沿用DeST、使用材料参数或自定义。')
        rho = number(row[5], str(key)+' 太阳反射率', optional=mode != MODES[2])
        eps = emissivity(row[6], str(key)+' 全长波发射率', optional=mode != MODES[2])
        result[key] = {'wall_id': row[0], 'source_id': row[1], 'mode': mode,
                       'solar_reflectance': rho, 'longwave_emissivity': eps, 'notes': row[9]}
    if set(result) != set(expected):
        raise ValueError('墙面光学设置：两侧清单不完整，不能删除任何表面行。')
    return list(result.values())


def rows_from_settings(walls, settings):
    chosen = {(a['wall_id'], a['source_id']): a for a in settings}
    rows = []
    for w in walls:
        for f in w['optical_faces']:
            a = chosen[(w['id'], f['source_id'])]
            rows.append([w['id'], f['source_id'], f['position'], f['environment'], a['mode'],
                         a['solar_reflectance'], a['longwave_emissivity'],
                         1-f['solar_absorptance'], f['thermal_absorptance'], a['notes']])
    return rows


def apply_wall(model, wall, settings, public_layers):
    """Called on a transactional model copy before constructing the final audit."""
    chosen = {(a['wall_id'], a['source_id']): a for a in settings}
    object_type=wall.get('object_type','BuildingSurface:Detailed')
    ref = model[object_type][wall['surface']]
    construction = model['Construction'][ref['construction_name']]
    names = [construction['outside_layer']] + [construction[f'layer_{i}'] for i in range(2, 11) if f'layer_{i}' in construction]
    resolved = []; targets = {}
    for f in wall['optical_faces']:
        a = chosen[(wall['id'], f['source_id'])]
        index = 0 if f['slot'] == 'outside' else len(names)-1
        props = {k: f[k] for k in KEYS}
        source_basis=f.get('basis','DeST原表面')
        solar_basis = thermal_basis = source_basis
        if a['mode'] == MODES[1]:
            if not public_layers:
                raise ValueError(f'{wall["id"]} / 表面{f["source_id"]}：使用材料参数须先在墙面构造分配中选择公共库构造。')
            m = public_layers[index]['public_material']
            rho, eps = m.get('solar_reflectance'), m.get('longwave_emissivity')
            if rho is not None:
                props['solar_absorptance'] = 1-number(rho, '公共材料太阳反射率')
                solar_basis = '公共材料 '+m['id']
            else:
                solar_basis = '公共材料缺值；'+source_basis
            if eps is not None:
                props['thermal_absorptance'] = emissivity(eps, '公共材料全长波发射率')
                thermal_basis = '公共材料 '+m['id']
            else:
                thermal_basis = '公共材料缺值；'+source_basis
        elif a['mode'] == MODES[2]:
            props['solar_absorptance'] = 1-number(a['solar_reflectance'], '自定义太阳反射率')
            props['thermal_absorptance'] = emissivity(a['longwave_emissivity'], '自定义全长波发射率')
            solar_basis = thermal_basis = '本建筑表面自定义'
        elif a['mode'] != MODES[0]:
            raise ValueError('未知表面光学来源：'+str(a['mode']))
        emissivity(props['thermal_absorptance'],f'{wall["id"]} / 表面{f["source_id"]} 最终全长波发射率')
        if index in targets and any(not math.isclose(props[k], targets[index][k], abs_tol=1e-12) for k in KEYS):
            raise ValueError(f'{wall["id"]}：单层墙两面光学参数不同，当前不能无损表示；请使用真实多层构造或设为相同参数。未自动增加涂层或改变厚度。')
        targets[index] = props
        resolved.append({'wall_id': wall['id'], 'source_id': f['source_id'], 'slot': f['slot'], 'reference_surface':wall['surface'],
                         'position': f['position'], 'environment': f['environment'], 'mode': a['mode'],
                         'source_solar_reflectance': 1-f['solar_absorptance'], 'source_longwave_emissivity': f['thermal_absorptance'],
                         'solar_reflectance': 1-props['solar_absorptance'], 'longwave_emissivity': props['thermal_absorptance'],
                         'solar_basis': solar_basis, 'thermal_basis': thermal_basis, 'notes': a['notes'], **props})
    # Preserve byte-for-byte model structure when the effective optics have not changed.
    changed = any(model['Material'][names[i]][k] != value for i,p in targets.items() for k,value in p.items())
    if changed:
        for i, props in targets.items():
            old = model['Material'][names[i]]
            if all(old[k] == v for k,v in props.items()):
                continue
            new_name = f'Optical_{wall["id"]}_Layer{i+1}'
            model['Material'][new_name] = {**copy.deepcopy(old), **props}
            names[i] = new_name
        for i, surface in enumerate(wall['surfaces']):
            ordered = names if i == 0 else list(reversed(names))
            cname = f'Optical_{wall["id"]}_Side{i+1}'
            model['Construction'][cname] = {('outside_layer' if j == 0 else f'layer_{j+1}'):n for j,n in enumerate(ordered)}
            model[object_type][surface]['construction_name'] = cname
    for r in resolved:
        r['ep_material'] = names[0 if r['slot'] == 'outside' else -1]
        r['changed_from_dest'] = any(not math.isclose(r[k], f[k], abs_tol=1e-12) for k in KEYS for f in wall['optical_faces'] if f['source_id'] == r['source_id'])
    return resolved
