"""Regional membership and aggregation are independent of station display names."""
import unittest
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from accdb_conversion import building_weather_site
from comparison_results import paired_station_geography
from plot_regional import aggregate, province_groups
from weather_quality import station_geography


class ProvinceMaps(unittest.TestCase):
    def test_station_coordinates_follow_verified_weather_not_the_building_or_display_name(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'station.epw'
            raw=b'\xef\xbb\xbfLOCATION,"Changsha, station",Hunan,CHN,CSWD,576870,28.22,112.92,8,68\r\n'
            path.write_bytes(raw)
            checksum=hashlib.sha256(raw).hexdigest()
            ref=dict(path=str(path),sha256=checksum)
            case=dict(weather_sha256=checksum)
            site=dict(name='Different city',weather=ref)
            expected=dict(latitude=28.22,longitude=112.92,country='CHN')
            self.assertEqual(station_geography(path,checksum),expected)
            imported=building_weather_site('building',site,path)
            self.assertEqual({k:imported[k] for k in expected},expected)
            self.assertIsNone(imported['climate'])
            self.assertEqual(paired_station_geography(site,case,case,{},{}),expected)
            self.assertEqual(paired_station_geography({},case,case,{},{checksum:path}),expected)
            self.assertEqual(paired_station_geography(site,case,dict(weather_sha256='other'),{},{}),{})
            path.write_bytes(raw.replace(b'28.22',b'98.22'))
            self.assertEqual(paired_station_geography(site,case,case,{},{}),{})
            self.assertEqual(station_geography(path,hashlib.sha256(path.read_bytes()).hexdigest()),{})
            path.unlink()
            self.assertEqual(paired_station_geography(site,case,case,{},{}),{})

    def test_membership_holes_and_outside_sites_keep_their_original_rows(self):
        shell=[[0,0],[4,0],[4,4],[0,4],[0,0]]
        hole=[[1,1],[1,2],[2,2],[2,1],[1,1]]
        coords=[(.5,.5),(1.5,1.5),(5,5),(None,None),(.25,.25)]
        sites=[dict(site_id=str(i),city='同名地点',status='paired',longitude=x,latitude=y,
                    total_saved_kWh=i-2,total_saved_percent=None if i==0 else 6)
               for i,(x,y) in enumerate(coords)]
        membership=province_groups(sites,{'110000':[[shell,hole]]})
        self.assertEqual(membership,{'0':'110000','4':'110000'})
        groups,rows=aggregate(dict(classes=[],sites=sites,conditioned_area_m2=2),'china','total',{},membership)
        self.assertEqual(len(rows),5)
        self.assertEqual([r['group'] for r in rows],['110000',None,None,None,'110000'])
        self.assertEqual(groups['110000'],dict(group='110000',sites=2,percent_sites=1,percent=6,kWh_m2=0,MJ_m2=0))
