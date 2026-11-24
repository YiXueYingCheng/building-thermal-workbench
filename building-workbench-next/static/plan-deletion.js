/* Explicit preview/confirmation only. Sources and referenced snapshots stay protected. */
const PD={preview:null,receipt:null,history:null,pending:false,executing:false,error:'',sequence:0};
const pdReads=new DialogReads(6);
const deletionSidebar=librarySidebar;
librarySidebar=function(){const t=document.createElement('template');t.innerHTML=deletionSidebar();t.content.querySelector('.sidebar')?.insertAdjacentHTML('beforeend',`<section class="well"><h3>方案管理</h3><button data-pd-record="${esc(S.saved?.id||'')}"${S.saved?'':' disabled'}>清理方案与关联资料</button><button data-pd="history">查看删除记录</button><p class="muted">先核对清理范围，再确认操作。</p></section>`);return t.innerHTML;};
const deletionVersionPanel=versionHistoryPanel;
versionHistoryPanel=function(){const t=document.createElement('template');t.innerHTML=deletionVersionPanel();t.content.querySelectorAll('[data-history-row]').forEach(row=>row.querySelector('.actions')?.insertAdjacentHTML('beforeend',`<button data-pd-version="${esc(row.dataset.historyRow)}" data-pd-record="${esc(S.saved.id)}">清理此版与关联资料</button>`));if(S.history?.deleted_revisions?.length)t.content.querySelector('.version-history-list')?.insertAdjacentHTML('beforebegin',`<p class="muted">已受控删除版本：${S.history.deleted_revisions.map(n=>'v'+esc(n)).join('、')}。编号不复用，删除记录保留。</p>`);return t.innerHTML;};
function pdDialog(){let d=document.getElementById('plan-deletion');if(d)return d;d=document.createElement('dialog');d.id='plan-deletion';d.className='library-adoption';d.setAttribute('aria-labelledby','pd-title');document.body.append(d);d.addEventListener('cancel',e=>{if(PD.executing)e.preventDefault();else PD.sequence++;});return d;}
function pdReceipt(r){if(r.cleanup)return `<h3>${esc(r.name)} · 清理完成</h3><p>已清理 ${r.removed_versions} 个版本、${r.batches.length} 个批次和 ${r.files_deleted} 个文件。</p><p>专属文件大小合计 ${(r.exclusive_bytes/1048576).toFixed(2)} MiB。操作记录已保存。</p>`;return `<h3>${esc(r.name)}</h3><p>已删除 ${r.removed_versions} 个保存版本（${r.versions.map(v=>'v'+esc(v.revision)).join('、')}）及 ${r.removed_current_notes} 条当前备注。</p><p>${r.latest_after==null?'该方案已无保留版本，不再显示于方案库。':'剩余最新版为 v'+esc(r.latest_after)+'；后续保存不复用已删除编号。'}</p><p><strong>未删除计算输入、结果或其他文件。</strong>操作及备注修改历史保留。</p><p>${esc(r.note)}</p><p class="muted">${esc(readableTime(r.completed))} · ${esc(r.id)}</p>`;}
function pdCleanupDetails(plan){
 const m=n=>(n/1048576).toLocaleString(undefined,{maximumFractionDigits:2})+' MiB';
 return `<h3>清理范围 · ${plan.batches.length} 个批次 · ${plan.files.length} 个文件</h3>
 <p><strong>预计可释放 ${m(plan.bytes)}</strong>，按专属文件大小估算，共享硬链接单独扣除。</p>
 <ul>${plan.batches.map(b=>`<li>计算批次 · ${esc(b)}</li>`).join('')}
 ${plan.groups.map(g=>`<li>${esc(g.kind)} · ${esc(g.path)} · ${g.files} 个文件 · ${m(g.bytes)}</li>`).join('')}</ul>
 ${plan.files.length?`<details><summary>查看将清理的文件（${plan.files.length}）</summary><ul>${plan.files.map(f=>`<li class="output-path">${esc(f[0])}</li>`).join('')}</ul></details>`:''}
 ${plan.retained.length?`<details><summary>保留的文件或位置（${plan.retained.length}）</summary><ul>${plan.retained.map(r=>`<li>${esc(r.reason)} · ${esc(r.path)}</li>`).join('')}</ul></details>`:''}`;
}
function pdEvidence(r){
 return `<details><summary>${esc(r.relations.join('、'))} · 查看文件</summary><p class="output-path">${esc(r.source)}</p></details>`;
}
function pdTree(i){
 const groups=new Map();
 for(const r of i.references){
  const key=JSON.stringify([r.kind,r.owner_key||r.owner||r.source]);
  if(!groups.has(key))groups.set(key,[]);
  groups.get(key).push(r);
 }
 const branches=Array.from(groups.values(),rows=>{
  const r=rows[0],versions=[...new Set(rows.flatMap(row=>row.relations))].join('、');
  return `<li><strong>${esc(r.kind)}</strong> · ${esc(r.label)} · ${esc(versions)}
  ${r.label===r.owner?'':`<div class="output-path">${esc(r.owner)}</div>`}
  ${r.action?relationButton(r.action):''}
  ${rows.map(pdEvidence).join('')}</li>`;
 }).join('');
 const outgoing=i.target.versions.map(v=>`<details open><summary>v${esc(v.revision)} · ${esc(v.name)}</summary>
 <ul>${(v.outgoing||[]).map(r=>`<li>${esc(r.kind)} · ${esc(r.name)}${r.version!=null?' · '+esc(typeof r.version==='number'?'v'+r.version:r.version):''}
 ${r.name!==r.id?`<small>${esc(r.id)}</small>`:''}</li>`).join('')||'<li>无已登记来源</li>'}</ul></details>`).join('');
 return `<section><h3>方案关系树</h3><details open><summary>${i.cleanup?'阻止清理的关联对象':'引用本方案的对象'}（${groups.size}）</summary>
 ${branches?`<ul>${branches}</ul>`:'<p>已核对资料中未发现引用。</p>'}</details>
 <details><summary>本方案使用的来源、配置和地点</summary>${outgoing}</details>
 ${i.historical_mentions?.length?`<details><summary>迁入时的历史清单（${i.historical_mentions.length}）</summary><p>记录交接时存在的版本，单独列出供追溯。</p>${i.historical_mentions.map(pdEvidence).join('')}</details>`:''}
 ${i.issues.length?`<details open><summary>尚未核对的资料（${i.issues.length}）</summary><ul>${i.issues.map(x=>`<li class="output-path">${esc(x)}</li>`).join('')}</ul></details>`:''}</section>`;
}
let pdClock=null;
function pdClockStart(){
 clearInterval(pdClock);
 const d=pdDialog(),label=d.querySelector('[data-pd-elapsed]');
 if(!label)return;
 const update=()=>{
  if(!d.open||!label.isConnected){clearInterval(pdClock);return;}
  label.textContent='已用 '+Math.floor((performance.now()-PD.started)/1000)+' 秒';
 };
 update();pdClock=setInterval(update,1000);
}
function pdBusyMessage(){
 const text=PD.executing?(PD.receipt?'清理已完成，正在刷新方案列表…':'正在重新核对引用，并处理已确认的版本和资料…'):'正在读取版本及关联资料…';
 return `<div class="well" role="status"><strong>${text}</strong> <span data-pd-elapsed role="timer" aria-live="off"></span><div><progress aria-label="操作进行中"></progress></div></div>`;
}
function pdDraw(){const d=pdDialog(),i=PD.preview?.inspection,t=i?.target;let body=PD.receipt?pdReceipt(PD.receipt):PD.history?PD.history.length?PD.history.map(r=>`<details><summary>${esc(r.name)} · ${r.removed_versions} 个版本 · ${esc(readableTime(r.completed))}</summary>${pdReceipt(r)}</details>`).join(''):'<p>还没有方案或版本删除记录。</p>':t?`<h3>${esc(t.name)} · ${t.scope==='record'?'整个方案':'版本 '+esc(t.revision)}</h3><p>${esc(i.impact)}</p><p class="muted">核对时间 ${esc(readableTime(PD.preview.created))} · 执行清理前会再次检查引用。 <button data-pd="refresh"${PD.pending?' disabled':''}>重新核对</button></p>${t.versions.length?`<div class="actions"><button data-pd="mode"${PD.pending?' disabled':''}>${i.cleanup?'改为仅删除方案版本':'同时清理专属计算资料'}</button></div>`:''}${i.cleanup?pdCleanupDetails(i.cleanup):''}${i.blocked.length?'<p class="warning" role="alert">'+i.blocked.map(esc).join('；')+'</p>':'<p>本次未发现阻止删除的受管引用。确认前请核对下面范围。</p>'}<h3>本次删除范围</h3>${t.versions.map(v=>`<p>v${esc(v.revision)} · ${esc(v.name)}${t.notes.some(n=>String(n.revision)===String(v.revision))?' · 含当前版本备注':''}</p>`).join('')||'<p>只读来源，无可删除版本。</p>'}<p>${t.latest_after==null?'执行后该方案将不再显示。':t.latest_after!==t.latest_before?'执行后回到 v'+esc(t.latest_after)+'，不改写其内容。':'最新保存版仍为 '+esc(t.latest_after)+'。'} ${t.versions.length?'剩余版本号保持，后续新版本不复用已删除编号。':''}</p>${pdTree(i)}<details><summary>继续保留的资料与检查范围</summary><ul>${i.kept.map(x=>'<li>'+esc(x)+'</li>').join('')}</ul><p>${esc(i.scope_note)}</p></details><label class="check"><input id="pd-confirm" type="checkbox"${PD.pending||i.blocked.length||!t.versions.length?' disabled':''}>${i.cleanup?'我确认清理以上版本、批次和文件，了解恢复需使用已有备份':'我确认仅删除列出的版本及当前备注'}</label>`:'<p role="status">正在核对版本、备注和关联，不删除资料；可以关闭窗口继续查看。</p>';
 d.innerHTML=`<header class="viewer-head"><h2 id="pd-title">方案与版本 · ${PD.history?'清理与删除记录':'方案清理预览'}</h2><button data-pd="close"${PD.executing?' disabled':''}>关闭</button></header><div class="mc-preview-body">${PD.error?'<p class="warning" role="alert">'+esc(PD.error)+'</p>':''}${body}</div><footer class="actions">${PD.pending?pdBusyMessage():''}<button data-pd="close"${PD.executing?' disabled':''}>${PD.receipt||PD.history?'完成':'取消，保留全部版本'}</button>${!PD.receipt&&!PD.history?'<button class="primary" data-pd="execute" disabled>'+ (i?.cleanup?'确认清理列出的资料':'确认删除列出的版本')+'</button>':''}</footer>`;if(PD.executing)d.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);if(!d.open)d.showModal();pdClockStart();}
