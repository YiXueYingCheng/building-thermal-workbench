"""Read-only plans from verified source polygons; never generate or edit inputs.

Polygon/label/normal helpers adapted from the original platform geometry_view.py.
World coordinates and zero north axis are intentionally the supported contract.
"""
import copy
import math
from foundation import digest,now


def vertices(surface):
    if 'vertices' in surface:
        points=[[v['vertex_'+c+'_coordinate'] for c in 'xyz'] for v in surface['vertices']]
    else:
        points=[[surface[f'vertex_{i}_{c}_coordinate'] for c in 'xyz'] for i in range(1,int(surface['number_of_vertices'])+1)]
    if len(points)<3 or any(type(x) not in (int,float) or not math.isfinite(x) for p in points for x in p):
        raise ValueError('顶点坐标无效。')
    return points


def area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1]))/2)


def label_point(poly):
    ys=sorted(set(p[1] for p in poly));best=None
    for lo,hi in zip(ys,ys[1:]):
        y=(lo+hi)/2;xs=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            if (a[1]>y)!=(b[1]>y):xs.append(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]))
        xs.sort()
        for left,right in zip(xs[::2],xs[1::2]):
            if best is None or right-left>best[0]:best=(right-left,[(left+right)/2,y])
    if best is None:raise ValueError('无法确定房间内部标注位置。')
    return best[1]


def segment(points):
    xy=[]
    for x,y,_ in points:
        if not any(math.hypot(x-a,y-b)<1e-7 for a,b in xy):xy.append([x,y])
    if len(xy)!=2 or math.dist(*xy)<1e-7:raise ValueError('不是可明确投影的竖直面。')
    return xy


def normal(points):
    n=[0.,0.,0.]
    for a,b in zip(points,points[1:]+points[:1]):
        n[0]+=(a[1]-b[1])*(a[2]+b[2]);n[1]+=(a[2]-b[2])*(a[0]+b[0]);n[2]+=(a[0]-b[0])*(a[1]+b[1])
    return n


