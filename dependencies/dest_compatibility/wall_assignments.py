"""Assign public-library opaque constructions to physical walls, with provenance.

One input row owns both room-side surfaces of an interzone wall. Geometry,
openings, boundary conditions and Kiva footing assumptions are not modified.
"""
import copy
import csv
import decimal
import hashlib
import json
import math
import pathlib
import re
import warnings

import openpyxl
import surface_optics

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parent
BASE = PROJECT / 'results/dest-model-only/TEST_20260910'
TABLES = PROJECT.parents[1] / 'work/dest-model-only/tables/TEST.accdb'
CATALOG = PROJECT / 'library/catalog.json'
SHEET = '墙面构造分配'
KEEP = '保留DeST原构造'
ORDER = ['自动', '按库正序', '按库倒序']
OPTICS = ['沿用原表面', '材料优先（不透明）', surface_optics.DELEGATE]
HEADERS = ['墙体编号', '参考墙面编号', '楼层', '参考房间', '相邻环境或房间', '墙体类型',
           '参考面朝向', '净墙面积 m²', '原构造', '替换构造', '层序选择', '光学参数', '备注']
GENERAL_HEADERS = ['构件编号', '参考表面编号', '楼层', '参考房间', '相邻环境或房间', '构件类型',
                   '参考面朝向', '净面积 m²', '原构造', '替换构造', '层序选择', '光学参数', '备注']


def object_surfaces(model, obj):
    return model[obj.get('object_type','BuildingSurface:Detailed')]


