"""Read-only check of openings against DeST physical room-side wall polygons.

This supplements the previous middle-plane checks. No geometry is changed.
"""
import json
import argparse
import math
import pathlib
import datetime

PROJECT=pathlib.Path(__file__).resolve().parents[1]
WORKSPACE=PROJECT.parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--tables',type=pathlib.Path,default=WORKSPACE/'work/dest-compatibility/tables/TEST.accdb')
parser.add_argument('--output',type=pathlib.Path,default=PROJECT/'results/dest-compatibility/TEST_20260909')
args=parser.parse_args()
TABLES=args.tables;OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
def read(t):return json.loads((TABLES/(t+'.json')).read_text(encoding='utf-8-sig'))
def keyed(t,k):return {r[k]:r for r in read(t)}
def sub(a,b):return [x-y for x,y in zip(a,b)]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def length(a):return math.sqrt(dot(a,a))
def normal(v):return [sum(cross(a,b)[i] for a,b in zip(v,v[1:]+v[:1])) for i in range(3)]
g=keyed('GEOMETRY','GEOMETRY_ID');pts=keyed('POINT','POINT_ID');lp=read('LOOP_POINT')
s=keyed('SURFACE','SURFACE_ID');e=keyed('MAIN_ENCLOSURE','ID');rooms=keyed('ROOM','ID')
def vertices(gid):
    loop=g[gid]['BOUNDARY_LOOP_ID']
    return [[pts[r['POINT']][x] for x in ['X','Y','Z']] for r in sorted([r for r in lp if r['LOOP_ID']==loop],key=lambda r:r['POINT_NO'])]
results=[]
for t in ['DOOR','WINDOW']:
    for obj in read(t):
        enclosure=e[obj['OF_ENCLOSURE']]
        for side in [1,2]:
            face=s[obj['SIDE'+str(side)]]
            if face['OF_ROOM'] not in rooms:continue
            host=next(s[enclosure['SIDE'+str(i)]] for i in [1,2] if s[enclosure['SIDE'+str(i)]]['OF_ROOM']==face['OF_ROOM'])
            wall=vertices(host['GEOMETRY']);opening=vertices(face['GEOMETRY'])
            n=normal(wall);n=[v/length(n) for v in n]
            planes=[]
            for p,q in zip(wall,wall[1:]+wall[:1]):
                inward=cross(n,sub(q,p));inward=[x/length(inward) for x in inward]
                assert min(dot(sub(w,p),inward) for w in wall)>-1e-7,'This checker requires a convex host'
                planes.append((p,inward))
            distances=[[dot(sub(v,p),iv) for p,iv in planes] for v in opening]
            penetration=max(0,-min(d for row in distances for d in row))
            coplanarity=max(abs(dot(sub(v,wall[0]),n)) for v in opening)
            results.append({'kind':t,'object_id':obj['ID'],'surface_id':face['SURFACE_ID'],'zone':rooms[face['OF_ROOM']]['NAME'],
                'host_enclosure_id':enclosure['ID'],'host_surface_id':host['SURFACE_ID'],'side':side,
                'opening_vertices_m':opening,'physical_host_vertices_m':wall,
                'maximum_outside_host_distance_mm':penetration*1000,'maximum_plane_distance_mm':coplanarity*1000,
                'inside_physical_host':penetration<1e-6 and coplanarity<1e-6})
expected_count=sum(s[obj['SIDE'+str(side)]]['OF_ROOM'] in rooms for table in ['DOOR','WINDOW'] for obj in read(table) for side in [1,2])
assert len(results)==expected_count
failures=[r for r in results if not r['inside_physical_host']]
data={'date':datetime.date.today().isoformat(),'method':'Convex half-space containment on DeST room-side surface geometry, not middle-plane geometry; boundary tolerance 1 micrometre.',
      'checked_room_side_openings':len(results),'out_of_boundary_count':len(failures),'results':results}
(OUT/'physical-opening-check.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'checked':len(results),'failures':[{k:r[k] for k in ['kind','object_id','zone','maximum_outside_host_distance_mm']} for r in failures]},ensure_ascii=False))
