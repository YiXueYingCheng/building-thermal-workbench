/* Input preparation stays with its saved version; closing a reader never submits a run. */
const inputFlowJobs=new Map();
function inputProgressMarkup(m){
 const j=m.job;if(!j)return m.pending?'<p>准备中；首个算例完成后显示实测估时。</p>':'';
 const seconds=n=>n<60?Math.ceil(n)+' 秒':Math.ceil(n/60)+' 分钟';
 const eta=j.remaining_range_seconds;
 return `<p>${esc(j.stage)} · ${j.completed||0} / ${j.total} 算例${j.city?' · '+esc(j.city):''}</p><progress max="${j.total||1}" value="${j.completed||0}" aria-label="输入准备进度"></progress><p>已用 ${seconds(j.elapsed_seconds||0)}${j.state==='running'&&eta?' · 预计剩余 '+seconds(eta[0])+'—'+seconds(eta[1])+'（按已完成算例估算，包含波动）':j.state==='running'?' · 首个算例完成后估算剩余时间':''}${j.resumed?' · 已核对续接 '+j.resumed+' 项':''}</p>`;
}
async function pollInputPreparation(m,job){
 for(;;){const previous=m.job?.id;m.job=job;if(previous!==job.id&&inputFlowWindow?.model===m)renderInputFlow();const p=inputFlowWindow?.model===m?document.getElementById('input-flow-progress'):null;if(p)p.innerHTML=inputProgressMarkup(m);
  if(!['queued','running'].includes(job.state))break;
  await new Promise(resolve=>setTimeout(resolve,1500));job=await api('/api/input-preparations/'+job.id);
 }
 if(job.state!=='ready')throw Error(job.error||'输入准备未完成；成功项保留，可重试续接。');
 return job.result;
}
async function recoverInputFlow(m){
 try{
  const job=await api('/api/input-preparations/latest?id='+encodeURIComponent(m.id)+'&revision='+m.revision);if(!job)return;
  m.job=job;
  if(job.kind==='prepare'&&!m.generated)m.generated=await api('/api/model-inputs/'+job.bundle_id+'/manifest.json');
  if(['queued','running'].includes(job.state))await inputFlowTask(m,'正在继续读取后台输入准备进度…',async()=>{const result=await pollInputPreparation(m,job);if(job.kind==='prepare'){m.prepared=result;m.outputContract=result.output_contract;}else m.generated=result;m.message='输入准备完成；尚未提交计算。';});
  else if(job.state==='ready'){if(job.kind==='prepare'){m.prepared=job.result;m.outputContract=job.result.output_contract;}else m.generated=job.result;m.message=job.lifecycle?.label||'已恢复本版本的输入记录；提交与结果状态见方案流程。';}
  else m.error=job.error||'上次输入准备未完成；完成项保留，可重试续接。';
  renderInputFlow();
 }catch(e){m.error=e.message;renderInputFlow();}
}
let inputFlowWindow=null;
const inputFlowInspectionMarkup=inputInspectionView;
planningPanel=()=>'';
inputInspectionView=()=>'';
function inputFlowIdentity(){return JSON.stringify([S.saved.id,S.saved.revision]);}
function inputFlowState(){
 const key=inputFlowIdentity();let m=inputFlowJobs.get(key);
 if(!m){m={key,id:S.saved.id,revision:S.saved.revision,name:S.saved.name,preview:null,previewKey:null,generated:S.dirty?null:S.generated,inspection:null,prepared:null,pending:false,error:'',message:''};inputFlowJobs.set(key,m);}
 return m;
}
function inputFlowCurrent(m){return m.key===inputFlowIdentity()&&S.view===(inputFlowWindow?.model===m?inputFlowWindow.originView:'editor');}
function inputFlowDialog(){
 let d=document.getElementById('input-workflow-dialog');if(d)return d;
 d=document.createElement('dialog');d.id='input-workflow-dialog';d.setAttribute('aria-labelledby','input-workflow-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeInputFlow();});
 d.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();if(b.disabled)return;void inputFlowButton(b).catch(x=>{const m=inputFlowWindow?.model;if(m){m.error=x.message;renderInputFlow();}});});
 return d;
}
function closeInputFlow(){const v=inputFlowWindow;if(!v)return;inputFlowWindow=null;inputFlowDialog().close();S.planningOpen=false;requestAnimationFrame(()=>{scrollTo({top:v.y,behavior:'instant'});document.querySelector('[data-action="preview"]')?.focus({preventScroll:true});});}
function openInputFlow(autoPreview=true){
 const m=inputFlowState();if(!inputFlowWindow)inputFlowWindow={model:m,y:scrollY,detail:false,originView:S.view};else inputFlowWindow.model=m;
 S.planningOpen=true;renderInputFlow();
 if(!m.checkedJob){m.checkedJob=true;m.recovering=true;renderInputFlow();void recoverInputFlow(m).finally(()=>{m.recovering=false;renderInputFlow();if(autoPreview&&!m.generated&&!m.pending&&m.previewKey!==capabilityKey())void readInputFlowPreview(m);});}
 else if(autoPreview&&!m.generated&&!m.pending&&m.previewKey!==capabilityKey())void readInputFlowPreview(m);
 return m;
}
async function inputFlowTask(m,message,work){
 if(m.pending)return;
 m.pending=true;m.error='';m.message=message;renderInputFlow();
 try{await work();}catch(e){m.error=e.message;m.message='操作未完成，可重试；没有提交计算。';}
 finally{m.pending=false;renderInputFlow();if(inputFlowCurrent(m))void loadPlanActivity();}
}
async function readInputFlowPreview(m){
 const key=capabilityKey(),payload=copy({id:S.id,revision:S.saved.revision,changes:changes()});
 await inputFlowTask(m,'正在核对本版本的地点与计算设置…',async()=>{const p=await api('/api/preview',payload);m.preview=p;m.previewKey=key;m.message='算例范围已核对；下一步生成并检查模型输入。';});
}
async function generateInputFlow(m){
 if(S.dirty)throw Error('请先返回方案并保存版本，再生成输入。');
 await inputFlowTask(m,'正在生成并核对模型输入…可以关闭窗口，稍后从“计算安排”回来查看。',async()=>{
  const job=await api('/api/input-preparations',{id:m.id,revision:m.revision,kind:'generate'});
  m.generated=await pollInputPreparation(m,job);m.inspection=null;m.prepared=null;
  m.message=m.generated.reused?'已核对并复用本版本输入；没有启动计算。':'模型输入已保存；没有启动计算。';
  if(inputFlowCurrent(m)&&!S.dirty)S.generated=m.generated;
 });
}
async function inspectInputFlow(m,id){
 await inputFlowTask(m,'正在读取已保存输入与差异…',async()=>{
  const d=await api('/api/input-inspection/'+encodeURIComponent(id));
  m.inspection=d;if(d.record.id===m.id&&d.record.revision===m.revision)m.generated={...d.manifest,exact_matches:d.manifest.cases.filter(x=>x.exact_input_match).length};m.message='已读取绑定版本的模型与差异。';
  if(inputFlowWindow?.model===m){inputFlowWindow.detail=true;S.inputDetail=null;S.inputInspectionError='';}
 });
}
async function prepareInputFlow(m,id){
 if(S.dirty)throw Error('请先保存或撤销未保存修改，再准备计算清单。');
 await inputFlowTask(m,'正在核对输入并准备预算清单…本操作不提交计算。',async()=>{
  const job=await api('/api/input-preparations',{id:m.id,revision:m.revision,kind:'prepare',bundle_id:id,output_contract:m.outputContract||'monthly_period_v1'});
  m.prepared=await pollInputPreparation(m,job);m.outputContract=m.prepared.output_contract;
  m.message=m.prepared.existing_batch?'已找到本输入的原批次，未重新排队。':'计算清单已准备；下一步查看预算，再明确提交。';
 });
}
async function showInputFlowBudget(m){
 await inputFlowTask(m,'正在读取空间预算与队列…',async()=>{
  const p=m.prepared,[execution,budget]=await Promise.all([api('/api/execution'),api('/api/calculation-budget',{review_id:p.id,plan_sha256:p.plan_sha256})]);
  // Closing or switching while reading must not navigate the user later.
  if(inputFlowWindow?.model!==m||!inputFlowCurrent(m)||S.dirty){m.message='预算已读取；再次打开后可前往计算队列。';return;}
  closeInputFlow();S.execution=execution;if(!S.resourcesDirty)S.resourceDraft=copy(execution.resources);S.executionReview=p;S.calculationBudget=budget;S.budgetError='';S.executionResults=null;resetBatchResults();S.view='execution';render();
  requestAnimationFrame(()=>document.getElementById('execution-review')?.scrollIntoView({block:'start'}));notice('请核对预算与清单。尚未提交计算。');
 });
}
function renderInputFlow(){
 const v=inputFlowWindow;if(!v)return;const m=v.model;
 if(!inputFlowCurrent(m)){closeInputFlow();return;}
 const d=inputFlowDialog(),oldY=d.querySelector('.input-flow-body')?.scrollTop||0;
 const p=m.previewKey===capabilityKey()?m.preview:null,g=!S.dirty?m.generated:null;
 if(p)S.preview=p;if(g)S.generated=g;
 let body='';
 if(v.detail&&m.inspection){S.inputInspection=m.inspection;body=inputFlowInspectionMarkup().replace('<button data-action="close-input-inspection">收起输入核对</button>','<button data-input-flow="back">← 返回输入摘要</button>');}
 else{
  body=`<details class="input-flow-settings"><summary>计算设置 · ${S.record.numerics.step_minutes} min · ${esc(periodLabel(S.record.factors.scope.period))}</summary>${select('求解步长 / min','numerics.step_minutes',[1,2,5,10,15,30,60].map(x=>[x,String(x)]),S.record.numerics.step_minutes)}<p>修改步长后需返回方案保存版本。设备投入在计算队列中统一管理。</p>${ordinaryTimeBasis()}</details>`;
  body+=outputResolutionMarkup(m);
  if(S.dirty)body+='<p class="warning">当前有未保存修改，请先返回方案保存版本。已有模型仍属于原保存版本。</p>';
  if(g){body+=`<section class="input-flow-result"><h3>模型输入已就绪</h3><p>${g.case_count} 个算例 · 已保存 v${m.revision} · 尚未由此操作提交计算。</p><p class="muted">下表为已生成模型；变化数相对源模型，不是相对上一次编辑，也不是错误数量。</p>${caseListView('generated')}<button data-input-flow="inspect"${m.pending?' disabled':''}>查看模型差异与实际参数</button><details><summary>来源与完整记录</summary><a href="/api/model-inputs/${esc(g.id)}/manifest.json" target="_blank" rel="noopener">差异与来源清单 ↗</a> · <a href="/api/model-inputs/${esc(g.id)}/record.json" target="_blank" rel="noopener">绑定方案版本 ↗</a><p><button data-input-flow="generate"${m.pending?' disabled':''}>重新核对并生成输入</button></p></details></section>`;}
  else if(p){body+=`<h3>待生成的算例</h3><p>${p.selected_sites} 个地点 · ${p.case_count} 个算例。这里只确认将计算什么，尚未生成模型。</p>${[...(p.errors||[]),...(p.requirements||[])].map(x=>`<p class="warning">${esc(x)}</p>`).join('')}${caseListView('preview')}`;}
  else if(!m.pending)body+='<button data-input-flow="preview">核对算例范围</button>';
  if(!g&&!S.dirty&&S.planActivity?.inputs.length)body+=`<details><summary>本版本已有 ${S.planActivity.inputs.length} 份输入</summary>${S.planActivity.inputs.map(x=>`<button data-inspect-input="${esc(x.id)}"${m.pending?' disabled':''}>读取已有输入 · ${esc(readableTime(x.created))}</button>`).join('')}</details>`;
 }
 const phase=m.prepared||m.job?.kind==='prepare'?3:g||m.job?.kind==='generate'?2:1;
 const next=m.prepared?'budget':g?'prepare':'generate',label={budget:m.prepared?.existing_batch?'查看已有计算批次':'前往预算与提交',prepare:'准备计算清单（不计算）',generate:'生成模型输入（不计算）'}[next];
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(m.name)} · 已保存 v${m.revision}</p><h2 id="input-workflow-title">计算安排与输入核对</h2></div><button data-input-flow="close">返回方案</button></header><div class="input-flow-steps" aria-label="输入准备进度"><span class="${phase===1?'current':''}">1 核对算例</span><span class="${phase===2?'current':''}">2 生成与检查输入</span><span class="${phase===3?'current':''}">3 预算与提交</span></div><div class="input-flow-body">${body}</div><footer class="viewer-foot input-flow-footer"><div id="input-flow-status" role="status" aria-live="polite" class="${m.error?'warning':m.pending?'input-flow-pending':''}"><strong>${esc(m.error||m.message||'生成输入与准备清单均不启动计算。')}</strong><div id="input-flow-progress">${inputProgressMarkup(m)}</div>${m.pending?'<p>可翻页、关闭后返回；生成完成后仍需明确提交计算。</p>':''}</div><div class="actions">${v.detail?'<button data-input-flow="back">返回输入摘要</button>':`<button class="primary" data-input-flow="${next}"${m.pending||m.recovering||S.dirty||(!g&&!p?.generation?.supported)?' disabled':''}>${label}</button>`}<button data-input-flow="close">返回方案</button></div></footer>`;
 if(!d.open)d.showModal();d.querySelector('.input-flow-body').scrollTop=oldY;
}
async function inputFlowButton(b){
 const m=inputFlowWindow?.model;if(!m)return;
 const op=b.dataset.inputFlow;if(op==='close'){closeInputFlow();return;}
 if(b.dataset.casePage){await inputReviewAction(b);return;}
 if(m.pending||m.recovering)return;
 if(op==='back'){inputFlowWindow.detail=false;renderInputFlow();return;}
 if(op==='preview')return readInputFlowPreview(m);
 if(op==='generate')return generateInputFlow(m);
 if(op==='inspect'||b.dataset.inspectInput)return inspectInputFlow(m,b.dataset.inspectInput||m.generated.id);
 if(op==='prepare')return prepareInputFlow(m,m.generated.id);
 if(op==='budget')return showInputFlowBudget(m);
 if(await inputReviewAction(b))renderInputFlow();
}
const inputFlowBeforeAction=action;
action=async function(b){
 const op=b.dataset.action;
 if(['preview','refresh-planning','generate','prepare-execution'].includes(op)||b.dataset.inspectInput||b.dataset.prepareInput){
  const m=openInputFlow(op==='preview'||op==='refresh-planning');
  if(b.dataset.inspectInput){if(!m.pending)void inspectInputFlow(m,b.dataset.inspectInput);else m.message='正在核对算例，完成后可读取已有输入。';}
  else if(b.dataset.prepareInput){if(!m.pending)void prepareInputFlow(m,b.dataset.prepareInput);}
  else if(op==='generate'&&!m.pending)void generateInputFlow(m);
  else if(op==='prepare-execution'&&!m.pending&&m.generated)void prepareInputFlow(m,m.generated.id);
  return;
 }
 return inputFlowBeforeAction(b);
};
// Workflow entry buttons use the same focused reader as the scheme header.
workflowDispatch=function(dataset){const b=document.createElement('button');Object.assign(b.dataset,dataset);return action(b);};
const inputFlowBeforeRender=render;
render=function(){inputFlowBeforeRender();renderInputFlow();};
window.addEventListener('beforeunload',e=>{if([...inputFlowJobs.values()].some(m=>m.pending)){e.preventDefault();e.returnValue='';}});