def read(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def layer_names(construction):
    return [construction['outside_layer']] + [construction[f'layer_{i}'] for i in range(2, 11) if f'layer_{i}' in construction]


def polygon_area(points):
    normal = [sum(a[(i+1)%3]*b[(i+2)%3]-a[(i+2)%3]*b[(i+1)%3]
                  for a,b in zip(points, points[1:]+points[:1])) for i in range(3)]
    return math.sqrt(sum(n*n for n in normal))/2


def inventory(model=None, audit=None, tables=None, source_id='DEST-06'):
    model = model or read(BASE/'model.epJSON')
    audit = audit or read(BASE/'conversion-audit.json')
    rooms = {r['name']:r for r in audit['rooms']}
    cons_audit = {c['name']:c for c in audit['constructions']}
    tables = pathlib.Path(tables) if tables is not None else TABLES
    enclosures = {e['ID']:e for e in read(tables/'MAIN_ENCLOSURE.json')}
    source_surfaces = {s['SURFACE_ID']:s for s in read(tables/'SURFACE.json')}
    source_kinds = {1:'SYS_OUTWALL', 2:'SYS_INWALL'}
    opening_area = {}
    for opening in model.get('FenestrationSurface:Detailed', {}).values():
        pts = [[opening[f'vertex_{i}_{a}_coordinate'] for a in 'xyz'] for i in range(1, int(opening['number_of_vertices'])+1)]
        host = opening['building_surface_name']
        opening_area[host] = opening_area.get(host, 0) + polygon_area(pts)
    grouped = {}
    for s in audit['surfaces']:
        if s['type']=='Wall': grouped.setdefault(s['enclosure_id'], []).append(s)
    result = []
    for eid, faces in sorted(grouped.items()):
        faces.sort(key=lambda s:s['source_id'])
        ref = faces[0]; ep = model['BuildingSurface:Detailed'][ref['name']]
        if ep['outside_boundary_condition']=='Surface':
            if len(faces)!=2 or ep['outside_boundary_condition_object']!=faces[1]['name']:
                raise ValueError(f'E{eid}: 共用墙的两侧关联不完整。')
            other = model['BuildingSurface:Detailed'][faces[1]['name']]
            if other.get('outside_boundary_condition_object')!=ref['name']:
                raise ValueError(f'E{eid}: 共用墙不是双向关联。')
        elif len(faces)!=1 or ep['outside_boundary_condition']!='Outdoors':
            raise ValueError(f'E{eid}: 当前仅支持室外墙和房间之间的内墙。')
        pts = ref['vertices']; n = [sum(a[(i+1)%3]*b[(i+2)%3]-a[(i+2)%3]*b[(i+1)%3] for a,b in zip(pts,pts[1:]+pts[:1])) for i in range(3)]
        azimuth = math.degrees(math.atan2(n[0],n[1]))%360
        direction = ['北','东北','东','东南','南','西南','西','西北'][int((azimuth+22.5)//45)%8]
        source = enclosures[eid]; table = source_kinds[source['KIND']]
        orig = next(c for c in read(tables/(table+'.json')) if c['ID' if 'ID' in c else ('WALL_ID' if 'WALL_ID' in c else 'STRUCT_ID')]==source['CONSTRUCTION'])
        ca = cons_audit[ep['construction_name']]
        peer_id = source['SIDE2'] if source['SIDE1']==ref['source_id'] else source['SIDE1']
        optical_faces = []
        for slot, sid, environment in [('outside',peer_id,faces[1]['zone'] if len(faces)==2 else '室外'),
                                      ('inside',ref['source_id'],ref['zone'])]:
            ss = source_surfaces[sid]
            optical_faces.append({'slot':slot,'source_id':sid,'environment':environment,
                                  'position':('室外侧' if slot=='outside' else '室内侧') if len(faces)==1 else ('相邻房间侧' if slot=='outside' else '参考房间侧'),
                                  'solar_absorptance':ss['ABSORB_COEF'],'thermal_absorptance':ss['BLACKNESS'],
                                  'visible_absorptance':ss['ABSORB_COEF']})
        result.append({'id':f'E{eid}', 'enclosure_id':eid, 'surface':ref['name'], 'surfaces':[s['name'] for s in faces],
                       'floor':rooms[ref['zone']]['storey'], 'zone':ref['zone'],
                       'neighbor':faces[1]['zone'] if len(faces)==2 else '室外',
                       'kind':'内墙' if len(faces)==2 else '外墙', 'direction':direction,
                       'azimuth_deg':azimuth, 'area_m2':polygon_area(pts)-opening_area.get(ref['name'],0),
                       'base_construction':ep['construction_name'], 'base_name':orig.get('CNAME') or orig.get('NAME'),
                       'source_id':source_id, 'source_table':table, 'source_construction_id':source['CONSTRUCTION'], 'source_side':ca['side'],
                       'base_layers':ca['layers_outside_to_inside'],'optical_faces':optical_faces})
    return result


def model_version():
    # Include values and geometry of the immutable input model, not run-dependent paths.
    return fingerprint(read(BASE/'model.epJSON'))


def thermal_catalog(catalog):
    keys = ['id','name','category','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK',
            'solar_reflectance','longwave_emissivity','status']
    return {'materials':[{k:m.get(k) for k in keys} for m in catalog['materials']],
            'constructions':[{k:c.get(k) for k in ['id','name','category','orientation','layers','status','origins']} for c in catalog['constructions']]}


def label(construction):
    return f"{construction['name']} [{construction['id']}]"


def choices(catalog, extended=False):
    kinds=('外墙','内墙','屋顶','接地楼板','楼层间楼板','架空楼板','内门','外门') if extended else ('外墙','内墙')
    return [c for c in catalog['constructions'] if c['category'] in kinds and c['status']!='停用']


def find_value(sheet, name):
    found = [sheet.cell(c.row,c.column+1).value for row in sheet for c in row if c.value==name]
    if len(found)!=1: raise ValueError(f'{SHEET}：缺少或重复{name}，请刷新墙面输入表。')
    return found[0]


def parse_workbook(workbook, catalog, walls=None, allow_catalog_refresh=False, expected_model_version=None):
    names = [n for n in (SHEET, '围护构造') if n in workbook.sheetnames]
    if not names: return None
    if len(names) != 1: raise ValueError('墙面构造存在两个编辑入口，请保留对应版本的一张输入页。')
    sheet = workbook[names[0]]; walls = walls or inventory()
    version = expected_model_version if expected_model_version is not None else model_version()
    if find_value(sheet,'模型版本（自动）')!=version:
        raise ValueError('墙面分配表与当前几何模型版本不一致，需重新生成墙面清单。')
    lib_version = fingerprint(thermal_catalog(catalog))
    if not allow_catalog_refresh and find_value(sheet,'公共库版本（自动）')!=lib_version:
        raise ValueError('公共库已更新。请先运行“刷新构造选项.cmd”，核对构造后再计算。')
    general=any(c.value==GENERAL_HEADERS[0] for row in sheet for c in row)
    labels=GENERAL_HEADERS if general else HEADERS
    header_rows = [c.row for row in sheet for c in row if c.value==labels[0]]
    if len(header_rows)!=1: raise ValueError('墙面分配表表头缺失或重复。')
    hr = header_rows[0]; columns = [c for c in sheet[hr] if c.value in labels]
    cols = {HEADERS[labels.index(c.value)]:c.column for c in columns}
    if set(cols)!=set(HEADERS) or len(columns)!=len(HEADERS): raise ValueError('构造分配表缺少必要列或表头重复。')
    byid = {w['id']:w for w in walls}; available = {c['id']:c for c in choices(catalog,extended=general)}
    assignments = {}; rows = []
    for row in range(hr+1, sheet.max_row+1):
        values = {h:sheet.cell(row,cols[h]).value for h in HEADERS}
        wid = values['墙体编号']
        if wid in ('模型版本（自动）','公共库版本（自动）'): continue
        if wid is None:
            if any(values[h] is not None for h in HEADERS): raise ValueError(f'第{row}行有填写内容但缺少墙体编号。')
            continue
        if wid not in byid or wid in assignments: raise ValueError(f'墙体编号未知或重复：{wid}')
        w = byid[wid]
        expected = dict(zip(HEADERS[:9],[w['id'],w['surface'],w['floor'],w['zone'],w['neighbor'],w['kind'],w['direction'],w['area_m2'],w['base_name']]))
        for key,value in expected.items():
            if key=='净墙面积 m²':
                actual = values[key]
                if isinstance(actual,bool) or not isinstance(actual,(float,int)) or not math.isclose(actual,value,abs_tol=1e-7):
                    raise ValueError(f'{wid}: 净墙面积与几何模型不符。')
            elif values[key]!=value: raise ValueError(f'{wid}: 定位列“{key}”被修改或错位。')
        selection = values['替换构造']; direction = values['层序选择']; optics = values['光学参数']
        if direction not in ORDER or optics not in OPTICS: raise ValueError(f'{wid}: 请选择有效层序与光学参数选项。')
        cid = None
        if selection not in (None,'',KEEP):
            m = re.search(r'\[([A-Za-z][A-Za-z0-9_-]{2,79})\]$',str(selection))
            cid = m.group(1) if m else selection
            if cid not in available: raise ValueError(f'{wid}: 公共库中不存在或已停用该墙体构造：{selection}')
            c = available[cid]
            if not allow_catalog_refresh and selection not in (cid,label(c)):
                raise ValueError(f'{wid}: 构造名称与ID不一致，请从下拉选项重新选择。')
            if c['category']!=w['kind']: raise ValueError(f'{wid}: {w["kind"]}不能直接选用{c["category"]}构造。')
            validate_construction(c,catalog)
            resolve_order(w,c,direction)
        elif direction!='自动' or optics not in (OPTICS[0],surface_optics.DELEGATE):
            raise ValueError(f'{wid}: 保留原构造时，层序请选自动、光学参数请选沿用原表面。')
        assignments[wid] = {'id':wid,'construction_id':cid,'order':direction,'optics':optics,'notes':values['备注'] or ''}
        rows.append(assignments[wid])
    if set(assignments)!=set(byid): raise ValueError(f'墙面清单不完整，缺少：{sorted(set(byid)-set(assignments))}')
    result = {'model_version':version,'library_version':lib_version,'assignments':rows}
    face_settings = surface_optics.parse_workbook(workbook,walls)
    if face_settings is not None:
        if any(r['optics']!=surface_optics.DELEGATE for r in rows):
            raise ValueError('已有独立表面光学页，请保留构造表的自动光学标记，并在新页分别设置两侧。')
        result['face_settings'] = face_settings
    elif any(r['optics']==surface_optics.DELEGATE for r in rows):
        raise ValueError('墙面光学设置页缺失，请恢复完整输入表，不能删除该页。')
    return result


def load_assignments(path, catalog):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        wb = openpyxl.load_workbook(path,data_only=False)
    try: return parse_workbook(wb,catalog)
    finally: wb.close()


def number(value, name, minimum, maximum=None):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<minimum or (maximum is not None and value>maximum):
        raise ValueError(f'{name}：参数无效或超出允许范围。')
    return value


def validate_construction(c,catalog):
    layers = c['layers']; materials = {m['id']:m for m in catalog['materials']}
    if not 1<=len(layers)<=10 or [l['sequence'] for l in layers]!=list(range(1,len(layers)+1)):
        raise ValueError(f'{c["name"]}：应有1–10层，层序须连续。')
    for layer in layers:
        number(layer['thickness_mm'],'层厚度',1e-9)
        m = materials.get(layer['material_id'])
        if m is None or m['status']=='停用': raise ValueError('构造引用了不存在或停用的材料。')
        for key in ('conductivity_W_mK','density_kg_m3','specific_heat_J_kgK'): number(m[key],m['name']+key,1e-12)
        number(m['specific_heat_J_kgK'],m['name']+' 比热（EnergyPlus至少100）',100)
        for key in ('solar_reflectance','longwave_emissivity'):
            if m.get(key) is not None: number(m[key],m['name']+key,0,1)


def resolve_order(w,c,selection):
    if selection=='按库正序': return False,'用户指定库中第1层为远离参考房间的一侧'
    if selection=='按库倒序': return True,'用户指定库中最后1层为远离参考房间的一侧'
    if selection!='自动': raise ValueError('未知层序选择。')
    if c['orientation'] in ('EnergyPlus外侧至内侧','外侧至内侧','室外至室内'):
        return False,'公共库明确按外侧至内侧排列'
    source_match = any(o.get('source_id')==w.get('source_id','DEST-06') and o.get('table')==w['source_table'] and
                       str(o.get('original_id'))==str(w['source_construction_id']) for o in c.get('origins',[]))
    if c['orientation']=='DeST原层号顺序；应用面方向需核对' and source_match:
        return w['source_side']==1,'匹配本建筑原DeST构造，按来源表面方向转换'
    raise ValueError(f'{w["id"]} / {c["name"]}：无法自动确定层序。请核对层列表，再选择按库正序或按库倒序。')


def apply_assignments(model, inputs, catalog, walls=None, expected_model_version=None):
    """Validate everything on a copy; only commit after all replacements succeed."""
    walls = walls or inventory(); byid = {w['id']:w for w in walls}
    model_copy = copy.deepcopy(model)
    construction_byid = {c['id']:c for c in catalog['constructions']}
    materials = {m['id']:m for m in catalog['materials']}
    edits = {a['id']:a for a in inputs['assignments']} if inputs else {}
    report = []; layer_report = []; optical_report = []
    face_settings = inputs.get('face_settings') if inputs else None
    if face_settings is not None:
        expected_faces = {(w['id'],f['source_id']) for w in walls for f in w['optical_faces']}
        actual_faces = [(a['wall_id'],a['source_id']) for a in face_settings]
        if len(actual_faces)!=len(expected_faces) or set(actual_faces)!=expected_faces:
            raise ValueError('墙面光学设置：两侧清单不完整或重复。')
    for w in walls:
        setting = edits.get(w['id'],{'construction_id':None,'optics':OPTICS[0],'order':'自动','notes':''})
        door_custom=w['id'] in (inputs or {}).get('door_custom_ids',[])
        cid = setting['construction_id']; before = {s:object_surfaces(model,w)[s]['construction_name'] for s in w['surfaces']}
        order_note = '保留原层序'; warnings_ = []; per_layer = []
        if cid:
            c = construction_byid[cid]; validate_construction(c,catalog)
            reverse, order_note = resolve_order(w,c,setting['order'])
            layers = list(reversed(c['layers'])) if reverse else c['layers']
            old_names = layer_names(model['Construction'][before[w['surface']]])
            old_outer, old_inner = [model['Material'][old_names[i]] for i in (0,-1)]
            for i,l in enumerate(layers):
                m = materials[l['material_id']]
                if m['status'] in ('待核对','待补充'): warnings_.append(m['name']+'：'+m['status'])
                optical = old_outer if i==0 else old_inner
                props = {'roughness':optical['roughness'],'thickness':l['thickness_mm']/1000,
                         'conductivity':m['conductivity_W_mK'],'density':m['density_kg_m3'],
                         'specific_heat':m['specific_heat_J_kgK']}
                props.update({k:optical[k] for k in ('solar_absorptance','thermal_absorptance','visible_absorptance')})
                solar_basis = thermal_basis = '沿用原表面'
                if setting['optics']==OPTICS[1]:
                    if m.get('solar_reflectance') is not None:
                        props['solar_absorptance']=1-m['solar_reflectance']; solar_basis='公共材料反射率；按不透明材料 α=1−ρ'
                    else: solar_basis='公共材料缺值；沿用原表面'
                    if m.get('longwave_emissivity') is not None:
                        props['thermal_absorptance']=m['longwave_emissivity']; thermal_basis='公共材料全长波发射率'
                    else: thermal_basis='公共材料缺值；沿用原表面'
                # One material object has one set of optical properties for both faces.
                if len(layers)==1 and face_settings is None:
                    check = {k:old_inner[k] for k in ('solar_absorptance','thermal_absorptance','visible_absorptance')}
                    if setting['optics']==OPTICS[1]:
                        if m.get('solar_reflectance') is not None: check['solar_absorptance']=1-m['solar_reflectance']
                        if m.get('longwave_emissivity') is not None: check['thermal_absorptance']=m['longwave_emissivity']
                    if any(not math.isclose(props[k],v,abs_tol=1e-12) for k,v in check.items()):
                        raise ValueError(f'{w["id"]}: 单层构造无法同时保留两面不同的光学参数，请使用明确一致的材料表面参数。')
                name = f'Public_{w["id"]}_Layer{i+1}'
                model_copy.setdefault('Material',{})[name]=props
                per_layer.append({'name':name,'material_id':m['id'],'material_name':m['name'],'source_sequence':l['sequence'],
                                  'solar_basis':solar_basis,'thermal_basis':thermal_basis,'public_material':m,**props})
            names = [p['name'] for p in per_layer]
            for index,face in enumerate(w['surfaces']):
                ordered = names if index==0 else list(reversed(names))
                cname = f'Public_{w["id"]}_Side{index+1}'
                model_copy.setdefault('Construction',{})[cname] = {('outside_layer' if i==0 else f'layer_{i+1}'):n for i,n in enumerate(ordered)}
                object_surfaces(model_copy,w)[face]['construction_name']=cname
            if c['status'] in ('待核对','待补充'): warnings_.append(c['name']+'：'+c['status'])
        face_report = surface_optics.apply_wall(model_copy,w,face_settings,per_layer) if face_settings is not None else []
        optical_report.extend(face_report)
        for side,face in enumerate(w['surfaces']):
            ep = object_surfaces(model_copy,w)[face]; cname = ep['construction_name']
            zone = ep.get('zone_name') or model_copy['BuildingSurface:Detailed'][ep['building_surface_name']]['zone_name']
            names = layer_names(model_copy['Construction'][cname])
            report.append({'wall_id':w['id'],'surface':face,'zone':zone,'floor':w['floor'],'kind':w['kind'],
                           'reference_surface':w['surface'],'neighbor':w['neighbor'],'base_construction':before[face],
                           'base_name':w['base_name'],'effective_construction':cname,'construction_id':cid,
                           'effective_name':construction_byid[cid]['name'] if cid else ('项目自定义单层门' if door_custom else w['base_name']),
                           'action':'公共库替换' if cid else ('项目自定义单层门' if door_custom else KEEP), 'order_note':order_note if side==0 else '与参考面相反的层序',
                           'optics':setting['optics'],'warnings':sorted(set(warnings_)),
                           'layer_count':len(names),'resistance_m2K_W':sum(model_copy['Material'][n]['thickness']/model_copy['Material'][n]['conductivity'] for n in names),
                           'notes':setting['notes']})
            ordered_props = per_layer if side==0 else list(reversed(per_layer))
            for i,name in enumerate(names):
                p = model_copy['Material'][name]
                original = next((v for v in w['base_layers'] if all(math.isclose(v[k],p[k],abs_tol=1e-12) for k in ('conductivity','density','specific_heat','thickness'))),{})
                source = ordered_props[i] if cid else {'material_name':original.get('source_name',name),'material_id':None,'solar_basis':'DeST原值','thermal_basis':'DeST原值'}
                source = dict(source)
                slot = ('outside' if side==0 else 'inside') if i==0 else ('inside' if side==0 else 'outside') if i==len(names)-1 else None
                optical = next((f for f in face_report if f['slot']==slot),None)
                if optical:
                    source.update(solar_basis=optical['solar_basis'],thermal_basis=optical['thermal_basis'])
                layer_report.append({'wall_id':w['id'],'surface':face,'sequence':i+1,'ep_material':name,
                                     **{k:source[k] for k in ('material_id','material_name','solar_basis','thermal_basis')},**p})
    if inputs:
        if set(edits)!=set(byid): raise ValueError('墙面分配范围与模型不一致。')
        version = expected_model_version if expected_model_version is not None else model_version()
        if inputs['model_version']!=version or inputs['library_version']!=fingerprint(thermal_catalog(catalog)):
            raise ValueError('输入版本与模型或公共库不匹配。')
    for kind in ('Material','Construction','BuildingSurface:Detailed','FenestrationSurface:Detailed'):
        if kind in model_copy:model[kind]=model_copy[kind]
    return {'physical_component_count':len(walls),'physical_wall_count':sum(w['kind'] in ('外墙','内墙') for w in walls),
            'surface_count':len(report),'changed_wall_count':sum(bool(a['construction_id']) and byid[a['id']]['kind'] in ('外墙','内墙') for a in edits.values()),
            'surfaces':report,'layers':layer_report,'inputs':inputs,'optical_faces':optical_report,
            'optical_custom_face_count':sum(f['mode']=='自定义' for f in optical_report),
            'foundation_policy':'可替换接地楼板材料分层；Kiva基础边墙、土壤、周长和基础对象保持原设定。',
            'optical_policy':'有墙面光学设置页时按各物理面独立取值，否则沿用旧整墙选项；反射率按不透明材料换算；材料缺项沿用DeST原面。可见光吸收率保持原近似。'}


def export_audit(folder, audit):
    folder = pathlib.Path(folder)
    write(folder/'wall-assignment-audit.json',audit)
    columns = [('墙体编号','wall_id'),('墙面编号','surface'),('房间','zone'),('楼层','floor'),('类型','kind'),
               ('原构造','base_name'),('采用构造','effective_name'),('公共构造ID','construction_id'),('处理','action'),
               ('层序依据','order_note'),('光学参数','optics'),('层数','layer_count'),('材料层热阻 m²·K/W','resistance_m2K_W'),('备注','notes')]
    with (folder/'墙面构造核对.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow([c[0] for c in columns]);writer.writerows([[r.get(k) for _,k in columns] for r in audit['surfaces']])
    cols=[('墙体编号','wall_id'),('墙面编号','surface'),('外侧至内侧层序','sequence'),('材料','material_name'),('公共材料ID','material_id'),
          ('厚度 m','thickness'),('热导率 W/(m·K)','conductivity'),('密度 kg/m³','density'),('比热 J/(kg·K)','specific_heat'),
          ('太阳吸收率','solar_absorptance'),('全长波吸收率','thermal_absorptance'),('太阳参数来源','solar_basis'),('长波参数来源','thermal_basis')]
    with (folder/'墙面实际分层.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow([c[0] for c in cols]);writer.writerows([[r.get(k) for _,k in cols] for r in audit['layers']])
    if audit.get('optical_faces'):
        cols = [('墙体编号','wall_id'),('DeST表面编号','source_id'),('位置','position'),('连接环境或房间','environment'),
                ('参数来源','mode'),('DeST太阳反射率','source_solar_reflectance'),('DeST全长波发射率','source_longwave_emissivity'),
                ('最终太阳反射率','solar_reflectance'),('最终太阳吸收率','solar_absorptance'),('最终全长波发射率','longwave_emissivity'),
                ('太阳参数依据','solar_basis'),('长波参数依据','thermal_basis'),('EP材料','ep_material'),('备注','notes')]
        with (folder/'墙面光学核对.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow([c[0] for c in cols]);writer.writerows([[r.get(k) for _,k in cols] for r in audit['optical_faces']])
    if any(r['kind'] not in ('外墙','内墙') for r in audit['surfaces']):
        wall_ids={r['wall_id'] for r in audit['surfaces'] if r['kind'] in ('外墙','内墙')}
        for old,new in [('墙面构造核对.csv','围护构造核对.csv'),('墙面实际分层.csv','围护实际分层.csv'),('墙面光学核对.csv','表面光学核对.csv')]:
            with (folder/old).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
            with (folder/new).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f);writer.writerow([h.replace('墙体编号','构件编号').replace('墙面编号','EP表面编号').replace('DeST表面编号','物理表面编号').replace('DeST太阳','源太阳').replace('DeST全长波','源全长波') for h in rows[0]]);writer.writerows(rows[1:])
            with (folder/old).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f);writer.writerow(rows[0]);writer.writerows(r for r in rows[1:] if r[0] in wall_ids)


def verify_models(folder):
    folder=pathlib.Path(folder); audit=read(folder/'wall-assignment-audit.json'); base=read(BASE/'model.epJSON')
    results=[]
    for case in ('natural','controlled'):
        model=read(folder/case/'model.epJSON')
        for r in audit['surfaces']:
            s=model['BuildingSurface:Detailed'][r['surface']]; old=base['BuildingSurface:Detailed'][r['surface']]
            if {k:v for k,v in s.items() if k!='construction_name'}!={k:v for k,v in old.items() if k!='construction_name'}:
                raise ValueError('墙面几何或边界被意外修改。')
            if s['construction_name']!=r['effective_construction']: raise ValueError('实际墙面构造与核对清单不同。')
            if s['outside_boundary_condition']=='Surface' and r['construction_id']:
                peer=model['BuildingSurface:Detailed'][s['outside_boundary_condition_object']]
                if layer_names(model['Construction'][s['construction_name']])!=list(reversed(layer_names(model['Construction'][peer['construction_name']]))):
                    raise ValueError('共用内墙两面层序不一致。')
        for l in audit['layers']:
            p=model['Material'][l['ep_material']]
            if any(not math.isclose(p[k],l[k],abs_tol=1e-12) for k in ('thickness','conductivity','density','specific_heat','solar_absorptance','thermal_absorptance')):
                raise ValueError('实际材料物性与核对清单不同。')
        if model.get('FenestrationSurface:Detailed')!=base.get('FenestrationSurface:Detailed'): raise ValueError('门窗被意外修改。')
        results.append({'case':case,'surfaces_checked':len(audit['surfaces']),'layers_checked':len(audit['layers'])})
    write(folder/'wall-assignment-verification.json',{'passed':True,'checks':results})
    return results


def verify_engine_materials(folder):
    """Compare engine-reported material values at its displayed precision."""
    folder=pathlib.Path(folder);audit=read(folder/'wall-assignment-audit.json');results=[]
    indexes={'thickness':4,'conductivity':5,'density':6,'specific_heat':7,
             'thermal_absorptance':8,'solar_absorptance':9,'visible_absorptance':10}
    for case in ('natural','controlled'):
        model = read(folder/case/'model.epJSON')
        rows=list(csv.reader((folder/case/'run/eplusout.eio').read_text(encoding='utf-8',errors='replace').splitlines()))
        headers=[s.strip() for s in next(r for r in rows if r and r[0].strip()=='! <Material Details>')]
        reported={r[1].strip().casefold():r for r in rows if r and r[0].strip()=='Material Details'}
        count=0
        for layer in audit['layers']:
            r=reported.get(layer['ep_material'].casefold())
            if r is None:raise ValueError('引擎未报告材料：'+layer['ep_material'])
            for key,index in indexes.items():
                token=r[index].strip();num=decimal.Decimal(token)
                tolerance=max(1e-10,0.51*10**num.as_tuple().exponent)
                if abs(float(num)-layer[key])>tolerance:
                    raise ValueError(f'引擎实际材料参数不符：{layer["ep_material"]} {key}')
                count+=1
            # 26.2 appends inside-face optics; blank inputs inherit outer values.
            props=model['Material'][layer['ep_material']]
            for key,label in [('thermal','Thermal'),('solar','Solar'),('visible','Visible')]:
                header='Absorptance:'+label+':InsideFace'
                if header not in headers:continue # historical 26.1 EIO
                field=key+'_absorptance'
                expected=props.get(field+'_inside_face',props[field])
                num=decimal.Decimal(r[headers.index(header)].strip())
                tolerance=max(1e-10,0.51*10**num.as_tuple().exponent)
                if abs(float(num)-expected)>tolerance:
                    raise ValueError(f'引擎内侧材料参数不符：{layer["ep_material"]} {field}')
                count+=1
        for face in audit.get('optical_faces',[]):
            surfaces=model['BuildingSurface:Detailed'] if face['reference_surface'] in model['BuildingSurface:Detailed'] else model['FenestrationSurface:Detailed']
            con = model['Construction'][surfaces[face['reference_surface']]['construction_name']]
            actual = layer_names(con)[0 if face['slot']=='outside' else -1]
            if actual!=face['ep_material']:
                raise ValueError('光学表面与最终构造端点未对应：'+str(face['source_id']))
            props=model['Material'][actual]
            if any(not math.isclose(props.get(k+'_inside_face',props[k]) if face['slot']!='outside' else props[k],face[k],abs_tol=1e-12) for k in surface_optics.KEYS):
                raise ValueError('最终模型的表面光学参数不符：'+str(face['source_id']))
        results.append({'case':case,'material_property_comparisons':count,'physical_optical_faces_checked':len(audit.get('optical_faces',[])),
                        'tolerance':'按eio报告的小数精度验证；物理表面与构造端点另按完整精度核对'})
    write(folder/'wall-engine-verification.json',{'passed':True,'checks':results})
    return results
