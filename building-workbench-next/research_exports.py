"""Export explicit, accepted set comparisons; missing and ambiguous data stay blank."""
from pathlib import Path
import re,uuid,zipfile,subprocess,sys,importlib.util
from foundation import ROOT,digest,read_json,write_json,sha,owned,now
from research_sets import ALL_ROLES,require
from comparison_results import pair_reason,finite
from result_exports import csv_bytes
from research_figures import coverage,plot_rows

def member_roles(data):return [k for k in ALL_ROLES if k in data['members']]

def selected(data,choices):
 require(isinstance(choices,dict) and not set(choices)-set(data['members']),'结果选择无效。')
 result={}
 for role in member_roles(data):
  usable=[b for b in data['members'][role] if b['usable']]
  chosen=choices.get(role)
  if chosen:
   usable=[b for b in usable if b['batch_id']==chosen]
   require(len(usable)==1,'所选结果批次已不可用，请重新读取。')
  sites={}
  for b in usable:
   for r in b['results']:
    if not r['accepted']:continue
    require(r['site_id'] not in sites,'同一地点存在多个可用结果，请先明确选择结果批次。')
    sites[r['site_id']]={**r,'batch_id':b['batch_id'],'source':b['source']}
  result[role]=sites
 return result

def tables(data,catalog,choices):
 picks=selected(data,choices);rows=[];evidence=[]
 for sid in data['scope']['site_ids']:
  site=catalog['sites'][sid];r=dict(site_id=sid,city=site['name'],climate=site.get('climate'),latitude=site.get('latitude'),longitude=site.get('longitude'))
  for role in member_roles(data):
   item=picks[role].get(sid)
   r[role+'_step_minutes']=item.get('step_minutes') if item else None
   r[role+'_status']=item['acceptance'] if item else 'no_data'
   r[role+'_data_retention']=(item.get('data_retention') or {}).get('mode','full_evidence') if item else ''
   r[role+'_batch']=item['batch_id'] if item else ''
   for metric in ('heating','cooling','total'):
    r[role+'_'+metric+'_kWh']=finite(item['loads'][metric+'_kWh']) if item and item.get('loads') else None
   if item:evidence.append(dict(item,role=role))
  for role in (k for k in data['members'] if k!='baseline'):
   base=picks['baseline'].get(sid);item=picks[role].get(sid)
   reason='；'.join(data['audit']['issues']) if not data['audit']['consistent'] else pair_reason(base,item)
   if not site.get('eligible',True):reason='来源地点暂缓接受'
   r[role+'_pair_status']='excluded' if reason else 'paired';r[role+'_pair_reason']=reason or ''
   for metric in ('heating','cooling','total'):
    b=r['baseline_'+metric+'_kWh'];v=r[role+'_'+metric+'_kWh'];delta=b-v if not reason and b is not None and v is not None else None
    r[role+'_'+metric+'_saved_kWh']=delta;r[role+'_'+metric+'_saved_percent']=delta/b*100 if delta is not None and b else None
  if 'feedback' in data['members']:
   for metric in ('heating','cooling','total'):
    r['orientation_increment_'+metric+'_saved_kWh']=(r['fixed_'+metric+'_kWh']-r['flip_'+metric+'_kWh']) if all(r[k+'_pair_status']=='paired' for k in ('fixed','flip')) else None
    r['feedback_increment_'+metric+'_saved_kWh']=(r['flip_'+metric+'_kWh']-r['feedback_'+metric+'_kWh']) if all(r[k+'_pair_status']=='paired' for k in ('flip','feedback')) else None
  rows.append(r)
 return rows,evidence

def load_export(ident,root=ROOT):
 require(bool(re.fullmatch(r'set_export_[a-f0-9]{32}',str(ident))),'导出编号无效。')
 folder=owned(Path(root)/'data/research-set-exports'/ident,root);receipt=read_json(folder/'receipt.json')
 for name,h in receipt['files'].items():require(sha(owned(folder/name,folder))==h,'导出文件内容变化，请核查。')
 return folder,receipt

