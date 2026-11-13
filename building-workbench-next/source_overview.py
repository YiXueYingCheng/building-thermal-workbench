"""Discover source updates for latest workspace plans without reading large source files."""
from foundation import ROOT, digest, now
from contracts import normalize
import component_updates


def build(catalog, store, root=ROOT):
    records=[r for r in store.all() if r['status']=='draft']
    rows=[]
    for r in records:
        f=r['factors'];components=[];weather=[];issues=[]
        try:
            components=component_updates.describe(r,root)['components']
            material=next(x for x in components if x['kind']=='material')
            pinned=component_updates.pinned(r,'material')
            if pinned:
                defined=normalize(r)['factors']['materials']['definitions']
                bound=normalize({'factors':{'materials':{'definitions':[pinned['content']]}}})['factors']['materials']['definitions']
                material['local_changes']=defined!=bound
        except (OSError,ValueError,KeyError,TypeError) as error:
            issues.append('库版本暂未能核对：'+str(error))
        reference_required=bool(f['condition'].get('reference_runs')) or any(c.get('mode')=='calendar' for c in f['condition'].get('controls',[]))
        for ident in f['scope']['site_ids']:
            site=catalog['sites'].get(ident)
            if not site:
                issues.append('地点未登记：'+str(ident));continue
            updates=[]
            for candidate in catalog['sites'].values():
                if candidate.get('supersedes')!=ident:continue
                eligible=bool(candidate.get('eligible') and candidate.get('weather'))
                updates.append(dict(id=candidate['id'],name=candidate['name'],eligible=eligible))
            if updates:weather.append(dict(id=ident,name=site['name'],updates=updates,reference_required=reference_required))
        count=sum(x['status']=='update_available' for x in components)+sum(len(x['updates']) for x in weather)
        attention=bool(issues or any(x['status'] in ('conflict','pinned_only') or x.get('local_changes') for x in components))
        rows.append(dict(id=r['id'],revision=r['revision'],record_sha256=digest(r),name=r['name'],
                         building_id=f['building']['id'],building=f['building']['name'],archived=r['archived'],
                         site_count=len(f['scope']['site_ids']),components=components,weather_updates=weather,
                         update_count=count,needs_attention=attention,issues=issues,
                         status='needs_attention' if attention else 'updates' if count else 'no_updates'))
    rows.sort(key=lambda r:(r['archived'],not r['needs_attention'],r['update_count']==0,r['name'],r['id']))
    return dict(checked_at=now(),records=rows,scope='latest_saved_workspace_plans',
                note='这里只查看本工作区方案的最新保存版与已登记库版本；不包含未保存编辑。文件内容从单方案来源核对中按需检查。')
