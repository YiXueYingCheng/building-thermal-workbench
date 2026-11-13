"""Independent mapping/result checks. No EnergyPlus process is launched."""
import math
from foundation import now, sha
from contracts import validate
from legacy_import import to_legacy_record

def verify_catalog(catalog):
    if catalog.get('catalog_kind')=='standalone_v1':return verify_standalone(catalog)
    checks=[];failures=[]
    def check(condition,label):
        checks.append(label)
        if not condition:failures.append(label)
    check(len(catalog['records'])==len(catalog['roundtrips'])+2,'旧方案与两个全球参考方案全部登记')
    for record in catalog['records'].values():
        check(not validate(record,catalog['sites']),'方案结构有效：'+record['id'])
        if record['provenance']['adapter']=='legacy_plan_v011':
            check(to_legacy_record(record)==record['provenance']['original'],'旧方案逐字段往返一致：'+record['id'])
    bundle=catalog['global_bundle'];data=bundle['historical']['dataset']
    by_site={s['site_id']:s for s in data['sites']}
    grouped={c['climate']:[] for c in data['classes']}
    area=data['conditioned_area_m2']
    for site_id,site in catalog['sites'].items():
        if site.get('source_kind')!='reviewed_global' or not site.get('eligible'):continue
        pairs={case:bundle['jobs'][site_id+'|'+case] for case in ('W00','FIXED_COOL_LOW7')}
        old=by_site[site_id]
        values={}
        for case,job in pairs.items():
            for quantity in ('heating','cooling','total'):
                expected=old[case+'_'+quantity+'_kWh']
                check(math.isclose(job['annual'][quantity+'_kWh'],expected,rel_tol=0,abs_tol=1e-8),'地点年度数值一致：'+site_id+'/'+case+'/'+quantity)
            for quantity in ('heating','cooling'):
                total=sum(m[quantity+'_kWh'] for m in job['monthly'])
                check(math.isclose(total,job['annual'][quantity+'_kWh'],rel_tol=1e-9,abs_tol=1e-5),'月年一致：'+site_id+'/'+case+'/'+quantity)
        for quantity in ('heating','cooling','total'):
            value=(pairs['W00']['annual'][quantity+'_kWh']-pairs['FIXED_COOL_LOW7']['annual'][quantity+'_kWh'])*3.6/area
            values[quantity]=value
            check(math.isclose(value,old[quantity+'_saved_MJ_m2'],rel_tol=0,abs_tol=1e-8),'单位与差值一致：'+site_id+'/'+quantity)
        grouped[site['climate']].append(values)
    for row in data['classes']:
        values=grouped[row['climate']]
        check(len(values)==row['validated_sites'],'气候样本数一致：'+row['climate'])
        for quantity in ('heating','cooling','total'):
            for stat,fn in [('mean',lambda x:sum(x)/len(x)),('min',min),('max',max)]:
                expected=row[quantity+'_saved_MJ_m2_'+stat]
                actual=fn([v[quantity] for v in values]) if values else None
                check(actual is None and expected is None or actual is not None and expected is not None and math.isclose(actual,expected,rel_tol=0,abs_tol=1e-8),
                    '气候汇总一致：'+row['climate']+'/'+quantity+'/'+stat)
    changed=[];available=0
    for path,entry in catalog['protection'].items():
        if not entry['sha256']:continue
        available+=1
        try:
            if sha(path)!=entry['sha256']:changed.append(path)
        except OSError:changed.append(path)
    check(not changed,'所有已核对来源保持不变')
    historical_mismatches=[]
    for r in catalog['records'].values():
        for ref in r['provenance']['source_refs']:
            if ref['status']!='verified':historical_mismatches.append(dict(record_id=r['id'],path=ref['path'],status=ref['status']))
    for ref in bundle['source_refs']:
        if ref['status']!='verified':historical_mismatches.append(dict(record_id='global_references',path=ref['path'],status=ref['status']))
    return dict(created=now(),passed=not failures,check_count=len(checks),failures=failures,
        imported_records=len(catalog['records']),active_records=sum(not r['archived'] for r in catalog['records'].values()),
        legacy_roundtrips=len(catalog['roundtrips']),global_cases=len(bundle['jobs']),
        protected_sources=available,changed_sources=changed,historical_source_mismatches=historical_mismatches,
        historical_results='annual_monthly_and_climate_values_matched',new_simulations=0,
        numerical_equivalence='not_claimed_no_new_simulation')

def verify_standalone(catalog):
    """Check imported records and their exact dependencies, with no historical claim."""
    from model_adapter import VerifiedReader
    reader=VerifiedReader(catalog);failures=[];checks=0;refs={}
    def collect(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
                refs[(value['path'],value['sha256'])]=value
            for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    for record in catalog['records'].values():
        checks+=1;failures.extend(record['id']+'：'+e for e in validate(record,catalog['sites']))
        for path,checksum in record.get('numerics',{}).get('engine_files',{}).items():
            refs[(path,checksum)]=dict(path=path,sha256=checksum)
    collect(catalog.get('ordinary_buildings',{}));collect(catalog['sites']);collect(catalog.get('example_bundle',{}))
    collect(catalog.get('example_controls',{}))
    for ref in refs.values():
        checks+=1
        try:reader.check(ref)
        except (OSError,ValueError) as error:failures.append(str(error))
    try:reader.unchanged()
    except (OSError,ValueError) as error:failures.append(str(error))
    return dict(created=now(),passed=not failures,check_count=checks,failures=failures,
        imported_records=len(catalog['records']),active_records=sum(not r['archived'] for r in catalog['records'].values()),
        legacy_roundtrips=0,global_cases=0,protected_sources=len(refs),new_simulations=0,
        historical_results='not_applicable',numerical_equivalence='not_claimed_no_new_simulation')
