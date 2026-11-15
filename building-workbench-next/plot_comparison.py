"""Publication plots and editable matrices from exactly one comparison dataset."""
import base64
import csv
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Polygon, Patch
from result_exports import color_limit,figure_kind,annual_site_rows


def plot_site(folder,d):
    """One pinned site, absolute sensible demand; no climate extrapolation."""
    site=d['sites'][0];rows=annual_site_rows(d)
    monthly=sorted((r for r in d['monthly'] if r['site_id']==site['site_id']),key=lambda r:r['month'])
    if not monthly:raise ValueError('Missing monthly paired data')
    for row in rows:
        if not all(np.isfinite(row[k]) for k in ('reference_kWh','study_kWh','saved_kWh')):raise ValueError('Non-finite site demand')
    if any(not np.isfinite(r[k+'_saved_kWh']) for r in monthly for k in ('heating','cooling')):raise ValueError('Non-finite monthly demand')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    period='Annual' if d['annual'] else f"{d['period'][0]:02d}/{d['period'][1]:02d}–{d['period'][2]:02d}/{d['period'][3]:02d}"
    fig,(top,bottom)=plt.subplots(2,1,figsize=(9.2,7.7),layout='constrained',gridspec_kw={'height_ratios':[1,1]})
    x=np.arange(3);w=.32
    for offset,key,color,label in [(-w/2,'reference_kWh','#758786','Reference'),(w/2,'study_kWh','#16745f','Study')]:
        bars=top.bar(x+offset,[r[key] for r in rows],w,color=color,label=label)
        top.bar_label(bars,labels=[f'{r[key]:,.0f}' for r in rows],padding=3,fontsize=9)
    top.set_xticks(x,['Heating','Cooling','Heating + cooling']);top.set(ylabel='Sensible demand (kWh)',title=f'(a) {period} reference and study demand')
    top.margins(y=.20);top.legend(frameon=False,ncols=2,loc='upper left');top.set_axisbelow(True);top.grid(axis='y',alpha=.18)
    m=np.arange(len(monthly))
    for offset,key,color,label in [(-w/2,'heating','#b96a32','Heating'),(w/2,'cooling','#16857d','Cooling')]:
        bottom.bar(m+offset,[r[key+'_saved_kWh'] for r in monthly],w,color=color,label=label)
    bottom.axhline(0,color='#47565b',linewidth=.8);bottom.set_xticks(m,[str(r['month']) for r in monthly])
    bottom.set(ylabel='Reference − study (kWh)',xlabel='Month',title='(b) Monthly contributions to demand reduction')
    bottom.set_axisbelow(True);bottom.grid(axis='y',alpha=.18);bottom.legend(frameon=False,ncols=2,loc='upper right')
    fig.suptitle(f"{period} sensible demand comparison · {d['step_minutes']} min",fontsize=13)
    fig.get_layout_engine().set(rect=(0,.08,1,.90))
    fig.text(.075,.025,'Positive reduction: lower demand; negative: higher demand. Sensible demand, not equipment electricity.\n'+
        ('Twelve full months.' if d['annual'] else f'Selected dates only: {period}; partial-month totals.')+f" Dataset: {d['dataset_sha256'][:16]}",fontsize=8)
    if __import__('summary_retention').notices(d):fig.text(.99,.99,'Retained summary; raw details removed',ha='right',va='top',fontsize=7,color='#805600')
    if (folder/'user-review-notes.json').exists():fig.text(.99,.955,'User-reviewed warnings retained; see review notes',ha='right',va='top',fontsize=7,color='#805600')
    for ext in ('svg','pdf','png'):fig.savefig(folder/('figure.'+ext),dpi=300,facecolor='white')
    plt.close(fig)
    (folder/'figure_caption.txt').write_text(f"{period} sensible heating and cooling demand at {site['city']} ({site['site_id']}). Panel (a) compares reference and study totals in kWh; panel (b) shows monthly reference-minus-study contributions, positive for reduced demand and negative for increased demand. The plotted period is {d['period']}; monthly values contain only selected dates. Reference: {d['records']['left']['name']} v{d['records']['left']['revision']}; study: {d['records']['right']['name']} v{d['records']['right']['revision']}. This single-site result is not a climate-type or global estimate. Timesteps: {d['step_minutes']} min. Dataset: {d['dataset_sha256']}. See dataset.json for pinned sources and scientific review evidence.",encoding='utf-8')


