/* Saved-version navigation only. Every calculation still uses the explicit queue submission. */
S.planActivity=null;S.planActivityError='';
let planActivityEpoch=0,planActivityFlight=null;
async function loadPlanActivity(){
 const key=JSON.stringify([S.saved.id,S.saved.revision]);if(planActivityFlight?.key===key)return planActivityFlight.promise;
 const flight={key};flight.promise=readPlanActivity();planActivityFlight=flight;try{return await flight.promise;}finally{if(planActivityFlight===flight)planActivityFlight=null;}
}
async function readPlanActivity(){
 const epoch=++planActivityEpoch,id=S.saved.id,revision=S.saved.revision;
 S.planActivity=null;S.planActivityError='';
 try{
  const d=await api('/api/plan-activity/'+encodeURIComponent(id)+'?revision='+encodeURIComponent(revision));
  if(epoch===planActivityEpoch&&S.saved.id===id&&S.saved.revision===revision)S.planActivity=d;
 }catch(error){if(epoch===planActivityEpoch)S.planActivityError=error.message;}
 if(epoch===planActivityEpoch&&S.saved.id===id&&S.saved.revision===revision){const el=document.getElementById('plan-activity');if(el)el.outerHTML=planActivityView();}
}
function activityDirtyText(){return S.dirty?'你有未保存修改；以下计算与结果属于当前已保存版本。':'以下仅列出当前保存版本的记录。查看结果时会继续核验结果文件。';}
function updateActivityDirtyStatus(){document.querySelectorAll('[data-prepare-input]').forEach(b=>b.disabled=S.dirty);const el=document.getElementById('activity-version-note');if(el){el.textContent=activityDirtyText();el.className=S.dirty?'warning':'muted';}}
function activityBatchState(b){
 const c=b.counts;
 if(c.running)return b.mode==='pause'?'当前算例完成后暂停':'计算中';
 if(c.pending)return b.mode==='pause'?'已暂停，有排队项':'有排队项';
 if(c.failed||c.interrupted)return '有失败或中断项';
 if(c.review)return '计算结束，有待复核项';
 if(c.cancelled)return '批次结束，含取消项';
 return '已完成';
}
function planActivityView(){
 const d=S.planActivity;
 const title=`<div class="row"><h2>本版本的计算与结果</h2><button data-action="refresh-plan-activity">刷新记录</button></div><p id="activity-version-note" class="${S.dirty?'warning':'muted'}">${esc(activityDirtyText())}</p>`;
 if(!d)return `<section class="section plan-activity" id="plan-activity">${title}<p class="${S.planActivityError?'warning':'muted'}">${esc(S.planActivityError||'正在读取本版本记录…')}</p></section>`;
 return `<section class="section plan-activity" id="plan-activity">${title}<p class="muted">${esc(planVersionLabel(d))} · 更新于 ${esc(readableTime(d.created))}</p>
 <div class="metrics"><span><strong>${d.inputs.length}</strong>已有输入包</span><span><strong>${d.batches.length}</strong>计算批次</span><span><strong>${d.comparisons.length}</strong>比较关系</span></div>
 ${d.issues.length?`<div class="warning"><p>部分记录未能核对，列表可能不完整。</p><details><summary>查看原因</summary>${d.issues.map(x=>`<p>${esc(x)}</p>`).join('')}</details></div>`:''}
 ${d.inputs.length?`<details class="activity-inputs"><summary>查看已保存输入包</summary><p class="muted">输入包已绑定此版本；准备计算时仍会核对模型与依赖文件。</p>${d.inputs.map(x=>`<div class="line"><span>${x.case_count} 个输入 · ${esc(readableTime(x.created))}</span><div class="actions"><button data-inspect-input="${esc(x.id)}">查看输入与变化</button><button data-prepare-input="${esc(x.id)}"${S.dirty?' disabled':''}>预算与计算清单</button><a href="/api/model-inputs/${esc(x.id)}/manifest.json" target="_blank" rel="noopener">输入清单 ↗</a></div></div>`).join('')}</details>`:''}
 ${d.batches.length?`<h3>计算批次</h3><div class="activity-list">${d.batches.map(b=>`<article class="well"><div class="row"><strong>${esc(activityBatchState(b))} · ${b.case_count} 个算例</strong><span class="muted">${esc(readableTime(b.created))}</span></div><p>${esc(batchCountSummary(b.counts))}</p><div class="actions"><button data-activity-batch="${esc(b.id)}">查看计算结果</button><button data-activity-queue="${esc(b.id)}">前往本批进度</button></div></article>`).join('')}</div>`:`<p class="muted">${d.issues.length?'当前可核对记录中尚无此版本的批次。':d.inputs.length?'本版本已生成输入，尚未提交计算批次。':'本版本尚无新工作区计算批次。可先预览计算安排，再生成模型输入。'}</p>`}
 ${d.comparisons.length?`<h3>已绑定的比较关系</h3><div class="activity-list">${d.comparisons.map(c=>`<article class="well"><strong>${esc(c.name)}</strong><p class="muted">${esc(c.names.left)}（${esc(planVersionLabel(c.left))}） → ${esc(c.names.right)}（${esc(planVersionLabel(c.right))}）</p><div class="actions"><button data-activity-comparison="${esc(c.id)}">查看版本差异</button><button data-activity-comparison-result="${esc(c.id)}">查看配对结果与地图</button></div></article>`).join('')}</div>`:'<p class="muted">此版本尚未绑定比较关系，可在“对照总览”中选择双方版本并保存。</p>'}
 ${d.historical?'<div class="well"><p>原来源版本另有正式 15 min 历史结果，继续保留在历史区。</p><button data-action="activity-history">查看原正式历史结果</button></div>':''}
 ${d.other_versions.length?`<details${!d.batches.length?' open':''}><summary>其他版本有输入或计算记录</summary><p class="muted">已有计算保留在原保存版本，可切换查看。</p><div class="actions"><button data-action="history">查看各版本变更与计算记录</button>${d.other_versions.map(h=>`<button data-activity-revision="${esc(h.revision)}">查看${esc(planVersionLabel(h))}</button>`).join('')}</div></details>`:''}
 </section>`;
}
function activityComparison(id){const c=S.planActivity?.comparisons.find(c=>c.id===id);if(!c)throw Error('该比较不属于当前保存版本，请刷新记录。');return c;}
async function openActivityComparison(id){
 const c=activityComparison(id);
 S.left=c.left.id;S.right=c.right.id;S.compareVersions={left_revision:c.left.revision,right_revision:c.right.revision};S.planComparisonDraft={name:c.name,metric:c.metric};
 await loadComparison();S.view='compare';
 // Any existing result panel belongs to its own explicit comparison, not this new selection.
 resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;
}
async function planActivityAction(button){
 if(button.dataset.prepareInput){if(!S.planActivity?.inputs.some(x=>x.id===button.dataset.prepareInput))throw new Error('输入包不属于当前保存版本，请刷新记录。');await openPreparedInput(button.dataset.prepareInput);return true;}
 if(button.dataset.activityRevision){const h=S.planActivity.other_versions.find(x=>String(x.revision)===button.dataset.activityRevision);if(!h)throw Error('该版本未登记。');await navigateHistoryVersion(h.revision);return true;}
 const batch=button.dataset.activityBatch||button.dataset.activityQueue;
 if(batch){
  if(!S.planActivity?.batches.some(b=>b.id===batch))throw Error('该批次不属于当前保存版本，请刷新记录。');
  await loadExecution();
  if(button.dataset.activityBatch)await loadBatchResults(batch,true);
  else{S.executionResults=null;resetBatchResults();}
  S.view='execution';return true;
 }
 const comparison=button.dataset.activityComparison||button.dataset.activityComparisonResult;
 if(comparison){
  const previous={...S};
  try{await openActivityComparison(comparison);if(button.dataset.activityComparisonResult)await comparisonResultAction({dataset:{comparisonResults:comparison}});return true;}
  catch(error){Object.assign(S,previous);throw error;}
 }
 switch(button.dataset.action){
  case 'refresh-plan-activity':await loadPlanActivity();return true;
  case 'activity-history':S.results=await api('/api/results');S.view='results';return true;
 }
 return false;
}

async function openPreparedInput(id,separateFrom=null,binding=null,outputContract='monthly_period_v1'){
 if(S.dirty)throw new Error('当前方案有未保存修改；请先保存或撤销，再准备计算。');
 notice('正在核对已有输入与计算清单…');
 const prepared=await api('/api/execution/prepare',{bundle_id:id,output_contract:outputContract,record:binding||{id:S.saved.id,revision:S.saved.revision},...(separateFrom?{separate_from:separateFrom}:{})});
 await loadExecution();S.executionReview=prepared;S.executionResults=null;resetBatchResults();S.view='execution';
 notice(prepared.existing_batch?'已找到原批次，没有重新排队。':prepared.preparation_reused?'已恢复原清单，尚未提交计算。':'计算清单已准备，尚未提交计算。');
}
