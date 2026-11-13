/* On-demand reads of existing performance and backup evidence. */
S.performanceHistory=null;S.backupChecks={};
const executionViewBeforeHistory=executionView;
executionView=function(){return executionViewBeforeHistory().replace('<h1>计算队列与设备投入</h1>',
 '<h1>计算队列与设备投入</h1><button data-action="open-performance">查看已有运行实测</button>')+performanceHistoryView();};
function performanceHistoryView(){
 const d=S.performanceHistory;if(!d)return '';
 return `<section class="section" id="performance-history"><div class="row"><h2>已有运行实测</h2><div class="actions"><button data-action="open-performance">刷新实测记录</button><button data-action="close-performance">关闭</button></div></div>
 <p class="muted">核对于 ${esc(d.created)}。整理已有日志，不启动计算或改变设备投入。</p>
 ${!d.batches.length?'<p>尚无计算批次；历史实测保留为空。</p>':d.batches.map(b=>{const m=b.metrics;return `<article class="well"><h3>${esc(b.record_name)} · 版本 ${esc(b.revision)}</h3><p>清单 ${b.selected_cases} 项 · 纳入 ${b.included_cases} 个原始执行 · ${Object.entries(b.excluded).map(([k,v])=>`${esc(jobLabels[k]||'不能核对')} ${v}`).join(' · ')||'无排除项'}</p>
 ${m?`<div class="metrics"><span><strong>${m.peak_parallel}</strong>纳入算例最高并行</span><span><strong>${format(m.average_parallel_when_busy,2)}</strong>运行窗口内平均并行</span><span><strong>${format(m.completed_cases_per_busy_hour,1)}</strong>每运行小时完成算例</span></div>
 <p>运行窗口合计 ${budgetTime(m.busy_seconds)}；首次启动至最后完成 ${budgetTime(m.span_seconds)}，其中记录间空档 ${budgetTime(m.gap_seconds)}。</p>
 <p>这些算例启动时的并行上限：${b.requested_parallel_limits.join(' / ')} 路；单算例实测内存峰值最高 ${format(b.observed_peak_memory_gib,2)} GiB；当前成果保留量合计 ${budgetBytes(b.retained_bytes)}。</p>
 <details><summary>并行分布、算例及依据</summary><p>${m.concurrency_seconds.map(x=>`${x.parallel} 路 ${budgetTime(x.seconds)}`).join('；')}。</p><p class="muted">墙钟跨度折算 ${format(m.completed_cases_per_span_hour,2)} 个/小时，包含记录间空档。单调计时的算例时长合计 ${budgetTime(b.elapsed_seconds)}。两种口径不混用。</p>
 <div class="table-wrap"><table class="table"><thead><tr><th>地点 / 模式</th><th>启动 / 完成</th><th>耗时</th><th>内存峰值</th><th>当前保留量</th></tr></thead><tbody>${b.rows.map(r=>`<tr><td>${esc(r.city)}<small>${esc(modes[r.mode])} · ${r.step_minutes} min</small></td><td>${esc(r.started)}<small>${esc(r.finished)}</small></td><td>${budgetTime(r.elapsed_seconds)}</td><td>${format(r.peak_gib,2)} GiB</td><td>${budgetBytes(r.retained_bytes)}</td></tr>`).join('')}</tbody></table></div></details>`:'<p>没有可核验的已完成执行，不计算吞吐量。</p>'}
 ${b.issues.length?`<details class="warning"><summary>${b.issues.length} 项记录未纳入</summary>${b.issues.map(x=>`<p>${x.index===null?'清单':'第 '+(x.index+1)+' 项'}：${esc(x.reason)}</p>`).join('')}</details>`:''}</article>`;}).join('')}
 <details><summary>统计口径与限制</summary>${d.notes.map(x=>`<p class="muted">${esc(x)}</p>`).join('')}<p class="muted">依据摘要 ${String(d.source_digest||'').match(/.{1,16}/g)?.map(esc).join('<wbr>')||''}</p><a href="/api/performance-history" target="_blank" rel="noopener">完整实测与来源 JSON ↗</a></details></section>`;
}
const storageReportBeforeChecks=storageReportView;
storageReportView=function(){let html=storageReportBeforeChecks();
 for(const b of S.storageReport?.backups||[]){const d=S.backupChecks[b.id];
  const extra=`<div class="well"><button data-check-backup="${esc(b.id)}">重新校验备份包</button>${d?`<p class="${d.passed?'muted':'warning'}">${esc(d.checked_at)} · ${esc(d.message)}${d.passed?' · 已核验 '+d.verified_files+' 个文件':''}</p>`:'<p class="muted">存在不等于当前完整；点击后只读核验整体及逐文件哈希，不创建恢复副本。</p>'}</div>`;
  html=html.replace(`<small>${esc(b.archive)}</small></p>`,`<small>${esc(b.archive)}</small></p>${extra}`);
 }return html;
};
const executionActionBeforeHistory=executionAction;
executionAction=async function(button){
 if(button.dataset.action==='open-performance'){
  S.performanceHistory=null;
  try{S.performanceHistory=await api('/api/performance-history');}
  catch(e){render();throw e;}
  requestAnimationFrame(()=>document.getElementById('performance-history')?.scrollIntoView({block:'start'}));return true;
 }
 if(button.dataset.action==='close-performance'){S.performanceHistory=null;return true;}
 if(button.dataset.checkBackup){
  const id=button.dataset.checkBackup;delete S.backupChecks[id];
  try{S.backupChecks[id]=await api('/api/storage-verify',{id});}
  catch(e){render();throw e;}
  return true;
 }
 const done=await executionActionBeforeHistory(button);
 if(done&&['open-storage','refresh-storage'].includes(button.dataset.action)){
  S.backupChecks={};requestAnimationFrame(()=>document.getElementById('storage-report')?.scrollIntoView({block:'start'}));
 }
 return done;
};