def plot(folder):
    folder=Path(folder);d=json.loads((folder/'dataset.json').read_text('utf-8'))
    if figure_kind(d)=='site':return plot_site(folder,d)
    a=json.loads((folder/'map.json').read_text('utf-8'))
    g=a['grid'];grid=np.frombuffer(base64.b64decode(g['data']),dtype=np.uint8).reshape((g['height'],g['width']))
    np.savetxt(folder/'matrix_climate.csv',grid,delimiter=',',fmt='%d')
    cmap=LinearSegmentedColormap.from_list('paired',['#2166ac','#f7f7f7','#b2182b']);cmap.set_bad('#d1d5db')
    limit=color_limit(d);norm=Normalize(-limit,limit);classes=d['classes'];land=a['land']['coordinates']
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    fig=plt.figure(figsize=(12,9.7),layout='constrained');gs=fig.add_gridspec(3,2,height_ratios=[1,1,1.12])
    period='Annual' if d['annual'] else f"{d['period'][0]:02d}/{d['period'][1]:02d}–{d['period'][2]:02d}/{d['period'][3]:02d}"
    axes=[fig.add_subplot(gs[0,0]),fig.add_subplot(gs[0,1]),fig.add_subplot(gs[1,:])]
    for ax,metric,title in zip(axes,['heating','cooling','total'],['Heating','Cooling','Total heating + cooling']):
        lut=np.full(31,np.nan)
        for c in classes:lut[c['id']]=c[metric+'_saved_MJ_m2_mean'] if c[metric+'_saved_MJ_m2_mean'] is not None else np.nan
        z=lut[grid]
        with (folder/('map_'+metric+'.csv')).open('w',encoding='utf-8',newline='') as f:
            csv.writer(f).writerows([float(v) if np.isfinite(v) else '' for v in row] for row in z)
        # An all-white ocean mask is independent of missing values on classified land.
        rgba=cmap(norm(z));rgba[grid==0]=[1,1,1,1]
        ax.imshow(rgba,extent=(-180,180,-90,90),origin='upper',interpolation='nearest')
        for poly in land:
            for ring in poly:ax.add_patch(Polygon(ring,closed=True,fill=False,edgecolor='#4b5563',linewidth=.25))
        ax.set(xlim=(-180,180),ylim=(-90,90),xticks=[-180,-90,0,90,180],yticks=[-60,0,60],title=f'{period} {title.lower()} demand reduction')
        ax.set_aspect('equal');ax.tick_params(labelsize=7);ax.spines[['left','bottom']].set_visible(False)
    cbar=fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm,cmap=cmap),ax=axes,orientation='horizontal',fraction=.025,pad=.015,shrink=.65)
    cbar.set_label('Reference − study (MJ m⁻² of conditioned floor area)')
    fig.legend(handles=[Patch(facecolor='#d1d5db',label='No paired data')],loc='center right',bbox_to_anchor=(.97,.57),frameon=False,fontsize=8)
    ax=fig.add_subplot(gs[2,:]);x=np.arange(len(classes));key=d['metric']+'_saved_MJ_m2_'
    vals=np.array([c[key+'mean'] if c[key+'mean'] is not None else np.nan for c in classes]);lo=np.array([c[key+'min'] if c[key+'min'] is not None else np.nan for c in classes]);hi=np.array([c[key+'max'] if c[key+'max'] is not None else np.nan for c in classes]);valid=np.isfinite(vals)
    ax.bar(x[valid],vals[valid],color=cmap(norm(vals[valid])),edgecolor='#6b7280',linewidth=.5)
    ax.errorbar(x[valid],vals[valid],yerr=[vals[valid]-lo[valid],hi[valid]-vals[valid]],fmt='none',ecolor='#30383d',capsize=2,linewidth=.8)
    ax.scatter(x[~valid],np.zeros((~valid).sum()),marker='x',color='#6b7280',label='No paired data')
    ax.axhline(0,color='#6b7280',linewidth=.7);ax.set_xticks(x,[c['climate']+'\n'+str(c['valid_sites']) for c in classes],fontsize=8)
    ax.set(ylabel='Demand reduction (MJ m⁻²)',xlabel='Köppen–Geiger climate type / paired sites (n)',title=f"{d['metric'].capitalize()} demand reduction: mean and site range")
    fig.suptitle(f"Climate representative comparison · {d['step_minutes']} min · {d['paired_sites']} paired sites",fontsize=14)
    fig.get_layout_engine().set(rect=(0,.105,1,.83))
    fig.text(.02,.068,f"Equal-site means; bars show site ranges, not confidence intervals. Grey / ×: no data.\nClimate-type mapping, not pixel simulations. Period: {period}; area: {d['conditioned_area_m2']:g} m². Dataset: {d['dataset_sha256'][:16]}",fontsize=8)
    attribution=('Climate: Beck et al. (2023), CC BY 4.0 (creativecommons.org/licenses/by/4.0/).\n'
        'Data: doi.org/10.6084/m9.figshare.21789074; 1991–2020 grid reduced from 0.1° to 0.5° by modal aggregation.\n'
        'Land: Natural Earth (public domain); @d3-maps/atlas 1.0.0 (MIT), © 2026 Georgii Bukharov. See MAP_ATTRIBUTION.md.')
    fig.text(.02,.016,attribution,fontsize=7,color='#4b5563')
    if __import__('summary_retention').notices(d):fig.text(.99,.99,'Retained summary; raw details removed',ha='right',va='top',fontsize=7,color='#805600')
    if (folder/'user-review-notes.json').exists():fig.text(.99,.955,'User-reviewed warnings retained; see review notes',ha='right',va='top',fontsize=7,color='#805600')
    for ext in ('svg','pdf','png'):fig.savefig(folder/('figure.'+ext),dpi=300,facecolor='white')
    plt.close(fig)
    (folder/'figure_caption.txt').write_text(f"{period} sensible heating and cooling demand reduction for the selected reference and study schemes. Class values are equal-weight means of paired representative sites; vertical ranges show site minima and maxima, not confidence intervals. Results are normalized by {d['conditioned_area_m2']} m² of conditioned floor area. Climate-type values are mapped onto an existing 0.5° display grid and are not simulations at every grid cell. Missing results remain missing. The figure uses {d['paired_sites']} paired sites, {d['step_minutes']} min simulation timesteps, and dataset {d['dataset_sha256']}. See dataset.json for pinned scheme revisions, source batches, excluded sites and review notes. Climate map source: {a['manifest']['source'].get('classification_url','')}.\n"+attribution,encoding='utf-8')


if __name__=='__main__':plot(sys.argv[1])
