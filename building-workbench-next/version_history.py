"""Saved-version changes and validated activity links, without rebinding any results."""
from pathlib import Path
import sqlite3
from foundation import ROOT,canonical,now
import plan_activity
import navigation_cache
from presentation import batch_status

GROUPS=(('building','建筑'),('materials','材料'),('condition','工况'),('scope','范围'))

def changes(previous,record):
    if previous is None:return dict(first=True,fields=[],summary='导入来源快照' if record['status']=='imported' else '首次保存')
    fields=[]
    equal=lambda a,b:canonical(a)==canonical(b)
    if not equal(previous.get('name'),record.get('name')):fields.append('名称')
    for key,label in GROUPS:
        if not equal(previous['factors'].get(key),record['factors'].get(key)):fields.append(label)
    extra=lambda r:{k:v for k,v in r['factors'].items() if k not in dict(GROUPS)}
    if not equal(extra(previous),extra(record)):fields.append('其他因素字段')
    for key,label in (('numerics','计算设置'),('execution','执行偏好记录'),('provenance','来源记录')):
        if not equal(previous.get(key),record.get(key)):fields.append(label)
    ignored={'id','revision','saved_at','record_sha256','name','factors','numerics','execution','provenance'}
    rest=lambda r:{k:v for k,v in r.items() if k not in ignored}
    if not equal(rest(previous),rest(record)):fields.append('其他记录字段')
    text='仅修改名称' if fields==['名称'] else '与上一版保存内容相同' if not fields else '修改：'+'、'.join(fields)
    return dict(first=False,fields=fields,previous_revision=previous['revision'],summary=text)

def build(ident,catalog,store,root=ROOT):
    history=store.history(ident)
    if not history:raise KeyError('没有该方案的保存版本。')
    records=[store.get(ident,h['revision']) for h in history]
    rows=[]
    for i,(h,r) in enumerate(zip(history,records)):
        previous=records[i+1] if i+1<len(records) else None
        row=dict(id=r['id'],revision=r['revision'],name=r['name'],saved_at=h['saved_at'],latest=i==0,
            period=r['factors']['scope']['period'],site_count=len(r['factors']['scope']['site_ids']),step_minutes=r['numerics']['step_minutes'],
            changes=changes(previous,r),input_count=None,batches=None,comparison_count=None,historical=False,issues=[])
        try:
            d=navigation_cache.activity(r,catalog,store,Path(root))
            row.update(input_count=len(d['inputs']),batches=[dict(**b,status=batch_status(b['counts'],b['case_count'],b['mode'])) for b in d['batches']],
                comparison_count=len(d['comparisons']),historical=d['historical'],issues=d['issues'])
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
            row['issues']=['该版本的计算记录暂未能读取：'+str(error)]
        rows.append(row)
    deleted=[]
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='plan_deleted_versions'").fetchone():
            deleted=[r[0] for r in db.execute('SELECT revision FROM plan_deleted_versions WHERE record_id=? ORDER BY revision',(ident,))]
    if deleted and rows[-1]['revision']!=1:
        rows[-1]['changes']['summary']='最早保留版本；更早版本已删除，内容不再用于此处对照'
    return dict(record_id=ident,latest_revision=rows[0]['revision'],created=now(),versions=rows,deleted_revisions=deleted,
        note='变更相对同方案上一保留的保存版本；已删版本不参与内容对照，版本号不重排或复用。计算和比较仍归属各自绑定版本。计数复用已核对清单的查看索引，记录变化后更新；查看结果时继续核验结果文件。设备投入以计算队列当前设置为准。')