def export(data,catalog,choices,root=ROOT):
 rows,evidence=tables(data,catalog,choices)
 require(any(r[k+'_pair_status']=='paired' for r in rows for k in data['members'] if k!='baseline'),'尚无可导出的同条件配对结果。')
 code=Path(__file__).resolve().parent
 ident='set_export_'+digest(dict(annotations=sha(ROOT/'review_annotations.py'),dataset=data['dataset_sha256'],choices=choices,exporter=sha(Path(__file__)),csv=sha(ROOT/'result_exports.py'),
     presentation=sha(code/'research_figures.py'),plotter=sha(code/'plot_research_set.py')))[:32]
 folder=owned(Path(root)/'data/research-set-exports'/ident,root)
 if folder.exists():return load_export(ident,root)[1]
 stage=folder.parent/('.preparing_'+uuid.uuid4().hex);stage.mkdir(parents=True)
 from review_annotations import annotate,export_notes
 export_notes(stage,evidence,root)
 (stage/'comparison.csv').write_bytes(csv_bytes(annotate(rows,evidence)));write_json(stage/'dataset.json',data,root);write_json(stage/'result-evidence.json',evidence,root)
 summary=coverage(rows);plots=plot_rows(rows)
 write_json(stage/'coverage.json',summary,root)
 periods={(tuple(r['period']),r['step_minutes']) for r in evidence}
 period,step=next(iter(periods)) if len(periods)==1 else (None,None)
 period_label=('全年' if period==(1,1,12,31) else f'{period[0]}/{period[1]}—{period[2]}/{period[3]}')+f' · {step} min' if period else '各地点时段与步长见数据快照'
 write_json(stage/'plot-data.json',dict(name=data['name'],revision=data['revision'],dataset_sha256=data['dataset_sha256'],period_label=period_label,coverage=summary,rows=plots),root)
 (stage/'plot-data.csv').write_bytes(csv_bytes(annotate(plots,evidence)))
 (stage/'说明.txt').write_text('研究对比集：'+data['name']+' · v'+str(data['revision'])+'\n单位 kWh，为所选时段建筑显热冷热需求，不是设备耗电。\n节省量 = W00 − 研究；节省率 = 节省量 / W00 × 100%。负值表示需求增加。\n空白为无有效配对或基准为零，不能填零。待复核及未完成结果不纳入。\n城市为代表地点，不代表全省平均；没有汇总为全国建筑总量。\n组内共同条件及逐地点气象、时段、步长、模式、完整天数均须一致，才计算节省量。\n各批次、保存版本、结果及复核依据标识见 JSON；原始计算文件保持原位。\n',encoding='utf-8')
 (stage/'图表编辑说明.txt').write_text('每页最多 12 个代表地点，含供暖、制冷、冷热合计三个面板。\nSVG 为可编辑文字与矢量图；PDF 为矢量图；PNG 为 300 dpi。\nOrigin：导入 plot-data.csv，按 metric 分为 heating/cooling/total，city 作类别，role 作分组，plot_kWh 作数值。请将空白保留为缺失值。\nplot_kWh 仅含同条件配对结果；source_kWh 保留可用源数值以便追溯，未配对时不绘制。pair_reason 给出原因。\nsaved_kWh/saved_percent 为 W00 减研究，负值表示需求增加；W00 为零时百分比留空。\ncomparison.csv 保留完整宽表，coverage.json 为当前选中批次的覆盖统计，figure-pages.json 记录各页地点。\n这里没有按省平均、气候面积加权或全国建筑存量推算。图名与组版本对应；结果来自同一数据快照。\n可在 Origin 调整配色、字体、坐标与布局，论文最终版式和归一化口径另行确定。\n',encoding='utf-8')
 from summary_retention import export_notice
 export_notice(stage,data)
 from runtime_settings import plotting_python,figure_font
 python=plotting_python(root)
 run=subprocess.run([str(python),'-X','utf8',str(code/'plot_research_set.py'),str(stage),'--font',str(figure_font(root))],capture_output=True,text=True,encoding='utf-8',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 require(run.returncode==0,'对比图导出失败：'+run.stderr[-600:])
 from summary_retention import export_notice
 export_notice(stage,data)
 names=sorted(p.name for p in stage.iterdir())
 with zipfile.ZipFile(stage/'comparison.zip','w',zipfile.ZIP_DEFLATED) as z:
  for name in names:z.write(stage/name,name)
 names.append('comparison.zip')
 receipt=dict(id=ident,created=now(),set_id=data['id'],revision=data['revision'],dataset_sha256=data['dataset_sha256'],choices=choices,rows=len(rows),paired=summary['paired'],coverage=summary,
     figure_pages=read_json(stage/'figure-pages.json')['pages'],new_simulations=0,source_results_modified=False,files={n:sha(stage/n) for n in names})
 write_json(stage/'receipt.json',receipt,root)
 try:stage.rename(folder)
 except FileExistsError:return load_export(ident,root)[1]
 return load_export(ident,root)[1]
