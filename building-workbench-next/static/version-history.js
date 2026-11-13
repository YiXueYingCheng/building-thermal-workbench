/* Read-only version navigation. A rename never moves results to a later revision. */
function versionHistoryPanel(){
 const d=S.history;if(!d||d.record_id!==S.saved.id)return '';
 return `<section class="version-history" id="version-history"><div class="row"><h2>保存版本记录</h2><div class="actions"><button data-action="history">刷新记录</button><button data-action="close-version-history">收起记录</button></div></div><p class="muted">${esc(d.note)}</p><p id="version-history-dirty" class="${S.dirty?'warning':'muted'}">${S.dirty?'当前修改尚未保存；版本对照使用保存内容，切换版本前请先保存或撤销。':'可查看旧版，或将某版与当前查看的保存版本逐项对照。'}</p><div class="version-history-list">${d.versions.map(r=>{
  const selected=r.revision===S.saved.revision;
  return `<article class="version-history-card${selected?' selected-version':''}" data-history-row="${esc(r.revision)}"><div class="row"><h3>${esc(planVersionLabel(r))}${r.latest?' · 最新保存':''}${selected?' · 正在查看':''}</h3><small class="muted">${esc(readableTime(r.saved_at))}</small></div><p>${esc(r.name)}</p><p class="version-change">${esc(r.changes.summary)}${!r.changes.first?' · 相对'+esc(planVersionLabel({revision:r.changes.previous_revision})):''}</p><p class="muted">${esc(periodLabel(r.period))} · ${r.step_minutes} min · ${r.site_count} 地点</p>
  <p class="muted">${r.input_count===null?'计算记录暂未能读取':`${r.issues.length?'当前可核对记录：':''}${r.input_count} 个输入包 · ${r.batches.length} 个批次 · ${r.comparison_count} 个比较`}</p>
  ${r.batches?.length?`<ul class="version-batch-list">${r.batches.map(b=>`<li>${esc(b.status)} · ${(b.counts.passed||0)+(b.counts.reused||0)} / ${b.case_count} 项通过${b.counts.review?' · 待复核 '+b.counts.review:''}${b.counts.pending?' · 待算 '+b.counts.pending:''}${b.counts.running?' · 运行 '+b.counts.running:''}</li>`).join('')}</ul>`:''}
  ${r.historical?'<p class="muted">原正式 15 min 历史结果保留在此来源版本。</p>':''}
  ${r.issues.length?`<details><summary class="warning">部分记录未能核对 · ${r.issues.length} 项</summary>${r.issues.map(x=>`<p class="warning">${esc(x)}</p>`).join('')}</details>`:''}
  <div class="actions"><button data-revision="${esc(r.revision)}"${selected||S.dirty?' disabled':''}>${selected?'正在查看':'查看此版与计算记录'}</button><button data-history-compare="${esc(r.revision)}"${selected?' disabled':''}>与当前查看版对照</button></div></article>`;
 }).join('')}</div></section>`;
}
function updateVersionHistoryDirty(){
 const note=document.getElementById('version-history-dirty');if(note){note.className=S.dirty?'warning':'muted';note.textContent=S.dirty?'当前修改尚未保存；版本对照使用保存内容，切换版本前请先保存或撤销。':'可查看旧版，或将某版与当前查看的保存版本逐项对照。';}
 document.querySelectorAll('#version-history [data-revision]').forEach(b=>b.disabled=S.dirty||b.dataset.revision===String(S.saved.revision));
 document.querySelectorAll('[data-history-latest]').forEach(b=>b.disabled=S.dirty);
}
function latestVersionButton(){
 const latest=S.boot.records.find(r=>r.id===S.saved.id);
 return latest&&latest.revision!==S.saved.revision?`<button data-history-latest="${esc(latest.revision)}"${S.dirty?' disabled':''}>返回最新保存版 ${esc(latest.revision)}</button>`:'';
}
async function readVersionHistory(){
 const id=S.saved.id;
 const history=await api('/api/version-history/'+encodeURIComponent(id));
 if(S.saved.id!==id)throw Error('当前方案已切换，请重新查看版本记录。');
 S.history=history;
}
async function navigateHistoryVersion(revision){
 const history=S.history,id=S.saved.id;
 await loadRecord(id,revision);
 if(history?.record_id===id)S.history=history;
}
async function compareHistoryVersion(revision){
 const row=S.history?.versions.find(r=>String(r.revision)===String(revision));
 if(!row||row.revision===S.saved.revision)throw Error('请选择另一个保存版本。');
 const previous={...S};
 try{
  S.left=S.saved.id;S.right=S.saved.id;S.compareVersions={left_revision:row.revision,right_revision:S.saved.revision};
  const natural=S.saved.factors.condition.operation.mode==='natural';
  S.planComparisonDraft={name:S.saved.name+' · '+planVersionLabel(S.saved)+' 对照 '+planVersionLabel(row),metric:natural?'temperature':'total'};
  await loadComparison();
  // Determine the metric from both pinned snapshots, never from an unsaved editor draft.
  if([S.comparison.left,S.comparison.right].some(r=>r.factors.condition.operation.mode==='natural'))S.planComparisonDraft.metric='temperature';
  resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;S.view='compare';
  notice('正在对照两个保存版本，尚未新建比较关系。');
 }catch(error){Object.assign(S,previous);throw error;}
}
async function versionHistoryAction(button){
 const revision=button.dataset.revision;
 if(revision&&button.closest('#version-history')){
  const row=S.history?.versions.find(r=>String(r.revision)===revision);if(!row)throw Error('没有该保存版本，请刷新记录。');
  await navigateHistoryVersion(row.revision);return true;
 }
 if(button.dataset.historyLatest){
  const latest=S.boot.records.find(r=>r.id===S.saved.id);if(!latest)throw Error('没有该方案，请刷新记录。');
  await navigateHistoryVersion(latest.revision);return true;
 }
 if(button.dataset.historyCompare){await compareHistoryVersion(button.dataset.historyCompare);return true;}
 switch(button.dataset.action){
  case 'history':await readVersionHistory();return true;
  case 'close-version-history':S.history=null;return true;
 }
 return false;
}
