"""Human-readable calendar differences, without re-deriving research dates."""
import datetime as dt

def calendars(record):
    condition=record['factors']['condition'];active={c.get('reference_id') for c in condition['controls'] if c.get('channel')=='orientation' and c.get('mode')=='calendar'}
    rows={};refs=[]
    for ref in condition.get('reference_runs',[]):
        if ref.get('id') not in active:continue
        s=ref.get('snapshot',{});refs.append(dict(id=s.get('id'),revision=s.get('revision'),name=s.get('name')))
        for row in s.get('content',{}).get('sites',[]):rows[row['site_id']]=row.get('calendar',[])
    faces=[c.get('face_id') for c in condition['controls'] if c.get('channel')=='orientation' and c.get('mode')=='fixed']
    return rows,refs,faces

def outline(values,fixed):
    if not values:return dict(initial='/'.join(sorted(set(fixed))) or '未启用',switches=[],days=0)
    return dict(initial='A' if values[0] else 'B',days=len(values),switches=[dict(date=(dt.date(2025,1,1)+dt.timedelta(days=i)).strftime('%m-%d'),face='A' if v else 'B') for i,v in enumerate(values) if i and v!=values[i-1]])

def describe(before,after,catalog):
    a,ar,af=calendars(before);b,br,bf=calendars(after);sites=list(dict.fromkeys(before['factors']['scope']['site_ids']+after['factors']['scope']['site_ids']))
    rows=[]
    for sid in sites:
        av=a.get(sid,[]);bv=b.get(sid,[]);left=outline(av,af);right=outline(bv,bf)
        if not av and not bv:continue
        changed=av!=bv or (not av and af!=bf)
        rows.append(dict(site_id=sid,city=catalog['sites'].get(sid,{}).get('name',sid),before=left,after=right,changed=changed,
            changed_days=sum(x!=y for x,y in zip(av,bv)) if len(av)==len(bv)==365 else None))
    return dict(before_refs=ar,after_refs=br,reference_changed=ar!=br,changed_sites=sum(r['changed'] for r in rows),rows=rows,
        note='日历日期取自本次编辑与原保存版本；本次不重新推导日期，不计算冷热负荷。')
