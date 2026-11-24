'use strict';
S.execution=null;S.executionReview=null;S.executionResults=null;S.resourceDraft=null;S.resourcesDirty=false;
const resourcePresets={light:{max_parallel:1,reserve_gib:3,disk_reserve_gib:5,priority:'below_normal'},balanced:{max_parallel:4,reserve_gib:2,disk_reserve_gib:5,priority:'below_normal'},high:{max_parallel:8,reserve_gib:2,disk_reserve_gib:5,priority:'normal'}};
const resourceFields={'resource-parallel':'max_parallel','resource-memory':'reserve_gib','resource-disk':'disk_reserve_gib','resource-cpu-percent':'cpu_limit_percent'};
const sampleLabel=x=>String(x||'').replaceAll('UNIFIED','统一反馈').replaceAll('GROUPED','按朝向分组').replaceAll('controlled','温控').replaceAll('natural','自然室温').replaceAll('cooling','制冷').replaceAll('heating','供暖');
const jobLabels={pending:'排队',running:'计算中',passed:'核验通过',reused:'已复用',review:'待复核',failed:'失败',interrupted:'中断',cancelled:'已取消'};
let executionFlight=null;
async function loadExecution(){if(executionFlight)return executionFlight;executionFlight=(async()=>{const [execution,storage]=await Promise.all([api('/api/execution'),api('/api/output-storage')]);S.execution=execution;S.outputStorage=storage;if(!S.resourcesDirty)S.resourceDraft=copy(execution.resources);})();try{await executionFlight;}finally{executionFlight=null;}}
function resourceEditStatus(){const p=S.execution.resources;return (S.resourcesDirty?'已修改，尚未应用。':'已应用。')+`当前生效：最多 ${p.max_parallel} 路，保留内存 ${p.reserve_gib} GiB、磁盘 ${p.disk_reserve_gib} GiB；CPU 控制${p.cpu_limit_enabled?'开启，目标 '+p.cpu_limit_percent+'%':'关闭'}。`;}
function updateResourceEditStatus(){const status=document.getElementById('resource-edit-status');if(status)status.textContent=resourceEditStatus();}
document.addEventListener('input',event=>{
 const key=resourceFields[event.target.id];if(!key||!S.resourceDraft)return;
 S.resourceDraft[key]=event.target.value===''?null:Number(event.target.value);S.resourceDraft.profile='custom';S.resourcesDirty=true;
 document.getElementById('resource-profile').value='custom';updateResourceEditStatus();
});
document.addEventListener('change',event=>{
 if(event.target.id==='resource-cpu-enabled'&&S.resourceDraft){
  S.resourceDraft.cpu_limit_enabled=event.target.checked;
  S.resourceDraft.cpu_limit_percent??=80;
  S.resourcesDirty=true;
  updateCpuDetails();updateResourceEditStatus();return;
 }
 if(event.target.id!=='resource-profile'||!S.resourceDraft)return;
 const profile=event.target.value;S.resourceDraft={...S.resourceDraft,...(resourcePresets[profile]||{}),profile};S.resourcesDirty=true;
 for(const [id,key] of Object.entries(resourceFields))document.getElementById(id).value=S.resourceDraft[key]??(key==='cpu_limit_percent'?80:'');updateResourceEditStatus();
});
function resourceCpuSettings(p){
 const enabled=p.cpu_limit_enabled;
 return `<section class="well resource-cpu-settings"><label class="check"><input type="checkbox" id="resource-cpu-enabled" aria-controls="resource-cpu-details"${enabled?' checked':''}>按 CPU 占用控制新增并行（可选）</label>
 <div id="resource-cpu-details"${enabled?'':' hidden'}><label class="field">整机 CPU 目标占用 / %<input id="resource-cpu-percent" type="number" min="10" max="100" step="1" value="${p.cpu_limit_percent??80}"${enabled?'':' disabled'}></label>
 <p>工作台根据整机负载决定何时派发新算例，每次启动后观察约 10 秒。达到目标时，运行中的算例继续计算。内存和磁盘限制始终生效。</p>
 <p class="muted">整机负载包含其他软件。若目标低于单个算例所需占用，新算例可能持续等待。</p>
 <div id="resource-cpu-monitor">${enabled?executionCpuStatus():''}</div></div></section>`;
}
function updateCpuDetails(){
 const checkbox=document.getElementById('resource-cpu-enabled');
 if(!checkbox)return;
 const draft=S.resourceDraft||S.execution.resources,enabled=Boolean(draft.cpu_limit_enabled);
 checkbox.checked=enabled;
 const details=document.getElementById('resource-cpu-details'),target=document.getElementById('resource-cpu-percent');
 details.hidden=!enabled;target.disabled=!enabled;
 if(document.activeElement!==target)target.value=draft.cpu_limit_percent??80;
 const monitor=document.getElementById('resource-cpu-monitor');
 if(enabled&&!monitor.querySelector('details[open]'))monitor.innerHTML=executionCpuStatus();
}
function cpuBudgetMarkup(c){if(!c)return '';return `<p>${c.enabled?'CPU 控制已开启':'CPU 控制未开启（按 '+format(c.limit_percent,0)+'% 目标预览预算）'}${c.enabled?' · 目标 '+format(c.limit_percent,0)+'%':''}。${c.ready?`新增一路 CPU 预算 ${format(c.next_job_percent,1)}%，按 CPU 余量和并行上限估计可新增 ${c.additional_slots} 路`:'等待有效 CPU 观测后显示余量预算'}；实际并行还受内存、磁盘和并行上限约束。</p><p class="muted">${esc(c.basis||'这是当前负载下的参考，不是整批耗时保证。')}</p>`;}
function executionCpuStatus(){
 const {machine:m,worker:w,cpu_budget:preview}=S.execution,online=Boolean(w?.online);
 const c=m.cpu||{},jobs=online?w?.cpu_jobs||[]:[],budget=(online?w?.budget?.cpu:null)||preview;
 return `<section class="well"><div class="metrics"><span><strong>${c.ready?format(c.percent,1)+'%':'采样中'}</strong>整机 CPU 当前</span><span><strong>${c.ready?format(c.average_percent,1)+'%':'—'}</strong>近期 CPU 平均</span><span><strong>${m.logical_cpus||'—'}</strong>逻辑处理器</span></div><p class="muted">${c.ready?'按 CPU 忙碌时间计量，近期窗口约 '+format(c.window_seconds,0)+' 秒；与系统任务管理器的数值可能略有差异。':esc(c.reason||'正在读取 CPU 状态。')}</p>${cpuBudgetMarkup(budget)}${jobs.length?`<details><summary>正在运行算例的 CPU 观测</summary>${jobs.map(j=>`<p>进程 ${j.pid}：${Number.isFinite(j.percent)?format(j.percent,1)+'%':'采样中'}，本次采样峰值 ${format(j.peak_percent,1)}%（占整机）。</p>`).join('')}</details>`:''}</section>`;
}
function resourceBudgetHistory(b){
 if(b.budget_note&&!b.used_samples)return '按初始预算 '+format(b.next_job_gib,2)+' GiB 安排首项，启动后按实测更新。'+esc(b.budget_note);
 const sources={exact:'同配置',comparable:'同建筑、同时段、同步长及相近模型',same_step:'同建筑、同步长及相同作息数量的其他配置',family:'同建筑的其他配置'};
 if(sources[b.basis]&&b.used_samples){
  const source=sources[b.basis]+'的 '+b.used_samples+' 次实测';
  const peak=b.legacy_peak?'旧记录合并了物理内存和提交量，取两者较高峰值':'物理内存峰值';
  return source+'。'+peak+' '+format(b.reference_peak_gib,2)+' GiB，按峰值 × 1.25 + 0.05 GiB 预留（最低 0.75 GiB）。系统提交量另预算 '+format(b.reserved_commit_gib,2)+' GiB。'+(b.basis==='exact'?'':'当前配置尚无实测。');
 }
 if(!b.basis)return b.completed_samples>=3?'按同批次、同运行模式的 '+b.completed_samples+' 个已完成样本估算。':'完成 3 个同类样本后按实测峰值更新估算。';
 const count=n=>Number.isInteger(n)&&n>0?n:0,family=count(b.family_samples),same=count(b.completed_samples);
 if(!family)return '尚无同建筑的内存观测，先用初始预算；新配置首路启动后等待稳定，再核对可用余量。';
 return `按同建筑 ${family} 次实际运行的内存峰值估算；${same?'其中当前配置 '+same+' 次。':'当前配置尚无运行记录，沿用同建筑预算并观察启动阶段。'}`;
}
function executionStatus(){
 const e=S.execution;if(!e)return '正在读取计算队列…';const m=e.machine,w=e.worker;
 const online=Boolean(w?.online);
 const b=online&&w.budget;
 const batch=b?e.batches.find(row=>row.id===b.batch):null;
 const job=batch?.jobs.find(row=>row.idx===b.index);
 const queued=job?.status==='pending'&&!b.allowed;
 const budget=b?`<p class="muted">普通调度的物理内存预算：保留给其他应用 ${format(b.reserve_gib,2)} + 新算例 ${format(b.next_job_gib,2)} + 已运行算例的增长余量 ${format(b.running_growth_gib,2)} = ${format(b.required_available_gib,2)} GiB。${resourceBudgetHistory(b)}</p>${queued?`<p>${esc(job.city)} · ${job.step_minutes} min ${queueJobActions(batch,job)}</p>`:''}`:'';
 return `<div class="metrics"><span><strong>${w&&online?w.active:0}</strong>当前运行</span><span><strong>${e.resources.max_parallel}</strong>工作区并行上限</span><span><strong>${format(m.available_gib,1)}</strong>可用内存 / GiB</span><span><strong>${format(m.disk_free_gib,1)}</strong>工作区磁盘可用 / GiB</span></div><p class="muted">${online?esc(w.reason||'调度正常，按资源余量派发任务。'):w?esc(w.diagnostic||'计算后台未就绪，请查看下方诊断。'):e.dispatch_enabled===false?'当前服务处于预览模式。排队请求可登记；派发算例需启动带计算后台的工作台。':'提交后将启动后台调度。'}${online&&w.foreign_engine_pids?.length?' 其他计算仍在运行，本工作区等待。':''}</p>${budget}${w&&!online&&e.dispatch_enabled!==false?`<section class="well worker-warning" role="alert"><strong>计算后台未就绪</strong><p>${esc(w.diagnostic||'请检查后台启动状态。')}</p><p>已完成结果保留。启动后台后，已暂停批次仍须点击“继续此批次”；中断项需重试。若由 AI 工具启动且报告权限限制，请先正常停止对应服务，再从普通 Windows 窗口启动。</p><button data-action="wake-execution">检查并启动后台</button>${w.log_tail?`<details><summary>查看启动诊断（可选择复制）</summary><pre class="worker-diagnostic">${esc(w.log_tail)}</pre></details>`:''}</section>`:''}`;
}
const openQueueDetails=new Set();
function queueDetailAttributes(batch,kind){
 const key=batch+'/'+kind;
 return `data-queue-detail="${esc(key)}" data-queue-detail-kind="${kind}"${openQueueDetails.has(key)?' open':''}`;
}
document.addEventListener('toggle',event=>{
 const item=event.target,key=item.dataset?.queueDetail;
 if(!key||!item.isConnected)return;
 if(item.open)openQueueDetails.add(key);else openQueueDetails.delete(key);
},true);
function queueJobRetryable(job){
 return (job.status==='failed'||job.status==='interrupted')&&!job.recalculations?.length;
}
function queueNeedsAttention(batch){
 const c=batch.counts;
 return c.pending||c.running||c.review||batch.jobs.some(job=>{
  const links=job.recalculations||[];
  return queueJobRetryable(job)||(links.length>0&&!links.some(r=>r.adopted));
 });
}
function queueFailureLabel(batch,retryCount){
 if(retryCount)return '计算结束 · 有待重试项';
 const originals=batch.jobs.filter(j=>j.recalculations?.length);
 return originals.every(j=>j.recalculations.some(r=>r.adopted))?'原记录保留 · 补算已并入':'原记录保留 · 已转入补算';
}
function queueJobStatus(job){
 if(job.status==='failed'&&job.error?.startsWith('输入需核查：')&&!job.recalculations?.length)return '输入需核查';
 const links=job.recalculations;
 if(!links?.length)return jobLabels[job.status];
 const adopted=links.find(r=>r.adopted);
 const progress=r=>{
  if(r.adopted)return '补算已并入';
  if(r.status==='passed'||r.status==='reused')return '补算已通过，待确认并入';
  return '补算'+(jobLabels[r.status]||'状态待核对');
 };
 return '原始'+jobLabels[job.status]+(adopted?[adopted]:links).map(r=>
  '<small>'+esc(r.step)+' min · '+progress(r)+'</small>').join('');
}
function queueJobActions(batch,job){
 const action=(key,label)=>` <button data-job-action="${key}" data-job-batch="${esc(batch.id)}" data-job-index="${job.idx}">${label}</button>`;
 if(job.status==='cancelled')return action('requeue_cancelled','重新计算此算例');
 if(job.manual_start==='exclusive')
  return job.status==='running'?' · 独占运行':' · 等待独占运行'+action('release_force','撤回强制启动');
 if(job.status==='pending'&&!S.execution.exclusive_job&&(batch.mode==='run'||job.manual_start==='normal'))
  return S.execution?.dispatch_enabled===false?' · 等待启用计算后台':action('force_one','强制启动此算例（独占）');
 return '';
}
function executionBatches(){
 if(!S.execution?.batches.length)return '<p class="muted">尚未提交计算。先在方案中生成输入，再准备计算清单。</p>';
 return S.execution.batches.map(b=>{
 const c=b.counts,retryCount=b.jobs.filter(queueJobRetryable).length;
 const unfinished=c.pending+c.running;
 const stale=c.running&&!S.execution.worker?.online;
 return `<article class="control" id="batch-${esc(b.id)}"><div class="row"><div><h3>${esc(b.record_name)} · ${esc(outputResolutionLabel(b.output_contract))}</h3><p class="muted">版本 ${esc(b.revision)} · ${b.case_count} 个算例 · ${esc(b.created)}</p></div><span class="tag">${stale?'运行状态待核对':!unfinished?(c.review?'计算结束 · 警告待复核':c.failed||c.interrupted?queueFailureLabel(b,retryCount):c.cancelled?'批次结束 · 含取消':'已完成'):b.mode==='pause'?(c.running?'等待当前完成后暂停':'已暂停'):b.mode==='cancel'?'已取消排队项':c.running?'计算中':S.execution?.dispatch_enabled===false?'排队中 · 预览模式':'排队中'}</span></div><details ${queueDetailAttributes(b.id,'storage')}><summary>结果保存位置</summary><p class="muted">结果位置：${esc(b.storage?.label||'工作区结果目录')}<small class="output-path">${esc(b.storage?.path||'')}</small></p></details><p>通过 ${c.passed} · 复用 ${c.reused} · 待复核 ${c.review} · 失败 ${c.failed} · 中断 ${c.interrupted} · 取消 ${c.cancelled}</p><p class="worker-batch-note">${b.mode==='pause'&&unfinished?'此批次已暂停。启动后台不会自动继续；请选择继续排队项或重试中断项。':''}</p><div class="actions">${c.pending||c.running?`<button data-batch="${b.id}" data-control="${b.mode==='pause'?'resume':'pause'}">${b.mode==='pause'?'继续此批次的排队项':'完成当前后暂停'}</button><button data-batch="${b.id}" data-control="cancel_pending">取消排队项</button>`:''}${retryCount?`<button data-batch="${b.id}" data-control="retry">重试 ${retryCount} 个失败或中断算例并继续此批次</button>`:''}<button data-batch-results="${b.id}">查看结果与核验</button></div><details ${queueDetailAttributes(b.id,'cases')}><summary>查看 ${b.case_count} 个算例</summary><table class="table"><thead><tr><th>地点</th><th>模式 / 时段</th><th>状态</th></tr></thead><tbody>${b.jobs.map(j=>`<tr><td>${esc(j.city)}</td><td>${esc(modes[j.mode])}<small>${j.period.slice(0,2).join('-')} 至 ${j.period.slice(2).join('-')} · ${j.step_minutes} min</small></td><td>${stale&&j.status==='running'?'调度失联，运行状态待核对':queueJobStatus(j)}${queueJobActions(b,j)}${j.status==='running'?` <button data-warmup-batch="${esc(b.id)}" data-warmup-index="${j.idx}">查看预热趋势</button>`:''}${j.error?'<small class="warning">'+esc(j.error)+'</small>':''}</td></tr>`).join('')}</tbody></table></details></article>`;}).join('');
}
function executionReview(){
 const p=S.executionReview;if(!p)return '';
 return `<section class="section" id="execution-review"><div class="row"><h2>${p.existing_batch?'已提交的计算清单':'提交前的计算清单'}</h2>${designQueueBack()}</div><p><strong>${esc(p.record_name)}${p.output_contract==='daily_sensible_reference_v1'?' · 逐日参考':''}</strong> · 版本 ${esc(p.revision)} · ${p.case_count} 个算例</p>${p.preparation_reused?`<p class="well">${p.existing_batch?'此清单已经提交，已找到原批次。原批次的暂停或完成状态保持不变。':'已核对并恢复原清单，无需重复准备。'}</p>`:''}<p class="muted">输入与方案版本已冻结。提交后按工作区统一预算运行；只复用输入、程序及结果文件全部核对通过的已完成算例。</p>${caseListView('review')}${outputResolutionSummary(p)}<p>${p.output_contract==='daily_sensible_reference_v1'?'保存逐日显热冷热需求 CSV、月度与全年汇总、运行日志和核验依据。待复核结果不会自动列为可用参考。':'按上方保存频率输出明细，并保留月度与整个时段汇总、运行日志和核验依据。自然室温单独汇总。短时段结果不会标成全年结果。'}</p><div class="actions">${p.existing_batch?`<button class="primary" data-prepared-batch="${esc(p.existing_batch.id)}">查看原批次</button><button data-action="prepare-independent">另备独立清单（不计算）</button>`:`<button data-action="submit-execution" class="primary">提交这 ${p.case_count} 个算例并开始计算</button>`}<button data-action="discard-execution-review">收起清单</button></div></section>`;
}
function executionResults(){
 const d=S.executionResults;if(!d)return '';
 if(!d.validation&&d.dataset_sha256)return batchResultsView();
 return `<section class="section" id="execution-results"><div class="row"><h2>${esc(d.record_name)} · 本批结果</h2><div class="actions"><button data-action="close-execution-results">关闭结果</button><a target="_blank" rel="noopener" href="${d.validation?'/api/execution/validation':'/api/execution/'+d.id+'/results'}">完整汇总与核验 JSON ↗</a></div></div><p class="muted">绑定版本 ${esc(d.revision)}。负荷为所选时段的显热冷热需求，单位 kWh；自然室温不填负荷。待复核结果单独标记。</p>${d.results.length?`<p class="muted scroll-hint">窄屏可左右滑动查看完整结果。</p><div class="table-wrap" tabindex="0" aria-label="计算结果，可横向滚动"><table class="table result-grid"><thead><tr><th>地点 / 模式</th><th>天数 / 核验</th><th>供暖</th><th>制冷</th><th>合计</th><th>室温极值 / °C</th></tr></thead><tbody>${d.results.map(r=>`<tr><td>${esc(r.city)}<small>${modes[r.mode]}</small>${r.validation_label?'<small>'+esc(sampleLabel(r.validation_label))+'</small>':''}</td><td>${r.days} 天<small>${r.period.slice(0,2).join('-')} 至 ${r.period.slice(2).join('-')} · ${r.step_minutes} min</small><small>${jobLabels[r.status]}</small></td>${['heating','cooling','total'].map(k=>`<td class="num">${r.loads?format(r.loads[k+'_kWh'],3):'—'}</td>`).join('')}<td>${format(r.temperature_extrema.min_C,2)} ～ ${format(r.temperature_extrema.max_C,2)}</td></tr>`).join('')}</tbody></table></div>${d.results.filter(r=>r.pending_warnings.length).map(r=>`<p class="warning">${esc(r.city)}：${esc(r.pending_warnings.join('；'))}</p>`).join('')}<details><summary>房间温度与分月明细</summary><pre>${esc(JSON.stringify(d.results.map(r=>({city:r.city,mode:r.mode,monthly:r.monthly,temperatures:r.temperatures})),null,2))}</pre></details>`:'<p class="muted">本批尚无已完成结果。失败与中断信息保留在算例列表中。</p>'}</section>`;
}
function executionView(){
 const e=S.execution;if(!e)return '<p>正在读取队列…</p>';const p=S.resourceDraft||e.resources;
 return `<section class="section"><div class="row"><h1>计算队列与设备投入</h1><div class="actions">${S.executionReview?'':designQueueBack()}<button data-action="refresh-execution">刷新</button></div></div><div id="execution-status">${executionStatus()}</div><div class="grid2"><label class="field">设备投入<select id="resource-profile">${options([['light','轻量 · 最多 1 路，保留 3 GiB'],['balanced','平衡 · 最多 4 路，保留 2 GiB'],['high','集中计算 · 最多 8 路，保留 2 GiB'],['custom','自定义']],p.profile)}</select></label><label class="field">并行上限<input id="resource-parallel" type="number" min="1" max="8" step="1" value="${p.max_parallel}"></label><label class="field">保留内存 / GiB<input id="resource-memory" type="number" min="1" max="64" value="${p.reserve_gib}" step="0.5"></label><label class="field">保留磁盘 / GiB<input id="resource-disk" type="number" min="2" max="1000" value="${p.disk_reserve_gib}" step="1"></label></div>${resourceCpuSettings(p)}<p id="resource-edit-status" class="muted">${esc(resourceEditStatus())}</p><div class="row"><p class="muted">手动修改数值会自动切换到自定义，点击“应用设备投入”后生效。设置对本工作区所有批次共同生效。提高上限后，有资源余量才新增进程；降低上限会等当前算例完成。其他平台的计算运行时，本工作区暂停派发。</p><button data-action="save-resources" class="primary">应用设备投入</button></div>${outputStorageSummary()}</section>${executionReview()}${executionResults()}<section class="section"><div class="row"><h2>批次与进度</h2><button data-action="validation-results">查看本阶段验收样本</button></div><div id="execution-batches">${executionBatches()}</div></section>`;
}
function confirmExclusiveStart(batch,job){
 const dialog=document.createElement('dialog');
 dialog.setAttribute('aria-labelledby','exclusive-start-title');
 dialog.style.maxWidth='min(36rem, 92vw)';
 dialog.innerHTML=`<h2 id="exclusive-start-title">强制启动一个算例</h2><p>${esc(batch.record_name)} · ${esc(job.city)} · ${esc(job.step_minutes)} min</p>
  <p>该算例将等待其他计算结束，再独占运行。本次跳过预计内存峰值和 CPU 目标限制。启动时仍检查内存保留线、系统可提交内存及磁盘空间。</p>
  <p class="warning"><strong>内存可能在运行中耗尽。</strong>系统可能频繁使用磁盘换页，导致整机变慢、卡住，其他软件也可能失去响应。计算进程可能退出，本次结果可能不完整，需要重新计算。</p>
  <label><input type="checkbox" data-risk-ack> 我已充分了解以上可能后果，同意强制启动此算例。</label>
  <div class="actions"><button type="button" data-dismiss autofocus>取消</button><button type="button" class="primary" data-agree disabled>确认强制启动</button></div>`;
 const ack=dialog.querySelector('[data-risk-ack]'),agree=dialog.querySelector('[data-agree]');
 ack.addEventListener('change',()=>{agree.disabled=!ack.checked;});
 return new Promise(resolve=>{
  dialog.addEventListener('close',()=>{const accepted=ack.checked&&dialog.returnValue==='accepted';dialog.remove();resolve(accepted);},{once:true});
  dialog.addEventListener('click',event=>{
   event.stopPropagation();
   if(event.target.closest('[data-dismiss]'))dialog.close();
   if(event.target.closest('[data-agree]')&&ack.checked)dialog.close('accepted');
  });
  document.body.append(dialog);dialog.showModal();
 });
}
async function executionAction(button){
 if(await batchResultsAction(button))return true;
 if(button.dataset.jobAction){
  const {jobAction:action,jobBatch:id,jobIndex}=button.dataset,index=Number(jobIndex);
  const batch=S.execution.batches.find(b=>b.id===id),job=batch?.jobs.find(j=>j.idx===index);
  if(!job)throw Error('算例状态已更新，请刷新队列。');
  if(action==='force_one'&&S.execution?.dispatch_enabled===false)throw Error('当前服务处于预览模式；启用计算后台后可申请独占运行。');
  const confirmed=action==='force_one'&&await confirmExclusiveStart(batch,job);
  if(action==='force_one'&&!confirmed)return true;
  try{await api('/api/execution/job-control',{id,index,action,confirmed,risk_acknowledged:confirmed});}finally{await loadExecution();}
  notice(({force_one:'已申请独占运行，可在开始前撤回。',release_force:'已恢复普通排队。',requeue_cancelled:'此算例已在原批次重新排队。'})[action]);return true;
 }
 if(button.dataset.batch){try{await api('/api/execution/control',{id:button.dataset.batch,action:button.dataset.control});}finally{await loadExecution();}notice(button.dataset.control==='resume'?'此批次已继续，待有资源余量后派发；中断项需另行重试。':button.dataset.control==='retry'?'已处理重试请求。可重试的算例将按资源余量派发，已关联补算的原记录保留。':'队列操作已记录。当前计算和已完成结果保留。');return true;}
 if(button.dataset.preparedBatch){await loadExecution();await loadBatchResults(button.dataset.preparedBatch,true);S.executionReview=null;return true;}
 if(button.dataset.batchResults){await loadBatchResults(button.dataset.batchResults,true);return true;}
 switch(button.dataset.action){
 case 'prepare-execution':if(!S.generated||S.dirty)throw new Error('请先保存方案并生成对应版本的模型输入。');await openPreparedInput(S.generated.id);return true;
 case 'submit-execution':{const p=S.executionReview;if(!p)throw new Error('请先准备计算清单。');if(p.existing_batch)throw new Error('此清单已经提交，请查看原批次。');const budget=S.calculationBudget;if(!budget||budget.id!==p.id||budget.plan_sha256!==p.plan_sha256||!budget.storage?.destination)throw Error('请先核对预算与结果保存位置。');const result=await api('/api/execution/submit',{review_id:p.id,plan_sha256:p.plan_sha256,destination:budget.storage.destination});invalidateWorkflowAfterSubmission(p.record_id,p.revision,result.id);S.executionReview=null;await loadExecution();notice(result.startup&&!result.startup.ready?'算例已登记，但后台未启动成功。请到计算队列查看启动诊断；不要重复提交。':result.reused_submission?'此清单已提交过，原批次及其队列状态保持不变。':'已提交后台队列；可以关闭页面，之后回来查看进度。');return true;}
 case 'prepare-independent':{const p=S.executionReview;if(!p?.existing_batch)throw new Error('请先打开原批次的计算清单。');await openPreparedInput(p.bundle_id,p.existing_batch.id,{id:p.record_id,revision:p.revision},p.output_contract);return true;}
 case 'discard-execution-review':{const p=S.executionReview;S.executionReview=null;notice(p?.output_contract==='daily_sensible_reference_v1'?'已收起，清单和批次状态保持。可从“工况 → 准备逐日参考”重新打开。':'已收起，清单仍保留；可从本版本的计算安排重新打开。');return true;}
 case 'save-resources':await api('/api/execution/resources',S.resourceDraft);S.resourcesDirty=false;await loadExecution();notice(resourceEditStatus()+'运行中的算例继续完成。');return true;
 case 'close-execution-results':S.executionResults=null;resetBatchResults();return true;
 case 'wake-execution':{const r=await api('/api/execution/wake',{});await loadExecution();notice(r.ready?'后台已确认运行。已暂停批次请点击“继续此批次”，中断项请重试。':r.error||'后台启动未完成，请查看诊断。');return true;}
 case 'validation-results':resetBatchResults();S.executionResults=await api('/api/execution/validation');return true;
 case 'refresh-execution':await loadExecution();if(S.executionResults){if(S.executionResults.validation)S.executionResults=await api('/api/execution/validation');else await loadBatchResults(S.executionResults.id);}return true;
 }
 return false;
}
setInterval(async()=>{
 if(S.view!=='execution'||S.busy||document.hidden||S.queueResultWindow)return;
 S.executionPollAt=Date.now(); // Keep CPU observations visible even before a batch starts.
 try{await loadExecution();if(S.view!=='execution'||S.busy)return;const a=document.getElementById('execution-status'),b=document.getElementById('execution-batches');if(a&&!a.querySelector('details[open]'))a.innerHTML=executionStatus();updateCpuDetails();updateResourceEditStatus();if(b&&!b.contains(document.activeElement)&&!b.querySelector('details[open]'))b.innerHTML=executionBatches();}catch(error){notice(error.message);}
},4000);
