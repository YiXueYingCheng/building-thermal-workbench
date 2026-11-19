'use strict';
function resetBatchResults(){S.batchFilter={query:'',climate:'',status:'',mode:''};S.batchTable='sites';S.batchSelected=null;S.batchExport=null;}
resetBatchResults();
async function loadBatchResults(id,reset=false){
 const d=await api('/api/execution/'+id+'/summary');
 if(reset)resetBatchResults();
 if(d.dataset_sha256!==S.executionResults?.dataset_sha256)S.batchExport=null;
 S.executionResults=d;
 if(!d.results.some(r=>r.index===S.batchSelected))S.batchSelected=null;
}
function batchBadge(r){return `<span class="tag ${r.acceptance==='reviewed'?'status-reviewed':r.accepted?'status-ok':'warning'}">${esc(r.status_label)}</span>`;}
// Group repeated text for display only. Preserve raw records and acceptance rules.
function warningGroups(warnings){
 const groups=new Map();for(const text of warnings||[])groups.set(text,(groups.get(text)||0)+1);
 return Array.from(groups,([text,records])=>({text,records}));
}
function warningRecordsView(warnings){
 const groups=warningGroups(warnings);
 return groups.map(g=>`<p class="warning warning-record">${esc(g.text)}${g.records>1?`<br><small>同文日志 ${g.records} 条 · 已合并展示</small>`:''}</p>`).join('')+(groups.some(g=>g.records>1)?'<p class="muted">日志条数不等于发生次数；首次提示和末尾汇总可能重复记录同一事件。原始日志与导出记录保留。</p>':'');
}
function pendingWarningView(warnings){
 return `<div class="review-note"><strong>自动校验已完成，${warningGroups(warnings).length} 类警告待复核</strong><p>请打开“复核处理”检查依据，再明确采用结论。此结果尚未纳入气候汇总。</p>${warningRecordsView(warnings)}</div>`;
}
function warmupTrendView(t){
 if(!t)return '';
 const labels={period_two:'隔天重复',shrinking:'温差缩小（慢收敛迹象）',unclear:'趋势待定'};
 const number=x=>Number(x.toPrecision(4)).toString();
 const rows=t.rows||[], periodic=rows.some(r=>r.kind==='period_two'), shrinking=rows.some(r=>r.kind==='shrinking');
 return `<section class="well"><h3>预热室温趋势</h3>
 ${t.first?`<p>第 ${t.first}–${t.last} 个预热日 · ${t.step} 分钟步长${t.live?(t.ended?' · 预热阶段已结束':' · 最新已记录时段'):''}</p>`:''}
 ${rows.length?`<div class="table-wrap"><table class="table"><thead><tr><th>房间 / 检查项</th><th>趋势</th><th>末两天室温 °C</th><th>相邻日温差 / 限值 °C</th><th>隔日最大温差 °C</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.zone)} · ${esc(r.label)}</td><td><strong>${labels[r.kind]}</strong></td><td>${format(r.previous,3)} → ${format(r.latest,3)}</td><td>${number(r.delta)} / ${number(r.tolerance)}</td><td>${r.max_two_day_delta==null?'—':number(r.max_two_day_delta)}</td></tr>`).join('')}</tbody></table></div>`:''}
 ${periodic?`<p><strong>奇偶日各自重复，且相邻日温差持续超限。</strong>${t.live&&!t.ended&&t.last<t.minimum_days?'仍在设定的最少预热天数内，可先继续观察。':t.step>1?'可在本批结果中打开这个失败地点，保留原时段和温控设置，缩短求解步长（例如 5 分钟改为 1 分钟），对照预热和负荷结果。':'当前已是 1 分钟步长，可核对该房间供暖启停与室温越过阈值的时刻。'}</p>`:''}
 ${shrinking?'<p>相邻日温差在观察期内总体缩小，可先看后续预热日是否达到限值，再决定是否延长预热。</p>':''}
 ${rows.some(r=>r.kind==='unclear')?'<p>现有日序列尚未形成明确规律，仅凭末两天温差无法判断缩短步长是否有帮助。</p>':''}
 ${t.note?`<p>${esc(t.note)}</p>`:''}</section>`;
}
document.addEventListener('click', event=>{
 const button=event.target.closest('[data-warmup-batch]');
 if(!button)return;
 event.stopImmediatePropagation();
 if(button.disabled||S.busy)return;
 const {warmupBatch,warmupIndex}=button.dataset;
 const x=scrollX,y=scrollY;
 const dialog=document.createElement('dialog');
 dialog.setAttribute('aria-label','预热室温趋势');
 dialog.style.cssText='width:min(900px,94vw);max-height:85vh;overflow:auto;padding:24px';
 dialog.innerHTML='<div class="row"><h2>算例预热记录</h2><button autofocus>关闭</button></div><div data-trend-body>正在读取最近预热日…</div>';
 document.body.append(dialog);
 let timer;
 dialog.addEventListener('click',e=>{
  e.stopPropagation();
  if(e.target.closest('button'))dialog.close();
 });
 dialog.addEventListener('close',()=>{
  clearTimeout(timer);dialog.remove();
  if(S.view!=='execution')return;
  const card=document.getElementById('batch-'+warmupBatch);
  const opener=card?.querySelector(`[data-warmup-index="${CSS.escape(warmupIndex)}"]`)||card?.querySelector('[data-queue-detail-kind="cases"] > summary');
  if(opener){opener.focus({preventScroll:true});scrollTo({left:x,top:y,behavior:'instant'});}
 },{once:true});
 const url='/api/warmup-trend?'+new URLSearchParams({batch:warmupBatch,index:warmupIndex});
 async function refresh(){
  try{
   const t=await api(url);
   if(!dialog.open)return;
   dialog.querySelector('[data-trend-body]').innerHTML=warmupTrendView(t);
   if(t.live&&!t.ended)timer=setTimeout(refresh,5000);
  }catch(error){
   if(dialog.open)dialog.querySelector('[data-trend-body]').textContent=error.message;
  }
 }
 dialog.showModal();
 void refresh();
},true);
function failureInfoView(info){
 if(!info)return '';
 const checks=info.failed_checks||[];
 const criteria=checks.length?`<p>未通过项：${esc(info.failed_checks_summary)}。</p><details><summary>查看各房间未通过项</summary><div class="table-wrap" tabindex="0"><table class="table batch-detail-table"><thead><tr><th>房间</th><th>检查项</th><th class="num">比较值</th><th class="num">收敛限值</th><th>口径</th></tr></thead><tbody>${checks.map(c=>`<tr><td>${esc(c.zone)}</td><td>${esc(c.label)}</td><td class="num">${format(c.value,6)}</td><td class="num">${format(c.tolerance,6)}</td><td>${esc(c.unit)}</td></tr>`).join('')}</tbody></table></div><p class="muted">温度列表示预热日间的温差；负荷列是引擎用于收敛检查的比值，不是实际负荷或能耗。</p></details>`:'';
 return `<div class="review-note"><strong>${esc(info.title)}</strong><p>${esc(info.explanation)}</p>${info.zones.length?`<p>涉及房间：${info.zones.map(z=>esc(z.zone)+'（'+z.warmup_days+' 天）').join('、')}。</p>`:''}${criteria}${warmupTrendView(info.warmup_trend)}<p>${esc(info.next_step)}</p><details><summary>查看错误日志摘录</summary>${info.log_excerpt.map(t=>'<p class="warning">'+esc(t)+'</p>').join('')}${info.truncated?'<p>日志过长，仅显示前段。</p>':''}<p class="muted">这是日志说明，未改变核验状态。</p></details></div>`;
}
function siteRecalculationView(d,r){
 const alternative=!!r.comparison_attempt;
 if(!r.failed_attempt&&!alternative)return '';
 const adopted=r.evidence?.original_failure;
 const attempts=(r.recalculations||[]).map(s=>{
  const ready=['passed','reused'].includes(s.status);
  const status=s.adopted?'已确认并入':ready?(alternative?'已通过，可在工况对照中选用':'已通过，等待确认并入'):({pending:'排队',running:'计算中',review:'待复核',failed:'补算失败',interrupted:'中断',cancelled:'已取消'}[s.status]||s.status);
  const button=!alternative&&!adopted&&ready?`<button class="primary" data-site-recalc="adopt" data-child="${esc(s.child)}" data-checksum="${esc(s.result_sha256)}">确认并入原批汇总…</button>`:'';
  return `<p><strong>${s.step} min · ${esc(status)}</strong> <button data-site-recalc="open" data-child="${esc(s.child)}">查看补算记录</button> ${button}</p>`;
 }).join('');
 const steps=r.available_steps||[];
 return `<section class="well"><h3>${alternative?'为工况对照加算本地点':'仅补算本地点'}</h3>${alternative?`<p>原算例 ${r.original_step_minutes} min 已通过。加算结果供对照单独选用。</p>`:`<p>原算例 ${r.original_step_minutes} min · 失败。<a download href="/api/failed-result/download?batch=${esc(d.id)}&index=${r.index}">下载原失败诊断</a></p>`}${adopted?.error?`<details><summary>原失败原因</summary><p>${esc(adopted.error)}</p></details>`:''}
 ${r.step_note?'<p class="review-note">'+esc(r.step_note)+'</p>':''}${attempts}${!adopted&&steps.length?`<label>补算步长 <select data-site-step>${steps.map(s=>`<option value="${s}">${s} min</option>`).join('')}</select></label> <button class="primary" data-site-recalc="submit">仅提交${esc(r.city)}${alternative?'加算':'补算'}</button><p>沿用本地点原模型、气象和时段。${alternative?'核验通过后，在对应工况对照的地点明细里选用。':'核验通过后，由你确认并入。'}</p>`:!adopted?'<p>此工况没有其他兼容的求解步长。</p>':''}
 ${attempts&&!adopted?'<button data-site-recalc="refresh">刷新补算状态</button>':''}<p role="status" data-site-message></p></section>`;
}
document.addEventListener('click',async event=>{
 const b=event.target.closest('[data-site-recalc]');if(!b)return;
 event.preventDefault();event.stopImmediatePropagation();
 const d=S.executionResults,r=d?.results.find(x=>x.index===S.batchSelected);if(!r)return;
 const section=b.closest('section'),op=b.dataset.siteRecalc;
 if(op==='adopt'&&!window.confirm(`将${r.city}的 ${r.recalculations.find(s=>s.child===b.dataset.child).step} min 补算结果计入原批汇总和后续导出？原失败记录将保留。`))return;
 b.disabled=true;
 const msg=section?.querySelector('[data-site-message]');
 try{
  if(op==='open'||op==='parent'){
   await loadBatchResults(b.dataset.child,true);S.batchSelected=op==='open'?0:Number(b.dataset.index);
   S.resultViewer.key=S.batchSelected;S.resultViewer.tab='summary';render();return;
  }
  let message='';
  if(op==='submit'){
   const step=Number(section.querySelector('[data-site-step]').value);
   const response=await api('/api/site-recalculation/submit',{parent:d.id,index:r.index,attempt:r.failed_attempt||r.comparison_attempt,step_minutes:step,purpose:r.comparison_attempt?'comparison':'recovery'});
   message=response.startup?.error||(response.reused_submission?'此步长已有补算记录，状态见上方。':'该地点的补算已登记。');
  }else if(op==='adopt'){
   await api('/api/site-recalculation/adopt',{parent:d.id,index:r.index,child:b.dataset.child,result_sha256:b.dataset.checksum});
   message='已确认并入，原批汇总已更新。';
  }
  await loadBatchResults(d.id);render();
  const status=document.querySelector('#result-viewer [data-site-message]');if(status)status.textContent=message;
 }catch(e){if(msg)msg.textContent=e.message;else notice(e.message);}
 finally{b.disabled=false;}
},true);
function batchDetail(d){
 const r=d.results.find(r=>r.index===S.batchSelected);if(!r)return '';
 const table=(heads,rows)=>`<div class="table-wrap" tabindex="0"><table class="table batch-detail-table"><thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 const review=r.review_info;
 return `<section id="batch-detail" class="well batch-detail" tabindex="-1"><div class="row"><h3>${esc(r.city)} · ${esc(modes[r.mode])}</h3><button data-action="close-batch-detail">收起明细</button></div><p>${batchBadge(r)} · ${esc(r.climate||'未分类')} · ${esc(r.site_kind)} · ${r.period.slice(0,2).join('-')} 至 ${r.period.slice(2).join('-')} · ${r.step_minutes} min</p>
 ${siteRecalculationView(d,r)}
 ${d.site_recalculation?`<p><button data-site-recalc="parent" data-child="${esc(d.site_recalculation.parent)}" data-index="${d.site_recalculation.idx}">${d.site_recalculation.purpose==='comparison'?'返回原地点，查看加算记录':'返回原地点，查看或确认并入'}</button></p>`:''}
 ${review?`<div class="review-note"><strong>复核结论与依据</strong><p>${esc(review.method)} · ${esc(new Date(review.reviewed_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}))}</p><p>${esc(review.note)}</p>${reviewUserDecisionMarkup(review)}<details><summary>原始警告与接受范围</summary>${warningRecordsView(review.warnings)}<p class="muted">${esc(review.display_scope)}</p></details></div>`:''}
 ${r.pending_warnings.length?pendingWarningView(r.pending_warnings):''}
 ${r.pending_warnings.length||review?`<div class="review-note"><button class="primary" data-open-result-review="${esc(r.evidence.batch_id)}" data-review-index="${r.evidence.index}" data-review-name="${esc(d.record_name)}">${review?'查看复核处理':'复核处理'}</button><p class="muted">检查依据、查看适用范围、登记结论；未知问题保持待复核。</p></div>`:''}
 ${r.failure_info?.kind==='warmup_convergence'?`<div class="review-note"><button class="primary" data-open-result-review="${esc(r.evidence.batch_id)}" data-review-index="${r.evidence.index}" data-review-name="${esc(d.record_name)}">查看诊断与处理</button><p class="muted">先核对年度诊断依据；确认采用前仍不计入汇总。</p></div>`:''}
 ${['failed','interrupted'].includes(r.status)?`<p><button data-failure-info="${esc(d.id)}" data-failure-index="${r.index}">查看失败原因与处理</button> <a class="button" download="failed-case-${r.index+1}.zip" href="/api/failed-result/download?batch=${esc(d.id)}&index=${r.index}">下载失败诊断</a></p>`:''}
 ${r.failure_info?failureInfoView(r.failure_info):r.error?`<p class="warning">${esc(r.error)}</p>`:''}
 ${!r.accepted&&!r.pending_warnings.length?`<p class="muted">${esc(r.status_label)}；空缺不作为零负荷。</p>`:''}
 ${r.monthly?.length?`<h3>月度显热需求 / kWh</h3><p class="muted">仅包括所选时段内的记录，短时段不代表完整月份。</p>${table(['月份','供暖','制冷','合计'],r.monthly.map(m=>`<tr><td>${m.month} 月</td>${['heating','cooling','total'].map(k=>`<td class="num">${format(m[k+'_kWh'],3)}</td>`).join('')}</tr>`))}`:''}
 ${r.temperatures?.length?`<h3>房间温度 / °C</h3>${table(['房间','时段均温','最低','最高'],r.temperatures.map(t=>`<tr><td>${esc(t.zone)}</td>${['mean_C','min_C','max_C'].map(k=>`<td class="num">${format(t[k],3)}</td>`).join('')}</tr>`))}`:''}
 ${r.rooms?.length?`<details><summary>查看各空调系统的显热需求</summary><p class="muted">保留原系统名称，不自行映射为房间名称。</p>${table(['系统','类型','需求 / kWh'],r.rooms.map(t=>`<tr><td>${esc(t.system)}</td><td>${t.kind==='heating'?'供暖':'制冷'}</td><td class="num">${format(t.kWh,3)}</td></tr>`))}</details>`:''}</section>`;
}
function batchRows(d){
 const f=S.batchFilter,q=f.query.trim().toLocaleLowerCase();
 return d.results.filter(r=>(!f.climate||r.climate===f.climate)&&(!f.status||r.acceptance===f.status)&&(!f.mode||r.mode===f.mode)&&(!q||[r.city,r.site_id,r.climate,r.site_kind,r.country].join(' ').toLocaleLowerCase().includes(q)));
}
function batchList(d){
 if(S.batchTable==='classes')return `<p class="muted">气候表覆盖全部 30 类，仅汇总已接受的温控结果。自然室温不做跨房间或气候平均。地点范围不是统计误差；面积未知时 MJ/m² 留空。</p><div class="table-wrap" tabindex="0"><table class="table batch-climate-grid"><thead><tr><th>气候类型</th><th>有效 / 所选</th><th class="num">供暖均值 / kWh</th><th class="num">制冷均值 / kWh</th><th class="num">合计均值 / kWh</th><th>合计地点范围 / kWh</th></tr></thead><tbody>${d.classes.map(c=>`<tr><td><button data-batch-climate="${esc(c.climate)}">${esc(c.climate+' · '+c.name)}</button></td><td>${c.valid_sites} / ${c.selected_sites}<small>${c.status==='no_data'?'无数据':c.status==='partial'?'部分地点有效':'所选地点已接受'}</small></td>${['heating','cooling','total'].map(k=>`<td class="num">${format(c[k+'_kWh_mean'],3)}</td>`).join('')}<td>${format(c.total_kWh_min,3)} ～ ${format(c.total_kWh_max,3)}</td></tr>`).join('')}</tbody></table></div>`;
 const rows=batchRows(d);
 return `<p id="batch-result-count" class="muted" aria-live="polite">显示 ${rows.length} / ${d.results.length} 个算例；导出始终包含完整批次。</p>${rows.length?`<p class="muted scroll-hint">窄屏可左右滑动查看完整结果。</p><div class="table-wrap" tabindex="0" aria-label="本批结果，可横向滚动"><table class="table batch-result-grid"><thead><tr><th>地点 / 气候</th><th>模式 / 核验</th><th class="num">供暖 / kWh</th><th class="num">制冷 / kWh</th><th class="num">合计 / kWh</th><th>室温极值 / °C</th><th>明细</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.city)}<small>${esc(r.climate||'未分类')} · ${esc(r.site_kind)} · ${r.step_minutes} min${r.evidence?.original_failure?' · 已并入补算':''}</small></td><td>${esc(modes[r.mode])}<small>${r.days?r.days+' 天':'尚无完整结果'}</small>${batchBadge(r)}</td>${['heating','cooling','total'].map(k=>`<td class="num">${r.loads?format(r.loads[k+'_kWh'],3):'—'}</td>`).join('')}<td>${format(r.temperature_extrema?.min_C,2)} ～ ${format(r.temperature_extrema?.max_C,2)}</td><td><button id="batch-case-${r.index}" data-batch-case="${r.index}">查看明细</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">当前筛选下无结果。未计算地区保留无数据。</p>'}`;
}
function batchResultsView(){
 const d=S.executionResults,c=d.counts,f=S.batchFilter;
 const link=(name,label)=>`<a class="button" download="${esc(name)}" href="/api/batch-exports/${esc(S.batchExport.id)}/${encodeURIComponent(name)}">${label}</a>`;
 return `<section class="section" id="execution-results"><div class="row"><div><h2>${esc(d.record_name)} · 本批结果</h2><p class="muted">版本 ${esc(d.revision)} · ${d.annual?'全年':d.period.slice(0,2).join('-')+' 至 '+d.period.slice(2).join('-')} · ${esc(d.step_label)}${d.conditioned_area_m2?' · 温控面积 '+format(d.conditioned_area_m2,3)+' m²':''}</p></div><div class="actions"><button data-action="refresh-batch-results">刷新本批结果</button><button data-action="close-execution-results">关闭结果</button></div></div>
 <div class="metrics"><span><strong>${c.routine_passed}</strong>核验通过</span><span><strong>${c.reviewed}</strong>附说明接受</span><span><strong>${c.pending_review}</strong>待复核</span><span><strong>${c.unfinished}</strong>尚未完成</span>${c.failed||c.cancelled?`<span><strong>${c.failed} / ${c.cancelled}</strong>失败 / 已取消</span>`:''}</div>
 <p class="muted">负荷为所选时段的显热冷热需求，单位 kWh。附说明接受的结果可在明细中查看依据与原警告。</p>${c.pending_review?'<p class="warning">待复核项已完成自动校验；请在算例明细的“来源与核查”打开“复核处理”，检查依据后明确采用结论。</p>':''}<details><summary>查看汇总口径</summary><p class="muted">${esc(d.note)}自然室温不填负荷。</p></details>
 <div class="actions batch-toolbar">${c.pending_review?`<button data-bulk-review="${esc(d.id)}">强制采用待复核结果…</button>`:''}<button data-batch-table="sites" aria-pressed="${S.batchTable==='sites'}">地点结果</button><button data-batch-table="classes" aria-pressed="${S.batchTable==='classes'}">气候汇总</button><button data-action="export-batch" class="primary"${!c.completed?' disabled':''}>导出本批数据包</button>${S.batchExport?link('batch.zip','下载完整批次')+link('阅读说明.txt','阅读说明'):''}<a target="_blank" rel="noopener" href="/api/execution/${d.id}/summary">完整数据与核验 JSON ↗</a></div>
 ${exportHistoryView('batch',d.id)}
 ${S.batchTable==='sites'?`<div class="batch-filters"><label class="field">搜索地点或站点类型<input id="batch-query" type="search" value="${esc(f.query)}" placeholder="城市、气候或站点名称"></label><label class="field">气候类型<select id="batch-climate">${options([['','全部气候'],...d.classes.map(c=>[c.climate,c.climate+' · '+c.name])],f.climate)}</select></label><label class="field">核验状态<select id="batch-status">${options([['','全部状态'],['passed','核验通过 / 已复用'],['reviewed','附说明接受'],['review','待复核'],['pending','排队'],['running','计算中'],['failed','失败'],['interrupted','中断'],['cancelled','已取消']],f.status)}</select></label><label class="field">运行模式<select id="batch-mode">${options([['','全部模式'],...d.modes.map(m=>[m,modes[m]])],f.mode)}</select></label></div>`:''}
 ${batchDetail(d)}<div id="batch-results-list">${batchList(d)}</div></section>`;
}
document.addEventListener('input',event=>{
 if(event.target.id!=='batch-query')return;S.batchFilter.query=event.target.value;
 const list=document.getElementById('batch-results-list');if(list)list.innerHTML=batchList(S.executionResults);
});
document.addEventListener('change',event=>{
 const key={'batch-climate':'climate','batch-status':'status','batch-mode':'mode'}[event.target.id];if(!key)return;
 S.batchFilter[key]=event.target.value;document.getElementById('batch-results-list').innerHTML=batchList(S.executionResults);
});
async function batchResultsAction(button){
 if(button.dataset.batchCase!==undefined){S.batchSelected=Number(button.dataset.batchCase);setTimeout(()=>{const p=document.getElementById('batch-detail');p?.focus();p?.scrollIntoView({block:'start'});},0);return true;}
 if(button.dataset.batchTable){S.batchTable=button.dataset.batchTable;S.batchSelected=null;return true;}
 if(button.dataset.batchClimate){S.batchTable='sites';S.batchFilter={query:'',climate:button.dataset.batchClimate,status:'',mode:'controlled'};S.batchSelected=null;return true;}
 switch(button.dataset.action){
 case 'close-batch-detail':{const index=S.batchSelected;S.batchSelected=null;setTimeout(()=>document.getElementById('batch-case-'+index)?.focus(),0);return true;}
 case 'refresh-batch-results':if(await loadBatchResults(S.executionResults.id,false,true))notice('本批结果与复核依据已重新核对。');return true;
 case 'export-batch':{
  const d=S.executionResults,receipt=await chooseBatchExport(d);
  if(receipt && S.executionResults?.dataset_sha256===d.dataset_sha256){
   S.batchExport=receipt;
   await refreshOpenExportHistory('batch',d.id);
   notice('数据包已生成，可下载本次选择的结果。');
  }
  return true;
 }
 }
 return false;
}

