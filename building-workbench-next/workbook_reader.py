"""Read literal cells from a legacy XLSX without evaluating or writing it."""
import math
from pathlib import PurePosixPath
import zipfile
import xml.etree.ElementTree as ET

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def cells(path, sheet_name):
    with zipfile.ZipFile(path) as book:
        if sum(i.file_size for i in book.infolist()) > 50 * 1024 * 1024:
            raise ValueError('参数表展开大小超限。')
        shared = []
        if 'xl/sharedStrings.xml' in book.namelist():
            shared = [''.join(e.itertext()) for e in ET.fromstring(book.read('xl/sharedStrings.xml')).findall(MAIN + 'si')]
        sheets = ET.fromstring(book.read('xl/workbook.xml')).findall(MAIN + 'sheets/' + MAIN + 'sheet')
        sheet = next((s for s in sheets if s.get('name') == sheet_name), None)
        if sheet is None:
            raise ValueError('没有预期参数页：' + sheet_name)
        relations = {r.get('Id'): r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        target = relations[sheet.get(REL + 'id')]
        member = target.lstrip('/') if target.startswith('/') else str(PurePosixPath('xl') / target)
        if '..' in PurePosixPath(member).parts:
            raise ValueError('参数表关系路径不受支持。')
        result = {}
        for cell in ET.fromstring(book.read(member)).iter(MAIN + 'c'):
            key = cell.get('r')
            if cell.find(MAIN + 'f') is not None:
                result[key] = {'formula': cell.findtext(MAIN + 'f')}
                continue
            kind = cell.get('t')
            value = cell.findtext(MAIN + 'v')
            if kind == 'inlineStr':
                value = ''.join(cell.find(MAIN + 'is').itertext())
            elif kind == 's' and value is not None:
                value = shared[int(value)]
            elif kind == 'b' and value is not None:
                value = value == '1'
            elif value is not None and kind not in ('str', 'e'):
                value = float(value)
            result[key] = value
        return result

def number(value, name, optional=False, optical=False):
    if value in (None, '') and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' 不是有效的直接输入数值。')
    if optical and not 0 <= value <= 1:
        raise ValueError(name + ' 应在 0–1 之间。')
    if not optical and value <= 0:
        raise ValueError(name + ' 必须大于 0。')
    return float(value)

def material_card(path):
    at = cells(path, '动态材料').get
    for cell, label in {'A6':'材料编号', 'A13':'厚度', 'A14':'厚度方向热导率', 'A28':'光学参数模式', 'B46':'1.0'}.items():
        if at(cell) != label:
            raise ValueError('旧材料模板不匹配：' + cell)
    states = []
    for ident, col, name in [('R', 'B', '蓬松'), ('C', 'C', '压缩')]:
        method = at(col + '12')
        thick = number(at(col + '13'), name + '厚度', optional=method == '直接热阻')
        if method == '厚度/热导率':
            conductivity = number(at(col + '14'), name + '导热系数')
            resistance = thick / 1000 / conductivity
        elif method == '直接热阻':
            conductivity = None
            resistance = number(at(col + '15'), name + '热阻')
        else:
            raise ValueError('未知热学输入方式。')
        density = number(at(col+'16'), name+'密度', optional=True)
        cp = number(at(col+'17'), name+'比热', optional=True)
        mass = number(at(col+'18'), name+'面密度', optional=True)
        if mass is None and thick is not None and density is not None:
            mass = thick / 1000 * density
        states.append(dict(id=ident, name=name, thermal_input='resistance' if method=='直接热阻' else 'conductivity_thickness',resistance_m2K_W=resistance, thickness_mm=thick,
            conductivity_W_mK=conductivity, density_kg_m3=density, specific_heat_J_kgK=cp,
            areal_mass_kg_m2=mass, areal_capacity_J_m2K=mass*cp if mass is not None and cp is not None else None))
    optics = {}
    rows = [('A_R',30),('B_R',31)] + ([('A_C',32),('B_C',33)] if at('B28')=='分态设置' else [])
    if at('B28') not in ('两态相同', '分态设置'):
        raise ValueError('未知光学参数模式。')
    for ident, row in rows:
        reflectance = number(at(f'B{row}'), ident+'反射率', optical=True)
        optics[ident] = dict(reflectance=reflectance, solar_absorptance=1-reflectance,
            emissivity=number(at(f'C{row}'), ident+'发射率', optical=True), input_basis='opaque_reflectance')
    if at('B28') == '两态相同':
        optics['A_C'], optics['B_C'] = dict(optics['A_R']), dict(optics['B_R'])
    definition = dict(id=str(at('B6')), name=str(at('B7') or at('B6')), kind='single_layer',
        source_note=str(at('B8') or ''), model='equivalent_resistance_no_layer_storage', states=states,
        optics=optics, optics_depend_on_state=at('B28')=='分态设置', state_identity='independent')
    return dict(definition=definition, case=at('B36'), mode=at('B37'), city=at('B35'))
