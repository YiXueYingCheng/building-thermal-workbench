'use strict';
// Views derived only from the already validated, pinned comparison dataset.
function resetComparisonDetails(){S.comparisonSelected=null;S.comparisonFilter={query:'',direction:''};}
resetComparisonDetails();
function comparisonDirection(row,metric){
 const v=row[metric+'_saved_kWh'];
 if(row.status!=='paired'||!Number.isFinite(v))return 'excluded';
 return v>0?'lower':v<0?'higher':'equal';
}
function comparisonFilteredSites(d){
 const q=S.comparisonFilter.query.trim().toLocaleLowerCase(),f=S.comparisonFilter.direction;
 return d.sites.filter(r=>(!S.climateFilter||r.climate===S.climateFilter)&&(!f||comparisonDirection(r,S.mapMetric)===f)&&(!q||[r.city,r.site_id,r.climate,r.country,r.site_kind].join(' ').toLocaleLowerCase().includes(q)));
}
function selectComparisonClimate(climate){S.climateFilter=climate;S.comparisonTable='sites';resetComparisonDetails();}
function comparisonFilters(d){
 const counts={lower:0,higher:0,equal:0,excluded:0};for(const r of d.sites)counts[comparisonDirection(r,S.mapMetric)]++;
 return `<div class="comparison-outcomes"><p>${metricNames[S.mapMetric]} · 全部所选地点</p><div class="actions">${[['lower','降低'],['higher','增加'],['equal','持平'],['excluded','未纳入']].map(([k,label])=>`<button data-comparison-direction="${k}" aria-pressed="${S.comparisonTable==='sites'&&S.comparisonFilter.direction===k}">${label} ${counts[k]} 地点</button>`).join('')}</div></div>
 ${S.comparisonTable==='sites'?`<div class="comparison-filters"><label class="field">搜索地点<input id="comparison-query" type="search" value="${esc(S.comparisonFilter.query)}" placeholder="地点、气候或站点名称"></label><label class="field">${metricNames[S.mapMetric]}变化<select id="comparison-direction">${options([['','全部'],['lower','需求降低'],['higher','需求增加'],['equal','需求持平'],['excluded','未纳入配对']],S.comparisonFilter.direction)}</select></label><button data-action="clear-comparison-filters">清除筛选</button></div><p class="muted">筛选只影响地点列表；地图、气候均值和导出仍使用本次读取的完整配对结果。</p>`:''}`;
}
function comparisonDataTable(d,metric,unit,unitLabel){
 const isClass=S.comparisonTable==='classes',rows=isClass?d.classes:comparisonFilteredSites(d);
 if(!rows.length)return '<p class="empty">当前筛选下没有地点；可清除筛选查看完整结果。</p>';
 return `${isClass?'':`<p class="muted" id="comparison-site-count" aria-live="polite">显示 ${rows.length} / ${d.sites.length} 个地点</p>`}<div class="table-scroll" tabindex="0" aria-label="比较结果，可横向滚动"><table class="table comparison-data-table"><thead><tr><th>${isClass?'气候类型':'地点 / 明细'}</th><th>样本 / 状态</th><th class="num">参考 / kWh</th><th class="num">研究 / kWh</th><th class="num">降低 / ${unitLabel}</th><th>${isClass?'地点范围 / '+unitLabel:'降低率 / 原因'}</th></tr></thead><tbody>${rows.map(r=>isClass?`<tr><td><button data-climate-filter="${esc(r.climate)}">${esc(r.climate+' · '+r.name)}</button></td><td>${r.valid_sites} / ${r.selected_sites}<small>${r.status==='no_data'?'无数据':r.status==='partial'?'部分地点有效':'所选地点已配对'}</small></td><td class="num">${format(r['left_'+metric+'_kWh_mean'])}</td><td class="num">${format(r['right_'+metric+'_kWh_mean'])}</td><td class="num">${format(r[metric+'_saved_'+unit+'_mean'])}</td><td>${format(r[metric+'_saved_'+unit+'_min'])} ～ ${format(r[metric+'_saved_'+unit+'_max'])}</td></tr>`:`<tr><td><button data-comparison-site="${esc(r.site_id)}" aria-label="查看 ${esc(r.city)} 比较明细">${esc(r.city)}</button><small>${esc(r.climate||'未分类')} · ${esc(r.site_kind||'地点')}</small></td><td>${r.status==='paired'?'已配对':'未纳入'}</td><td class="num">${format(r['left_'+metric+'_kWh'])}</td><td class="num">${format(r['right_'+metric+'_kWh'])}</td><td class="num">${format(r[metric+'_saved_'+unit])}</td><td>${r.reason?esc(r.reason):r[metric+'_saved_percent']===null?'基准为零，比例不适用':format(r[metric+'_saved_percent'])+'%'}${r.left_pending_warnings.length||r.right_pending_warnings.length?`<details><summary>${r.status==='paired'?'原警告记录':'待复核警告'}</summary><p>参考结果</p>${warningRecordsView(r.left_pending_warnings)}<p>研究结果</p>${warningRecordsView(r.right_pending_warnings)}</details>`:''}</td></tr>`).join('')}</tbody></table></div>`;
}
function comparisonReviewSide(d,r,side){
 const e=r[side+'_evidence'],review=e?.scientific_review,record=d.records[side],pending=r[side+'_pending_warnings']||[];
 const labels={passed:'核验通过',reused:'核验通过并复用',review:'待复核',pending:'待计算',running:'计算中',failed:'失败',interrupted:'中断',cancelled:'已取消',missing:'无结果'};
 return `<div class="review-note"><h4>${side==='left'?'参考':'研究'}：${esc(record.name)} · 版本 ${esc(record.revision)}</h4><p>${review?'附说明接受':e?.kind==='reviewed_historical'&&['passed','reused'].includes(r[side+'_status'])?'已复核历史来源':esc(labels[r[side+'_status']]||r[side+'_status'])}</p>
 ${review?`<p>${esc(review.method)}</p><p>${esc(review.display_scope)}</p><p class="muted">复核时间：${esc(new Date(review.reviewed_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}))}</p><details><summary>原警告与依据标识</summary>${warningRecordsView(review.warnings)}<p class="source-path">原结果 ${esc(review.original_result_sha256)}<br>复核依据 ${esc(review.evidence_sha256)}</p></details>`:pending.length?`<p>自动校验已完成，警告需单独复核；当前没有自动复核任务。</p><details><summary>${warningGroups(pending).length} 类警告记录</summary>${warningRecordsView(pending)}</details>`:e?.kind==='reviewed_historical'?'<p class="muted">沿用该历史来源已登记的逐地点复核结论。</p>':''}
 ${e?`<details><summary>来源标识</summary><p class="source-path">${e.kind==='execution'?'批次 '+esc(e.batch_id)+'<br>结果 '+esc(e.result_sha256||'未形成完整结果'):'历史结果 '+esc(e.result?.sha256||'')+'<br>原登记状态 '+esc(e.review_status||'')}</p></details>`:''}</div>`;
}
function comparisonMonthChart(rows,unit){
 const series=[['heating','供暖','#bd6a30'],['cooling','制冷','#16857d']];
 if(!rows.length||rows.some(r=>series.some(([k])=>!Number.isFinite(r[k+'_saved_'+unit]))))return '<p class="muted">缺少可绘制的月度配对结果，不补零。</p>';
 const width=720,height=246,pad=58,top=30,bottom=205,zero=(top+bottom)/2;
 const limit=Math.max(1,...rows.flatMap(r=>series.map(([k])=>Math.abs(r[k+'_saved_'+unit])))),scale=(bottom-top)/2/limit;
 const span=(width-pad-12)/rows.length,bw=Math.min(18,span*.28),y=v=>zero-v*scale;
 return `<div class="comparison-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="所选时段月度供暖与制冷需求降低量；正值降低，负值增加，明细数值见下表"><title>月度冷热贡献</title>${[-limit,0,limit].map(v=>`<line x1="${pad}" y1="${y(v)}" x2="${width-12}" y2="${y(v)}" class="${v===0?'chart-zero':'chart-grid'}"/><text x="${pad-8}" y="${y(v)+4}" text-anchor="end">${format(v,1)}</text>`).join('')}${rows.map((r,i)=>{const center=pad+span*(i+.5);return series.map(([k,label,color],j)=>{const v=r[k+'_saved_'+unit];return `<rect data-month="${r.month}" data-component="${k}" data-value="${v}" x="${center+(j-1)*bw}" y="${Math.min(zero,y(v))}" width="${bw-2}" height="${Math.abs(v)*scale}" fill="${color}"><title>${r.month} 月${label}降低 ${format(v,4)} ${unit==='MJ_m2'?'MJ/m²':'kWh'}</title></rect>`;}).join('')+`<text x="${center}" y="${bottom+22}" text-anchor="middle">${r.month}月</text>`;}).join('')}<text x="${pad}" y="15">${unit==='MJ_m2'?'MJ/m²':'kWh'} · 参考减研究</text></svg></div><div class="comparison-chart-legend"><span><i class="heating-swatch"></i>供暖</span><span><i class="cooling-swatch"></i>制冷</span><span>正值：需求降低；负值：需求增加</span></div>`;
}
function comparisonSiteDetail(d){
 const r=d?.sites.find(r=>r.site_id===S.comparisonSelected);if(!r)return '';
 const table=(headers,rows,cls='')=>`<div class="table-scroll" tabindex="0"><table class="table comparison-detail-table ${cls}"><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 const unit=d.normalized?'MJ_m2':'kWh',label=d.normalized?'MJ/m²':'kWh';
 const monthly=d.monthly.filter(m=>m.site_id===r.site_id).slice().sort((a,b)=>a.month-b.month);
 let body='';
 if(r.status!=='paired')body=`<p class="warning">未纳入配对：${esc(r.reason||'缺少可比较结果')}。本地点不计算降低量，不参与本次气候均值。</p>`;
 else if(d.metric==='temperature'){
  body=`<h4>逐房间室温 / °C</h4><p class="muted">温差为研究减参考。极值差不是同一时刻的温差，不把不同房间自行平均为节能量。</p>${table(['房间','指标','参考','研究','研究减参考'],d.rooms.filter(t=>t.site_id===r.site_id).flatMap(t=>[['mean_C','时段均温'],['min_C','最低温'],['max_C','最高温']].map(([key,name])=>`<tr><td>${esc(t.zone)}</td><td>${name}</td><td class="num">${format(t['left_'+key],3)}</td><td class="num">${format(t['right_'+key],3)}</td><td class="num">${format(t['right_minus_left_'+key],3)}</td></tr>`)),'comparison-room-detail')}`;
 }else{
  const explain=k=>`${metricNames[k]}${r[k+'_saved_kWh']>0?'降低':r[k+'_saved_kWh']<0?'增加':'持平'}${r[k+'_saved_kWh']===0?'':' '+format(Math.abs(r[k+'_saved_'+unit]),3)+' '+label}`;
  body=`<p class="comparison-outcome-text">${['heating','cooling','total'].map(explain).join('；')}。</p><p class="muted scroll-hint">窄屏可左右滑动图表和表格，查看完整月份与数据列。</p><h4>${d.annual?'年度':'所选时段'}负荷对照</h4>${table(['需求','参考 / kWh','研究 / kWh','降低 / '+label,'降低率'],['heating','cooling','total'].map(k=>`<tr><td>${metricNames[k]}</td><td class="num">${format(r['left_'+k+'_kWh'],3)}</td><td class="num">${format(r['right_'+k+'_kWh'],3)}</td><td class="num">${format(r[k+'_saved_'+unit],3)}</td><td>${r[k+'_saved_percent']===null?'基准为零，比例不适用':format(r[k+'_saved_percent'],3)+'%'}</td></tr>`),'comparison-annual-detail')}
  <h4>月度冷热贡献</h4><p class="muted">${d.annual?'全年覆盖月份':'仅所选时段覆盖的月份，短时段不代表完整月份'}；每根柱为同月参考减研究，供暖与制冷相加为总需求降低。</p>${comparisonMonthChart(monthly,unit)}
  ${table(['月份','供暖降低 / '+label,'制冷降低 / '+label,'总需求降低 / '+label],monthly.map(m=>`<tr><td>${m.month} 月</td>${['heating','cooling','total'].map(k=>`<td class="num">${format(m[k+'_saved_'+unit],3)}</td>`).join('')}</tr>`),'comparison-month-detail')}
  <details><summary>查看双方月度原负荷 / kWh</summary>${table(['月份','参考供暖','研究供暖','参考制冷','研究制冷','参考合计','研究合计'],monthly.map(m=>`<tr><td>${m.month} 月</td>${['heating','cooling','total'].flatMap(k=>['left','right'].map(side=>`<td class="num">${format(m[side+'_'+k+'_kWh'],3)}</td>`)).join('')}</tr>`))}</details>`;
 }
 return `<section id="comparison-site-detail" class="well comparison-site-detail" tabindex="-1"><div class="row"><h3>${esc(r.city)} · 比较明细</h3><button data-action="close-comparison-detail">收起明细</button></div><p>${esc(r.climate||'未分类')} · ${esc(r.site_kind||'地点')} · ${d.period.slice(0,2).join('-')} 至 ${d.period.slice(2).join('-')} · ${d.step_minutes} min</p>${body}<details class="comparison-review"><summary>双方来源与复核说明</summary><div class="grid2">${comparisonReviewSide(d,r,'left')}${comparisonReviewSide(d,r,'right')}</div></details></section>`;
}
function refreshComparisonList(){
 const d=S.comparisonData;if(!d)return;
 if(S.comparisonSelected&&!comparisonFilteredSites(d).some(r=>r.site_id===S.comparisonSelected))S.comparisonSelected=null;
 const slot=document.getElementById('comparison-table-slot');if(slot)slot.innerHTML=comparisonDataTable(d,S.mapMetric,d.normalized?'MJ_m2':'kWh',d.normalized?'MJ/m²':'kWh');
 const detail=document.getElementById('comparison-detail-slot');if(detail)detail.innerHTML=comparisonSiteDetail(d);
}
function comparisonDetailAction(button){
 if(button.dataset.comparisonSite){S.comparisonSelected=button.dataset.comparisonSite;setTimeout(()=>{const p=document.getElementById('comparison-site-detail');p?.focus();p?.scrollIntoView({block:'start'});},0);return true;}
 if(button.dataset.comparisonDirection){S.comparisonTable='sites';S.comparisonFilter={query:'',direction:button.dataset.comparisonDirection};S.climateFilter='';S.comparisonSelected=null;return true;}
 if(button.dataset.action==='clear-comparison-filters'){S.climateFilter='';resetComparisonDetails();return true;}
 if(button.dataset.action==='close-comparison-detail'){const selected=S.comparisonSelected;S.comparisonSelected=null;setTimeout(()=>[...document.querySelectorAll('[data-comparison-site]')].find(b=>b.dataset.comparisonSite===selected)?.focus(),0);return true;}
 return false;
}
document.addEventListener('input',event=>{if(event.target.id!=='comparison-query')return;S.comparisonFilter.query=event.target.value;refreshComparisonList();});
document.addEventListener('change',event=>{if(event.target.id!=='comparison-direction')return;S.comparisonFilter.direction=event.target.value;S.comparisonSelected=null;render();});
