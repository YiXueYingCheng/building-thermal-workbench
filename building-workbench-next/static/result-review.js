/* A review checks evidence; acceptance is an explicit, separately bound action. */
let resultReviewWindow=null;
function reviewAnnualTable(report){
 const rows=report?.annual_sensitivity;if(!rows?.length)return '';
 return `<section><h4>年度初始化敏感性 / kWh</h4><div class="table-wrap" tabindex="0"><table class="table batch-detail-table"><thead><tr><th>需求</th><th class="num">原计算</th><th class="num">隔离对照</th><th class="num">变化</th></tr></thead><tbody>${rows.map(r=>`<tr><th>${esc(r.label)}</th><td class="num">${format(r.original_kWh,3)}</td><td class="num">${format(r.comparison_kWh,3)}</td><td class="num">${format(r.delta_kWh,3)}</td></tr>`).join('')}</tbody></table></div>${report.sensitivity_note?`<p class="warning">${esc(report.sensitivity_note)}</p>`:''}</section>`;
}
function reviewDialog(){
 let d=document.getElementById('result-review-dialog');if(d)return d;
 d=document.createElement('dialog');d.id='result-review-dialog';d.setAttribute('aria-labelledby','result-review-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeReview();});
 d.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();if(!b.disabled)void reviewButton(b).catch(x=>{if(resultReviewWindow){resultReviewWindow.error=x.message;resultReviewWindow.pending=false;renderReview();}});});
 d.addEventListener('change',e=>{if(e.target.id==='review-confirm'&&resultReviewWindow){resultReviewWindow.confirmed=e.target.checked;d.querySelector('[data-review-action="accept"]').disabled=!e.target.checked;}});
 return d;
}
function renderReview(){
 const v=resultReviewWindow;if(!v)return;const d=reviewDialog(),j=v.job,r=j?.report,accepted=!!j?.acceptance,running=['queued','running'].includes(j?.state),canAccept=r?.recommendation==='accept_with_notes'&&j?.state==='ready'&&!accepted;
 const stage=accepted?3:j?.workflow==='warmup_annual'&&!j.id?0:r?2:running?1:0,labels=['查看情况','检查依据','决定处理','已登记'];
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(v.name)} · 第 ${v.index+1} 个算例</p><h2 id="result-review-title" tabindex="-1">结果复核处理</h2></div><button data-review-action="close"${v.accepting||v.registering?' disabled':''}>返回结果明细</button></header>
 <div class="focused-body"><ol class="review-steps" aria-label="复核进度">${labels.map((s,i)=>`<li${i===stage?' aria-current="step"':''}>${i+1} ${s}</li>`).join('')}</ol>
 <p>计算已经结束。这里核查警告对本次研究结果的影响，不重新运行建筑模拟。</p>
 ${v.error?`<p class="warning" role="alert">${esc(v.error)}</p>`:''}
 <div role="status" aria-live="polite">${v.registering?'<div class="well"><strong>正在核对并建立复核记录…</strong><p>完成前请稍候；本步骤不采用研究结果。</p></div>':v.pending?'<p>正在读取…</p>':running?`<div class="well"><strong>${esc(j.message)}</strong><p>可以返回结果列表；检查继续进行，稍后从同一入口查看。结果尚未被接受。</p></div>`:accepted?'<div class="well"><strong>已登记为附说明接受</strong><p>原始数值、日志和警告保留；结果与参考可用性已更新。</p></div>':j?.state==='error'||j?.state==='interrupted'?`<p class="warning">${esc(j.error||'检查中断，请重新检查。')}</p>`:!r?'<div class="well"><strong>尚未检查复核依据</strong><p>点击下方按钮核对本次输入、结果和已接通的诊断方法。证据不足时仍保持待复核。</p></div>':''}</div>
 ${r?`<section class="review-conclusion"><h3>${esc(r.title)}</h3><p>${esc(r.explanation)}</p>${reviewAnnualTable(r)}${r.scope?`<h4>适用范围</h4><p>${esc(r.scope)}</p>`:''}<p>${esc(accepted?'结论已登记，可返回结果明细查看或继续进行同条件对照。':r.next_step||'')}</p>${r.checks?.length?`<details><summary>查看 ${r.checks.length} 项检查依据</summary><ul class="review-checks">${r.checks.map(c=>`<li><strong>${esc(c.label)}</strong>${c.detail?`<p class="muted">${esc(c.detail)}</p>`:''}</li>`).join('')}</ul></details>`:''}<details><summary>保留说明</summary><ul>${(r.limits||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details></section>`:''}
 ${canAccept?'<label class="review-confirm"><input type="checkbox" id="review-confirm"'+(v.confirmed?' checked':'')+(v.accepting||v.registering||v.pending?' disabled':'')+'>我已查看本次结论及适用范围，采用“附说明接受”。</label>':''}
 </div><footer class="viewer-foot"><div class="actions">${!running&&!accepted?`<button class="${canAccept?'':'primary'}" data-review-action="check"${v.pending||v.accepting?' disabled':''}>${j?.workflow==='warmup_annual'&&!j.id?(j.assessment_available?'核对并建立复核记录':'刷新诊断依据'):r||j?'重新检查依据':'检查复核依据'}</button>`:''}${canAccept?`<button class="primary" data-review-action="accept"${!v.confirmed||v.accepting?' disabled':''}>${v.accepting?'正在登记…':'确认采用复核结论'}</button>`:''}${r&&j.id?`<a class="button" download="复核资料.zip" href="/api/result-reviews/${esc(j.id)}/download">下载复核资料</a>`:''}<button data-review-action="close"${v.accepting||v.registering?' disabled':''}>${accepted?'返回结果':running?'稍后回来查看':j?.workflow==='warmup_annual'&&!j.id?'保留未通过，返回':'保持待复核，返回'}</button></div></footer>`;
 if(!d.open)d.showModal();
}
function closeReview(){const v=resultReviewWindow;if(!v||v.accepting||v.registering)return;clearTimeout(v.timer);resultReviewWindow=null;reviewDialog().close();reviewDialog().replaceChildren();if(S.resultViewer)renderResultViewer();}
async function pollReview(v){
 if(resultReviewWindow!==v||!v.job||!['queued','running'].includes(v.job.state))return;
 try{const job=await api('/api/result-reviews/'+v.job.id);if(resultReviewWindow!==v)return;v.job=job;renderReview();if(['queued','running'].includes(job.state))v.timer=setTimeout(()=>pollReview(v),1200);}
 catch(e){if(resultReviewWindow===v){v.error=e.message;renderReview();}}
}
async function openReview(batch,index,name){
 const v={batch,index,name,job:null,pending:true,confirmed:false};resultReviewWindow=v;renderReview();
 try{const job=await api('/api/result-review?batch='+encodeURIComponent(batch)+'&index='+index);if(resultReviewWindow!==v)return;v.job=job;v.pending=false;renderReview();void pollReview(v);}
 catch(e){if(resultReviewWindow===v){v.pending=false;v.error=e.message;renderReview();}}
}
async function reviewButton(b){
 const v=resultReviewWindow;if(!v)return;const op=b.dataset.reviewAction;
 if(op==='close'){closeReview();return;}if(v.pending||v.accepting)return;
 if(op==='check'){
  v.pending=true;v.registering=v.job?.workflow==='warmup_annual'&&!v.job.id&&v.job.assessment_available;v.error='';v.confirmed=false;renderReview();
  try{const job=await api('/api/result-reviews',{batch:v.batch,index:v.index,force:!!v.job});if(resultReviewWindow!==v)return;v.job=job;
   if(v.registering&&job?.id){await loadExecution();if(S.executionResults?.id===v.batch)await loadBatchResults(v.batch);render();}
  }finally{v.pending=false;v.registering=false;if(resultReviewWindow===v)renderReview();}
  void pollReview(v);
 }
 if(op==='accept'){
  if(!v.confirmed||!v.job?.report_sha256)throw Error('请先查看并确认本次结论。');
  v.accepting=true;renderReview();
  try{await api('/api/result-reviews/accept',{id:v.job.id,report_sha256:v.job.report_sha256,confirmed:true});v.job=await api('/api/result-reviews/'+v.job.id);await loadExecution();if(S.executionResults?.id===v.batch)await loadBatchResults(v.batch);v.error='';render();}
  finally{v.accepting=false;if(resultReviewWindow===v)renderReview();}
 }
}
// Capture inside the existing result dialog, which stops normal bubbling.
document.addEventListener('click',e=>{const b=e.target.closest('[data-open-result-review]');if(!b)return;e.preventDefault();e.stopPropagation();void openReview(b.dataset.openResultReview,Number(b.dataset.reviewIndex),b.dataset.reviewName||'本批结果');},true);
