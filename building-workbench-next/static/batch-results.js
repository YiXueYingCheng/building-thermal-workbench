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
function failureInfoView(info){
 if(!info)return '';
 const checks=info.failed_checks||[];
 const criteria=checks.length?`<p>未通过项：${esc(info.failed_checks_summary)}。</p><details><summary>查看各房间未通过项</summary><div class="table-wrap" tabindex="0"><table class="table batch-detail-table"><thead><tr><th>房间</th><th>检查项</th><th class="num">比较值</th><th class="num">收敛限值</th><th>口径</th></tr></thead><tbody>${checks.map(c=>`<tr><td>${esc(c.zone)}</td><td>${esc(c.label)}</td><td class="num">${format(c.value,6)}</td><td class="num">${format(c.tolerance,6)}</td><td>${esc(c.unit)}</td></tr>`).join('')}</tbody></table></div><p class="muted">温度列表示预热日间的温差；负荷列是引擎用于收敛检查的比值，不是实际负荷或能耗。</p></details>`:'';
 return `<div class="review-note"><strong>${esc(info.title)}</strong><p>${esc(info.explanation)}</p>${info.zones.length?`<p>涉及房间：${info.zones.map(z=>esc(z.zone)+'（'+z.warmup_days+' 天）').join('、')}。</p>`:''}${criteria}<p>${esc(info.next_step)}</p><details><summary>查看错误日志摘录</summary>${info.log_excerpt.map(t=>'<p class="warning">'+esc(t)+'</p>').join('')}${info.truncated?'<p>日志过长，仅显示前段。</p>':''}<p class="muted">这是日志说明，未改变核验状态。</p></details></div>`;
}
function batchDetail(d){
 const r=d.results.find(r=>r.index===S.batchSelected);if(!r)return '';
 const table=(heads,rows)=>`<div class="table-wrap" tabindex="0"><table class="table batch-detail-table"><thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 const review=r.review_info;
 return `<section id="batch-detail" class="well batch-detail" tabindex="-1"><div class="row"><h3>${esc(r.city)} · ${esc(modes[r.mode])}</h3><button data-action="close-batch-detail">收起明细</button></div><p>${batchBadge(r)} · ${esc(r.climate||'未分类')} · ${esc(r.site_kind)} · ${r.period.slice(0,2).join('-')} 至 ${r.period.slice(2).join('-')} · ${r.step_minutes} min</p>
 ${review?`<div class="review-note"><strong>复核结论与依据</strong><p>${esc(review.method)} · ${esc(new Date(review.reviewed_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}))}</p><p>${esc(review.note)}</p>${reviewUserDecisionMarkup(review)}<details><summary>原始警告与接受范围</summary>${warningRecordsView(review.warnings)}<p class="muted">${esc(review.display_scope)}</p></details></div>`:''}
 ${r.pending_warnings.length?pendingWarningView(r.pending_warnings):''}
 ${r.pending_warnings.length||review?`<div class="review-note"><button class="primary" data-open-result-review="${esc(d.id)}" data-review-index="${r.index}" data-review-name="${esc(d.record_name)}">${review?'查看复核处理':'复核处理'}</button><p class="muted">检查依据、查看适用范围、登记结论；未知问题保持待复核。</p></div>`:''}
 ${r.failure_info?.kind==='warmup_convergence'?`<div class="review-note"><button class="primary" data-open-result-review="${esc(d.id)}" data-review-index="${r.index}" data-review-name="${esc(d.record_name)}">查看诊断与处理</button><p class="muted">先核对年度诊断依据；确认采用前仍不计入汇总。</p></div>`:''}
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
 return `<p id="batch-result-count" class="muted" aria-live="polite">显示 ${rows.length} / ${d.results.length} 个算例；导出始终包含完整批次。</p>${rows.length?`<p class="muted scroll-hint">窄屏可左右滑动查看完整结果。</p><div class="table-wrap" tabindex="0" aria-label="本批结果，可横向滚动"><table class="table batch-result-grid"><thead><tr><th>地点 / 气候</th><th>模式 / 核验</th><th class="num">供暖 / kWh</th><th class="num">制冷 / kWh</th><th class="num">合计 / kWh</th><th>室温极值 / °C</th><th>明细</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.city)}<small>${esc(r.climate||'未分类')} · ${esc(r.site_kind)}</small></td><td>${esc(modes[r.mode])}<small>${r.days?r.days+' 天':'尚无完整结果'}</small>${batchBadge(r)}</td>${['heating','cooling','total'].map(k=>`<td class="num">${r.loads?format(r.loads[k+'_kWh'],3):'—'}</td>`).join('')}<td>${format(r.temperature_extrema?.min_C,2)} ～ ${format(r.temperature_extrema?.max_C,2)}</td><td><button id="batch-case-${r.index}" data-batch-case="${r.index}">查看明细</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">当前筛选下无结果。未计算地区保留无数据。</p>'}`;
}
function batchResultsView(){
 const d=S.executionResults,c=d.counts,f=S.batchFilter;
 const link=(name,label)=>`<a class="button" download="${esc(name)}" href="/api/batch-exports/${esc(S.batchExport.id)}/${encodeURIComponent(name)}">${label}</a>`;
 return `<section class="section" id="execution-results"><div class="row"><div><h2>${esc(d.record_name)} · 本批结果</h2><p class="muted">版本 ${esc(d.revision)} · ${d.annual?'全年':d.period.slice(0,2).join('-')+' 至 '+d.period.slice(2).join('-')} · ${d.step_minutes} min${d.conditioned_area_m2?' · 温控面积 '+format(d.conditioned_area_m2,3)+' m²':''}</p></div><div class="actions"><button data-action="refresh-batch-results">刷新本批结果</button><button data-action="close-execution-results">关闭结果</button></div></div>
 <div class="metrics"><span><strong>${c.routine_passed}</strong>核验通过</span><span><strong>${c.reviewed}</strong>附说明接受</span><span><strong>${c.pending_review}</strong>待复核</span><span><strong>${c.unfinished}</strong>尚未完成</span>${c.failed||c.cancelled?`<span><strong>${c.failed} / ${c.cancelled}</strong>失败 / 已取消</span>`:''}</div>
 <p class="muted">负荷为所选时段的显热冷热需求，单位 kWh。附说明接受的结果可在明细中查看依据与原警告。</p>${c.pending_review?'<p class="warning">待复核项已完成自动校验；请在算例明细的“来源与核查”打开“复核处理”，检查依据后明确采用结论。</p>':''}<details><summary>查看汇总口径</summary><p class="muted">${esc(d.note)}自然室温不填负荷。</p></details>
 <div class="actions batch-toolbar"><button data-batch-table="sites" aria-pressed="${S.batchTable==='sites'}">地点结果</button><button data-batch-table="classes" aria-pressed="${S.batchTable==='classes'}">气候汇总</button><button data-action="export-batch" class="primary"${!c.completed?' disabled':''}>导出本批数据包</button>${S.batchExport?link('batch.zip','下载完整批次')+link('阅读说明.txt','阅读说明'):''}<a target="_blank" rel="noopener" href="/api/execution/${d.id}/summary">完整数据与核验 JSON ↗</a></div>
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
 case 'refresh-batch-results':await loadBatchResults(S.executionResults.id);notice('本批结果与复核依据已重新核对。');return true;
 case 'export-batch':{
  const d=S.executionResults;notice('正在核对结果与复核依据，生成完整批次数据包…');
  S.batchExport=await api('/api/batch-export',{id:d.id,expected_dataset_sha256:d.dataset_sha256});
  await refreshOpenExportHistory('batch',d.id);notice('完整批次数据包已生成；页面筛选不影响导出内容。');return true;
 }
 }
 return false;
}

const batchResultsBeforeInputNote=batchResultsView;batchResultsView=function(){const html=batchResultsBeforeInputNote();return html.replace('<div class="metrics">',researchInputNoteMarkup(S.executionResults?.research_input_note)+'<div class="metrics">');};
