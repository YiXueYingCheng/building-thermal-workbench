"""Portable, plot-ready Origin tables for the exact selected map and metric."""
import csv
import json

import numpy as np
from PIL import Image, ImageDraw

from plot_regional import climate_raster, scale, transform


def table(path, header, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        w=csv.writer(stream)
        w.writerow(header)
        w.writerows(rows)


def write(folder,data,division,curved,metric,regions,extent,summary,sites):
    xmin,xmax,ymin,ymax=extent
    if division=='climate':
        assets=json.loads((folder/'map.json').read_text(encoding='utf8'))
        classes=sorted(data['classes'], key=lambda row:row['id'])
        keys=[c['climate'] for c in classes]
        labels=[c['name'] for c in classes]
        lut=np.zeros(256,dtype=int)
        for i,c in enumerate(classes,1):
            lut[c['id']]=i
        grid=lut[climate_raster(assets,curved)]
        borders=[transform(r,curved) for p in assets['land']['coordinates'] for r in p]
    else:
        keys=sorted(regions)
        labels=[regions[k]['names'][-1] for k in keys]
        width=1080
        height=round(width*(ymax-ymin)/(xmax-xmin))
        grid=np.zeros((height,width),dtype=int)
        borders=[]
        for i,code in enumerate(keys,1):
            mask=Image.new('1',(width,height))
            draw=ImageDraw.Draw(mask)
            for polygon in regions[code]['polygons']:
                for j,ring in enumerate(polygon):
                    xy=transform(ring,curved,division)
                    borders.append(xy)
                    pixels=np.column_stack(((xy[:,0]-xmin)*width/(xmax-xmin)-.5,
                                            (ymax-xy[:,1])*height/(ymax-ymin)-.5))
                    draw.polygon(list(map(tuple,pixels)),fill=int(j==0))
            grid[np.asarray(mask)]=i
    if curved and division!='china':
        angle=np.linspace(0,2*np.pi,721)
        borders.append(np.column_stack((xmax*np.cos(angle),ymax*np.sin(angle))))
    height,width=grid.shape
    np.savetxt(folder/'origin-grid.csv',grid[::-1],fmt='%d',delimiter=',')
    def lines():
        for ring in borders:
            yield from ring.round(7)
            yield ('','')
    table(folder/'origin-borders.csv',['X','Y'],lines())
    table(folder/'origin-values.csv',['id','group','name','percent','kWh_m2','MJ_m2','sites','percent_sites'],
          ((i,k,n,*(summary.get(k,{}).get(f) for f in ('percent','kWh_m2','MJ_m2')),
            summary.get(k,{}).get('sites',0),summary.get(k,{}).get('percent_sites',0))
           for i,(k,n) in enumerate(zip(keys,labels),1)))
    stations=[s for s in sites if s['group'] and s['longitude'] is not None and s['latitude'] is not None
              and abs(s['longitude'])<=180 and abs(s['latitude'])<=90]
    table(folder/'origin-stations.csv',['X','Y','city','group','percent','kWh_m2','MJ_m2'],
          ((*transform([[s['longitude'],s['latitude']]],curved,division)[0],s['city'],s['group'],s['percent'],
            s['kWh_m2'],s['kWh_m2']*3.6) for s in stations))
    styles={}
    for field in (['percent','kWh_m2'] if curved else ['MJ_m2']):
        cmap,norm=scale([s[field] for s in summary.values()],not curved)
        if not curved and division=='climate':
            from result_exports import color_limit
            norm.vmin,norm.vmax=-color_limit(data),color_limit(data)
        styles[field]=dict(limits=[norm.vmin,norm.vmax],palette=(cmap(np.linspace(0,1,256))[:,:3]*255).round().astype(int).tolist())
    dx,dy=(xmax-xmin)/width/2,(ymax-ymin)/height/2
    spec=dict(division=division,metric=metric,style='pair' if curved else 'standard',extent=list(extent),
              centres=[xmin+dx,xmax-dx,ymin+dy,ymax-dy],height=height,width=width,fields=styles,
              dataset_sha256=data['dataset_sha256'])
    (folder/'origin-map.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf8')
