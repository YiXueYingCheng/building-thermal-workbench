"""Prepare independent Beijing four-condition records from pinned corrected sources."""
import copy
from contracts import normalize
from solid_eca import definition,PROFILE,PLACEMENT,POLICY
from research_sets import Sets

SOURCE_SET='set_ee15528c18034b53a0bc0df7881fc98d'
SOURCE_REVISION=4
SITE='weather_48a4408f6680bbc77c3710eb43a9887f'
NAME='北京五层 · 实体 ECA 四工况 · 1 min'

def records(catalog,root=None):
    sets=Sets(catalog,root) if root else Sets(catalog)
    old=sets.records(sets.get(SOURCE_SET,SOURCE_REVISION));out={}
    for role in ('baseline','fixed','flip','feedback'):
        r=copy.deepcopy(old['baseline' if role=='baseline' else 'fixed'])
        r['numerics'].update(step_minutes=1,heat_transfer_profile=PROFILE)
        r['factors']['scope']['site_ids']=[SITE]
        if role!='baseline':
            m=r['factors']['materials'];m.pop('definition_reference',None);m['definitions']=[definition()]
            m['applications'][0].update(material_id=definition()['id'],placement_basis=PLACEMENT)
            for ctl in r['factors']['condition']['controls']:
                if ctl['channel']=='thermal':
                    ctl.update(mode='feedback' if role=='feedback' else 'fixed',state_id='C' if role=='feedback' else 'R')
                    if role=='feedback':ctl.update(copy.deepcopy(POLICY))
                else:ctl.update(mode='calendar' if role in ('flip','feedback') else 'fixed',face_id='A');ctl.pop('reference_id',None)
        r['factors']['condition']['reference_runs']=[];out[role]=normalize(r)
    return out