function chooseBatchExport(batch){
 const dialog=document.createElement('dialog');
 dialog.className='batch-export-dialog';
 dialog.setAttribute('aria-labelledby','batch-export-title');
 dialog.innerHTML='<header class="viewer-head"><h2 id="batch-export-title">选择数据包内容</h2><button type="button" data-close>关闭</button></header><div class="focused-body"><p>包含全批次的基础汇总、核验状态和来源。可另选各算例的时序明细。</p><div data-choices aria-live="polite">正在核对已保存的指标和频率…</div><p role="alert" class="warning"></p></div><footer class="actions"><button class="primary" data-build>仅导出基础汇总</button></footer>';
 document.body.append(dialog);
 dialog.addEventListener('click',event=>event.stopPropagation());
 const request={id:batch.id,expected_dataset_sha256:batch.dataset_sha256};
 const choices=dialog.querySelector('[data-choices]'),run=dialog.querySelector('[data-build]'),close=dialog.querySelector('[data-close]');
 let inventory,receipt,busy=false;
 const selected=()=>Array.from(choices.querySelectorAll('input:checked'),e=>[e.dataset.group,e.value]);
 close.onclick=()=>dialog.close();
 dialog.oncancel=e=>{if(busy)e.preventDefault();};
 const done=new Promise(resolve=>dialog.addEventListener('close',()=>{dialog.remove();resolve(receipt);},{once:true}));
 choices.onchange=()=>{run.textContent=selected().length?'生成所选数据包':'仅导出基础汇总';};
 run.onclick=async()=>{
  if(busy)return;
  const selection=selected();
  busy=true;run.disabled=close.disabled=true;choices.inert=true;
  run.textContent='正在生成数据包…';
  try{
   receipt=await api('/api/batch-export',{...request,selection,inventory_sha256:inventory?.inventory_sha256});
   dialog.close();
  }catch(error){dialog.querySelector('[role="alert"]').textContent=error.message;}
  finally{busy=false;run.disabled=close.disabled=false;choices.inert=false;choices.onchange();}
 };
 dialog.showModal();
 api('/api/batch-export/options',request).then(info=>{
  if(!dialog.isConnected)return;
  inventory=info;
  const row=(key,label)=>{
   const available=info.choices.filter(x=>x.group===key);
   const preferred=['thermal','optical'].includes(key)?info.frequencies.find(f=>available.some(x=>x.frequency===f)):null;
   return '<fieldset><legend>'+esc(label)+'</legend>'+(available.length?info.frequencies.map(f=>{
    const item=available.find(x=>x.frequency===f);
    return item?`<label><input type="checkbox" data-group="${esc(key)}" value="${esc(f)}"${preferred===f?' checked':''}> ${esc(rtFreq[f])}${item.cases<info.total_cases?'（'+item.cases+'/'+info.total_cases+' 个算例）':''}</label>`:'';
   }).join(''):'<span class="muted">未找到对应的时序记录</span>')+'</fieldset>';
  };
  const missing=info.cases.filter(c=>!c.available.length);
  choices.innerHTML=Object.entries(info.groups).map(([k,v])=>row(k,v)).join('')+
   '<p class="muted">可多选。各频率沿用实际保存的读数；逐步明细可能较大。</p>'+
   (missing.length?`<details><summary>有 ${missing.length} 个算例缺少可导出明细</summary>${missing.map(c=>'<p>'+esc(c.city)+' · '+esc(c.note||'没有匹配的输出记录')+'</p>').join('')}</details>`:'');
  if(!busy)choices.onchange();
 }).catch(error=>{if(dialog.isConnected)choices.textContent='时序清单读取失败。'+error.message+' 可关闭后重试，或仅导出基础汇总。';});
 return done;
}

const batchResultsBeforeInputNote=batchResultsView;batchResultsView=function(){const html=batchResultsBeforeInputNote();return html.replace('<div class="metrics">',researchInputNoteMarkup(S.executionResults?.research_input_note)+'<div class="metrics">');};
