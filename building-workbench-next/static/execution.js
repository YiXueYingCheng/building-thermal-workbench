'use strict';
S.execution=null;S.executionReview=null;S.executionResults=null;S.resourceDraft=null;S.resourcesDirty=false;
const resourcePresets={light:{max_parallel:1,reserve_gib:3,disk_reserve_gib:5,priority:'below_normal'},balanced:{max_parallel:4,reserve_gib:2,disk_reserve_gib:5,priority:'below_normal'},high:{max_parallel:8,reserve_gib:2,disk_reserve_gib:5,priority:'normal'}};
const resourceFields={'resource-parallel':'max_parallel','resource-memory':'reserve_gib','resource-disk':'disk_reserve_gib'};
const sampleLabel=x=>String(x||'').replaceAll('UNIFIED','统一反馈').replaceAll('GROUPED','按朝向分组').replaceAll('controlled','温控').replaceAll('natural','自然室温').replaceAll('cooling','制冷').replaceAll('heating','供暖');
const jobLabels={pending:'排队',running:'计算中',passed:'核验通过',reused:'已复用',review:'待复核',failed:'失败',interrupted:'中断',cancelled:'已取消'};
let executionFlight=null;
async function loadExecution(){if(executionFlight)return executionFlight;executionFlight=(async()=>{const [execution,storage]=await Promise.all([api('/api/execution'),api('/api/output-storage')]);S.execution=execution;S.outputStorage=storage;if(!S.resourcesDirty)S.resourceDraft=copy(execution.resources);})();try{await executionFlight;}finally{executionFlight=null;}}
function resourceEditStatus(){const p=S.execution.resources;return (S.resourcesDirty?'已修改，尚未应用。':'已应用。')+`当前生效：最多 ${p.max_parallel} 路，保留内存 ${p.reserve_gib} GiB、磁盘 ${p.disk_reserve_gib} GiB。`;}
function updateResourceEditStatus(){const status=document.getElementById('resource-edit-status');if(status)status.textContent=resourceEditStatus();}
document.addEventListener('input',event=>{
 const key=resourceFields[event.target.id];if(!key||!S.resourceDraft)return;
 S.resourceDraft[key]=event.target.value===''?null:Number(event.target.value);S.resourceDraft.profile='custom';S.resourcesDirty=true;
 document.getElementById('resource-profile').value='custom';updateResourceEditStatus();
});
document.addEventListener('change',event=>{
 if(event.target.id!=='resource-profile'||!S.resourceDraft)return;
 const profile=event.target.value;S.resourceDraft={...S.resourceDraft,...(resourcePresets[profile]||{}),profile};S.resourcesDirty=true;
 for(const [id,key] of Object.entries(resourceFields))document.getElementById(id).value=S.resourceDraft[key];updateResourceEditStatus();
});
function resourceBudgetHistory(b){
 if(!b.basis)return b.completed_samples>=3?'按同批次、同运行模式的 '+b.completed_samples+' 个已完成样本估算。':'完成 3 个同类样本后按实测峰值更新估算。';
 const count=n=>Number.isInteger(n)&&n>0?n:0,family=count(b.family_samples),same=count(b.completed_samples);
 if(!family)return '尚无同建筑的内存观测，先用初始预算；新配置首路启动后等待稳定，再核对可用余量。';
 return `按同建筑 ${family} 次实际运行的内存峰值估算；${same?'其中当前配置 '+same+' 次。':'当前配置尚无运行记录，沿用同建筑预算并观察启动阶段。'}`;
}
function executionStatus(){
 const e=S.execution;if(!e)return '正在读取计算队列…';const m=e.machine,w=e.worker;
 const online=w&&Date.now()-Date.parse(w.heartbeat)<15000;
 const budget=online&&w.budget?`<p class="muted">新增一路的内存预算：保留给其他应用 ${format(w.budget.reserve_gib,2)} + 新算例 ${format(w.budget.next_job_gib,2)} + 已运行算例的增长余量 ${format(w.budget.running_growth_gib,2)} = ${format(w.budget.required_available_gib,2)} GiB。${resourceBudgetHistory(w.budget)}</p>`:'';
 return `<div class="metrics"><span><strong>${w&&online?w.active:0}</strong>当前运行</span><span><strong>${e.resources.max_parallel}</strong>工作区并行上限</span><span><strong>${format(m.available_gib,1)}</strong>可用内存 / GiB</span><span><strong>${format(m.disk_free_gib,1)}</strong>工作区磁盘可用 / GiB</span></div><p class="muted">${online?esc(w.reason||'调度正常，按资源余量派发任务。'):w?'调度暂未响应。已完成结果保留，可恢复调度后检查中断项。':'提交后将启动后台调度。'}${online&&w.foreign_engine_pids?.length?' 其他计算仍在运行，本工作区等待。':''}</p>${budget}${w&&!online?'<button data-action="wake-execution">恢复调度</button>':''}`;
}
function executionBatches(){
 if(!S.execution?.batches.length)return '<p class="muted">尚未提交计算。先在方案中生成输入，再准备计算清单。</p>';
 return S.execution.batches.map(b=>{const c=b.counts,unfinished=c.pending+c.running+c.interrupted,stale=c.running&&(!S.execution.worker||Date.now()-Date.parse(S.execution.worker.heartbeat)>=15000);return `<article class="control" id="batch-${esc(b.id)}"><div class="row"><div><h3>${esc(b.record_name)}${b.output_contract==='daily_sensible_reference_v1'?' · 逐日参考':''}</h3><p class="muted">版本 ${esc(b.revision)} · ${b.case_count} 个算例 · ${esc(b.created)}</p></div><span class="tag">${stale?'运行状态待核对':!unfinished?(c.review?'计算结束 · 警告待复核':c.failed?'计算结束 · 有失败':c.cancelled?'批次结束 · 含取消':'已完成'):b.mode==='pause'?(c.running?'等待当前完成后暂停':'已暂停'):b.mode==='cancel'?'已取消排队项':'进行中'}</span></div><p class="muted">结果位置：${esc(b.storage?.label||'工作区结果目录')}<small class="output-path">${esc(b.storage?.path||'')}</small></p><p>通过 ${c.passed} · 复用 ${c.reused} · 待复核 ${c.review} · 失败 ${c.failed} · 中断 ${c.interrupted} · 取消 ${c.cancelled}</p><div class="actions">${c.pending||c.running?`<button data-batch="${b.id}" data-control="${b.mode==='pause'?'resume':'pause'}">${b.mode==='pause'?'继续排队项':'完成当前后暂停'}</button><button data-batch="${b.id}" data-control="cancel_pending">取消排队项</button>`:''}${c.failed||c.interrupted?`<button data-batch="${b.id}" data-control="retry">重试失败 / 中断项</button>`:''}<button data-batch-results="${b.id}">查看结果与核验</button></div><details><summary>查看 ${b.case_count} 个算例</summary><table class="table"><thead><tr><th>地点</th><th>模式 / 时段</th><th>状态</th></tr></thead><tbody>${b.jobs.map(j=>`<tr><td>${esc(j.city)}</td><td>${esc(modes[j.mode])}<small>${j.period.slice(0,2).join('-')} 至 ${j.period.slice(2).join('-')} · ${j.step_minutes} min</small></td><td>${stale&&j.status==='running'?'调度失联，运行状态待核对':jobLabels[j.status]}${j.error?'<small class="warning">'+esc(j.error)+'</small>':''}</td></tr>`).join('')}</tbody></table></details></article>`;}).join('');
}
function executionReview(){
 const p=S.executionReview;if(!p)return '';
 return `<section class="section" id="execution-review"><h2>${p.existing_batch?'已提交的计算清单':'提交前的计算清单'}</h2><p><strong>${esc(p.record_name)}${p.output_contract==='daily_sensible_reference_v1'?' · 逐日参考':''}</strong> · 版本 ${esc(p.revision)} · ${p.case_count} 个算例</p>${p.preparation_reused?`<p class="well">${p.existing_batch?'此清单已经提交，已找到原批次。原批次的暂停或完成状态保持不变。':'已核对并恢复原清单，无需重复准备。'}</p>`:''}<p class="muted">输入与方案版本已冻结。提交后按工作区统一预算运行；只复用输入、程序及结果文件全部核对通过的已完成算例。</p>${caseListView('review')}<p>${p.output_contract==='daily_sensible_reference_v1'?'保存逐日显热冷热需求 CSV、月度与全年汇总、运行日志和核验依据。待复核结果不会自动列为可用参考。':'保存月度与整个时段汇总、运行日志和核验依据。自然室温单独汇总。短时段结果不会标成全年结果。'}</p><div class="actions">${p.existing_batch?`<button class="primary" data-prepared-batch="${esc(p.existing_batch.id)}">查看原批次</button><button data-action="prepare-independent">另备独立清单（不计算）</button>`:`<button data-action="submit-execution" class="primary">提交这 ${p.case_count} 个算例并开始计算</button>`}<button data-action="discard-execution-review">收起清单</button></div></section>`;
}
function executionResults(){
 const d=S.executionResults;if(!d)return '';
 if(!d.validation&&d.dataset_sha256)return batchResultsView();
 return `<section class="section" id="execution-results"><div class="row"><h2>${esc(d.record_name)} · 本批结果</h2><div class="actions"><button data-action="close-execution-results">关闭结果</button><a target="_blank" rel="noopener" href="${d.validation?'/api/execution/validation':'/api/execution/'+d.id+'/results'}">完整汇总与核验 JSON ↗</a></div></div><p class="muted">绑定版本 ${esc(d.revision)}。负荷为所选时段的显热冷热需求，单位 kWh；自然室温不填负荷。待复核结果单独标记。</p>${d.results.length?`<p class="muted scroll-hint">窄屏可左右滑动查看完整结果。</p><div class="table-wrap" tabindex="0" aria-label="计算结果，可横向滚动"><table class="table result-grid"><thead><tr><th>地点 / 模式</th><th>天数 / 核验</th><th>供暖</th><th>制冷</th><th>合计</th><th>室温极值 / °C</th></tr></thead><tbody>${d.results.map(r=>`<tr><td>${esc(r.city)}<small>${modes[r.mode]}</small>${r.validation_label?'<small>'+esc(sampleLabel(r.validation_label))+'</small>':''}</td><td>${r.days} 天<small>${r.period.slice(0,2).join('-')} 至 ${r.period.slice(2).join('-')} · ${r.step_minutes} min</small><small>${jobLabels[r.status]}</small></td>${['heating','cooling','total'].map(k=>`<td class="num">${r.loads?format(r.loads[k+'_kWh'],3):'—'}</td>`).join('')}<td>${format(r.temperature_extrema.min_C,2)} ～ ${format(r.temperature_extrema.max_C,2)}</td></tr>`).join('')}</tbody></table></div>${d.results.filter(r=>r.pending_warnings.length).map(r=>`<p class="warning">${esc(r.city)}：${esc(r.pending_warnings.join('；'))}</p>`).join('')}<details><summary>房间温度与分月明细</summary><pre>${esc(JSON.stringify(d.results.map(r=>({city:r.city,mode:r.mode,monthly:r.monthly,temperatures:r.temperatures})),null,2))}</pre></details>`:'<p class="muted">本批尚无已完成结果。失败与中断信息保留在算例列表中。</p>'}</section>`;
}
function executionView(){
 const e=S.execution;if(!e)return '<p>正在读取队列…</p>';const p=S.resourceDraft||e.resources;
 return `<section class="section"><div class="row"><h1>计算队列与设备投入</h1><button data-action="refresh-execution">刷新</button></div><div id="execution-status">${executionStatus()}</div><div class="grid2"><label class="field">设备投入<select id="resource-profile">${options([['light','轻量 · 最多 1 路，保留 3 GiB'],['balanced','平衡 · 最多 4 路，保留 2 GiB'],['high','集中计算 · 最多 8 路，保留 2 GiB'],['custom','自定义']],p.profile)}</select></label><label class="field">并行上限<input id="resource-parallel" type="number" min="1" max="8" step="1" value="${p.max_parallel}"></label><label class="field">保留内存 / GiB<input id="resource-memory" type="number" min="1" max="64" value="${p.reserve_gib}" step="0.5"></label><label class="field">保留磁盘 / GiB<input id="resource-disk" type="number" min="2" max="1000" value="${p.disk_reserve_gib}" step="1"></label></div><p id="resource-edit-status" class="muted">${esc(resourceEditStatus())}</p><div class="row"><p class="muted">手动修改数值会自动切换到自定义，点击“应用设备投入”后生效。设置对本工作区所有批次共同生效。提高上限后，有资源余量才新增进程；降低上限会等当前算例完成。其他平台的计算运行时，本工作区暂停派发。</p><button data-action="save-resources" class="primary">应用设备投入</button></div>${outputStorageSummary()}</section>${executionReview()}${executionResults()}<section class="section"><div class="row"><h2>批次与进度</h2><button data-action="validation-results">查看本阶段验收样本</button></div><div id="execution-batches">${executionBatches()}</div></section>`;
}
async function executionAction(button){
 if(await batchResultsAction(button))return true;
 if(button.dataset.batch){await api('/api/execution/control',{id:button.dataset.batch,action:button.dataset.control});await loadExecution();notice('队列操作已记录。当前计算和已完成结果会保留。');return true;}
 if(button.dataset.preparedBatch){await loadExecution();await loadBatchResults(button.dataset.preparedBatch,true);S.executionReview=null;return true;}
 if(button.dataset.batchResults){await loadBatchResults(button.dataset.batchResults,true);return true;}
 switch(button.dataset.action){
 case 'prepare-execution':if(!S.generated||S.dirty)throw new Error('请先保存方案并生成对应版本的模型输入。');await openPreparedInput(S.generated.id);return true;
 case 'submit-execution':{const p=S.executionReview;if(!p)throw new Error('请先准备计算清单。');if(p.existing_batch)throw new Error('此清单已经提交，请查看原批次。');const budget=S.calculationBudget;if(!budget||budget.id!==p.id||budget.plan_sha256!==p.plan_sha256||!budget.storage?.destination)throw Error('请先核对预算与结果保存位置。');const result=await api('/api/execution/submit',{review_id:p.id,plan_sha256:p.plan_sha256,destination:budget.storage.destination});invalidateWorkflowAfterSubmission(p.record_id,p.revision,result.id);S.executionReview=null;await loadExecution();notice(result.reused_submission?'此清单已提交过，原批次及其队列状态保持不变。':'已提交后台队列；可以关闭页面，之后回来查看进度。');return true;}
 case 'prepare-independent':{const p=S.executionReview;if(!p?.existing_batch)throw new Error('请先打开原批次的计算清单。');await openPreparedInput(p.bundle_id,p.existing_batch.id,{id:p.record_id,revision:p.revision},p.output_contract);return true;}
 case 'discard-execution-review':{const p=S.executionReview;S.executionReview=null;notice(p?.output_contract==='daily_sensible_reference_v1'?'已收起，清单和批次状态保持。可从“工况 → 准备逐日参考”重新打开。':'已收起，清单仍保留；可从本版本的计算安排重新打开。');return true;}
 case 'save-resources':await api('/api/execution/resources',S.resourceDraft);S.resourcesDirty=false;await loadExecution();notice(resourceEditStatus()+'运行中的算例继续完成。');return true;
 case 'close-execution-results':S.executionResults=null;resetBatchResults();return true;
 case 'wake-execution':await api('/api/execution/wake',{});await loadExecution();notice('已请求恢复调度；中断算例保留现场，可使用重试按钮继续。');return true;
 case 'validation-results':resetBatchResults();S.executionResults=await api('/api/execution/validation');return true;
 case 'refresh-execution':await loadExecution();if(S.executionResults){if(S.executionResults.validation)S.executionResults=await api('/api/execution/validation');else await loadBatchResults(S.executionResults.id);}return true;
 }
 return false;
}
setInterval(async()=>{
 if(S.view!=='execution'||S.busy||document.hidden||S.queueResultWindow)return;
 if(!S.execution?.batches.some(b=>b.counts.running||b.counts.pending)&&Date.now()-(S.executionPollAt||0)<20000)return;S.executionPollAt=Date.now();
 try{await loadExecution();if(S.view!=='execution'||S.busy)return;const a=document.getElementById('execution-status'),b=document.getElementById('execution-batches');if(a)a.innerHTML=executionStatus();updateResourceEditStatus();if(b&&!b.contains(document.activeElement)&&!b.querySelector('details[open]'))b.innerHTML=executionBatches();}catch(error){notice(error.message);}
},4000);
