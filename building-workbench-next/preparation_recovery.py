"""Idempotent preparation around the frozen executor; never submits a batch."""
from pathlib import Path
from contextlib import closing
import re
import sqlite3
from foundation import ROOT,read_json,sha,digest,canonical,loads,owned,now
from execution_inputs import load_review,public,code_hashes,OUTPUT_CONTRACT,validate_output
from input_pipeline import prepare as freeze
from model_adapter import VerifiedReader

def saved_input(root,ident,store,expected=None):
    if not re.fullmatch(r'inputs_[a-f0-9]{32}',str(ident)):raise ValueError('输入包编号不正确。')
    folder=owned(Path(root)/'data/model-inputs'/ident,root)
    m=read_json(folder/'manifest.json');r=read_json(folder/'record.json')
    if m['id']!=ident or (m['record_id'],m['revision'],m['identity']['record'])!=(r['id'],r['revision'],digest(r)):
        raise ValueError('输入包与绑定方案版本不一致。')
    if r!=store.get(r['id'],r['revision']):raise ValueError('输入包未对应已保存的方案版本。')
    if expected is not None and expected!=dict(id=r['id'],revision=r['revision']):raise ValueError('所选输入包不属于当前保存版本。')
    return m,r,sha(folder/'manifest.json')

def submitted(root,bundle_id):
    path=Path(root)/'data/execution/queue.sqlite'
    if not path.exists():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT id,review,plan,checksum,mode,created FROM batches ORDER BY created DESC,rowid DESC')]
    return [dict(b,plan=loads(b['plan'])) for b in rows if loads(b['plan']).get('bundle_id')==bundle_id]

def checked(root,review,checksum,bundle_id,bundle_sha,record,queue_plan=None):
    p=load_review(root,review,checksum)
    if (p['bundle_id'],p['bundle_sha256'],p['record_id'],p['revision'],p['record_sha256'])!=(bundle_id,bundle_sha,record['id'],record['revision'],digest(record)):
        raise ValueError('已准备清单与输入包或保存版本不一致，请保留并核查。')
    if p['id']!=review or (queue_plan is not None and p!=queue_plan):raise ValueError('已提交批次与冻结清单不一致。')
    folder=owned(Path(root)/'data/model-inputs'/bundle_id,root);manifest=read_json(folder/'manifest.json');reader=VerifiedReader()
    for c in manifest['cases']:
        reader.check(dict(path=str(owned(folder/c['model_file'],folder)),sha256=c['model_sha256']))
        if c.get('audit'):
            from input_pipeline import read_audit
            read_audit(folder,c)
    reader.unchanged()
    return p

def prepare(root,ident,store,expected=None,separate_from=None,output_contract=OUTPUT_CONTRACT):
    root=Path(root).resolve();m,r,bundle_sha=saved_input(root,ident,store,expected)
    validate_output(r,output_contract)
    rows=[b for b in submitted(root,ident) if b['plan']['output_contract']==output_contract]
    if separate_from is not None:
        candidates=[b for b in rows if b['id']==separate_from]
        if len(candidates)!=1:raise ValueError('另备清单必须明确引用此输入包的原批次。')
        b=candidates[0];checked(root,b['review'],b['checksum'],ident,bundle_sha,r,b['plan'])
    if rows and separate_from is None:
        b=rows[0];p=checked(root,b['review'],b['checksum'],ident,bundle_sha,r,b['plan'])
        return dict(public(p,root),preparation_reused=True,existing_batch={k:b[k] for k in ('id','mode','created')},existing_batch_count=len(rows))
    codes=code_hashes();identity=dict(bundle_sha256=bundle_sha,code_hashes=codes,separate_from=separate_from)
    if output_contract!=OUTPUT_CONTRACT:identity['output_contract']=output_contract
    key=digest(identity)
    folder=owned(root/'data/execution',root);folder.mkdir(parents=True,exist_ok=True)
    # Independent registry and write lock: repeated threads/processes cannot create duplicate plans.
    with closing(sqlite3.connect(folder/'preparations.sqlite',timeout=30)) as db:
        db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS preparations(key TEXT PRIMARY KEY,bundle_id TEXT NOT NULL,bundle_sha256 TEXT NOT NULL,review TEXT NOT NULL,checksum TEXT NOT NULL,created TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        try:
            if db.execute('SELECT 1 FROM preparations WHERE bundle_id=? AND bundle_sha256<>?',(ident,bundle_sha)).fetchone():
                raise ValueError('已登记输入包的清单内容变化，请保留并核查。')
            row=db.execute('SELECT * FROM preparations WHERE key=?',(key,)).fetchone()
            if row:
                p=checked(root,row['review'],row['checksum'],ident,bundle_sha,r)
                if p['code_hashes']!=codes:raise ValueError('已准备清单的执行版本不一致。')
                if p['output_contract']!=output_contract:raise ValueError('已准备清单的输出类型不一致。')
                result=public(p,root);reused=True
            else:
                result=freeze(root,ident,output_contract=output_contract) if output_contract!=OUTPUT_CONTRACT else freeze(root,ident)
                p=read_json(root/'data/execution/reviews'/result['id']/'plan.json')
                if p['bundle_sha256']!=bundle_sha or p['record_sha256']!=digest(r) or p['code_hashes']!=codes or code_hashes()!=codes:
                    raise ValueError('准备期间输入或程序变化，请保留现场并重新核对。')
                db.execute('INSERT INTO preparations VALUES(?,?,?,?,?,?)',(key,ident,bundle_sha,result['id'],result['plan_sha256'],now()));reused=False
            db.commit()
        except BaseException:db.rollback();raise
    # Another request may have submitted this exact review while it was being restored.
    matches=[b for b in submitted(root,ident) if b['review']==result['id']]
    existing={k:matches[0][k] for k in ('id','mode','created')} if matches else None
    return dict(result,preparation_reused=reused,existing_batch=existing,existing_batch_count=len(matches),separate_from=separate_from)
