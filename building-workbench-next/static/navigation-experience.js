/* Viewing is local and cancellable; mutation actions retain existing guards. */
let historyViewEpoch=0;
const navigationHistoryPanel=versionHistoryPanel;
versionHistoryPanel=function(){return S.historyLoading?'<section id="version-history" class="section"><div class="row"><h2>保存版本记录</h2><button data-action="close-version-history">收起记录</button></div><p role="status">正在读取版本摘要，可继续查看其他功能…</p></section>':navigationHistoryPanel();};
async function openHistoryLocally(){const epoch=++historyViewEpoch,id=S.id;S.historyLoading=true;render();try{const value=await api('/api/version-history/'+encodeURIComponent(id));if(epoch===historyViewEpoch&&S.id===id)S.history=value;}catch(e){if(epoch===historyViewEpoch&&S.id===id)notice(e.message);}finally{if(epoch===historyViewEpoch){S.historyLoading=false;if(S.view==='editor')render();}}}
async function openExecutionLocally(){S.view='execution';S.executionError='';render();scrollTo({top:0,behavior:'instant'});try{await loadExecution();}catch(e){S.executionError=e.message;}if(S.view==='execution')render();}
const navigationExecutionView=executionView;
executionView=function(){return S.execution?navigationExecutionView():`<section class="section"><h1>计算队列</h1><p role="status">${esc(S.executionError||'正在读取任务摘要，可切换到其他页面…')}</p><button data-view="execution">重新读取</button></section>`;};

S.queueQuery='';S.queueCategory='all';S.queueGroupOpen=new Set();
const navigationBatchCards=executionBatches;
function queueGroups(){const groups=new Map();for(const b of S.execution?.batches||[]){const owner=S.boot.records.find(r=>r.id===b.record_id)?.research_set;const key=JSON.stringify([b.record_id||b.record_name,b.revision,b.output_contract]);if(!groups.has(key))groups.set(key,{key,name:b.record_name,revision:b.revision,owner,batches:[]});groups.get(key).batches.push(b);}return [...groups.values()];}
executionBatches=function(){const groups=queueGroups(),q=S.queueQuery.trim().toLocaleLowerCase(),all=groups.filter(g=>(S.queueCategory==='all'||S.queueCategory==='research'&&g.owner||S.queueCategory==='other'&&!g.owner||S.queueCategory==='attention'&&g.batches.some(queueNeedsAttention))&&(!q||[g.name,...g.batches.flatMap(b=>b.jobs.map(j=>j.city))].join(' ').toLocaleLowerCase().includes(q)));
 const original=S.execution.batches;let content='';try{content=all.map(g=>{const counts=g.batches.reduce((c,b)=>{for(const [k,n] of Object.entries(b.counts))c[k]=(c[k]||0)+n;return c;},{}),n=g.batches.reduce((n,b)=>n+b.case_count,0),id=sectionHash(g.key),sites=new Set(g.batches.flatMap(b=>b.jobs.map(j=>j.site_id)));S.execution.batches=g.batches.filter(b=>!q||[g.name,...b.jobs.map(j=>j.city)].join(' ').toLocaleLowerCase().includes(q));let ci=0;const cards=navigationBatchCards().replace(/<h3>(.*?)<\/h3>/g,(_,title)=>{const b=S.execution.batches[ci++];return '<h4>'+esc(b.jobs.map(j=>j.city).join('、'))+' · '+title+'</h4>';});return `<details class="queue-group" data-queue-group="${esc(id)}"${S.queueGroupOpen.has(id)?' open':''}><summary><strong>${esc(g.name)}</strong><span>v${g.revision} · ${sites.size} 地点 · ${n} 条算例记录 · 通过/复用 ${(counts.passed||0)+(counts.reused||0)} 条${counts.review?' · 待复核 '+counts.review:''}${counts.pending||counts.running?' · 待算/运行 '+((counts.pending||0)+(counts.running||0)):''}</span></summary><p class="muted">按同一保存版本聚合 ${g.batches.length} 个底层批次；逐项来源、重试与核验记录保留。</p>${cards}</details>`;}).join('');}finally{S.execution.batches=original;}
 return `<div class="queue-filters"><label>任务范围<select id="queue-category">${options([['research','对比集研究任务'],['attention','运行与待处理'],['other','其他方案与历史记录'],['all','全部记录']],S.queueCategory)}</select></label><label>查找方案或地点<input id="queue-query" type="search" value="${esc(S.queueQuery)}" placeholder="如：昆明、W00"></label></div><p class="muted">显示 ${all.length} 组，共登记 ${groups.length} 组 / ${original.length} 个底层批次。展开后选择具体地点结果。尚未提交的成员在对比集中查看。</p><div id="queue-groups">${content||'<p>当前筛选没有任务。</p>'}</div>`;
};
document.addEventListener('toggle',e=>{const k=e.target.dataset?.queueGroup;if(k){if(e.target.open)S.queueGroupOpen.add(k);else S.queueGroupOpen.delete(k);}},true);
function refreshQueueGroups(){const p=document.getElementById('execution-batches');if(!p)return;const active=document.activeElement,id=active?.id,position=active?.selectionStart;p.innerHTML=executionBatches();if(id){const el=document.getElementById(id);el?.focus({preventScroll:true});if(id==='queue-query')el.setSelectionRange(position,position);}}
document.addEventListener('input',e=>{if(e.target.id==='queue-query'){S.queueQuery=e.target.value;refreshQueueGroups();}});
document.addEventListener('change',e=>{if(e.target.id==='queue-category'){S.queueCategory=e.target.value;refreshQueueGroups();}});

