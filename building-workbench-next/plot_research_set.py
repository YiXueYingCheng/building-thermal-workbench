"""Render paginated, editable set figures from frozen plot rows; never read runs."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch

def plot(folder, font=None):
    folder=Path(folder);d=json.loads((folder/'plot-data.json').read_text('utf-8'))
    if font is None:
        from runtime_settings import figure_font
        font=figure_font()
    font=Path(font)
    if not font.exists():raise ValueError('未找到中文绘图字体 Microsoft YaHei。')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),'font.size':9,
        'axes.unicode_minus':False,'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    colors={'baseline':'#778681','fixed':'#267c61','flip':'#b87333','feedback':'#715596'}
    colors={k:v for k,v in colors.items() if any(r['role']==k for r in d['rows'])}
    offsets=[(i-(len(colors)-1)/2)*.21 for i in range(len(colors))]
    labels={'baseline':'W00 原构造','fixed':'固定 ECA','flip':'ECA 表面光学切换','feedback':'表面光学切换＋热阻调节'}
    metrics={'heating':'供暖显热需求','cooling':'制冷显热需求','total':'冷热需求合计'}
    sites=list(dict.fromkeys(r['site_id'] for r in d['rows']));pages=[]
    lookup={(r['site_id'],r['metric'],r['role']):r for r in d['rows']}
    limits={metric:max([r['plot_kWh'] for r in d['rows'] if r['metric']==metric and r['plot_kWh'] is not None]+[0])*1.32 or 1 for metric in metrics}
    for start in range(0,len(sites),12):
        ids=sites[start:start+12];page=len(pages)+1
        fig,axes=plt.subplots(1,3,figsize=(15,max(4,1.9+.55*len(ids))),layout='constrained',sharey=True)
        for ax,(metric,title) in zip(axes,metrics.items()):
            limit=limits[metric]
            for i,sid in enumerate(ids):
                for offset,(role,color) in zip(offsets,colors.items()):
                    row=lookup[(sid,metric,role)];value=row['plot_kWh'];y=i+offset
                    if value is None:
                        text='无数据' if row['source_kWh'] is None else '未配对'
                        ax.text(limit*.015,y,text,va='center',color='#707b76',fontsize=7)
                    else:
                        if value:ax.barh(y,value,height=.18,color=color)
                        ax.text(value+limit*.012,y,f'{value:,.1f}',va='center',color='#34463e',fontsize=7)
            ax.set(title=title,xlabel='显热需求 / kWh',xlim=(0,limit),ylim=(len(ids)-.5,-.6))
            ax.set_yticks(range(len(ids)),[lookup[(sid,metric,'baseline')]['city'] for sid in ids])
            ax.set_axisbelow(True);ax.grid(axis='x',alpha=.16);ax.tick_params(axis='y',length=0)
        height=fig.get_figheight()
        fig.suptitle(d['name']+' · v'+str(d['revision'])+f' · 第 {page}/{(len(sites)+11)//12} 页',fontsize=13,y=1-.05/height).set_in_layout(False)
        fig.legend(handles=[Patch(facecolor=c,label=labels[k]) for k,c in colors.items()],loc='upper center',ncols=len(colors),frameon=False,bbox_to_anchor=(.55,1-.35/height))
        fig.get_layout_engine().set(rect=(0,.5/height,1,1-1.25/height))
        fig.text(.02,.025,'仅绘制同条件、已接受结果；空缺不记为零。各地点为代表城市，不代表全省平均或全国总量。\n'
            +d['period_label']+'；建筑显热需求，不是设备耗电。数据快照：'+d['dataset_sha256'][:16],fontsize=8,color='#516259')
        name=f'figure-{page:02d}'
        if (folder/'summary-retention.json').exists():fig.text(.99,.99,'Retained summary; raw details removed',ha='right',va='top',fontsize=7,color='#805600')
        if (folder/'user-review-notes.json').exists():fig.text(.99,.955,'User-reviewed warnings retained; see review notes',ha='right',va='top',fontsize=7,color='#805600')
        for ext in ('svg','pdf','png'):fig.savefig(folder/(name+'.'+ext),dpi=300,facecolor='white')
        plt.close(fig);pages.append(dict(page=page,site_ids=ids,files=[name+'.'+ext for ext in ('svg','pdf','png')]))
    (folder/'figure-pages.json').write_text(json.dumps(dict(pages=pages,dataset_sha256=d['dataset_sha256']),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('folder')
    parser.add_argument('--font')
    args=parser.parse_args()
    plot(args.folder,args.font)
