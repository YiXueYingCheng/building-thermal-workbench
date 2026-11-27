/* Read-only budget and recovery information; no submission or settings writes. */
S.calculationBudget=null;S.budgetError='';S.storageReport=null;
function budgetBytes(n){return n===null||n===undefined?'暂无依据':n>=2**30?format(n/2**30,2)+' GiB':format(n/2**20,2)+' MiB';}
function budgetTime(n){return n>=3600?format(n/3600,2)+' 小时':format(n/60,1)+' 分钟';}
function budgetRange(r,fn){return r?`${fn(r.min)} ～ ${fn(r.max)}（中位数折算 ${fn(r.median)}）`:'暂无足够的同类实测样本';}
async function refreshCalculationBudget(){
 const p=S.executionReview;S.calculationBudget=null;S.budgetError='';if(!p)return;
 try{const d=await api('/api/calculation-budget',{review_id:p.id,plan_sha256:p.plan_sha256});if(S.executionReview===p)S.calculationBudget=d;}
 catch(e){if(S.executionReview===p)S.budgetError=e.message;}
}
function storageBudgetView(d){
 const s=d.storage;if(!s)return '';
 return `<section class="well" id="storage-budget"><h3>磁盘空间预算</h3>${outputStorageBudget(s)}<div class="metrics"><span><strong>${budgetBytes(s.capacity?.target_free_bytes??d.machine.disk_free_gib*2**30)}</strong>结果位置可用</span><span><strong>${budgetBytes(d.policy.disk_reserve_gib*2**30)}</strong>保留空间</span><span><strong>${budgetBytes(s.available_after_reserve_bytes)}</strong>扣除保留后的余量</span></div>
 <p>本清单已准备输入占用：${budgetBytes(s.prepared_bytes)}，已包含在当前磁盘占用中。</p><p>新增执行模型副本：${budgetBytes(s.execution_model_copy_bytes)}。这里只计模型文件，输出与日志另计。</p>
 <p><strong>预计新增成果保留量：</strong>${budgetRange(d.additional_retained_bytes,budgetBytes)}。</p><p><strong>历史采样空间参考：</strong>${budgetRange(s.historical_peak_allocation_bytes,budgetBytes)}。</p>
 ${s.historical_peak_allocation_bytes&&s.historical_peak_allocation_bytes.max>s.available_after_reserve_bytes?'<p class="warning">历史采样空间参考的上沿超过扣除保留后的余量；请缩小批次或另行安排存储。</p>':''}
 ${s.unknown_peak_cases?`<p class="muted">${s.unknown_peak_cases} 个需算任务缺少足够的同类完整采样；当前不能给出整批运行空间预测。</p>`:''}
 ${s.observations.length?`<h4>本清单的实际运行采样</h4>${s.observations.map(x=>`<p>${esc(x.city)} · ${esc(jobLabels[x.status]||x.status)}：采样最大 ${budgetBytes(x.peak_bytes)}，最近一次 ${budgetBytes(x.last_bytes)}；${x.finalized?'采样已结束':'观测中'}${x.adequate?'':'，覆盖情况待核对'}。</p>`).join('')}`:'<p class="muted">本清单尚无运行采样；开始计算后自动记录，刷新预算可查看。</p>'}
 <p class="muted">采样参考按各算例目录的历史采样最大值合计，包含需保留的结束目录；不等于同时运行峰值，也不保证捕获瞬时最高占用。</p>
 ${d.groups.some(g=>g.observed_peak_range)?`<details><summary>同类已完成样本</summary>${d.groups.filter(g=>g.observed_peak_range).map(g=>`<p>${esc(modes[g.mode])} · ${g.disk_sample_count} 个合格采样：${budgetRange(g.observed_peak_range,budgetBytes)}${g.disk_sample_count<3?'；样本不足，仅展示实测参考':''}。</p>`).join('')}</details>`:''}
 ${s.excluded_disk_observations?`<p class="muted">${s.excluded_disk_observations} 份采样记录未通过核对，未用于估算。</p>`:''}</section>`;
}
function calculationBudgetView(p=S.executionReview,d=S.calculationBudget,standalone=false){
 const head='<div class="row"><h3>整批计算预算</h3>'+(standalone?'':'<button data-action="refresh-calculation-budget">刷新预算</button>')+'</div>';
 if(!d||d.id!==p.id||d.plan_sha256!==p.plan_sha256)return `<div id="calculation-budget" class="well">${head}<p class="warning">${esc(S.budgetError||'预算尚未核对。刷新预算仅检查已有文件。')}</p></div>`;
 const policyChanged=!standalone&&S.execution&&JSON.stringify(S.execution.resources)!==JSON.stringify(d.policy);
 return `<div id="calculation-budget" class="well">${head}<p class="muted">核对于 ${esc(d.created)}${p.existing_batch?' · 原批次保持现状；以下按此输入再次提交估算':''}</p>
 <div class="metrics"><span><strong>${d.reusable}</strong>已核验可复用</span><span><strong>${d.needs_compute}</strong>仍需计算</span><span><strong>${d.invalid_cache}</strong>缓存未通过核验</span></div>
 <p>串行算例耗时合计：${budgetRange(d.serial_seconds,budgetTime)}。</p>
 <p>按并行上限 ${d.assumed_parallel} 路均分的理想耗时：${budgetRange(d.ideal_parallel_seconds,budgetTime)}。</p><p class="muted">资源等待会延长实际耗时。</p>${d.cpu?.enabled?cpuBudgetMarkup(d.cpu):''}
 ${storageBudgetView(d)||`<p>预计新增保留量：${budgetRange(d.additional_retained_bytes,budgetBytes)}；运行期间新增磁盘峰值：${d.peak_extra_bytes===null?'尚无实测记录':budgetBytes(d.peak_extra_bytes)}。</p>`}
 <p class="muted">工作区可用 ${budgetBytes(d.machine.disk_free_gib*2**30)}，磁盘保留线 ${d.policy.disk_reserve_gib} GiB；当前保留内存 ${d.policy.reserve_gib} GiB，最多 ${d.policy.max_parallel} 路。${standalone?'':'设备投入在本页上方统一调整。'}${policyChanged?'设置已变化，请刷新预算。':''}${!standalone&&S.resourcesDirty?'尚未应用的设备投入不计入预算。':''}</p>
 ${d.additional_retained_bytes&&d.additional_retained_bytes.max>(d.storage?.available_after_reserve_bytes??(d.machine.disk_free_gib-d.policy.disk_reserve_gib)*2**30)?'<p class="warning">按历史保留量上沿估算，剩余磁盘不足以覆盖整批；请缩小批次或另行安排存储。</p>':''}
 ${d.unknown_estimate_cases?`<p class="muted">${d.unknown_estimate_cases} 个需算任务不足 3 个同类实测，整批耗时与保留量暂不外推。</p>`:''}
 <details><summary>估算依据与逐项复用核对</summary><p>${esc(d.basis)}</p>${d.limits.map(x=>`<p class="muted">${esc(x)}</p>`).join('')}
 <p>当前队列运行 ${d.queue_running}、等待 ${d.queue_pending}；预算不会改变队列。</p>
 ${d.groups.map(g=>`<p>${esc(modes[g.mode])} · ${g.step_minutes} min · ${g.period.join('/')}：${g.total} 个任务，同类实测 ${g.sample_count} 个。</p>`).join('')}
 <div class="table-wrap"><table class="table"><thead><tr><th>地点</th><th>模式</th><th>核对结果</th></tr></thead><tbody>${d.cases.map(c=>`<tr><td>${esc(c.city)}</td><td>${esc(modes[c.mode])}</td><td>${esc(c.reason)}</td></tr>`).join('')}</tbody></table></div></details></div>`;
}
const executionReviewBeforeBudget=executionReview;
executionReview=function(){const html=executionReviewBeforeBudget();return S.executionReview?html.replace("<div class=\"actions\">",calculationBudgetView()+"<div class=\"actions\">"):html;};
const openPreparedInputBeforeBudget=openPreparedInput;
openPreparedInput=async function(...args){await openPreparedInputBeforeBudget(...args);await refreshCalculationBudget();};
const executionActionBeforeBudget=executionAction;
executionAction=async function(button){
 if(button.dataset.action==='refresh-calculation-budget'){await refreshCalculationBudget();return true;}
 if(button.dataset.action==='open-storage'||button.dataset.action==='refresh-storage'){S.storageReport=await api('/api/storage-status');return true;}
 if(button.dataset.action==='close-storage'){S.storageReport=null;return true;}
 const done=await executionActionBeforeBudget(button);
 if(done&&button.dataset.action==='save-resources'&&S.executionReview)await refreshCalculationBudget();
 return done;
};
function storageReportView(){
 const r=S.storageReport;if(!r)return '';
 const labels={available_unverified:'可访问，未重算哈希',matches:'哈希一致',unavailable:'不可访问',directory_unexpanded:'目录存在，未展开',observed_only:'仅记录当前哈希',historical_hash_differs:'与部分历史哈希不同',changed_during_read:'读取期间变化'};
 return `<section class="section" id="storage-report"><div class="row"><h2>存储与恢复</h2><div class="actions"><button data-action="refresh-storage">刷新清单</button><button data-action="close-storage">关闭</button></div></div><p class="muted">${esc(r.created)} · 查看不会备份、迁移或清理文件。</p>
 <div class="metrics"><span><strong>${budgetBytes(r.local_bytes)}</strong>本地待保护内容</span><span><strong>${r.local_files}</strong>文件</span><span><strong>${budgetBytes(r.disk_free_bytes)}</strong>工作区磁盘可用</span></div><p>${esc(r.coverage)}</p>
 <details><summary>各部分占用与外置依赖</summary>${Object.entries(r.groups).map(([k,v])=>`<p>${esc(k)}：${budgetBytes(v.bytes)} · ${v.files} 个文件</p>`).join('')}
 <p>外置依赖状态：${Object.entries(r.dependency_status).map(([s,n])=>`${esc(labels[s]||s)} ${n}`).join('；')}。本页检查可访问性，备份时另做哈希核对；历史来源变化与当前计算输入核验分别记录。</p>
 <div class="table-wrap"><table class="table"><thead><tr><th>登记位置 / 实际位置</th><th>状态</th><th>大小</th></tr></thead><tbody>${r.dependencies.map(x=>`<tr><td>${esc(x.path)}${x.resolved_path!==x.path?'<small>'+esc(x.resolved_path||'未找到')+'</small>':''}</td><td>${esc(labels[x.status]||x.status)}</td><td>${budgetBytes(x.bytes)}</td></tr>`).join('')}</tbody></table></div><p>未展开的链接：${esc(r.links_not_followed.join('；')||'无')}。</p></details>
 <h3>本地备份与隔离恢复</h3>${r.backups.length?r.backups.map(b=>`<p>${esc(b.created)} · ${esc(b.version)} · ${b.files} 个文件 · ${budgetBytes(b.bytes)} · ${b.archive_available?'备份包存在':'备份包不可访问'}<small>${esc(b.archive)}</small></p>`).join(''):'<p>当前尚无完成的工作区备份。</p>'}
 ${r.drills.map(d=>`<p>恢复演练：${d.passed?'文件及数据库核验通过':'待核对'} · ${d.restored_files} 个文件 · ${esc(d.created)}<small>${esc(d.target)}</small></p>`).join('')}
 <p class="muted">本地备份与原件同盘，不能覆盖磁盘损坏。外置依赖不在包内；恢复副本禁用调度，绝对路径尚未迁移。完整异盘灾备需另定目的地与外置资料范围。</p>
 <p><a href="/api/workspace-docs/recovery" target="_blank" rel="noopener">备份与恢复操作说明 ↗</a></p></section>`;
}
const guideViewBeforeRecovery=guideView;
guideView=function(){return guideViewBeforeRecovery().replace('<h2>常用入口</h2>','<h2>常用入口</h2><div class="actions"><button data-action="open-storage">查看存储与恢复</button></div>')+storageReportView();};