let queueResultEpoch=0;
const navigationResultsMarkup=executionResults;
executionResults=function(){return S.queueResultWindow?'':navigationResultsMarkup();};
function queueResultDialog(){let d=document.getElementById('queue-results-dialog');if(d)return d;d=document.createElement('dialog');d.id='queue-results-dialog';d.className='queue-results-dialog';d.setAttribute('aria-labelledby','queue-result-title');document.body.append(d);d.addEventListener('cancel',e=>{e.preventDefault();closeQueueResult();});d.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();if(b.dataset.action==='close-execution-results'){closeQueueResult();return;}const v=S.queueResultWindow;if(!v||v.pending)return;v.scroll=d.querySelector('.focused-body').scrollTop;if(b.dataset.batchCase!==undefined){v.suspended=true;d.close();await batchResultsAction(b);resultViewDialog().addEventListener('close',()=>{if(S.queueResultWindow===v){v.suspended=false;drawQueueResult();}},{once:true});return;}v.pending=true;try{await batchResultsAction(b);}catch(error){v.error=error.message;}finally{v.pending=false;drawQueueResult();}});return d;}
function drawQueueResult(){
 const v=S.queueResultWindow;if(!v||v.suspended)return;
 const d=queueResultDialog();
 const receipt=v.verified&&!v.error&&!v.pending?`<p class="muted" data-batch-read-status>${v.reused?'已读取最近核验的结果 · 登记与文件状态一致':'本次已完成内容核验'} · ${esc(v.verified.replace('T',' '))}</p>`:'';
 d.innerHTML=`<header class="viewer-head"><h2 id="queue-result-title">计算结果与核验</h2><button data-action="close-execution-results">关闭并返回任务</button></header><div class="focused-body">${v.error?'<p class="warning" role="alert">'+esc(v.error)+'</p>':''}${v.pending?'<p role="status">正在读取批次，首次打开需核验文件。可以先关闭窗口。</p>':receipt+navigationResultsMarkup()}</div>`;
 if(!d.open)d.showModal();
 d.querySelector('.focused-body').scrollTop=v.scroll||0;
}
function closeQueueResult(){const v=S.queueResultWindow;if(!v)return;++queueResultEpoch;S.queueResultWindow=null;queueResultDialog().close();queueResultDialog().replaceChildren();S.executionResults=null;resetBatchResults();requestAnimationFrame(()=>{scrollTo({top:v.y,behavior:'instant'});document.querySelector(`[data-batch-results="${v.id}"], [data-index-open="${v.id}"]`)?.focus({preventScroll:true});});}
const batchReadsInProgress=new Map();
function readBatchView(id,force){
 const running=batchReadsInProgress.get(id);
 if(running&&(!force||running.force))return running.promise;
 const promise=api('/api/execution/'+id+'/summary?view='+(force?'refresh':'recent'));
 const read={promise,force};batchReadsInProgress.set(id,read);
 const clear=()=>{if(batchReadsInProgress.get(id)===read)batchReadsInProgress.delete(id);};
 promise.then(clear,clear);return promise;
}
loadBatchResults=async function(id,reset=false,force=false){
 const epoch=++queueResultEpoch;let v=S.queueResultWindow;
 if(!v||v.id!==id){S.executionResults=null;resetBatchResults();v=S.queueResultWindow={id,y:scrollY,scroll:0};}
 v.pending=true;v.error='';drawQueueResult();
 try{
   const read=await readBatchView(id,force);
   if(epoch!==queueResultEpoch||S.queueResultWindow!==v)return false;
   const d=read.summary||read;
   if(reset)resetBatchResults();
   if(d.dataset_sha256!==S.executionResults?.dataset_sha256)S.batchExport=null;
   S.executionResults=d;v.verified=read.verified;v.reused=read.reused;
   return true;
 }catch(e){
   if(epoch===queueResultEpoch&&S.queueResultWindow===v){S.executionResults=null;v.error=e.message;v.verified=null;}
   return false;
 }finally{
   if(epoch===queueResultEpoch&&S.queueResultWindow===v){v.pending=false;drawQueueResult();}
 }
};
let listViewEpoch=0,sourceSelectionBusy=false,indexSelectionEpoch=0;
async function openListLocally(view){
 const epoch=++listViewEpoch;S.view=view;
 const read=view==='sources'?loadSourceOverview():loadResultIndex();render();
 scrollTo({top:0,behavior:'instant'});await read;
 if(epoch===listViewEpoch&&S.view===view)render();
}
async function selectSourceLocally(button){
 if(sourceSelectionBusy)return;
 sourceSelectionBusy=true;button.disabled=true;const label=button.textContent;button.textContent='正在读取所选方案…';
 try{await sourceOverviewAction(button);}catch(e){notice(e.message);}finally{sourceSelectionBusy=false;if(button.isConnected){button.disabled=false;button.textContent=label;}}
}
async function selectIndexVersionLocally(button){
 const epoch=++indexSelectionEpoch,view=S.view,ident=S.id,revision=S.saved?.revision;
 const stillHere=()=>epoch===indexSelectionEpoch&&S.view===view&&S.id===ident&&S.saved?.revision===revision&&!S.dirty&&!S.usageDirty;
 button.disabled=true;const label=button.textContent;button.textContent='正在读取绑定方案…';
 try{if(await loadRecord(button.dataset.indexRecord,/^\d+$/.test(button.dataset.indexRevision)?Number(button.dataset.indexRevision):button.dataset.indexRevision,stillHere)){S.resultIndexOrigin=button.closest('[data-index-kind]').id.slice(6);S.view='editor';render();scrollTo({top:0,behavior:'instant'});}}catch(e){notice(e.message);}finally{if(button.isConnected){button.disabled=false;button.textContent=label;}}
}
// Capture just these read-only entries. All other actions keep their existing rules.
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled||S.busy||b.closest('dialog'))return;
 const a=b.dataset.action,view=b.dataset.view,flow=b.dataset.flowOpen;
 if(view==='sources'||view==='result-index'){e.stopImmediatePropagation();void openListLocally(view);return;}
 if(a==='refresh-result-index'||b.dataset.sourceOverview==='refresh'){e.stopImmediatePropagation();void openListLocally(a==='refresh-result-index'?'result-index':'sources');return;}
 if(['open','plan','weather'].includes(b.dataset.sourceOverview)){e.stopImmediatePropagation();void selectSourceLocally(b);return;}
 if(b.dataset.indexRecord){e.stopImmediatePropagation();void selectIndexVersionLocally(b);return;}
 if(b.dataset.indexOpen&&resultIndexAll().some(r=>r.id===b.dataset.indexOpen&&r.kind==='batch')){e.stopImmediatePropagation();void loadBatchResults(b.dataset.indexOpen,true);return;}
 if(a==='history'||flow==='history'){e.stopImmediatePropagation();void openHistoryLocally();return;}
 if(a==='close-version-history'){e.stopImmediatePropagation();++historyViewEpoch;S.historyLoading=false;S.history=null;render();return;}
 if(view==='editor'){e.stopImmediatePropagation();S.view='editor';render();void loadPlanActivity({forceWorkflow:false});return;}
 if(view==='execution'||flow==='queue'){e.stopImmediatePropagation();void openExecutionLocally();return;}
 if(b.dataset.batchResults){e.stopImmediatePropagation();void loadBatchResults(b.dataset.batchResults,true);return;}
},true);
