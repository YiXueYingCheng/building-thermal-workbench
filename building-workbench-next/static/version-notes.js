/* Notes have their own concurrency token and never enter a calculation record. */
let versionNoteDialogState=null;
function versionNoteRow(record){return S.boot?.version_notes?.find(n=>n.record_id===record.id&&String(n.revision)===String(record.revision));}
function versionNoteText(record){return versionNoteRow(record)?.note||'';}
function versionNoteLabel(record,max=64){const text=versionNoteText(record).replace(/\s+/g,' ');return text?(text.length>max?text.slice(0,max)+'…':text):'未填写备注';}
function versionNoteMarkup(record,editable=false){
 const note=versionNoteRow(record);
 return `<div class="version-note"><span class="muted">${esc(planVersionLabel(record))} 备注</span><p class="note-text">${esc(note?.note||'未填写备注')}</p>${editable?`<button data-version-note="${esc(record.id)}" data-note-revision="${esc(record.revision)}">${note?.note?'编辑':'添加'}此版本备注</button>`:''}${note?.updated_at?`<small class="muted">备注更新于 ${esc(readableTime(note.updated_at))}</small>`:''}</div>`;
}
function versionNoteDialog(){let d=document.getElementById('version-note-dialog');if(!d){d=document.createElement('dialog');d.id='version-note-dialog';document.body.append(d);d.addEventListener('cancel',e=>{if(versionNoteDialogState?.pending)e.preventDefault();});}return d;}
async function editVersionNote(id,revision){
 const row=await api('/api/version-notes/'+encodeURIComponent(id)+'?revision='+encodeURIComponent(revision));
 versionNoteDialogState={...row,pending:false};const d=versionNoteDialog();
 d.innerHTML=`<header class="viewer-head"><h2>保存版本 ${esc(revision)} 的备注</h2><button data-note-close>关闭</button></header><div class="viewer-body"><p>备注只解释这个保存版本，可随时补写；不会新增方案版本或重新计算。</p><label class="field">版本备注<textarea id="version-note-text" rows="6" maxlength="2000">${esc(row.note)}</textarea></label><p id="version-note-feedback" role="status"></p></div><footer class="viewer-foot"><button data-note-close>取消</button><button class="primary" data-note-save>保存备注</button></footer>`;
 d.showModal();d.querySelector('textarea').focus();
}
async function versionNoteAction(button){
 if(button.dataset.versionNote!==undefined){await editVersionNote(button.dataset.versionNote,button.dataset.noteRevision);return true;}
 if(button.hasAttribute('data-note-close')){if(!versionNoteDialogState?.pending)versionNoteDialog().close();return true;}
 if(!button.hasAttribute('data-note-save'))return false;
 const state=versionNoteDialogState,d=versionNoteDialog();if(!state||state.pending)return true;
 state.pending=true;d.querySelectorAll('button,textarea').forEach(x=>x.disabled=true);
 try{
  const row=await api('/api/version-notes',{id:state.record_id,revision:/^\d+$/.test(state.revision)?Number(state.revision):state.revision,note:d.querySelector('textarea').value,expected_generation:state.generation});
  S.boot.version_notes=(S.boot.version_notes||[]).filter(n=>!(n.record_id===row.record_id&&String(n.revision)===row.revision));S.boot.version_notes.push(row);
  d.close();render();notice('版本备注已保存；方案版本和已有结果保持原样。');
 }catch(e){d.querySelector('#version-note-feedback').textContent=e.message;}
 finally{state.pending=false;d.querySelectorAll('button,textarea').forEach(x=>x.disabled=false);}
 return true;
}
let copyDialogState=null;
function openCopyDialog(){
 if(S.usageDirty)throw usagePendingError('另存方案');
 let d=document.getElementById('copy-plan-dialog');if(!d){d=document.createElement('dialog');d.id='copy-plan-dialog';document.body.append(d);d.addEventListener('cancel',e=>{if(copyDialogState?.pending)e.preventDefault();});}
 const c=changes();if(c.name===S.saved.name)c.name=(c.name+' · 新方案').slice(0,100);
 copyDialogState={source_id:S.id,base_revision:S.saved.revision,changes:copy(c),pending:false};
 d.innerHTML=`<header class="viewer-head"><h2>另存为研究方案</h2><button data-copy-close>关闭</button></header><div class="viewer-body"><label class="field">新方案名称<input id="copy-plan-name" maxlength="100" value="${esc(c.name)}"></label><p>确认后创建新方案 v1，包含当前四因素编辑。原方案和已有结果保留。</p><p id="copy-plan-feedback" role="status"></p></div><footer class="viewer-foot"><button data-copy-close>取消</button><button class="primary" data-copy-confirm>确认另存</button></footer>`;
 d.showModal();d.querySelector('input').focus();d.querySelector('input').select();
}
async function copyPlanAction(button){
 const d=document.getElementById('copy-plan-dialog'),v=copyDialogState;
 if(button.hasAttribute('data-copy-close')){if(!v?.pending)d?.close();return true;}
 if(!button.hasAttribute('data-copy-confirm'))return false;
 if(!v||v.pending)return true;
 const name=d.querySelector('input').value.trim();if(!name){d.querySelector('#copy-plan-feedback').textContent='请填写新方案名称。';return true;}
 v.pending=true;d.querySelectorAll('button,input').forEach(x=>x.disabled=true);
 try{const r=await api('/api/drafts',{source_id:v.source_id,base_revision:v.base_revision,changes:{...v.changes,name}});S.dirty=false;d.close();await bootstrap();await loadRecord(r.id);render();notice('已按新名称另存为 v1。');}
 catch(e){d.querySelector('#copy-plan-feedback').textContent=e.message;}
 finally{v.pending=false;d.querySelectorAll('button,input').forEach(x=>x.disabled=false);}
 return true;
}
