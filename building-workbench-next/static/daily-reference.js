/* Read-only next-step preparation. A preview is never a submitted calculation. */
function dailyReferenceDialog(){
 let d=document.querySelector('#daily-reference-dialog');
 if(!d){d=document.createElement('dialog');d.id='daily-reference-dialog';d.className='room-tool calendar-preview-dialog';d.setAttribute('aria-labelledby','daily-reference-title');document.body.append(d);
  d.addEventListener('cancel',()=>{S.dailyReference=null;});
  d.addEventListener('click',e=>{const a=e.target.closest('[data-daily-reference-tool]')?.dataset.dailyReferenceTool;if(!a)return;e.stopPropagation();if(a==='close'){S.dailyReference=null;d.close();return;}
   const m=S.dailyReference;if(a==='download'&&m?.result&&m.key===referenceContext()){const u=URL.createObjectURL(new Blob([JSON.stringify(m.result,null,2)],{type:'application/json;charset=utf-8'})),link=document.createElement('a');link.href=u;link.download='daily-reference-preparation-'+m.result.record.sha256.slice(0,12)+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
  });
 }
 return d;
}
function dailyWorkflowMarkup(w){if(!w)return '';return `<section class="well" id="daily-workflow-status"><div class="row"><h3>${esc(w.label)}</h3><button data-daily-reference="refresh">刷新状态</button></div><p>已准备未提交 ${w.summary.prepared} 份 · 相关批次 ${w.summary.submitted} 个 · 可用逐日参考 ${w.summary.daily_ready} / ${w.summary.sites} 地点</p><p class="muted">${esc(w.note)}</p>
 ${w.preparation_history?.length?`<details><summary>已提交的逐日历史准备（${w.preparation_history.length} 份）</summary>${w.preparation_history.map(p=>`<p>${esc(p.created.replace('T',' '))} · ${esc(p.lifecycle.label)}</p>`).join('')}<p>关联批次和结果状态见下方；查看不会重新提交。</p></details>`:''}${w.preparations.map(p=>`<article class="control"><strong>${p.valid?'已准备清单 · 未提交':'原清单需核对'}</strong><p class="muted">${esc(p.created.replace('T',' '))}</p>${p.valid?`<button data-daily-reference="restore" data-review-id="${esc(p.id)}" ${S.dailyReference?.dirty||S.dailyReference?.freezing?'disabled':''}>恢复清单（不计算）</button>`:`<p class="warning">${esc(p.issue)}</p>`}</article>`).join('')}
 ${w.sites.filter(s=>s.ready).map(s=>`<p><strong>${esc(s.city)}</strong> · 已有可用逐日参考 ${s.downloads.map(d=>`<a href="/api/daily-reference/${encodeURIComponent(d.batch_id)}/${d.index}/daily.csv" download="daily-loads.csv">下载逐日 CSV</a>`).join(' · ')}</p>`).join('')}
 ${w.batches.map(b=>`<article class="control"><strong>${esc(b.label)}</strong><p>${esc(b.record_name)} · v${b.revision}${b.same_saved_version?' · 当前保存版本':' · 输入匹配的原构造参考'}</p><p class="muted">${esc(b.created.replace('T',' '))} · ${Object.entries(b.counts).map(([k,v])=>esc(jobLabels[k]||k)+' '+v).join(' · ')}</p><button data-daily-reference="batch" data-batch-id="${esc(b.id)}">查看批次与结果</button></article>`).join('')}
 ${w.issues.map(i=>`<p class="warning">${esc(i)}</p>`).join('')}<p class="muted">状态截至本次核对；运行中可点击“刷新状态”。</p></section>`;}
function dailyReferenceMarkup(r){const s=r.summary;return `${['queued','running','ready'].includes(S.dailyReference?.job?.state)?'':dailyWorkflowMarkup(r.workflow)}<div class="well"><h3>${r.input_ready?'参考输入核对通过':'参考准备尚有待处理项'}</h3><p>${esc(r.preservation)}</p><p>${esc(r.quantity)}</p><p>${esc(r.retention)}</p></div>${r.issues.map(x=>`<p class="warning">${esc(x)}</p>`).join('')}${s?`<div class="metrics"><span><strong>${s.ready} / ${s.sites}</strong>地点输入可准备</span><span><strong>${s.additional_daily_values.toLocaleString()}</strong>逐日输出数值规模</span><span><strong>${s.building_daily_rows.toLocaleString()}</strong>核对后楼级汇总行数</span></div>`:''}<p class="muted">${esc(r.storage_note)}</p><div class="reference-sites">${r.rows.map(x=>`<details${r.rows.length===1?' open':''}><summary><strong>${esc(x.city)}</strong><span>${x.ready?'输入核对通过':'需处理'}</span></summary>${x.ready?`<p>全年 ${x.days} 天 · ${r.step_minutes} min · ${x.conditioned_systems} 个温控系统。</p><p>每天记录供暖、制冷两项需求：2 × ${x.conditioned_systems} × ${x.days} = ${x.additional_daily_values.toLocaleString()} 条；核对后汇总为建筑每日 ${x.building_daily_rows} 行。</p><p>物理输入保持一致，新增内容仅为结果输出；作息日历和预热设置沿用本方案。</p>`:''}${x.issues.map(i=>`<p class="warning">${esc(i)}</p>`).join('')}</details>`).join('')}</div><details><summary>清单与结果的关系</summary><p>${esc(r.next_step)}</p><p>结果核对会检查每天是否完整、每个房间的逐日/月度/全年需求是否相符。数据核对通过后，还需确认运行日志和警告，才可登记为参考。</p></details>`;}
function renderDailyReference(){const m=S.dailyReference;if(!m)return;const d=dailyReferenceDialog();d.innerHTML=`<div class="room-tool-head"><div><h2 id="daily-reference-title">逐日参考补算准备</h2><span class="muted">${esc(m.label)}${m.dirty?' · 含未保存修改':''}</span></div><button data-daily-reference-tool="close">关闭</button></div><div class="calendar-preview-body"><p role="status">${esc(m.message)}</p><div id="daily-preparation-progress" role="status">${dailyPreparationMarkup(m)}</div>${m.result?dailyReferenceMarkup(m.result):''}</div><div class="calendar-preview-footer"><span class="muted">准备清单 · 不启动计算</span>${m.result?'<button data-daily-reference-tool="download">下载准备清单</button>':''}<button data-daily-reference-tool="close">关闭</button></div>`;if(!d.open)d.showModal();}
async function openDailyReference(){
 if(S.usageDirty)throw Error('房间配置还有独立编辑，请先保存配置或撤销后再准备。');
 const old=document.querySelector('#calendar-library-dialog');if(old?.open){S.calendarLibrary=null;old.close();}
 const m={id:S.id,revision:S.saved.revision,recovering:!S.dirty,key:referenceContext(),label:S.record.name+' · v'+S.saved.revision,dirty:S.dirty,result:null,message:'正在核对原构造参考输入及逐日输出规模…'};S.dailyReference=m;renderDailyReference();
 if(!m.dirty){await recoverDailyPreparation(m);if(!dailyPreparationCurrent(m)||m.recovering||m.freezing||m.prepared)return;}
 try{const result=await api('/api/reference-readiness/daily-preparation',{id:S.id,revision:S.saved.revision,changes:changes()});if(S.dailyReference===m&&m.key===referenceContext()){m.result=result;m.message='已核对输入、已有清单与批次。本次核对未提交计算或修改方案。';}}
 catch(e){if(S.dailyReference===m)m.message=e.message;}
 finally{if(S.dailyReference===m){if(m.key!==referenceContext()){m.result=null;m.message='方案已变化，请关闭后重新准备。';}renderDailyReference();}}
}
const beforeDailyReferenceAction=configurationAction;
configurationAction=async function(b){if(!b.dataset.dailyReference)return beforeDailyReferenceAction(b);const a=b.dataset.dailyReference;if(a==='freeze'){void freezeDailyReference().catch(e=>notice(e.message));return true;}if(a==='prepared'){const m=S.dailyReference;if(m?.prepared&&!S.dirty&&m.key===referenceContext())await showDailyPrepared(m,m.prepared);return true;}if(a==='restore'){await restoreDailyReference(b.dataset.reviewId);return true;}if(a==='batch'){const m=S.dailyReference;if(!m?.result?.workflow?.batches.some(x=>x.id===b.dataset.batchId)||m.key!==referenceContext())throw Error('方案内容已变化，请重新核对。');S.dailyReference=null;dailyReferenceDialog().close();await loadExecution();S.executionReview=null;S.view='execution';await loadBatchResults(b.dataset.batchId,true);return true;}void openDailyReference().catch(e=>notice(e.message));return true;};

const beforeDailyFreezeRender=renderDailyReference;
renderDailyReference=function(){beforeDailyFreezeRender();const m=S.dailyReference,r=m?.result;if(!m)return;const d=dailyReferenceDialog(),footer=d.querySelector('.calendar-preview-footer');
 if(m.prepared){const b=document.createElement('button');b.className='primary';b.dataset.dailyReference='prepared';b.textContent='前往预算与提交';b.disabled=m.dirty||m.key!==referenceContext();footer.querySelector('[data-daily-reference-tool="close"]').before(b);}if(!r)return;
 const w=r.workflow,existing=w&&(w.preparations.length||w.batches.some(x=>x.same_saved_version)||w.state==='available');
 const note=document.createElement('p');note.className='muted';note.textContent=m.dirty?'当前有未保存修改，请先保存方案，再创建或恢复对应版本的参考清单。':w?.state==='available'?'已有匹配且已接受的逐日参考，可直接下载；日历生成与采用另行操作。':existing?'已有清单或批次保留，请使用上方入口继续查看。':r.freeze_issue||'创建清单不启动计算；随后进入统一队列核对预算，再明确提交。';d.querySelector('.calendar-preview-body').append(note);
 if(r.can_freeze&&r.input_ready&&!m.dirty&&!existing&&!m.prepared){const b=document.createElement('button');b.className='primary';b.dataset.dailyReference='freeze';b.textContent=m.freezing?'正在后台准备…':m.job&&['failed','interrupted'].includes(m.job.state)?'核对并继续准备':'创建逐日参考清单（不计算）';b.disabled=!!m.freezing||!!m.recovering;footer.querySelector('[data-daily-reference-tool="close"]').before(b);}
};
async function showDailyPrepared(m,prepared){if(S.dailyReference!==m||m.key!==referenceContext()){notice(prepared.existing_batch?'已找到原批次，未重复提交。':'清单已保留，未提交。重新打开相同版本可恢复。');return;}
 S.dailyReference=null;dailyReferenceDialog().close();await loadExecution();S.executionReview=prepared;S.executionResults=null;resetBatchResults();S.view='execution';await refreshCalculationBudget();notice(prepared.existing_batch?'已找到原逐日参考批次，未重复提交。':'逐日参考清单已保留；收起后可从“准备逐日参考”恢复。');}
async function restoreDailyReference(id){const m=S.dailyReference,p=m?.result?.workflow?.preparations.find(p=>p.id===id&&p.valid);if(!p||m.dirty||S.dirty||m.key!==referenceContext()||m.freezing)throw Error('请先保存并重新核对原清单。');m.freezing=true;renderDailyReference();
 try{await showDailyPrepared(m,await api('/api/reference-readiness/daily-restore',{id:S.id,revision:S.saved.revision,record_sha256:m.result.record.sha256,review_id:p.id,plan_sha256:p.plan_sha256}));}catch(e){if(S.dailyReference===m)m.message=e.message;else notice(e.message);}finally{if(S.dailyReference===m){m.freezing=false;renderDailyReference();}}}
function dailyPreparationMarkup(m){return m.job?inputProgressMarkup(m)+(m.job.error?'<p class="warning">'+esc(m.job.error)+'</p>':'')+'<p class="muted">关闭窗口后准备继续；重新打开相同方案版本可查看进度。准备完成不自动提交计算。</p>':m.recovering?'<p>正在查找本版本的后台准备记录…</p>':'';}
function dailyPreparationCurrent(m){return S.dailyReference===m&&m.key===referenceContext();}
async function pollDailyPreparation(m,job){
 for(;;){m.job=job;m.freezing=['queued','running'].includes(job.state);
  if(!dailyPreparationCurrent(m))return;
  const el=document.getElementById('daily-preparation-progress');if(el)el.innerHTML=dailyPreparationMarkup(m);
  if(!m.freezing){if(job.state==='ready'){m.prepared=job.result;m.message='逐日参考清单准备完成。下一步核对预算，再明确提交计算。';}else m.message='本次准备未完成，成功项已保留，可核对后继续。';renderDailyReference();return;}
  await new Promise(resolve=>setTimeout(resolve,1500));if(!dailyPreparationCurrent(m))return;
  job=await api('/api/input-preparations/'+job.id);
 }
}
async function recoverDailyPreparation(m){
 try{const job=await api('/api/input-preparations/latest?id='+encodeURIComponent(m.id)+'&revision='+m.revision+'&kind=daily');if(!dailyPreparationCurrent(m))return;m.recovering=false;if(job){m.job=job;m.freezing=['queued','running'].includes(job.state);m.message=m.freezing?'已恢复后台准备进度；关闭窗口不会停止准备。':'已读取本版本的准备记录。';renderDailyReference();void pollDailyPreparation(m,job).catch(e=>{if(dailyPreparationCurrent(m)){m.message='后台进度暂未读取：'+e.message+'；可关闭后重新打开查看。';renderDailyReference();}});}}
 catch(e){if(dailyPreparationCurrent(m))m.message='后台准备状态暂未读取：'+e.message+'；可关闭后重新打开查看。';}
 finally{m.recovering=false;if(dailyPreparationCurrent(m))renderDailyReference();}
}
async function freezeDailyReference(){const m=S.dailyReference;if(!m?.result?.can_freeze||!m.result.input_ready||m.dirty||S.dirty||m.key!==referenceContext()||m.freezing||m.recovering)throw Error('请先保存并重新核对全年温控原构造方案。');m.freezing=true;m.message='正在后台生成逐日参考输入与预算清单；不提交计算。';renderDailyReference();
 try{const job=await api('/api/input-preparations',{id:m.id,revision:m.revision,kind:'daily',record_sha256:m.result.record.sha256});await pollDailyPreparation(m,job);}
 catch(e){if(dailyPreparationCurrent(m))m.message=e.message+'；后台状态可重新打开查看。';}
 finally{m.freezing=false;if(dailyPreparationCurrent(m))renderDailyReference();}
}
