/* Manage comparison bindings without changing either simulation. */
function relationButton(row) {
 return `<button type="button" data-relation-kind="${esc(row.kind)}" data-relation-id="${esc(row.id)}">${esc(row.label)}</button>`;
}
function relationDialog(title) {
 const dialog=document.createElement('dialog');
 dialog.className='library-adoption';
 dialog.setAttribute('aria-label',title);
 dialog.innerHTML=`<header class="viewer-head"><h2>${esc(title)}</h2><button data-close>关闭</button></header><div class="mc-preview-body" aria-live="polite">正在读取关系…</div>`;
 document.body.append(dialog);
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();
 dialog.addEventListener('close',()=>dialog.remove(),{once:true});
 dialog.showModal();
 return dialog;
}
async function listStudyRelations(dialog) {
 const body=dialog.querySelector('.mc-preview-body');
 try {
  const rows=await api('/api/study-relations');
  body.innerHTML=rows.map(r=>`<div class="row"><span>${esc(r.name)} · ${esc(r.title)}</span>${relationButton(r)}</div>`).join('')||'<p>还没有已保存的比较或对比集。</p>';
 } catch(e) { body.textContent=e.message; }
}
async function manageStudyRelation(button) {
 const kind=button.dataset.relationKind,id=button.dataset.relationId;
 const parent=button.closest('dialog');
 const dialog=relationDialog(button.textContent),body=dialog.querySelector('.mc-preview-body');
 try {
  const p=await api('/api/study-relations/preview',{kind,id});
  if(!dialog.open)return;
  const note=kind==='comparison'?'此比较在各集中的收录和逐地点步长选择将一起移除。'
   :kind==='design'?'移除这份设计的所有保存版本。':'解散后移除这个集的成员关系、收录及集版本。成员方案仍可单独打开，两两比较仍在比较库中。';
  body.innerHTML=`<h3>${esc(p.name)} · ${esc(p.title)}</h3><p>${note} 双方的方案版本、计算批次和原始结果都保留。</p>
   <ul>${p.counts.map(r=>`<li>${esc(r.label)} · ${esc(r.count)} 项</li>`).join('')}</ul>
   ${p.collection_names.length?'<p>收录这一比较的对比集：'+p.collection_names.map(esc).join('、')+'</p>':''}
   ${p.preparations?'<p>已有的组准备记录与已提交批次保留。解散后不能从该集继续准备或提交。</p>':''}
   <p>恢复已移除的关系需要备份。</p>
   <button class="primary" data-remove>确认${esc(p.verb)}</button> <button data-cancel>取消</button><p role="alert"></p>`;
  body.querySelector('[data-cancel]').onclick=()=>dialog.close();
  body.querySelector('[data-remove]').onclick=async()=>{
   const controls=dialog.querySelectorAll('button');
   controls.forEach(b=>b.disabled=true);
   const busy=e=>e.preventDefault();
   dialog.addEventListener('cancel',busy);
   try {
    await api('/api/study-relations/remove',{kind,id,sha256:p.sha256,confirmed:true});
   } catch(e) {
    body.querySelector('[role=alert]').textContent=e.message;
    controls.forEach(b=>b.disabled=false);
    dialog.removeEventListener('cancel',busy);
    return;
   }
   dialog.close();
   pdReads.entries.clear();
   const inspection=parent?.id==='plan-deletion' && PD.preview?.inspection;
   if(inspection)void pdPreview(inspection.target.id,inspection.target.scope==='record'?undefined:inspection.target.revision,!!inspection.cleanup);
   try {
    await bootstrap();
    if(kind==='comparison' && S.resultComparison?.comparison?.id===id){
     resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;
    }
    const openedFromGroup=!parent && ['reading','set'].includes(kind);
    if(openedFromGroup && ['collection-home','research-sets'].includes(S.view)){
     if(RS.current?.id===id){RS.epoch++;RS.current=null;RS.results=null;rsPoll();}
     await listReadingGroups(null);
    }else if(S.view==='compare')render();
    if(parent?.open && !inspection){
     if(parent.hasAttribute('data-study-relations'))await listStudyRelations(parent);
     else await listReadingGroups(parent);
    }
    notice(p.name+' · 已'+p.verb);
   } catch(e) { notice('关系已解除。刷新列表时遇到问题：'+e.message,'warning'); }
  };
 } catch(e) {body.textContent=e.message;}
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-relation-list],[data-relation-kind]');
 if(!button || button.disabled)return;
 e.preventDefault();e.stopImmediatePropagation();
 if(button.hasAttribute('data-relation-list')){
  const dialog=relationDialog('管理比较与对比集');dialog.setAttribute('data-study-relations','');
  void listStudyRelations(dialog);
 }else void manageStudyRelation(button);
},true);