def build(model,settings):
    rules=list(model.get('GlobalGeometryRules',{}).values())
    if len(rules)!=1 or rules[0].get('coordinate_system')!='World' or rules[0].get('vertex_entry_direction')!='Counterclockwise':
        raise ValueError('此坐标或顶点规则尚未接入平面查看；请沿用原参数核对。')
    buildings=list(model.get('Building',{}).values())
    if len(buildings)!=1 or not math.isfinite(float(buildings[0].get('north_axis',0))) or abs(float(buildings[0].get('north_axis',0)))>1e-8:
        raise ValueError('非零建筑北轴尚未接入平面查看。')
    surfaces=model['BuildingSurface:Detailed'];zones=model['Zone'];rooms=[];walls=[];openings=[];warnings=[]
    if {r['zone'] for r in settings}!=set(zones) or len(settings)!=len(zones):
        raise ValueError('房间配置与模型热区不一一对应。')
    for setting in settings:
        zone=setting['zone'];polygons=[];elevations=[];floor_ids=[]
        for ident,s in surfaces.items():
            if s.get('zone_name')!=zone or s.get('surface_type')!='Floor':continue
            xyz=vertices(s)
            if max(p[2] for p in xyz)-min(p[2] for p in xyz)>1e-6:raise ValueError(zone+' 含倾斜地面，暂不能绘制平面。')
            poly=[p[:2] for p in xyz]
            if area(poly)<1e-8:raise ValueError(zone+' 地面投影面积无效。')
            polygons.append(poly);elevations.append(xyz[0][2]);floor_ids.append(ident)
        if not polygons or max(elevations)-min(elevations)>1e-6:raise ValueError(zone+' 缺少单一地面标高，暂不能明确分层。')
        projected=sum(area(p) for p in polygons)
        if abs(projected-setting['area_m2'])>max(.01,.001*setting['area_m2']):warnings.append(zone+' 输入面积与投影面积不同，分别保留。')
        if zones[zone].get('multiplier',1)!=1:warnings.append(zone+' 含热区倍数；图中仅绘制原几何。')
        rooms.append(dict(id=setting['id'],zone=zone,area_m2=setting['area_m2'],conditioned=setting['conditioned'],polygons=polygons,
                          floor_surfaces=floor_ids,elevation=elevations[0],projected_area_m2=projected,label=label_point(max(polygons,key=area))))
    levels=[]
    for r in sorted(rooms,key=lambda r:r['elevation']):
        if not levels or abs(r['elevation']-levels[-1])>1e-6:levels.append(r['elevation'])
        r['floor']=len(levels)-1
    by_zone={r['zone']:r for r in rooms};unplotted=[]
    for ident,s in surfaces.items():
        if s.get('surface_type')!='Wall':continue
        r=by_zone[s['zone_name']];xyz=vertices(s)
        try:line=segment(xyz)
        except ValueError as e:unplotted.append(ident);warnings.append(ident+'：'+str(e));continue
        n=normal(xyz);angle=math.degrees(math.atan2(n[0],n[1]))%360;gross=math.sqrt(sum(x*x for x in n))/2
        if gross<1e-8:raise ValueError(ident+' 墙面面积无效。')
        holes=[(k,h) for k,h in model.get('FenestrationSurface:Detailed',{}).items() if h.get('building_surface_name')==ident]
        hole_area=sum(math.sqrt(sum(x*x for x in normal(vertices(h))))/2 for _,h in holes)
        if hole_area>gross+1e-6:raise ValueError(ident+' 洞口面积超过墙面面积。')
        walls.append(dict(id=ident,room_id=r['id'],zone=r['zone'],floor=r['floor'],line=line,exterior=s['outside_boundary_condition']=='Outdoors',
                          boundary=s['outside_boundary_condition'],pair=s.get('outside_boundary_condition_object') if s['outside_boundary_condition']=='Surface' else None,
                          construction=s['construction_name'],azimuth=angle,direction=['北','东北','东','东南','南','西南','西','西北'][int((angle+22.5)//45)%8],
                          gross_area_m2=gross,net_area_m2=max(0,gross-hole_area)))
        for name,h in holes:
            try:line_h=segment(vertices(h))
            except ValueError as e:warnings.append(name+' 洞口：'+str(e));continue
            openings.append(dict(id=name,host=ident,floor=r['floor'],line=line_h,kind=h['surface_type']))
    floors=[]
    for i,z in enumerate(levels):
        on=[r for r in rooms if r['floor']==i];points=[p for r in on for poly in r['polygons'] for p in poly]
        points += [p for w in walls if w['floor']==i for p in w['line']]
        floors.append(dict(id=i,elevation=z,room_count=len(on),bounds=[min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]))
    return dict(rooms=rooms,walls=walls,openings=openings,floors=floors,warnings=warnings,unplotted_walls=unplotted,
                counts=dict(rooms=len(rooms),floors=len(floors),exterior_walls=sum(w['exterior'] for w in walls),exterior_net_area_m2=sum(w['net_area_m2'] for w in walls if w['exterior'])))


def describe(record,catalog):
    adapter=record.get('provenance',{}).get('adapter')
    if adapter not in ('global_frozen_v011','ordinary_building_v1'):
        return dict(supported=False,note='此旧来源的几何尚未接入本页，请沿用原配置核对。')
    from building_configuration import baseline
    from model_adapter import VerifiedReader
    building=copy.deepcopy(record['factors']['building']);building.pop('usage_profile',None);building.pop('envelope_overrides',None);building.pop('library_constructions',None)
    expected=(catalog['records']['global_w00']['factors']['building'] if adapter=='global_frozen_v011' else catalog['ordinary_buildings'][building['id']]['building'])
    if building!=expected:raise ValueError('建筑身份或几何来源已改变，请先核对来源。')
    reader=VerifiedReader(catalog);base,m,job=baseline(catalog,reader,building['id'])
    if record['factors']['building'].get('library_constructions'):
        from construction_library import apply
        apply(m,record)
    result=build(m,base['rooms']);reader.unchanged()
    return dict(result,supported=True,checked_at=now(),record_id=record['id'],revision=record['revision'],building_id=building['id'],building_name=building['name'],
                source_sha256=job['model'].get('expected_sha256') or job['model']['sha256'],geometry_sha256=digest(result),
                note='按地面标高由低到高分层，北向朝上；图中为模型表面投影，不含真实墙厚。房间颜色表示原空调归属，本次运行模式由工况确定。材料标记读取当前页面的方案设置。')
