/* A file recovery restores pinned bytes at the shared path; it never edits a recipe. */
const recoveryStatuses={prepared:'操作未完成，请核对原路径',restored:'已恢复',failed:'未恢复',needs_review:'需核对'};
function sourceRecoveryMarkup(m){let html='';const r=m.recovery;
 if(r)html=`<section class="well source-update-section" aria-label="恢复缺失引用"><div class="row"><h3>恢复缺失引用</h3><button data-source-recovery="cancel">取消本次恢复</button></div><p>原引用路径<small class="source-path">${esc(r.target)}</small></p><label class="field">原文件副本路径<input data-recovery-candidate value="${esc(r.candidate)}" placeholder="选择或填写原文件副本的完整路径"></label><div class="actions"><button data-source-recovery="browse">浏览副本…</button><button data-source-recovery="inspect">核对副本与恢复影响</button></div>${r.preview?`<div class="source-recovery-preview source-update-section"><p>副本内容与原引用完全一致 · ${(r.preview.candidate.bytes/1024/1024).toFixed(2)} MiB<small class="source-path">SHA-256：${esc(r.preview.target.expected_sha256)}</small></p><p>${esc(r.preview.note)}</p><div class="actions"><button class="primary" data-source-recovery="restore">恢复到原路径</button></div></div>`:'<p class="muted">仅恢复缺失文件，已有文件不会被覆盖。先检查内容，再执行恢复。</p>'}</section>`;
 const history=m.audit?.recoveries||[];
 if(history.length)html+=`<details class="source-recovery-history"><summary>本方案引用的恢复记录 · ${history.length} 条</summary>${history.map((x,i)=>`<section class="source-recovery-entry"><p><strong>${esc(recoveryStatuses[x.status]||x.status)}</strong> · ${esc(x.created)}<small class="source-path">${esc(x.plan.target.path)}</small></p>${x.error?`<p>${esc(x.error)}</p>`:''}<button data-source-recovery="download" data-recovery-index="${i}">下载恢复回执</button></section>`).join('')}<p class="muted">记录表示当时操作；当前文件状态以上方本次核对为准。</p></details>`;
 return html;
}
const beforeSourceRecoveryAction=configurationAction;
configurationAction=async function(button){const action=button.dataset.sourceRecovery;if(!action)return beforeSourceRecoveryAction(button);const m=S.weatherImport;if(!m||m.pending)return true;
 if(action==='choose'){m.locationChoice=null;const target=button.dataset.recoveryPath;if(!m.audit?.files.some(f=>f.path===target&&f.status==='missing'&&!f.roles.includes('计算引擎')))return true;m.recovery={target,candidate:'',preview:null};m.message='';renderWeatherImport();return true;}
 if(action==='cancel'){m.recovery=null;m.message='已取消本次恢复；原路径未写入。';renderWeatherImport();return true;}
 if(action==='download'){const row=m.audit?.recoveries[Number(button.dataset.recoveryIndex)];if(row){const url=URL.createObjectURL(new Blob([JSON.stringify(row,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=row.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}return true;}
 const r=m.recovery;if(!r)return true;const context=weatherContext();m.pending=true;m.message='正在核对…';renderWeatherImport();
 try{
  if(action==='browse'){const out=await api('/api/source-updates/recovery-browse',{path:r.candidate});if(S.weatherImport!==m)return true;if(out.path&&out.path!==r.candidate){r.candidate=out.path;r.preview=null;}m.message=out.cancelled?'已取消选文件，原路径保留。':'';}
  if(action==='inspect'){r.preview=null;const p=await api('/api/source-updates/recovery-preview',{id:S.id,revision:S.record.revision,changes:changes(),target:r.target,candidate:r.candidate});if(S.weatherImport!==m||context!==weatherContext())return true;r.preview=p;r.context=context;m.message='副本核对通过，尚未写入原路径。';}
  if(action==='restore'){
   if(!r.preview||r.context!==weatherContext()){r.preview=null;throw Error('方案或恢复预览已变化，请重新核对副本。');}
   const result=await api('/api/source-updates/recover',{id:S.id,revision:S.record.revision,changes:changes(),target:r.target,candidate:r.candidate,expected_plan:r.preview.plan_sha256});
   const message=result.status==='restored'?'原引用文件已恢复，回执已保存。方案和计算队列未修改。':'恢复后需要核对，请查看回执。';
   if(S.weatherImport!==m){notice(message);return true;}
   m.recovery=null;m.message=message;
   const audit=await api('/api/source-updates/audit',{id:S.id,revision:S.record.revision,changes:changes()});if(S.weatherImport===m)m.audit=audit;
  }
 }catch(e){if(S.weatherImport===m){r.preview=null;m.message=e.message;}}
 finally{if(S.weatherImport===m){m.pending=false;renderWeatherImport();}}
 return true;
};
document.addEventListener('input',e=>{if(!e.target.matches('[data-recovery-candidate]'))return;const r=S.weatherImport?.recovery;if(r){r.candidate=e.target.value;r.preview=null;weatherDialog().querySelector('.source-recovery-preview')?.remove();}});
