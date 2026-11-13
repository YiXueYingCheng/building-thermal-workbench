"""Freeze additional, read-only legacy template bindings without rewriting the first catalog."""
from pathlib import Path
from foundation import ROOT, Sources, config, read_json, write_json, digest, now
from manage import current

def register():
 target=ROOT/'data/dynamic-sources.json'
 if target.exists():return read_json(target)
 c=current();cfg=config();reader=Sources();batch,bref=reader.json(cfg['material_batch']);rows={}
 for r in c['records'].values():
  if not r['factors']['condition']['reference_runs']:continue
  p=r['provenance']['original'];site=r['factors']['scope']['site_ids'][0];ref=r['factors']['condition']['reference_runs'][0]
  dependencies=[bref]
  if p.get('dynamic_site'):
   profile,pref=reader.json(p['dynamic_site']['path'],p['dynamic_site']['sha256']);dependencies.append(pref)
   template=Path(profile['template'])/'LOW'
   for name,h in profile['protected'].items():
    if reader.ref(name,h)['status']!='verified':raise ValueError('动态城市依赖与原校验不一致：'+name)
  else:
   city=next(x for x in batch['cities'] if 'legacy_city_'+x['region_id']==site)
   template=Path(batch['archive'])/'cities'/(city['region_id']+'_'+city['city'])/'annual/LOW'
  meta,mref=reader.json(template/'case.json');dependencies.append(mref)
  modes={}
  for mode in ('controlled','natural'):
   path=template/mode/'model.epJSON';m,mref=reader.json(path);schedules=[]
   for obj in m.get('Schedule:File',{}).values():
    f=(path.parent/obj['file_name']).resolve();schedules.append(reader.ref(f))
   modes[mode]=dict(model=mref,dependencies=list({s['path']:s for s in schedules}.values()))
  rows[r['id']]=dict(site_id=site,building=r['factors']['building'],reference=ref,weather=c['sites'][site]['weather'],walls=meta['walls'],modes=modes,sources=dependencies)
 protection=reader.check_unchanged()
 if not protection['passed'] or any(x['status']!='verified' for x in reader.observed.values()):raise ValueError('动态来源核对未通过。')
 data=dict(created=now(),records=rows,policy=batch['policy'],walls=batch['walls'],source_refs=list(reader.observed.values()),source_protection=protection)
 write_json(target,dict(data=data,sha256=digest(data)))
 return read_json(target)

if __name__=='__main__':
 v=register();print('Dynamic source records',len(v['data']['records']),'protected',v['data']['source_protection']['checked'])
