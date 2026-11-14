/* Projection of existing evidence. Opening a node never saves or submits. */
S.workflow=null;S.workflowError='';S.workflowPending=false;S.workflowNode=null;S.workflowBranch=false;S.workflowBatch=null;
let workflowEpoch=0,workflowTimer,workflowIdentity='',workflowScheduledKey=null,workflowInFlight=null;
function workflowKey(){return S.record&&S.saved?capabilityKey():null;}
function workflowBranchVisible(){return S.workflowBranch||S.record?.factors.condition.controls.some(c=>c.mode==='calendar');}
function workflowCalendarBranch(job){
 const branch=job?.branch,p=job?.result,rows=p?.rows||[],pending=rows.filter(x=>!x.ready);
 if(!branch||p.source_kind!=='accepted_queue_daily_v1'||p.can_save||p.can_apply||p.issues.length||!rows.length||rows.length!==branch.total||!pending.length||!rows.every(x=>x.source?.batch_id&&x.preview?.days?.length===365)||!pending.every(x=>x.preview.transition_review_needed&&x.issues.length===1&&x.issues[0]==='出现多段或不确定季节，可查看完整曲线，但保存前需共同确认，不自动合并。'))return branch;
 const out=copy(branch);out.rows=out.rows.map(x=>({...x,reference_ready:true,calendar_pending:!x.ready}));
 out.nodes=out.nodes.map(x=>x.id==='reference'?{...x,state:'done',label:`${rows.length}/${branch.total} 地点参考就绪`}:x.id==='calendar'?{...x,state:'attention',label:`${pending.length} 地点待确认季节切换`,note:'逐日参考齐备；请核对待确认地点的切换规则，再保存日历。'}:x.id==='orientation'?{...x,state:'attention',label:'待日历确认',note:'日历确认后再核对材料与翻面执行。'}:x);return out;
}
function workflowCurrent(){const d=S.workflow?.key===workflowKey()?S.workflow.data:null;if(!d)return null;return {...d,branches:workflowBranchVisible()?workflowCalendarBranch(currentCalendarInspection()?.job)||null:null};}
function workflowBranchStatus(){const state=currentCalendarInspection();return `<div class="flow-branch"><h3>翻面研究分支</h3><p role="status" class="${state?.error?'warning':'muted'}">${esc(calendarInspectionMessage())}</p>${!state?.pending?workflowButton('branch-refresh','重新核对'):''}</div>`;}
function workflowButton(action,label,extra=''){return `<button data-flow-open="${action}" ${extra}>${label}</button>`;}
function workflowSteps(nodes,branch=false){
 return `<ol class="flow-steps${branch?' flow-branch-steps':''}">${nodes.map((n,i)=>`<li><button data-flow-node="${esc(n.id)}" class="flow-step flow-${esc(n.state)}" aria-pressed="${S.workflowNode===n.id}" aria-expanded="${S.workflowNode===n.id}" aria-controls="flow-detail"><span class="flow-step-title"><span class="flow-number">${branch?'↳':i+1}</span>${esc(n.title)}</span><span class="flow-state">${esc(n.label)}</span></button></li>`).join('')}</ol>`;
}
function workflowDetail(d){
 const n=[...d.nodes,...(d.branches?.nodes||[])].find(n=>n.id===S.workflowNode);if(!n)return '';
 let content='';
 if(n.id==='prepare')content=`<div class="actions">${factors.map(([k,label])=>workflowButton('factor',`查看${label}`,`data-flow-value="${k}"`)).join('')}${workflowButton('sources','核对方案来源')}</div>`;
 if(n.id==='inputs')content=`<div class="actions">${workflowButton('planning','查看计算安排')}</div>${d.inputs.map(x=>`<div class="flow-record"><span>${x.case_count} 个输入 · ${esc(x.created.replace('T',' '))}</span><button data-inspect-input="${esc(x.id)}">查看输入与变化</button></div>`).join('')}${!d.inputs.length&&d.other_versions.length?'<p>其他版本有输入或结果，不属于当前版本。</p>'+workflowButton('history','查看版本记录'):''}`;
 if(n.id==='budget')content=`<p>收起清单只隐藏窗口。未提交清单保留在此，不排队、不占计算进程。</p>${d.preparations.map(x=>`<div class="flow-record"><div><strong>${x.output_contract==='daily_sensible_reference_v1'?'逐日参考清单':'计算清单'}</strong> · ${esc(x.created.replace('T',' '))}<p class="${x.valid?'muted':'warning'}">${esc(x.valid?'已准备 · 未提交':x.note)}</p></div>${workflowButton('restore','恢复原清单',`data-flow-value="${esc(x.id)}"${!x.valid||S.dirty?' disabled':''}`)}</div>`).join('')}${!d.preparations.length?'<p class="muted">没有当前版本的未提交清单。</p>':''}<div class="actions">${workflowButton('queue','查看队列与设备投入')}${d.inputs.length?`<button data-prepare-input="${esc(d.inputs[0].id)}"${S.dirty?' disabled':''}>用已有输入准备预算</button>`:workflowButton('planning','先查看计算安排')}</div>`;
 if(n.id==='budget'&&d.preparation_history?.length)content+=`<details class="flow-preparation-history"><summary>已提交的历史准备记录（${d.preparation_history.length} 份）</summary>${d.preparation_history.map(p=>`<p>${esc(p.created.replace('T',' '))} · ${esc(p.lifecycle.label)} ${(p.lifecycle.batches||[]).map(b=>`<button data-activity-queue="${esc(b.id)}">查看关联批次</button>`).join('')}</p>`).join('')}<p>保留原清单用于追溯，不计入未提交任务；结果接受情况从对应批次核对。</p></details>`;
 if(n.id==='results')content=d.batches.length?`<label class="field">当前查看的批次<select data-flow-batch>${d.batches.map((b,i)=>`<option value="${esc(b.id)}"${b.id===d.selected_batch?' selected':''}>${i+1} · ${b.output_contract==='daily_sensible_reference_v1'?'逐日参考':'常规结果'} · ${esc(b.created.replace('T',' '))} · ${b.case_count} 个算例</option>`).join('')}</select></label><p class="muted">本阶段状态只对应所选批次。${d.verified?'已读取结果，接受状态以本次核验为准。':'可按需读取结果，确认有效数量与复核说明。'}</p><div class="actions">${workflowButton('verify','读取结果状态')}${`<button data-activity-batch="${esc(d.selected_batch)}">查看本批结果与导出</button><button data-activity-queue="${esc(d.selected_batch)}">查看本批进度</button>`}</div>`:workflowButton('queue','查看计算队列');
 if(n.id==='results'&&!d.batches.length&&d.preparation_history?.length)content+=`<button data-flow-node="budget">查看历史准备与关联批次</button>`;
 if(n.id==='compare')content=`${d.comparisons.map(c=>`<div class="flow-record"><div><strong>${esc(c.name)}</strong><p class="muted">参考 v${c.left.revision} → 研究 v${c.right.revision}；进入后选择双方结果。</p></div><div class="actions"><button data-activity-comparison="${esc(c.id)}">查看差异</button><button data-activity-comparison-result="${esc(c.id)}">选择配对结果与出图</button></div></div>`).join('')}<div class="actions">${workflowButton('compare','前往对照总览')}</div>`;
 if(n.id==='reference')content=`${(d.branches.rows||[]).map(x=>`<p>${esc(x.city)} · ${x.reference_ready?'参考就绪'+(x.calendar_pending?'；季节切换待确认':''):x.ready?'参考就绪':esc(x.issues.join('；'))}</p>`).join('')}<div class="actions">${workflowButton('daily','查看参考与补算准备')}${workflowButton('calendar','查看日历核对')}</div>`;
 if(n.id==='calendar'||n.id==='orientation')content=`${(d.branches.rows||[]).map(x=>x.orientation_input?`<p>${esc(x.city)} · ${esc(x.orientation_input)}</p>`:'').join('')}<div class="actions">${workflowButton('calendar','查看翻面日历与输入核对')}</div>`;
 return `<div id="flow-detail" class="flow-detail"><div class="row"><h3>${esc(n.title)} · ${esc(n.label)}</h3><button data-flow-node="${esc(n.id)}" aria-label="收起阶段详情">收起</button></div><p>${esc(n.note)}</p>${['prepare','reference','calendar','orientation'].includes(n.id)?'':`<p class="muted">依据：当前已保存 v${d.revision} 的记录。</p>`}${content}</div>`;
}
function planWorkflowView(){
 if(!S.record)return '';const d=workflowCurrent();
 const content=d?`${S.dirty?`<p class="warning flow-draft">有未保存编辑：准备与翻面分支按当前编辑检查；输入、清单、批次和比较仍属于已保存 v${d.revision}。${d.same_recipe?'计算输入配方未变，仍需保存后准备计算。':'当前编辑尚无对应计算结果。'}</p>`:''}${workflowSteps(d.nodes)}<div class="flow-tools"><span class="muted">点选阶段查看依据与下一步操作。</span><button data-flow-open="branch" aria-expanded="${!!workflowBranchVisible()}"${d.branches&&!d.branches.optional?' disabled':''}>${d.branches&&!d.branches.optional?'翻面分支（当前已启用）':workflowBranchVisible()?'收起翻面分支':'查看翻面研究分支'}</button></div>${d.branches?`<div class="flow-branch"><h3>翻面研究分支${d.branches.optional?' · 可选':''}</h3><p class="muted">${d.branches.optional?'当前为固定工况；下列准备不影响固定工况主线。':'按当前翻面控制检查参考与日历。'}</p><p class="muted">${esc(calendarInspectionMessage())}</p>${workflowButton('branch-refresh','重新核对',currentCalendarInspection()?.pending?'disabled':'')}${workflowSteps(d.branches.nodes,true)}${d.branches.issues.length?`<p class="warning">${esc(d.branches.issues.join('；'))}</p>`:''}</div>`:workflowBranchVisible()?workflowBranchStatus():''}${workflowDetail(d)}${d.issues.length?`<details class="warning"><summary>部分记录需核对，流程可能不完整</summary>${d.issues.map(x=>`<p>${esc(x)}</p>`).join('')}</details>`:''}<p class="muted flow-stamp">读取于 ${esc(d.checked_at.replace('T',' '))} · ${d.scope_sites} 个范围地点 · 查看流程不启动计算</p>`:`<p class="${S.workflowError?'warning':'muted'}" role="status">${esc(S.workflowError||'正在读取当前方案状态…')}</p>`;
 return `<section id="plan-workflow" class="section plan-workflow" aria-label="方案流程总览"><div class="row"><div><h2>方案流程总览</h2><p class="muted">${esc(S.record.name)} · 已保存 v${S.record.revision}</p></div><button data-flow-open="refresh"${S.workflowPending?' disabled':''}>${S.workflowPending?'正在核对…':'刷新流程'}</button></div>${content}</section>`;
}
function updateWorkflowDOM(){const el=document.getElementById('plan-workflow');if(el)el.outerHTML=planWorkflowView();}
function alignWorkflowIdentity(){
 const identity=JSON.stringify([S.saved.id,S.saved.revision]);
 if(identity!==workflowIdentity){workflowIdentity=identity;++workflowEpoch;clearTimeout(workflowTimer);workflowTimer=null;workflowScheduledKey=null;S.workflowNode=null;S.workflowBatch=null;S.workflowBranch=false;S.workflow=null;S.workflowPending=false;}
}
function workflowRequestKey(verify=false){return JSON.stringify([workflowKey(),S.workflowBatch,S.workflowBranch,verify]);}
async function refreshWorkflow(verify=false){
 if(!S.record||!S.saved||S.view!=='editor')return;alignWorkflowIdentity();clearTimeout(workflowTimer);workflowTimer=null;workflowScheduledKey=null;
 const requestKey=workflowRequestKey(verify);if(workflowInFlight?.key===requestKey&&workflowInFlight.epoch===workflowEpoch)return workflowInFlight.promise;
 const key=workflowKey(),epoch=++workflowEpoch,flight={key:requestKey,epoch};S.workflowPending=true;S.workflowError='';updateWorkflowDOM();
 flight.promise=(async()=>{try{const d=await api('/api/plan-workflow',{id:S.saved.id,revision:S.saved.revision,changes:changes(),batch_id:S.workflowBatch,branch:S.workflowBranch,defer_branch:true,verify_results:verify});
  if(epoch===workflowEpoch&&key===workflowKey()){S.workflow={key,data:d};S.workflowBatch=d.selected_batch;}
 }catch(e){if(epoch===workflowEpoch&&key===workflowKey()){S.workflow=null;S.workflowError=e.message;}}
 finally{if(workflowInFlight===flight)workflowInFlight=null;if(epoch===workflowEpoch){S.workflowPending=false;updateWorkflowDOM();}}})();workflowInFlight=flight;return flight.promise;
}
function scheduleWorkflow(force=false){
 if(!S.record||!S.saved||S.view!=='editor')return;alignWorkflowIdentity();if(!force&&S.workflow?.key===workflowKey())return;
 const key=workflowRequestKey();if(workflowScheduledKey===key||workflowInFlight?.key===key&&workflowInFlight.epoch===workflowEpoch)return;
 clearTimeout(workflowTimer);++workflowEpoch;workflowScheduledKey=key;S.workflowPending=true;S.workflowError='';updateWorkflowDOM();workflowTimer=setTimeout(()=>refreshWorkflow(),450);
}
function invalidateWorkflowAfterSubmission(id,revision,batchId){
 if(S.saved?.id!==id||S.saved.revision!==revision)return;
 ++workflowEpoch;clearTimeout(workflowTimer);workflowTimer=null;workflowScheduledKey=null;
 S.workflow=null;S.workflowError='';S.workflowPending=false;S.workflowBatch=batchId||null;
 if(S.view==='editor')scheduleWorkflow();
}
function workflowActivityStamp(d){
 return JSON.stringify([(d.inputs||[]).map(x=>x.id),(d.batches||[]).map(x=>[x.id,x.mode,x.counts]),(d.comparisons||[]).map(x=>[x.id,x.name])]);
}
const workflowEditor=editor;editor=function(){return workflowEditor().replace('<nav class="factor-nav"',planWorkflowView()+'<nav class="factor-nav"');};
const workflowActivity=loadPlanActivity;loadPlanActivity=async function(options={}){const identity=JSON.stringify([S.saved.id,S.saved.revision]);await workflowActivity();if(identity===JSON.stringify([S.saved.id,S.saved.revision])){const changed=S.planActivity&&S.workflow?.key===workflowKey()&&workflowActivityStamp(S.planActivity)!==workflowActivityStamp(S.workflow.data);scheduleWorkflow(options.forceWorkflow!==false||changed);}};
const workflowDirty=updateDirtyStatus;updateDirtyStatus=function(){workflowDirty();scheduleWorkflow();};
// Also cover component adoption, which updates capability without typing in an input.
const workflowCapability=updateCapabilityStatus;updateCapabilityStatus=function(){workflowCapability();if(S.record&&(!S.workflow||S.workflow.key!==workflowKey()))scheduleWorkflow();};
function workflowDispatch(dataset){const button=document.createElement('button');Object.assign(button.dataset,dataset);return workflowAction(button);}
const workflowAction=action;action=async function(button){
 if(button.dataset.flowNode){S.workflowNode=S.workflowNode===button.dataset.flowNode?null:button.dataset.flowNode;updateWorkflowDOM();return;}
 const op=button.dataset.flowOpen;if(!op)return workflowAction(button);
 if(op==='refresh'||op==='verify'){void refreshWorkflow(op==='verify');return;}
 if(op==='branch-refresh'){void requestCalendarInspection(true);return;}
 if(op==='branch'){if(S.record.factors.condition.controls.some(c=>c.mode==='calendar'))return;S.workflowBranch=!S.workflowBranch;S.workflowNode=null;updateWorkflowDOM();if(S.workflowBranch)void requestCalendarInspection();return;}
 if(op==='restore'){
  if(S.dirty)throw Error('请先保存或撤销未保存修改，再恢复原清单。');
  const prepared=await api('/api/plan-workflow/preparation',{id:S.saved.id,revision:S.saved.revision,review:button.dataset.flowValue});
  await loadExecution();S.executionReview=prepared;S.executionResults=null;resetBatchResults();S.view='execution';render();notice('已恢复原清单，仍未提交计算。');return;
 }
 if(op==='factor'){await workflowDispatch({factor:button.dataset.flowValue});return;}
 if(op==='planning'||op==='history'){await workflowDispatch({action:op==='planning'?'preview':'history'});return;}
 if(op==='queue'||op==='compare'){await workflowDispatch({view:op==='queue'?'execution':'compare'});return;}
 if(op==='daily')await workflowDispatch({dailyReference:'open'});
 if(op==='calendar')await workflowDispatch({calendarLibrary:'open'});
 if(op==='sources')await workflowDispatch({weatherAction:'sources'});
};
app.addEventListener('change',event=>{if(event.target.matches('[data-flow-batch]')){S.workflowBatch=event.target.value;S.workflow=null;refreshWorkflow();}});
