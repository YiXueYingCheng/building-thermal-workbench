"""Repeatable six-case acceptance through local material, plan, queue and comparison services."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'building-workbench-next'))
from foundation import ROOT,sha,digest,read_json
from research_materials import example
from component_library import Library
from material_catalog import adoption_preview,import_definition
from manage import current
from record_store import Store
from contracts import normalize
from input_pipeline import build_bundle
from execution_inputs import prepare
from execution_queue import Queue,ensure_worker

CASES={'pcm':'C18 相变','sensible':'C18 等物性显热','broadband':'常规宽带制冷面',
       'covered':'PE 解耦层','bare':'裸露选择性发射层','sensitivity':'PE 窗口外高发射'}
def definition(k):
    if k in ('pcm','sensible'):
        d=example('pcm')
        if k=='sensible':d['phase_change']['latent_kJ_kg']=0.
    else:
        d=example('spectral','covered' if k=='sensitivity' else k)
        if k=='sensitivity':d['spectral']['outside_window_emissivity']=.95
    d['name']=CASES[k]
    return import_definition(dict(schema='workbench-material/v1',source_revision=1,material=d))

def start(cases,base_id,output,refresh=False):
    catalog=current(ROOT)
    store=Store(catalog)
    base=store.get(base_id,1)
    lib=Library()
    ledger=read_json(output) if output.exists() else {}
    for k in cases:
        step=2 if k in ('pcm','sensible') else 5
        old=ledger.get(k)
        if old and not refresh and store.get(old['plan'],old['revision'])['numerics']['step_minutes']==step:continue
        source=store.update_payload(base,dict(numerics=dict(base['numerics'],step_minutes=step)))
        d=definition(k)
        ref=next((r for r in lib.all('material') if r['content']==d),None) or lib.save('material',d['name'],d)
        selected=adoption_preview(source,{n:ref[n] for n in ('id','revision','sha256')},catalog)
        factors=base['factors'].copy()
        factors['materials']=selected['materials']
        factors['condition']=dict(base['factors']['condition'],controls=selected['controls'])
        name='长沙三日 · '+CASES[k]
        plan=next((r for r in store.all() if r['name']==name and r['factors']==factors),None)
        changes=dict(name=name,factors=factors,numerics=source['numerics'])
        if plan and plan['numerics']['step_minutes']!=step:plan=store.save(plan['id'],plan['revision'],changes)
        if not plan:plan=store.create(base_id,1,changes)
        bundle=build_bundle(plan,catalog)
        review=prepare(ROOT,bundle['id'],'timeseries_timestep_v1')
        queue=Queue()
        batch=queue.submit(review['id'],review['plan_sha256'])
        ledger[k]=dict(plan=plan['id'],revision=plan['revision'],material=ref['id'],bundle=bundle['id'],
                       review=review['id'],batch=batch['id'])
        if old:ledger[k]['previous_attempt']=old
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf8')
        print(k,batch,flush=True)
        ensure_worker()
    for left,right in [('sensible','pcm'),('broadband','covered'),('bare','covered'),('covered','sensitivity')]:
        if left in ledger and right in ledger:
            store.save_comparison('长沙三日 · '+CASES[left]+' 与 '+CASES[right],
                *[dict(id=ledger[k]['plan'],revision=ledger[k]['revision']) for k in (left,right)],'total')

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('--refresh',action='store_true')
    cli.add_argument('--base',required=True)
    cli.add_argument('--ledger',type=Path,required=True)
    cli.add_argument('cases',choices=CASES,nargs='+')
    args=cli.parse_args()
    start(args.cases,args.base,args.ledger,args.refresh)
