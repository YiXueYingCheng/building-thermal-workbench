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
 return `${isClass?'':`<p class="muted" id="comparison-site-count" aria-live="polite">显示 ${rows.length} / ${d.sites.length} 个地点</p>`}<div class="table-scroll" tabindex="0" aria-label="比较结果，可横向滚动"><table class="table comparison-data-table"><thead><tr><th>${isClass?'气候类型':'地点 / 明细'}</th><th>样本 / 状态</th><th class="num">参考 / kWh</th><th class="num">研究 / kWh</th><th class="num">降低 / ${unitLabel}</th><th>${isClass?'地点范围 / '+unitLabel:'降低率 / 原因'}</th></tr></thead><tbody>${rows.map(r=>isClass?`<tr><td><button data-climate-filter="${esc(r.climate)}">${esc(r.climate+' · '+r.name)}</button></td><td>${r.valid_sites} / ${r.selected_sites}<small>${r.status==='no_data'?'无数据':r.status==='partial'?'部分地点有效':'所选地点已配对'}</small></td><td class="num">${format(r['left_'+metric+'_kWh_mean'])}</td><td class="num">${format(r['right_'+metric+'_kWh_mean'])}</td><td class="num">${format(r[metric+'_saved_'+unit+'_mean'])}</td><td>${format(r[metric+'_saved_'+unit+'_min'])} ～ ${format(r[metric+'_saved_'+unit+'_max'])}</td></tr>`:`<tr><td><button data-comparison-site="${esc(r.site_id)}" aria-label="查看 ${esc(r.city)} 比较明细">${esc(r.city)}</button><small>${esc(r.climate||'未分类')} · ${esc(r.site_kind||'地点')}</small><small>参考 ${r.left_step_minutes??'—'} min · 研究 ${r.right_step_minutes??'—'} min</small></td><td>${r.status==='paired'?esc(r.pairing_basis||'已配对'):'未纳入'}</td><td class="num">${format(r['left_'+metric+'_kWh'])}</td><td class="num">${format(r['right_'+metric+'_kWh'])}</td><td class="num">${format(r[metric+'_saved_'+unit])}</td><td>${r.reason?esc(r.reason):r[metric+'_saved_percent']===null?'基准为零，比例不适用':format(r[metric+'_saved_percent'])+'%'}${r.left_pending_warnings.length||r.right_pending_warnings.length?`<details><summary>${r.status==='paired'?'原警告记录':'待复核警告'}</summary><p>参考结果</p>${warningRecordsView(r.left_pending_warnings)}<p>研究结果</p>${warningRecordsView(r.right_pending_warnings)}</details>`:''}</td></tr>`).join('')}</tbody></table></div>`;
}
function comparisonReviewSide(d,r,side){
 const e=r[side+'_evidence'],review=e?.scientific_review,record=d.records[side],pending=r[side+'_pending_warnings']||[];
 if(e?.kind==='observed')return `<div class="review-note"><h4>${side==='left'?'参考':'研究'} · ${esc(record.name)}</h4><p>独立实算 · 已核对输入、气象及原始 SQL</p><p>求解 ${r[side+'_step_minutes']} min · 绑定版本 v${record.revision}</p><details><summary>核对标识及日志</summary><p class="source-path">已验收模型 ${esc(e.model_sha256)}<br>实际运行模型 ${esc(e.run_sha256)}<br>结果 SQL ${esc(e.result_sha256)}</p><p>${esc(e.warnings.join(' / '))}</p></details></div>`;
 const labels={passed:'核验通过',reused:'核验通过并复用',review:'待复核',pending:'待计算',running:'计算中',failed:'失败',interrupted:'中断',cancelled:'已取消',missing:'无结果'};
 return `<div class="review-note"><h4>${side==='left'?'参考':'研究'}：${esc(record.name)} · 版本 ${esc(record.revision)}</h4><p>${review?esc(review.label):e?.kind==='reviewed_historical'&&['passed','reused'].includes(r[side+'_status'])?'已复核历史来源':esc(labels[r[side+'_status']]||r[side+'_status'])}</p>
 ${review?`<p>${esc(review.method)}</p><p>${esc(review.display_scope)}</p>${reviewUserDecisionMarkup(review)}<p class="muted">复核时间：${esc(new Date(review.reviewed_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}))}</p><details><summary>原警告与依据标识</summary>${warningRecordsView(review.warnings)}<p class="source-path">原结果 ${esc(review.original_result_sha256)}<br>复核依据 ${esc(review.evidence_sha256)}</p></details>`:pending.length?`<p>自动校验已完成，警告需单独复核；当前没有自动复核任务。</p><details><summary>${warningGroups(pending).length} 类警告记录</summary>${warningRecordsView(pending)}</details>`:e?.kind==='reviewed_historical'?'<p class="muted">沿用该历史来源已登记的逐地点复核结论。</p>':''}
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

function comparisonStepPanel(d,row){
 const info=d.step_controls?.[row.site_id];
 if(!info)return '';
 const labels={left:'参考侧',right:'研究侧'};
 const button=(op,title,o={},run={})=>`<button data-pair-step="${op}" data-side="${o.side||''}" data-child="${esc(run.child||'')}" data-sha="${esc(run.result_sha256||'')}">${esc(title)}</button>`;
 let contents='';
 const waived=info.selected?.kind==='waiver';
 if(info.selected&&!waived){
  const choice=info.selected;
  contents=`<p>${labels[choice.side]}已为本次对照选用 ${choice.chosen.step} min，原批结果为 ${choice.pins[choice.side==='left'?0:1].step} min。</p>${button('clear','恢复本对照的原批结果…')}`;
 }else{
  contents=info.options.map(o=>{
   const active=o.runs.some(r=>['pending','running','review','passed','reused'].includes(r.status));
   const runs=o.runs.map(r=>{
    const state={pending:'排队中',running:'计算中',interrupted:'已中断',review:'待复核',failed:'失败',cancelled:'已取消',passed:'已通过',reused:'已通过'}[r.status]||r.status;
    return `<p>${o.step} min · ${esc(state)} ${['passed','reused'].includes(r.status)?button('select','仅在本对照选用 '+o.step+' min…',o,r):''}${r.error?' · '+esc(r.error):''}</p>`;
   }).join('');
   return `<p>${labels[o.side]}原批 ${row[o.side+'_step_minutes']} min，对侧 ${o.step} min。</p>${runs}${active?'':button('submit','仅加算'+row.city+' · '+labels[o.side]+' '+o.step+' min',o)}`;
  }).join('');
  if(waived){
   contents=`<p><strong>${row.pairing_basis==='跨步长豁免'?'本地点已确认跨步长豁免':'原豁免需重新核对'}</strong> · 参考 ${row.left_step_minutes} min / 研究 ${row.right_step_minutes} min</p>${button('clear','撤回本地点豁免…')}`+contents;
  }else if(info.can_waive){
   contents+=`<p>参考 ${row.left_step_minutes} min / 研究 ${row.right_step_minutes} min。差值可能包含步长变化的影响。确认后，该地点进入含豁免汇总，严格配对汇总单列。</p>${button('waive','仅此地点按不同步长纳入…')}`;
  }
  if(info.options.length)contents+=button('refresh','刷新加算状态');
 }
 return `<section class="well" data-step-panel><h3>按地点配对步长</h3>${contents}<p>选用只影响当前两个批次的这组对照与导出。原批汇总保留原结果。</p><p role="status" data-step-message></p></section>`;
}
document.addEventListener('click',async event=>{
 const b=event.target.closest('[data-pair-step]');
 if(!b)return;
 event.preventDefault();event.stopImmediatePropagation();
 const d=S.comparisonData,site=S.comparisonSelected,info=d?.step_controls?.[site];
 if(!info)return;
 const action=b.dataset.pairStep,side=b.dataset.side;
 const opt=info.options.find(o=>o.side===side);
 const row=d.sites.find(r=>r.site_id===site);
 const req={id:d.comparison.id,left_source:d.left.id,right_source:d.right.id,mode:d.mode};
 const msg=b.closest('[data-step-panel]').querySelector('[data-step-message]');
 if(action==='select'&&!window.confirm(`将${row.city}的${side==='left'?'参考':'研究'}侧 ${opt.step} min 加算用于本次对照及导出？原批结果保留。`))return;
 if(action==='waive'&&!window.confirm(`确认将${row.city}按参考 ${row.left_step_minutes} min、研究 ${row.right_step_minutes} min 纳入含豁免汇总？差值可能包含步长影响。导出将同时保留严格配对口径。`))return;
 if(action==='clear'&&!window.confirm(`恢复${row.city}的原批结果？两侧步长不一致时，该地点会列入未配对清单。`))return;
 b.disabled=true;
 msg.textContent='正在读取结果…';
 try{
  let message='';
  if(action==='submit'){
   const response=await api('/api/site-recalculation/submit',{purpose:'comparison',parent:opt.parent,index:opt.index,attempt:opt.attempt,step_minutes:opt.step});
   message=response.startup?.error||'已登记该地点的加算。';
  }else if(['select','waive','clear'].includes(action)){
   await api('/api/comparison-site-step',{...req,site,action,side,child:b.dataset.child,result_sha256:b.dataset.sha,expected:info.expected});
   message=action==='waive'?'已登记本地点豁免，可导出两种口径。':action==='select'?'已选用，当前对照和导出已更新。':'已恢复使用原批结果。';
  }
  const updated=await api('/api/comparison-results',req);
  if(S.comparisonData!==d)return;
  S.comparisonData=updated;S.comparisonExport=null;render();
  if(S.comparisonSelected===site){
   const status=document.querySelector('#result-viewer [data-step-message]');
   if(status)status.textContent=message;
  }
 }catch(e){msg.textContent=e.message;}
 finally{b.disabled=false;}
},true);

function comparisonWallScope(d, site){
 const scopes=d.wall_scopes?.[site];
 if(!scopes)return '';
 return '<section class="well"><h4>两侧外墙铺设与反馈</h4>'+['left','right'].map(side=>{
   const s=scopes[side],label=side==='left'?'参考':'研究';
   if(!s)return `<p>${label} · 此输入未记录逐墙明细</p>`;
   const installed=s.rows.filter(w=>w.covered),active=installed.filter(w=>w.thermal==='feedback');
   const other=scopes[side==='left'?'right':'left'];
   const outside=new Set(other?.rows.filter(w=>!w.covered).map(w=>w.id));
   const diff=installed.filter(w=>outside.has(w.id));
   return `<div><strong>${label} · 铺设 ${installed.length} 段（${format(s.covered_m2,2)} m²），反馈 ${active.length} 段（${format(s.feedback_m2,2)} m²）</strong>${diff.length?`<p>仅本侧铺设 · ${format(diff.reduce((n,w)=>n+w.net_m2,0),2)} m² · ${diff.map(w=>esc(w.id)).join('、')}</p>`:''}<details><summary>逐墙核对</summary>${s.rows.map(w=>`<p>${esc(w.id)} · ${esc(w.zone)} · ${format(w.net_m2,2)} m² · ${w.covered?(w.thermal==='feedback'?'已铺反馈':'已铺固定'):'未铺'}</p>`).join('')}</details></div>`;
 }).join('')+'</section>';
}
function comparisonSiteDetail(d,pinnedSite){
 const r=d?.sites.find(r=>r.site_id===(pinnedSite||S.comparisonSelected));if(!r)return '';
 const table=(headers,rows,cls='')=>`<div class="table-scroll" tabindex="0"><table class="table comparison-detail-table ${cls}"><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 const unit=d.normalized?'MJ_m2':'kWh',label=d.normalized?'MJ/m²':'kWh';
 const monthly=d.monthly.filter(m=>m.site_id===r.site_id).slice().sort((a,b)=>a.month-b.month);
 let body='';
 if(r.status!=='paired')body=`<p class="warning">未纳入配对：${esc(r.reason||'缺少可比较结果')}。本地点不计算降低量，不参与本次气候均值。</p>`;
 else if(d.metric==='temperature'){
  body=`<h4>逐房间室温 / °C</h4><p class="muted">温差为研究减参考。极值差不是同一时刻的温差，不把不同房间自行平均为节能量。</p>${table(['房间','指标','参考','研究','研究减参考'],d.rooms.filter(t=>t.site_id===r.site_id).flatMap(t=>[['mean_C','时段均温'],['min_C','最低温'],['max_C','最高温']].map(([key,name])=>`<tr><td>${esc(t.zone)}</td><td>${name}</td><td class="num">${format(t['left_'+key],3)}</td><td class="num">${format(t['right_'+key],3)}</td><td class="num">${format(t['right_minus_left_'+key],3)}</td></tr>`)),'comparison-room-detail')}`;
 }else{
  const explain=k=>`${metricNames[k]}${r[k+'_saved_kWh']>0?'降低':r[k+'_saved_kWh']<0?'增加':'持平'}${r[k+'_saved_kWh']===0?'':' '+format(Math.abs(r[k+'_saved_'+unit]),3)+' '+label}`;
  body=(d.wall_coverage?coverageResultView(d,r):`<p class="comparison-outcome-text">${['heating','cooling','total'].map(explain).join('；')}。</p><p class="muted scroll-hint">窄屏可左右滑动图表和表格，查看完整月份与数据列。</p><h4>${d.annual?'年度':'所选时段'}负荷对照</h4>${table(['需求','参考 / kWh','研究 / kWh','降低 / '+label,'降低率'],['heating','cooling','total'].map(k=>`<tr><td>${metricNames[k]}</td><td class="num">${format(r['left_'+k+'_kWh'],3)}</td><td class="num">${format(r['right_'+k+'_kWh'],3)}</td><td class="num">${format(r[k+'_saved_'+unit],3)}</td><td>${r[k+'_saved_percent']===null?'基准为零，比例不适用':format(r[k+'_saved_percent'],3)+'%'}</td></tr>`),'comparison-annual-detail')}`)+`${pinnedSite?`<details><summary>查看月度差异 · ${monthly.length} 个月</summary>`:''}<h4>月度冷热贡献</h4><p class="muted">${d.annual?'全年覆盖月份':'仅所选时段覆盖的月份，短时段不代表完整月份'}；每根柱为同月参考减研究，供暖与制冷相加为总需求降低。</p>${comparisonMonthChart(monthly,unit)}
  ${table(['月份','供暖降低 / '+label,'制冷降低 / '+label,'总需求降低 / '+label],monthly.map(m=>`<tr><td>${m.month} 月</td>${['heating','cooling','total'].map(k=>`<td class="num">${format(m[k+'_saved_'+unit],3)}</td>`).join('')}</tr>`),'comparison-month-detail')}
  <details><summary>查看双方月度原负荷 / kWh</summary>${table(['月份','参考供暖','研究供暖','参考制冷','研究制冷','参考合计','研究合计'],monthly.map(m=>`<tr><td>${m.month} 月</td>${['heating','cooling','total'].flatMap(k=>['left','right'].map(side=>`<td class="num">${format(m[side+'_'+k+'_kWh'],3)}</td>`)).join('')}</tr>`))}</details>${pinnedSite?'</details>':''}`;
 }
 return `<section id="comparison-site-detail" class="well comparison-site-detail" tabindex="-1"><div class="row"><h3>${esc(r.city)} · 比较明细</h3>${pinnedSite?'':'<button data-action="close-comparison-detail">收起明细</button>'}</div><p>${esc(r.climate||'未分类')} · ${esc(r.site_kind||'地点')} · ${d.period.slice(0,2).join('-')} 至 ${d.period.slice(2).join('-')} · 参考 ${r.left_step_minutes??'—'} min · 研究 ${r.right_step_minutes??'—'} min</p>${comparisonStepPanel(d,r)}${body}${comparisonWallScope(d,r.site_id)}<details class="comparison-review"><summary>双方来源与复核说明</summary><div class="grid2">${comparisonReviewSide(d,r,'left')}${comparisonReviewSide(d,r,'right')}</div></details></section>`;
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
function coverageResultView(d, site) {
 const scope=d.wall_coverage, gains=site.savings_per_added_m2, timing=site.feedback_timing;
 const counts=scope.feedback_same?'反馈仍为同一组 '+scope.left_feedback+' 段':'反馈墙 '+scope.left_feedback+' → '+scope.right_feedback+' 段';
 const calendar=site.coverage_calendar_same===null?'固定光学配置':site.coverage_calendar_same?'共用该地点光学日历':'光学日历有差异';
 const walls=(items,label)=>items.length?'<details><summary>'+label+' '+items.length+' 段 · '+format(items.reduce((x,w)=>x+w.net_m2,0),2)+' m²</summary><div class="table-scroll"><table class="table"><thead><tr><th>墙号</th><th>所属房间</th><th>朝向</th><th class="num">净面积 / m²</th></tr></thead><tbody>'+items.map(w=>'<tr><td>'+esc(w.id)+'</td><td>'+esc(w.zone)+' · '+(w.conditioned==null?'空调归属未记录':w.conditioned?'空调房':'非空调房')+'</td><td>'+esc(w.direction||'未记录')+'</td><td class="num">'+format(w.net_m2,2)+'</td></tr>').join('')+'</tbody></table></div></details>':'';
 const fields=['heating','cooling','total'];
 const table='<div class="table-scroll"><table class="table comparison-detail-tab comparison-detail-table"><thead><tr><th>显热需求</th><th class="num">参考 / kWh</th><th class="num">研究 / kWh</th><th class="num">降低 / kWh</th><th class="num">降低率</th>'+(gains?'<th class="num">按新增面积 / kWh/(m²·年)</th>':'')+'</tr></thead><tbody>'+fields.map(k=>'<tr><th>'+metricNames[k]+'</th><td class="num">'+format(site['left_'+k+'_kWh'],2)+'</td><td class="num">'+format(site['right_'+k+'_kWh'],2)+'</td><td class="num">'+format(site[k+'_saved_kWh'],2)+'</td><td class="num">'+(site[k+'_saved_percent']==null?'—':format(site[k+'_saved_percent'],2)+'%')+'</td>'+(gains?'<td class="num">'+format(gains[k],2)+'</td>':'')+'</tr>').join('')+'</tbody></table></div>';
 const minuteLabel=n=>{const d=new Date(Date.UTC(2001,0,1,0,n));return d.toISOString().slice(5,16).replace('T',' ');};
 const state=v=>v===null?'—':v===1?'压缩':'蓬松';
 let feedback='<p class="muted">没有已核对的双方逐步反馈状态，切换时刻未作比较。</p>';
 if(timing){
   const rows=timing.unmatched.map(e=>'<tr><td>'+minuteLabel(e.minute)+'</td><td>'+state(e.left)+'</td><td>'+state(e.right)+'</td></tr>').join('');
   feedback='<p>参考切换 '+format(timing.left,0)+' 次，研究切换 '+format(timing.right,0)+' 次，其中 '+format(timing.coincident,0)+' 次在同一分钟同方向切换。两侧状态不同的时间共 '+Math.floor(timing.different_minutes/60)+' 小时 '+timing.different_minutes%60+' 分钟。</p>'+(rows?'<details><summary>查看切换时刻差异 · '+timing.step+' min 记录</summary><div class="table-scroll" style="max-height:22rem"><table class="table"><thead><tr><th>月日 / 当地时刻</th><th>参考切换至</th><th>研究切换至</th></tr></thead><tbody>'+rows+'</tbody></table></div></details>':'');
 }
 return '<section class="coverage-outcome"><h4>材料铺设与反馈范围</h4><p><strong>'+scope.left_count+' → '+scope.right_count+' 段外墙</strong> · '+esc(counts)+' · '+esc(calendar)+'</p>'+walls(scope.added,'新增铺设')+walls(scope.removed,'撤除铺设')+'<h4>'+(d.annual?'全年':'时段')+'显热需求</h4>'+table+'<p class="muted">'+(gains?'降低量为参考减研究，单位面积值按新增材料净面积 '+format(scope.added_m2,2)+' m² 计算。':'单位新增面积指标适用于共同条件一致、仅扩大铺设范围的严格全年配对。')+'</p>'+feedback+'</section>';
}

