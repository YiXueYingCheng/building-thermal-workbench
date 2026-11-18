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
 d.addEventListener('input',e=>{const key=e.target.dataset.reviewField;if(key&&resultReviewWindow){resultReviewWindow.decision??={};resultReviewWindow.decision[key]=e.target.value;}});
 return d;
}
function renderReview(){
 const v=resultReviewWindow;if(!v)return;const d=reviewDialog(),j=v.job,r=j?.report,accepted=!!j?.acceptance,running=['queued','running'].includes(j?.state),canAccept=['accept_with_notes','user_decision'].includes(r?.recommendation)&&j?.state==='ready'&&!accepted;
 const manual=r?.recommendation==='user_decision';
 const stage=accepted?3:j?.workflow==='warmup_annual'&&!j.id?0:r?2:running?1:0,labels=['查看情况','检查依据','决定处理','已登记'];
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(v.name)} · 第 ${v.index+1} 个算例</p><h2 id="result-review-title" tabindex="-1">结果复核处理</h2></div><button data-review-action="close"${v.accepting||v.registering?' disabled':''}>返回结果明细</button></header>
 <div class="focused-body"><ol class="review-steps" aria-label="复核进度">${labels.map((s,i)=>`<li${i===stage?' aria-current="step"':''}>${i+1} ${s}</li>`).join('')}</ol>
 <p>计算已经结束。这里检查文件与输出完整性，并记录你对警告及用途的判断；不重新运行建筑模拟。</p>
 ${v.error?`<p class="warning" role="alert">${esc(v.error)}</p>`:''}
 <div role="status" aria-live="polite">${v.registering?'<div class="well"><strong>正在核对并建立复核记录…</strong><p>完成前请稍候；本步骤不采用研究结果。</p></div>':v.pending?'<p>正在读取…</p>':running?`<div class="well"><strong>${esc(j.message)}</strong><p>可以返回结果列表；检查继续进行，稍后从同一入口查看。结果尚未被接受。</p></div>`:accepted?'<div class="well"><strong>已登记为附说明接受</strong><p>原始数值、日志和警告保留；用户审阅与专项复核采用不同标记，可在结果明细查看。</p></div>':j?.state==='error'||j?.state==='interrupted'?`<p class="warning">${esc(j.error||'检查中断，请重新检查。')}</p>`:!r?'<div class="well"><strong>尚未检查复核依据</strong><p>点击下方按钮核对本次输入和完整输出。检查通过后，可自行审阅警告并填写采用说明。</p></div>':''}</div>
 ${r?`<section class="review-conclusion"><h3>${esc(r.title)}</h3><p>${esc(r.explanation)}</p>${reviewAnnualTable(r)}${r.scope?`<h4>适用范围</h4><p>${esc(r.scope)}</p>`:''}<p>${esc(accepted?'结论已登记，可返回结果明细查看或继续进行同条件对照。':r.next_step||'')}</p>${r.checks?.length?`<details><summary>查看 ${r.checks.length} 项检查依据</summary><ul class="review-checks">${r.checks.map(c=>`<li><strong>${esc(c.label)}</strong>${c.detail?`<p class="muted">${esc(c.detail)}</p>`:''}</li>`).join('')}</ul></details>`:''}<details><summary>保留说明</summary><ul>${(r.limits||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details></section>`:''}
 ${accepted&&j.user_decision?reviewUserDecisionMarkup({user_decision:j.user_decision}):''}
 ${r?.pending_warnings?.length?`<section><h3>本次待审阅警告</h3><ul>${r.pending_warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul><details><summary>查看原日志中的警告与上下文</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:22rem;overflow:auto">${esc(r.warning_excerpt||'')}</pre>${r.excerpt_truncated?'<p>摘录较长已截断，完整内容见下载资料中的 eplusout.err。</p>':''}</details><p class="muted">首次提示和末尾汇总可能来自同一事件；上方条目数不等于发生次数。</p></section>`:''}
 ${canAccept&&manual?`<section class="well"><h3>用户审阅后采用</h3><p>程序只确认输出完整，未证明警告无害。请写清自己的判断，说明会随结果保留。</p><label class="field">审阅人（姓名或代号）<input data-review-field="reviewer" maxlength="80" value="${esc(v.decision?.reviewer||'')}"></label><label class="field">采用理由<textarea data-review-field="reason" maxlength="3000" rows="3" placeholder="警告可能影响什么，你据什么判断本次结果可用">${esc(v.decision?.reason||'')}</textarea></label><label class="field">用途范围<textarea data-review-field="scope" maxlength="2000" rows="2" placeholder="例如：本项目一月显热负荷的探索性对比；局限与排除用途">${esc(v.decision?.scope||'')}</textarea></label></section>`:''}
 ${canAccept?'<label class="review-confirm"><input type="checkbox" id="review-confirm"'+(v.confirmed?' checked':'')+(v.accepting||v.registering||v.pending?' disabled':'')+'>我已查看原警告与适用范围，并对本次采用判断负责；原警告继续保留。</label>':''}
 </div><footer class="viewer-foot"><div class="actions">${!running&&!accepted?`<button class="${canAccept?'':'primary'}" data-review-action="check"${v.pending||v.accepting?' disabled':''}>${j?.workflow==='warmup_annual'&&!j.id?(j.assessment_available?'核对并建立复核记录':'刷新诊断依据'):r||j?'重新检查依据':'检查复核依据'}</button>`:''}${canAccept?`<button class="primary" data-review-action="accept"${!v.confirmed||v.accepting?' disabled':''}>${v.accepting?'正在登记…':manual?'登记为用户审阅后采用':'确认采用复核结论'}</button>`:''}${r&&j.id?`<a class="button" download="复核资料.zip" href="/api/result-reviews/${esc(j.id)}/download">下载复核资料</a>`:''}<button data-review-action="close"${v.accepting||v.registering?' disabled':''}>${accepted?'返回结果':running?'稍后回来查看':j?.workflow==='warmup_annual'&&!j.id?'保留未通过，返回':'保持待复核，返回'}</button></div></footer>`;
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
  if(v.job.report?.recommendation==='user_decision'&&!['reviewer','reason','scope'].every(k=>v.decision?.[k]?.trim()))throw Error('请填写审阅人、采用理由和用途范围。');
  v.accepting=true;renderReview();
  try{await api('/api/result-reviews/accept',{id:v.job.id,report_sha256:v.job.report_sha256,confirmed:true,decision:{...(v.decision||{}),acknowledged:v.confirmed}});v.job=await api('/api/result-reviews/'+v.job.id);await loadExecution();if(S.executionResults?.id===v.batch)await loadBatchResults(v.batch);v.error='';render();}
  finally{v.accepting=false;if(resultReviewWindow===v)renderReview();}
 }
}
// Capture inside the existing result dialog, which stops normal bubbling.
document.addEventListener('click',e=>{const b=e.target.closest('[data-open-result-review]');if(!b)return;e.preventDefault();e.stopPropagation();void openReview(b.dataset.openResultReview,Number(b.dataset.reviewIndex),b.dataset.reviewName||'本批结果');},true);

function reviewUserDecisionMarkup(review){const d=review?.user_decision;if(!d)return '';return `<section class="well"><strong>${d.acceptance_mode==='bulk_force'?'用户强制采用':'用户审阅后采用'}</strong><p>审阅人：${esc(d.reviewer)}</p><p>采用理由：${esc(d.reason)}</p><p>用途范围：${esc(d.scope)}</p><p class="muted">平台核对输出完整性，未自动证明警告无害。</p></section>`;}
