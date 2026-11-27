"""Build map assets once from the supplied 2022 SHP/DBF/SHX/PRJ (pyshp, shapely, pyproj)."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import shapefile
from shapely.geometry import shape
from shapely.geometry.polygon import orient


def rings(geom, inverse):
    polys = geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]
    output = []
    for poly in polys:
        poly = orient(poly)
        coords = []
        for ring in (poly.exterior, *poly.interiors):
            x, y = inverse.transform(*ring.xy)
            coords.append(np.column_stack((x, y)).round(6).tolist())
        output.append(coords)
    return output


def convert(source, out):
    crs = CRS.from_wkt(source.with_suffix('.prj').read_text())
    inverse = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    display, full = {}, {}
    with shapefile.Reader(str(source), encoding='gbk') as reader:
        for item in reader.iterShapeRecords():
            name, code = item.record['省'], str(item.record['省代码'])
            geom = shape(item.shape.__geo_interface__)
            if not geom.is_valid or code in full:
                raise ValueError(name)
            full[code] = rings(geom, inverse)
            display[code] = dict(names=[name],polygons=rings(geom.simplify(180, preserve_topology=True),inverse))
    if len(display) != 34:
        raise ValueError('Unexpected province count')
    for name, data in [('china-provinces', display), ('china-membership', full)]:
        payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
        (out/(name+'.json.gz')).write_bytes(gzip.compress(payload,compresslevel=9,mtime=0))
    print(hashlib.sha256(source.read_bytes()).hexdigest(),len(display))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('shp',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    convert(args.shp,args.output)
