"""Read-only discovery of immutable exports. Never assembles results or exports anew."""
from pathlib import Path
import re
from foundation import ROOT,read_json,digest,now
import result_exports
import batch_results

def listing(kind,ident,root=ROOT):
    if kind not in ('comparison','batch') or not re.fullmatch(kind+r'_[a-f0-9]{32}',str(ident)):
        raise ValueError('请选择有效的比较或批次编号。')
    rows=[];issues=[];root=Path(root).resolve()
    loader=result_exports.load_export if kind=='comparison' else batch_results.load_export
    for folder in sorted((root/f'data/{kind}-exports').glob(kind+'_export_*')):
        if not folder.is_dir():continue
        try:
            # Establish scope first; an unreadable package has explicitly unknown ownership.
            data=read_json(folder/'dataset.json')
            owner=data['comparison']['id'] if kind=='comparison' else data['id']
        except (OSError,ValueError,KeyError,TypeError) as error:
            issues.append(dict(id=folder.name,scope='unknown',message='无法识别归属：'+str(error)));continue
        if owner!=ident:continue
        try:
            _,r=loader(folder.name,root)
            required={'dataset.json','comparison.zip' if kind=='comparison' else 'batch.zip'}
            if r['id']!=folder.name or not isinstance(r['created'],str) or not required<=set(r['files']):raise ValueError('导出回执编号、时间或必需文件不完整。')
            excluded={'dataset_sha256','created'} if kind=='comparison' else {'dataset_sha256'}
            h=digest({k:v for k,v in data.items() if k not in excluded})
            if h!=data['dataset_sha256'] or h!=r['dataset_sha256']:raise ValueError('导出数据内容摘要不一致。')
            row=dict(id=r['id'],created=r['created'],dataset_sha256=h,period=data['period'],step_minutes=data['step_minutes'],step_label=data.get('step_label') or f"{data['step_minutes']} min",files=sorted(r['files']))
            if kind=='comparison':
                c=data['comparison']
                for side in ('left','right'):
                    if {k:data['records'][side][k] for k in ('id','revision')}!=c[side]:raise ValueError('导出保存版本与比较关系不一致。')
                if r['paired_sites']!=data['paired_sites']:raise ValueError('导出地点计数不一致。')
                row.update(name=c['name'],records=data['records'],sources={s:data[s]['id'] for s in ('left','right')},
                    mode=data['mode'],metric=data['metric'],paired_sites=data['paired_sites'],selected_sites=data['selected_sites'],
                    unit='°C' if data['metric']=='temperature' else 'MJ/m²' if data.get('normalized') else 'kWh' if 'normalized' in data else '见包内说明')
                if r.get('figure_kind')=='site':row['unit']='图表 kWh；数据表另含 MJ/m²' if data.get('normalized') else 'kWh'
            else:
                if r['batch_id']!=ident or r['counts']!=data['counts']:raise ValueError('导出批次或计数不一致。')
                row.update(name=data['record_name'],record=dict(id=data['record_id'],revision=data['revision']),counts=data['counts'],modes=data['modes'],selection=r.get('selection',[]))
            rows.append(row)
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
            issues.append(dict(id=folder.name,scope='selected',message=str(error)))
    return dict(kind=kind,owner_id=ident,checked_at=now(),exports=sorted(rows,key=lambda r:(r['created'],r['id']),reverse=True),issues=issues)
