"""Read each accepted building result once and check its host walls and apertures."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'building-workbench-next'))
from foundation import ROOT,read_json
from input_pipeline import read_audit
from result_reading import results
from record_store import Store
from manage import current
from material_response import summarize

def run(folder):
    ledger=read_json(folder/'算例清单.json');store=Store(current(ROOT));all_results={}
    for key,row in ledger.items():
        case=results(ROOT,row['batch'])['results'][0]
        if case['status']!='passed':raise ValueError(key)
        path=ROOT/'data/model-inputs'/row['bundle'];manifest=read_json(path/'manifest.json')
        case_input=manifest['cases'][0];a=read_audit(path,case_input)
        old=read_json(Path(case_input['source_model']['path']));new=read_json(path/case_input['model_file'])
        if old.get('FenestrationSurface:Detailed')!=new.get('FenestrationSurface:Detailed'):raise ValueError('洞口模型发生变化')
        app=a['material_application']
        for w in app['surfaces']:
            if w['layers_after'][1:]!=w['layers_before'] or new['BuildingSurface:Detailed'][w['surface']]['outside_boundary_condition']!='Outdoors':raise ValueError('层序或外界条件改变')
        plan=store.get(row['plan'],row['revision'])
        output=summarize(case,app,plan['factors']['materials']['definitions'][0],ROOT,
            aperture_signatures=a.get('spectral_solar',{}).get('aperture_signatures'))
        output.update(weather_sha256=case_input['weather']['sha256'],source_model_sha256=case_input['source_model']['sha256'],all_aperture_definitions_unchanged=True,building=plan['factors']['building'].get('name'),warnings=case['warnings'],pending_warnings=case['pending_warnings'])
        all_results[key]=output
        print(key,case['loads'],output.get('aperture_series_verified'),output.get('applied_boundary_residual_W_m2'),flush=True)
    if len({v['weather_sha256'] for v in all_results.values()})!=1 or len({v['source_model_sha256'] for v in all_results.values()})!=1: raise ValueError('建筑或气象不一致')
    (folder/'材料响应.json').write_text(json.dumps(all_results,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);run(p.parse_args().folder)
