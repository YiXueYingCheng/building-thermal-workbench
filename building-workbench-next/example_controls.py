"""Opt-in Drawing26 controls; existing source and result records stay pinned."""
import copy
from pathlib import Path
from foundation import ROOT,read_json,write_json,sha,digest,owned
from workspace_setup import setup_lock
REGISTRY='data/examples/drawing26-controls.json'

def has_dynamic(catalog):
    data=catalog.get('dynamic_registry',{})
    return any(data.get(k) for k in ('records','walls','policy','source_refs'))

def merge(catalog,root):
    path=Path(root)/REGISTRY
    if not path.exists():return catalog
    saved=read_json(path);data=saved['data']
    if saved['sha256']!=digest(data) or not catalog.get('example_bundle'):raise ValueError('Drawing26 控制示例登记校验失败。')
    source=data['source'];p=owned(source['path'],root)
    if sha(p)!=source['sha256']:raise ValueError('Drawing26 控制规则来源已变化。')
    controls=read_json(p)
    if controls.get('kind')!='drawing26_controls_v1':raise ValueError('控制规则类型不匹配。')
    if has_dynamic(catalog):raise ValueError('已有动态来源，未覆盖。')
    catalog['dynamic_registry']=dict(records={},policy=controls['policy'],walls=controls['walls'],source_refs=[source])
    catalog['example_controls']=dict(**data,settings=controls)
    return catalog

def enable(root=ROOT):
    from manage import current
    root=Path(root).resolve()
    with setup_lock(root):
        c=current(root)
        if c.get('example_controls'):return c['example_controls']
        if not c.get('example_bundle') or has_dynamic(c):raise ValueError('请先在独立工作区登记 Drawing26 示例。')
        package=Path(__file__).resolve().parents[1]/'examples/drawing26/controls.json';checksum=sha(package)
        target=root/'data/examples'/('controls_'+checksum[:16]+'.json')
        if target.exists() and sha(target)!=checksum:raise ValueError('已有规则副本不同，未覆盖。')
        if not target.exists():target.write_bytes(package.read_bytes())
        data=dict(source=dict(path=str(target),sha256=checksum,status='verified'))
        write_json(root/REGISTRY,dict(data=data,sha256=digest(data)),root)
    return current(root)['example_controls']

def create(root=ROOT):
    from manage import current
    from record_store import Store
    root=Path(root).resolve();enable(root)
    with setup_lock(root):
        c=current(root);store=Store(c,root);receipt=root/'data/examples/control-examples.json'
        if receipt.exists():
            saved=read_json(receipt)
            for row in saved['records'].values():store.get(row['id'],row['revision'])
            return {**saved,'reused':True}
        fixed=read_json(root/'data/examples/fixed-comparison.json');policy=c['example_controls']['settings']
        base=store.get('global_fixed');f=copy.deepcopy(base['factors'])
        f['condition']['controls'][0].update(mode='feedback',state_id=policy['initial_state'],rule=policy['feedback_rule'],policy=policy['policy'],update=policy['update'],state_roles=policy['state_roles'])
        dynamic=store.create(base['id'],base['revision'],dict(name='Drawing26 示例 · 热阻反馈 · 长沙两日',factors=f))
        rows={'feedback':dict(id=dynamic['id'],revision=dynamic['revision'])};comparisons={}
        for state,label in [('R','蓬松'),('C','压缩')]:
            comp=store.add_comparison('Drawing26 · 固定'+label+'与热阻反馈',fixed['records'][state],rows['feedback'],'total');comparisons[state]=comp['id']
        original=store.get('global_w00');f=copy.deepcopy(original['factors']);f['scope']['period']=[1,1,12,31]
        annual=store.create(original['id'],original['revision'],dict(name='Drawing26 示例 · 光学切换日历全年参考',factors=f))
        rows['annual_reference']=dict(id=annual['id'],revision=annual['revision'])
        saved=dict(records=rows,comparisons=comparisons,new_simulations=0);write_json(receipt,saved,root)
        return {**saved,'reused':False}

def create_orientation(root=ROOT):
    """Use accepted local daily results; show 31 days around the first switch."""
    import datetime as dt
    from manage import current
    from record_store import Store
    from calendar_library import prepare,save_or_apply
    root=Path(root).resolve();create(root)
    with setup_lock(root):
        c=current(root);store=Store(c,root);receipt=root/'data/examples/orientation-example.json'
        if receipt.exists():
            saved=read_json(receipt)
            for row in saved['records'].values():store.get(row['id'],row['revision'])
            return {**saved,'reused':True}
        fixed=read_json(root/'data/examples/fixed-comparison.json')['records']['R'];base=store.get(fixed['id'],fixed['revision'])
        preview=prepare(base,c,root)
        if not preview['can_apply']:raise ValueError('逐日日历尚不能采用：'+'；'.join(preview['issues']+preview['application_issues']+[i for row in preview['rows'] for i in row['issues']]))
        switches=preview['rows'][0]['preview']['switches']
        if not switches:raise ValueError('该参考全年使用同一组光学参数，不能作为切换演示。')
        switch=switches[0];start=max(1,min(335,switch['day_of_year']-15));end=start+30
        a=dt.date(2025,1,1)+dt.timedelta(days=start-1);b=dt.date(2025,1,1)+dt.timedelta(days=end-1)
        accepted=save_or_apply(base,c,root,preview['content_sha256'],True,'apply',preview['record_sha256'])
        f=copy.deepcopy(base['factors']);f['scope']['period']=[a.month,a.day,b.month,b.day]
        left=store.create(base['id'],base['revision'],dict(name='Drawing26 示例 · 固定 A · 长沙31日',factors=f))
        f['condition']=accepted['condition'];right=store.create(base['id'],base['revision'],dict(name='Drawing26 示例 · 逐日光学切换 · 长沙31日',factors=f))
        rows={key:dict(id=r['id'],revision=r['revision']) for key,r in [('fixed_A',left),('orientation',right)]}
        comp=store.add_comparison('Drawing26 · 固定 A与逐日光学切换',rows['fixed_A'],rows['orientation'],'total')
        saved=dict(records=rows,comparison_id=comp['id'],period=f['scope']['period'],switch=switch,calendar=accepted['snapshot'],new_simulations=0)
        write_json(receipt,saved,root)
        return {**saved,'reused':False}
