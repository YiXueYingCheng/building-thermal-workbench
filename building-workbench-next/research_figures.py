"""Presentation only: derive coverage and plot rows from the accepted paired table."""
METRICS={'heating':'供暖显热需求','cooling':'制冷显热需求','total':'冷热需求合计'}
LABELS={'baseline':'W00 · 原构造','fixed':'固定 ECA','flip':'翻面 ECA'}

def coverage(rows):
    return dict(selected=len(rows),available={k:sum(r[k+'_total_kWh'] is not None for r in rows) for k in LABELS},
        paired={k:sum(r[k+'_pair_status']=='paired' for r in rows) for k in ('fixed','flip')},
        complete=sum(all(r[k+'_pair_status']=='paired' for k in ('fixed','flip')) for r in rows))

def plot_rows(rows):
    out=[]
    for r in rows:
        for metric,label in METRICS.items():
            for role,condition in LABELS.items():
                paired=any(r[k+'_pair_status']=='paired' for k in ('fixed','flip')) if role=='baseline' else r[role+'_pair_status']=='paired'
                source=r[role+'_'+metric+'_kWh']
                reason='' if paired else ('无可配对研究结果' if role=='baseline' else r[role+'_pair_reason'])
                out.append(dict(site_id=r['site_id'],city=r['city'],metric=metric,metric_label=label,role=role,condition=condition,
                    plot_kWh=source if paired else None,source_kWh=source,pair_status='paired' if paired else 'excluded',pair_reason=reason,
                    saved_kWh=r.get(role+'_'+metric+'_saved_kWh') if paired else None,
                    saved_percent=r.get(role+'_'+metric+'_saved_percent') if paired else None,batch_id=r[role+'_batch']))
    return out
