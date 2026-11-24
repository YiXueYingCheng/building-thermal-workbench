"""Exercise the same read-only material and comparison calls as the results page."""
import argparse,json,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'building-workbench-next'))
from foundation import ROOT,config,read_json
from record_store import Store
from manage import current
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('folder',type=Path,help='包含算例清单.json 和材料响应.json 的核验目录')
folder=parser.parse_args().folder
ledger=read_json(folder/'算例清单.json')
answers=read_json(folder/'材料响应.json')
base='http://127.0.0.1:'+str(config(ROOT)['port'])
def query(route,body=None):
    headers={'Origin':base,'Content-Type':'application/json','X-Workbench-Token':read_json(ROOT/'data/session-token.json')['token']}
    req=urllib.request.Request(base+route,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
assert Path(query('/api/health')['root'])==ROOT
library=query('/api/material-library')
assert all(k in library['templates'] for k in ('pcm','spectral'))
by_pair=Store(current(ROOT)).comparisons()
receipts={}
for left,right in [('sensible','pcm'),('broadband','covered'),('bare','covered'),('covered','sensitivity')]:
    pair=next(c for c in by_pair if all(c[s]['id']==ledger[k]['plan'] and c[s]['revision']==ledger[k]['revision'] for s,k in [('left',left),('right',right)]))
    picked=query('/api/comparisons/'+pair['id']+'/sources')
    assert all(any(s['id']==ledger[k]['batch'] for s in picked[side]) for side,k in [('left',left),('right',right)])
    body=dict(id=pair['id'],left_source=ledger[left]['batch'],right_source=ledger[right]['batch'],mode='controlled')
    view=query('/api/comparison-results',body)
    assert view['paired_sites']==1 and view['material_response_available'],view.get('blocked')
    body['site_id']=view['sites'][0]['site_id']
    data=query('/api/material-response',body)
    for side,k in [('left',left),('right',right)]:
        assert data[side]['segments']==answers[k]['segments'] and data[side]['loads']==answers[k]['loads']
    receipts[pair['name']]=dict(**body,paired_sites=1,output_matches=True)
    print(pair['name'],'OK',flush=True)
(folder/'工作台对照核查.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf8')
