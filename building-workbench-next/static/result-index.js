/* Discovery links only. Numerical results remain in their original pinned views. */
S.resultIndex=null;S.resultIndexError='';S.resultIndexFilter={query:'',kind:'all',building:'',step:''};
S.resultIndexLimits={comparison:20,batch:20,historical:20};S.resultIndexOrigin=null;
let resultIndexTarget='';
let resultIndexFlight=null;
function loadResultIndex(){
 if(resultIndexFlight)return resultIndexFlight;
 S.resultIndexLoading=true;S.resultIndexError='';
 resultIndexFlight=(async()=>{try{S.resultIndex=await api('/api/result-index');}catch(error){S.resultIndexError=error.message;}finally{S.resultIndexLoading=false;resultIndexFlight=null;}})();return resultIndexFlight;
}
function resultIndexRecords(row){return row.kind==='batch'?[row.record]:Object.values(row.sides);}
function resultIndexAll(){const d=S.resultIndex;return d?[...d.comparisons,...d.batches,...d.historical]:[];}
function resultIndexMatches(row){
 const f=S.resultIndexFilter,records=resultIndexRecords(row),q=f.query.trim().toLocaleLowerCase();
 return (f.kind==='all'||row.kind===f.kind)&&(!f.building||records.some(r=>r.building_id===f.building))&&(!f.step||records.some(r=>String(r.step_minutes)===f.step))&&(!q||[row.name,row.id,row.status,...records.flatMap(r=>[r.name,r.id,String(r.revision),r.building,...r.material_summary,...r.site_names])].filter(Boolean).join(' ').toLocaleLowerCase().includes(q));
}
function resultIndexFacts(r){return `${esc(r.building)} · ${esc(periodLabel(r.period))} · ${r.step_minutes} min · ${r.site_names.length<=3?esc(r.site_names.join('、'))+' · ':''}${r.site_count} 地点 · ${esc(modes[r.mode]||r.mode)}`;}
function resultIndexVersion(r){return `<button class="index-version" data-index-record="${esc(r.id)}" data-index-revision="${esc(r.revision)}">查看绑定方案 · ${esc(planVersionLabel(r))}</button>`;}
function resultIndexCard(row){
 const buttons=`<button class="primary" data-index-open="${esc(row.id)}">${row.kind==='comparison'?'选择批次并读取配对结果':row.kind==='batch'?'查看本批结果与核验':'打开原平台 15 min 历史'}</button>${row.kind!=='historical'?`<button data-index-exports="${esc(row.id)}">查看已导出数据包</button>`:''}`;
 if(row.kind==='batch'){
  const c=row.counts;
  return `<article class="index-card" id="index-${esc(row.id)}" data-index-kind="batch"><div class="row"><h3>${esc(row.name)}</h3><span class="tag">${esc(row.status)}</span></div><p class="index-batch-scope"><strong>本批计算：${(row.site_names||[]).slice(0,3).map(esc).join("、")}${row.site_count>3?" 等":""} · ${row.site_count} 地点 · ${row.case_count} 算例</strong></p><p class="muted">绑定方案保存${esc(planVersionLabel(row.record))} · ${esc(row.record.building)} · ${esc(periodLabel(row.record.period))} · ${row.record.step_minutes} min · 方案完整范围 ${row.record.site_count} 地点</p><p class="index-recipe">${row.record.material_summary.map(esc).join('；')}</p>${researchInputNoteMarkup(row.record.research_input_note,true)}<p>队列登记通过 ${c.passed+c.reused} / ${row.case_count} 项 · 待复核 ${c.review} · 待算 ${c.pending} · 运行 ${c.running}${c.failed+c.interrupted?' · 失败/中断 '+(c.failed+c.interrupted):''}${c.cancelled?' · 取消 '+c.cancelled:''}</p><p class="muted">${esc(readableTime(row.created))} · 批次 ${esc(row.id.slice(-8))}${row.site_count!==row.record.site_count?' · 此批 '+row.site_count+' 地点':''}</p><div class="actions">${buttons}${resultIndexVersion(row.record)}</div></article>`;
 }
 return `<article class="index-card" id="index-${esc(row.id)}" data-index-kind="${row.kind}"><div class="row"><h3>${esc(row.name)}</h3><span class="tag">${row.kind==='historical'?'只读历史快照':esc(comparisonMetricLabels[row.metric]||row.metric)}</span></div><div class="grid2">${['left','right'].map(side=>{const r=row.sides[side];return `<div class="index-side"><strong>${side==='left'?'基准':'研究'}：${esc(r.name)}</strong><p class="muted">${esc(planVersionLabel(r))} · ${resultIndexFacts(r)}</p><p class="index-recipe">${r.material_summary.map(esc).join('；')}</p>${researchInputNoteMarkup(r.research_input_note,true)}${row.kind==='comparison'?`<p class="muted">绑定此版本的批次 ${r.batch_ids.length}${r.historical?' · 有原正式历史来源':''}</p>`:''}</div>`;}).join('')}</div>${row.kind==='comparison'?`<p class="muted">保存于 ${esc(readableTime(row.created))}。${['left','right'].every(s=>row.sides[s].batch_ids.length||row.sides[s].historical)?'双方已有登记来源，读取时再核对可配对地点。':'至少一侧尚缺登记来源，可打开查看具体情况。'}</p>`:'<p class="muted">原平台正式全球 15 min；保留原比较口径。后续 5 min 与新建筑批次列在上方。</p>'}<div class="actions">${buttons}</div></article>`;
}
function resultIndexRows(){
 const rows=resultIndexAll().filter(resultIndexMatches),labels={comparison:'已保存的比较',batch:'计算批次',historical:'原平台历史'};
 return `<p class="muted" role="status">匹配 ${rows.length} / ${resultIndexAll().length} 条入口；比较、批次和历史快照分别计数。</p>`+(['comparison','batch','historical'].map(kind=>{
  const group=rows.filter(r=>r.kind===kind);if(!group.length)return '';
  return `<section class="index-group" id="result-index-${kind}"><h2>${labels[kind]} <span class="tag">${group.length}</span></h2>${group.slice(0,S.resultIndexLimits[kind]).map(resultIndexCard).join('')}${group.length>S.resultIndexLimits[kind]?`<button data-index-more="${kind}">再显示 20 条</button>`:''}</section>`;
 }).join('')||'<p class="empty">没有匹配的记录。可调整搜索条件或清除筛选。</p>');
}
function resultIndexView(){
 const d=S.resultIndex,f=S.resultIndexFilter;
 const head='<div class="row"><h1>结果索引</h1><button data-action="refresh-result-index">刷新索引</button></div><p class="muted">查找已有比较、计算批次和原平台历史。版本号是同一方案的保存快照；W00、固定 ECA、翻面 ECA 是不同研究成员。本批地点与方案完整范围分别列出。</p>'+`<p role="status" class="muted">${esc(S.resultIndexError?'读取失败：'+S.resultIndexError:S.resultIndexLoading?'正在刷新结果索引，可继续其他操作…':'')}</p>`;
 if(!d)return `<section class="section">${head}<p class="warning">${esc(S.resultIndexError?'索引读取失败：'+S.resultIndexError:'正在读取索引…')}</p></section>`;
 const records=resultIndexAll().flatMap(resultIndexRecords),buildings=[...new Map(records.map(r=>[r.building_id,r.building])).entries()].sort((a,b)=>a[1].localeCompare(b[1])),steps=[...new Set(records.map(r=>r.step_minutes))].sort((a,b)=>a-b);
 return `<section class="section" id="result-index"><div>${head}</div><p class="muted">读取于 ${esc(readableTime(d.read_at||d.checked_at))}。${esc(d.note)}</p><div class="index-filter"><label class="field">搜索名称、地点或编号<input id="result-index-query" type="search" value="${esc(f.query)}" placeholder="例如：北京、五层、全球"></label><label class="field">记录类型<select id="result-index-kind">${options([['all','全部类型'],['comparison','已保存的比较'],['batch','计算批次'],['historical','原平台历史']],f.kind)}</select></label><label class="field">建筑<select id="result-index-building">${options([['','全部建筑'],...buildings],f.building)}</select></label><label class="field">求解步长<select id="result-index-step">${options([['','全部步长'],...steps.map(s=>[String(s),s+' min'])],f.step)}</select></label><button data-action="clear-result-index-filter">清除筛选</button></div>${d.issues.length?`<details class="warning index-issues"><summary>${d.issues.length} 条记录未纳入索引，需核对</summary>${d.issues.map(x=>`<p>${esc(x.id)}：${esc(x.message)}</p>`).join('')}</details>`:''}<div id="result-index-rows">${resultIndexRows()}</div></section>`;
}
function resultIndexReturnView(){
 return S.resultIndexOrigin&&['compare','execution','editor','results'].includes(S.view)?'<div class="index-return"><button data-action="return-result-index">← 返回结果索引</button><span class="muted">保留上次搜索和筛选</span></div>':'';
}
function finishResultIndexNavigation(){
 if(!resultIndexTarget)return;const target=document.getElementById(resultIndexTarget);resultIndexTarget='';
 if(target){target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'start'});}else window.scrollTo({top:0});
}
async function resultIndexAction(button){
 const a=button.dataset.action;
 if(a==='refresh-result-index'){await loadResultIndex();return true;}
 if(a==='clear-result-index-filter'){S.resultIndexFilter={query:'',kind:'all',building:'',step:''};S.resultIndexLimits={comparison:20,batch:20,historical:20};return true;}
 if(button.dataset.indexMore){S.resultIndexLimits[button.dataset.indexMore]+=20;return true;}
 if(a==='return-result-index'){S.view='result-index';if(!S.resultIndex)await loadResultIndex();resultIndexTarget='index-'+S.resultIndexOrigin;return true;}
 if(button.dataset.indexRecord){
  const r=resultIndexAll().flatMap(resultIndexRecords).find(r=>r.id===button.dataset.indexRecord&&String(r.revision)===button.dataset.indexRevision);if(!r)throw Error('未找到此保存版本，请刷新索引。');
  await loadRecord(r.id,r.revision);S.resultIndexOrigin=button.closest('[data-index-kind]').id.slice(6);S.view='editor';resultIndexTarget='plan-activity';return true;
 }
 const id=button.dataset.indexOpen||button.dataset.indexExports;if(!id)return false;
 const row=resultIndexAll().find(r=>r.id===id);if(!row)throw Error('未找到此入口，请刷新索引。');
 const previous={...S,comparisonSources:{...S.comparisonSources}};
 try{
  if(row.kind==='batch'){
   await loadBatchResults(id,true);await loadExecution();S.view='execution';resultIndexTarget='execution-results';
   if(button.dataset.indexExports)await refreshExportHistory('batch',id);
  }else if(row.kind==='comparison'){
   await bootstrap();await openSavedComparison(id,true);resultIndexTarget='comparison-results';
   if(button.dataset.indexExports)await refreshExportHistory('comparison',id);
  }else{S.results=await api('/api/results');S.view='results';resultIndexTarget='legacy-result-purpose';}
  S.resultIndexOrigin=id;return true;
 }catch(error){Object.assign(S,previous);resultIndexTarget='';throw error;}
}
document.addEventListener('input',event=>{
 if(event.target.id!=='result-index-query')return;S.resultIndexFilter.query=event.target.value;S.resultIndexLimits={comparison:20,batch:20,historical:20};document.getElementById('result-index-rows').innerHTML=resultIndexRows();
});
document.addEventListener('change',event=>{
 const key={'result-index-kind':'kind','result-index-building':'building','result-index-step':'step'}[event.target.id];if(!key)return;
 S.resultIndexFilter[key]=event.target.value;S.resultIndexLimits={comparison:20,batch:20,historical:20};document.getElementById('result-index-rows').innerHTML=resultIndexRows();
});