async function pdPreview(id,revision,cleanup,force=false){
 if(PD.executing)return;
 if(S.dirty||S.usageDirty){notice('当前有未保存编辑，请先保存或撤销，再核对删除。');return;}
 const record=S.boot.records.find(r=>r.id===id);
 const target=JSON.stringify([id,revision??null,record?.revision]);
 if(cleanup===undefined)cleanup=PD.target===target?PD.cleanup:true;
 const key=JSON.stringify([target,cleanup]);
 const dialog=pdDialog(),seq=++PD.sequence;
 const valid=p=>p.expires_epoch*1000>Date.now();
 if(force)pdReads.entries.delete(key);
 const cached=pdReads.entries.get(key);
 const reusable=cached?.ready && valid(cached.value);
 if(reusable && PD.preview===cached.value && !PD.error && !PD.receipt && !PD.history && !PD.pending){
  if(!dialog.open)dialog.showModal();
  const check=dialog.querySelector('#pd-confirm');if(check)check.checked=false;
  dialog.querySelector('[data-pd="execute"]').disabled=true;
  return;
 }
 if(!cached||cached.ready)PD.started=performance.now();
 Object.assign(PD,{target,cleanup,preview:reusable?cached.value:null,receipt:null,history:null,error:'',pending:!reusable});
 pdDraw();
 if(reusable)return;
 try{
  const p=await pdReads.read(key,()=>api('/api/plan-deletion/preview',{
   id,cleanup,scope:revision===undefined?'record':'version',
   ...(revision===undefined?{}:{revision:/^\d+$/.test(revision)?Number(revision):revision})
  }),valid);
  if(seq===PD.sequence)PD.preview=p;
 }catch(e){if(seq===PD.sequence)PD.error=e.message;}
 finally{if(seq===PD.sequence){PD.pending=false;if(dialog.open)pdDraw();}}
}
async function pdRefreshAfterDelete(){await bootstrap();const remaining=S.boot.records.find(r=>r.id===S.id)||S.boot.records[0];S.history=null;S.comparison=null;S.resultComparison=null;S.comparisonData=null;S.compareVersions={};S.planComparisonDraft=null;for(const side of ['left','right'])if(!S.boot.records.some(r=>r.id===S[side]))S[side]=remaining?.id||'';if(remaining){await loadRecord(remaining.id);S.view='editor';}else{S.id='';S.record=null;S.saved=null;S.view='workspace';}render();}
async function pdExecute(){const p=PD.preview;if(PD.pending||!p||p.inspection.blocked.length||!document.getElementById('pd-confirm')?.checked||S.dirty||S.usageDirty)return;PD.pending=true;PD.executing=true;PD.started=performance.now();pdDraw();try{pdReads.entries.clear();PD.receipt=await api('/api/plan-deletion/execute',{id:p.id,sha256:p.sha256,confirmed:true});PD.error='';pdDraw();try{await pdRefreshAfterDelete();}catch(e){PD.error='删除已完成，页面刷新失败；请刷新页面查看。'+e.message;}}catch(e){PD.error=e.message;}finally{PD.pending=false;PD.executing=false;pdDraw();}}
async function pdHistory(){if(PD.executing)return;const seq=++PD.sequence;Object.assign(PD,{preview:null,receipt:null,history:null,pending:true,error:'',started:performance.now()});pdDraw();try{const rows=await api('/api/plan-deletion/history');if(seq===PD.sequence&&pdDialog().open)PD.history=rows;}catch(e){if(seq===PD.sequence)PD.error=e.message;}finally{if(seq===PD.sequence){PD.pending=false;if(pdDialog().open)pdDraw();}}}
document.addEventListener('click',e=>{const b=e.target.closest('[data-pd-record],[data-pd]');if(!b||b.disabled)return;e.preventDefault();e.stopImmediatePropagation();if(b.hasAttribute('data-pd-record')){void pdPreview(b.dataset.pdRecord,b.dataset.pdVersion);return;}if(['mode','refresh'].includes(b.dataset.pd)){const i=PD.preview?.inspection,refresh=b.dataset.pd==='refresh';if(i&&!PD.pending)void pdPreview(i.target.id,i.target.scope==='record'?undefined:String(i.target.revision),refresh?!!i.cleanup:!i.cleanup,refresh);return;}if(b.dataset.pd==='close'){if(!PD.executing){PD.sequence++;pdDialog().close();}return;}if(b.dataset.pd==='history'){void pdHistory();return;}void pdExecute();},true);
document.addEventListener('change',e=>{if(e.target.id==='pd-confirm'){const i=PD.preview?.inspection;pdDialog().querySelector('[data-pd="execute"]').disabled=PD.pending||!e.target.checked||!i?.target.versions.length||!!i.blocked.length;}});
