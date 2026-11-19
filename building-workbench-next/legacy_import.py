"""Read-only migration of v0.11 records. Never import legacy execution modules."""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path
from foundation import Sources, digest, now, sha
from contracts import validate, recipe_digest
from workbook_reader import material_card

PROJECT_NAMES={'drawing26':'Drawing26 参考建筑','building2':'五层建筑','dynamic':'Drawing26 动态材料研究'}

def base_record(ident,name,snapshot,kind):
    return dict(schema_version=1,id=ident,revision='source_'+snapshot[:16],name=name,status='imported',archived=False,
        factors=dict(building={},materials=dict(definitions=[],applications=[]),
            condition=dict(operation=dict(mode='inherited'),controls=[],reference_runs=[]),
            scope=dict(site_ids=[],period=[1,1,12,31],aggregation=dict(kind='site_results'))),
        numerics=dict(step_minutes=5),execution=dict(profile='balanced',max_parallel=4),
        provenance=dict(adapter=kind,snapshot_id=snapshot,source_refs=[],notes=[]))

def legacy_fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def policy_from_source(path):
    for node in ast.parse(Path(path).read_text(encoding='utf-8-sig')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POLICY' for t in node.targets):
            if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='dict':
                return {k.arg:ast.literal_eval(k.value) for k in node.value.keywords}
    return None

class Importer:
    def __init__(self, cfg):
        self.cfg=cfg
        self.old=Path(cfg['legacy_root'])
        self.sources=Sources()
        self.sites={}
        self.records={}
        self.issues=[]
        self._batch=None
        self.policy=None
        source=Path(cfg['material_root'])/'material_entry.py'
        self.policy_ref=self.sources.ref(source)
        if self.policy_ref['status']=='verified':
            self.policy=policy_from_source(source)

    def add_ref(self, record, path, expected=None):
        ref=self.sources.ref(path,expected)
        record['provenance']['source_refs'].append(ref)
        return ref

    def dynamic_site(self, p, card, record):
        if p.get('dynamic_site'):
            selection=p['dynamic_site']
            profile,ref=self.sources.json(selection['path'],selection['sha256'])
            record['provenance']['source_refs'].append(ref)
            city=profile['city']
            site_id=selection['id']
            reference=profile.get('reference',{})
            rule=profile.get('rule',{})
            for path,checksum in profile.get('protected',{}).items():
                self.add_ref(record,path,checksum)
        else:
            if self._batch is None:
                self._batch,self._batch_ref=self.sources.json(self.cfg['material_batch'])
            record['provenance']['source_refs'].append(self._batch_ref)
            if p.get('dynamic_city'):
                selection=p['dynamic_city']
                region=selection['id'].removeprefix('legacy_')
                city=next(c for c in self._batch['cities'] if c['region_id']==region)
                if legacy_fingerprint(city)!=selection['sha256']:
                    raise ValueError('原城市日历内容与方案记录不同。')
            else:
                city=next(c for c in self._batch['cities'] if c['city']==card['city'])
                record['provenance']['notes'].append('工作簿城市已解析；其隐含日历来自现有登记批次，未据此证明历史执行等价。')
            site_id='legacy_city_'+str(city['region_id'])
            reference=dict(kind='legacy_W00_reference',source_ref=self._batch_ref)
            rule=dict(kind='legacy_season_calendar')
        climate=city['climate']
        weather=climate.get('weather',{})
        path=climate.get('path') or climate.get('region',{}).get('epw_path')
        weather_ref=self.add_ref(record,path,weather.get('sha256')) if path else None
        self.sites[site_id]=dict(id=site_id,name=city['city'],climate=None,eligible=True,
            weather=weather_ref,location=weather.get('location'),source_kind='legacy_dynamic')
        calendar=city.get('daily_cooling_face')
        if not isinstance(calendar,list) or len(calendar)!=365 or any(v not in (0,1,False,True) for v in calendar):
            raise ValueError('换季日历不是完整的非闰年逐日光学选择。')
        record['factors']['condition']['reference_runs']=[dict(id='season_reference',purpose='orientation_calendar',
            reference=reference,rule=rule,calendar=calendar,calendar_sha256=digest(calendar))]
        return site_id

    def import_plan(self,path):
        p,source=self.sources.json(path)
        record=base_record('legacy_'+p['id'],p['name'],source['sha256'],'legacy_plan_v011')
        record['archived']=bool(p.get('deleted'))
        record['provenance'].update(source_path=str(path.resolve()),original=copy.deepcopy(p))
        record['provenance']['source_refs'].append(source)
        f=record['factors']
        book=self.add_ref(record,p['workbook'],p.get('input_sha256'))
        library=self.add_ref(record,p['library'],p.get('library_sha256')) if p.get('library') else None
        guards=[self.add_ref(record,file,checksum) for file,checksum in p.get('source_guard',{}).items()]
        f['building']=dict(id=p['project_id'],name=PROJECT_NAMES.get(p['project_id'],p['project_id']),
            legacy_project_id=p['project_id'],input_snapshot=book,source_guards=guards,
            legacy_family_id=p.get('family_id'),imported_summary=p.get('shared_summary'),definition_status='legacy_snapshot')
        f['materials'].update(library_snapshot=library,legacy_construction_overrides=copy.deepcopy(p.get('research')))
        f['scope'].update(period=p['period'],weather_selection=copy.deepcopy(p.get('weather')),
            dynamic_site_selection=copy.deepcopy(p.get('dynamic_site')),dynamic_city_selection=copy.deepcopy(p.get('dynamic_city')))
        f['condition']['legacy_selector']=copy.deepcopy(p.get('dynamic_run'))
        record['numerics']['step_minutes']=p['minutes']
        site_id='source_'+p['project_id']+'_'+source['sha256'][:12]
        weather=p.get('weather') or {}
        weather_ref=self.add_ref(record,weather['path'],weather.get('sha256')) if weather.get('path') else next((r for r in guards if r['path'].lower().endswith('.epw')),None)
        self.sites[site_id]=dict(id=site_id,name=weather.get('city') or weather.get('name') or '随原输入快照',
            climate=None,eligible=True,weather=weather_ref,source_kind='legacy_snapshot')
        if p['project_id']=='dynamic':
            try:
                if book['status']!='verified':
                    raise ValueError('材料参数快照与原方案不一致。')
                card=material_card(p['workbook'])
                definition=card['definition']
                f['materials']['definitions']=[definition]
                walls=list(self.global_data['initial'])
                active=[w['surface'] for w in self.global_data['walls'] if w['eligible']]
                inactive=[w for w in walls if w not in active]
                app=dict(id='eca_walls',material_id=definition['id'],component='wall',position='exterior',
                    target_ids=walls,orientation=dict(A='cooling_face',B='other_face'),placement_basis='legacy_outer_equivalent_model')
                f['materials']['applications']=[app]
                selection=p.get('dynamic_run') or {}
                case=selection.get('case','workbook')
                if case=='workbook':case=card['case']
                mode=selection.get('mode','workbook')
                if mode=='workbook':mode={'温控':'controlled','自然室温':'natural','两者':'both'}[card['mode']]
                if case not in ('LOW','HIGH','UNIFIED','GROUPED'):
                    raise ValueError('无法识别旧动态工况。')
                low=min(definition['states'],key=lambda s:s['resistance_m2K_W'])['id']
                high=max(definition['states'],key=lambda s:s['resistance_m2K_W'])['id']
                f['condition']['operation']=dict(mode=mode,settings='inherit_frozen_building')
                f['condition']['controls']=[dict(application_id='eca_walls',channel='thermal',
                    mode='fixed' if case in ('LOW','HIGH') else 'feedback',target_ids=active,
                    state_id=high if case=='HIGH' else low,rule=case,
                    update=dict(kind='solver_step',legacy_effective_minutes=5),policy=self.policy,
                    policy_source=copy.deepcopy(self.policy_ref)),
                    dict(application_id='eca_walls',channel='thermal',mode='fixed',target_ids=inactive,state_id=high),
                    dict(application_id='eca_walls',channel='orientation',mode='calendar',target_ids=walls,
                        reference_id='season_reference',update=dict(kind='daily_midnight'))]
                site_id=self.dynamic_site(p,card,record)
                record['provenance']['notes'].append('LOW/HIGH 只固定热学状态，仍保留原逐日光学选择日历。')
            except (OSError,ValueError,KeyError,StopIteration) as error:
                record['provenance']['notes'].append('动态定义待核对：'+str(error))
                self.issues.append(dict(record_id=record['id'],message=str(error)))
        else:
            record['provenance']['notes'].append('建筑作息与运行细节继续引用原输入快照；构造指定完整保留，未推断为新的材料物理模型。')
        f['scope']['site_ids']=[site_id]
        record['provenance']['mapping_status']='structured_with_source_bindings'
        problems=validate(record,self.sites)
        if problems:
            record['provenance']['notes'].extend(problems)
            record['provenance']['mapping_status']='needs_review'
        record['provenance']['imported_recipe_sha256']=recipe_digest(record)
        self.records[record['id']]=record
        return record

    def import_global(self):
        catalog,source=self.sources.json(self.old/'data/global-source.json')
        if digest(catalog['data'])!=catalog['sha256']:
            raise ValueError('旧全球来源目录内部校验不一致。')
        data=catalog['data'];self.global_data=data
        refs=[source]
        for path,checksum in {**data.get('evidence',{}),**data.get('engine_files',{})}.items():
            refs.append(self.sources.ref(path,checksum))
        jobs={};eligible=[]
        for site in data['sites']:
            ident=site['site_id']
            self.sites[ident]=dict(id=ident,name=site['city'],climate=site['climate'],country=site.get('country'),
                eligible=bool(site['eligible']),site_kind=site.get('site_kind'),latitude=site.get('latitude'),
                longitude=site.get('longitude'),review_note=site.get('review_note'),source_kind='reviewed_global',weather=None)
            if not site['eligible']:continue
            eligible.append(ident)
            for job in site['jobs']:
                result=job['reviewed_result']
                model_ref=self.sources.ref(job['model'],job['model_sha256'])
                weather_ref=self.sources.ref(job['weather'],job['weather_sha256'])
                sql_ref=self.sources.ref(Path(job['output'])/'eplusout.sql',result['sql_sha256'])
                dependencies=[self.sources.ref(p,h) for p,h in job['dependencies'].items()]
                refs.extend([model_ref,weather_ref,sql_ref,*dependencies])
                self.sites[ident]['weather']=weather_ref
                if result['annual']!=site[job['case']]:
                    raise ValueError('地点汇总与案例年度结果不一致。')
                if not result.get('structural_checks_passed'):
                    raise ValueError('正式目录中有未通过结构核查的案例。')
                jobs[ident+'|'+job['case']]=dict(id=job['id'],site_id=ident,case=job['case'],model=model_ref,
                    weather=weather_ref,result=sql_ref,dependencies=dependencies,annual=result['annual'],
                    monthly=result['monthly'],review_status=site.get('review_status'),raw_status=result.get('status'),
                    warnings=result.get('warnings',[]),pending_warnings=result.get('pending_warnings',[]))
        refs=list({(r['path'],r.get('expected_sha256')):r for r in refs}.values())
        first=next(j for j in jobs.values() if j['case']=='W00')
        model,_=self.sources.json(first['model']['path'],first['model']['sha256'])
        walls=list(data['initial']);active=[w['surface'] for w in data['walls'] if w['eligible']]
        protocol=data['protocol']
        for case,ident,name in [('W00','global_w00','全球参考 · W00 原建筑'),('FIXED_COOL_LOW7','global_fixed','全球参考 · 固定 ECA')]:
            r=base_record(ident,name,source['sha256'],'global_frozen_v011')
            r['provenance'].update(source_refs=[source],case=case,catalog_sha256=catalog['sha256'],
                source_path=source['path'],mapping_status='frozen_model_references',
                notes=['引用正式 15 分钟冻结模型与复核结果；本轮没有重新运行模拟。'])
            f=r['factors']
            f['building']=dict(id='drawing26_global_frozen',name='Drawing26 全球参考建筑',
                definition_status='frozen_model_family',zones=len(model.get('Zone',{})),
                north_axis=next(iter(model.get('Building',{}).values()),{}).get('north_axis'),
                conditioned_area_m2=132.735,total_area_m2=166.935,wall_ids=walls)
            if case!='W00':
                material=dict(id='OLD_ECA',name='OLD_ECA',kind='single_layer',model='equivalent_resistance_no_layer_storage',
                    state_identity='independent',states=[dict(id='R',name='蓬松',thermal_input='resistance',resistance_m2K_W=protocol['high_R']),
                    dict(id='C',name='压缩',thermal_input='resistance',resistance_m2K_W=protocol['low_R'])],
                    optics={key:dict(reflectance=protocol['reflectance'],solar_absorptance=1-protocol['reflectance'],
                        emissivity=protocol['emissivity'],input_basis='opaque_reflectance') for key in ('A_R','A_C')},optics_depend_on_state=False,
                    source_note='正式全球固定工况协议；另一面参数不由本批次推断。')
                app=dict(id='eca_walls',material_id='OLD_ECA',component='wall',position='exterior',target_ids=walls,
                    orientation=dict(A='cooling_face',B='other_face'),placement_basis='legacy_outer_equivalent_model')
                f['materials'].update(definitions=[material],applications=[app])
                f['condition']['controls']=[dict(application_id='eca_walls',channel='thermal',mode='fixed',target_ids=active,state_id='C'),
                    dict(application_id='eca_walls',channel='thermal',mode='fixed',target_ids=[w for w in walls if w not in active],state_id='R'),
                    dict(application_id='eca_walls',channel='orientation',mode='fixed',target_ids=walls,face_id='A')]
            f['condition']['operation']=dict(mode='controlled',settings='inherit_frozen_building',load_basis='zone_sensible_demand')
            f['scope'].update(site_ids=eligible,period=[1,1,12,31],aggregation=dict(kind='climate',weighting='equal_sites',
                missing='null',class_count=30))
            r['numerics']=dict(step_minutes=15,engine=Path(data['engine']).name,engine_files=data['engine_files'])
            r['provenance']['imported_recipe_sha256']=recipe_digest(r)
            self.records[ident]=r
        exports=list((self.old/'data/global-exports').glob('baseline-*/dataset.json'))
        historical=None
        for path in exports:
            value,ref=self.sources.json(path)
            if value.get('catalog_sha256')==catalog['sha256']:
                historical=dict(source=ref,dataset=value);break
        if historical is None:
            raise ValueError('没有匹配的正式全球结果数据集。')
        self.global_bundle=dict(catalog_sha256=catalog['sha256'],source=source,source_refs=refs,jobs=jobs,
            classes=data['classes'],summary=data['summary'],historical=historical,protocol=protocol)

    def run(self):
        # Protect source code without copying inputs or outputs.
        for p in sorted(self.old.glob('*.py')):
            self.sources.ref(p)
        for p in sorted((self.old/'static').glob('*')):
            if p.is_file():self.sources.ref(p)
        self.sources.ref(self.old/'VERSION')
        self.import_global()
        for path in sorted((self.old/'data/plans').glob('*/plan.json')):
            try:self.import_plan(path)
            except (OSError,ValueError,KeyError) as error:
                self.issues.append(dict(source=str(path),message=str(error)))
        roundtrips=[]
        for r in self.records.values():
            if r['provenance']['adapter']=='legacy_plan_v011':
                roundtrips.append(dict(id=r['id'],passed=to_legacy_record(r)==r['provenance']['original']))
        if any(not r['passed'] for r in roundtrips):
            raise ValueError('旧方案无损映射核查失败。')
        return dict(schema_version=1,created=now(),legacy_root=str(self.old),records=self.records,sites=self.sites,
            global_bundle=self.global_bundle,issues=self.issues,roundtrips=roundtrips,
            protection=self.sources.observed,import_scope='configuration_mapping_and_historical_results',
            numerical_equivalence='not_claimed_no_new_simulation')

def to_legacy_record(record):
    if record['provenance']['adapter']!='legacy_plan_v011':
        raise ValueError('该记录不是旧方案映射。')
    original=record['provenance']['original'];out=copy.deepcopy(original);f=record['factors']
    out.update(name=record['name'],project_id=f['building']['legacy_project_id'],period=f['scope']['period'],
        minutes=record['numerics']['step_minutes'],workbook=f['building']['input_snapshot']['path'],
        input_sha256=f['building']['input_snapshot'].get('expected_sha256') or f['building']['input_snapshot']['sha256'])
    # Preserve original path spelling as well as unknown legacy fields.
    if Path(out['workbook']).resolve()==Path(original['workbook']).resolve():out['workbook']=original['workbook']
    mappings={'research':f['materials'].get('legacy_construction_overrides'),'weather':f['scope'].get('weather_selection'),
        'dynamic_site':f['scope'].get('dynamic_site_selection'),'dynamic_city':f['scope'].get('dynamic_city_selection'),
        'dynamic_run':f['condition'].get('legacy_selector'),'deleted':record['archived']}
    for key,value in mappings.items():
        if key in original:out[key]=copy.deepcopy(value)
    return out
