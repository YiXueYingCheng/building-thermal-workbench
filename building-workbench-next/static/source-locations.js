function sourceLocationButton(f){return !f.roles.includes('计算引擎')&&['matches','missing'].includes(f.status)?`<button data-source-location="choose" data-location-target="${esc(f.path)}">${f.relocation?'更换登记位置…':'登记新位置…'}</button>`:'';}
function sourceLocationsMarkup(m){let html='';const r=m.locationChoice;
 if(r)html=`<section class="well source-update-section" aria-label="来源位置登记"><div class="row"><h3>${r.action==='revoke'?'撤销来源位置登记':'登记来源的新位置'}</h3><button data-source-location="cancel">取消本次操作</button></div><p>原引用<small class="source-path">${esc(r.target)}</small></p>${r.action==='register'?`<label class="field">新位置文件<input data-location-candidate value="${esc(r.candidate)}" placeholder="选择搬迁后的原文件副本"></label><div class="actions"><button data-source-location="browse">浏览文件…</button><button data-source-location="preview">核对位置与影响</button></div>`:''}${r.preview?`<div class="source-location-preview source-update-section"><p>原路径状态：${esc(weatherStatuses[r.preview.original_status]||r.preview.original_status)}</p>${r.preview.candidate?`<p>新位置内容与原引用一致<small class="source-path">${esc(r.preview.candidate.path)}</small></p>`:''}<p>${esc(r.preview.note)}</p><div class="actions"><button class="primary" data-source-location="apply">${r.action==='revoke'?'确认撤销登记':'采用这个文件位置'}</button></div></div>`:'<p class="muted">仅登记相同内容的位置关系，不移动或复制文件。取消和关闭预览不会写入登记。</p>'}</section>`;
 const active=m.audit?.files.filter(f=>f.relocation)||[];
 if(active.length)html+=`<section class="well source-update-section" aria-label="已登记来源位置"><h3>后续读取使用的新位置 · ${active.length}</h3><p class="muted">原引用保留用于追溯。已有输入包和批次仍绑定生成时路径。</p>${active.map(f=>`<div class="source-recovery-entry"><p>${esc(f.roles.join('、'))} · ${esc(weatherStatuses[f.status])}<small class="source-path">原引用：${esc(f.path)}</small><small class="source-path">当前读取：${esc(f.actual_path)}</small></p><div class="actions"><button data-source-location="choose" data-location-target="${esc(f.path)}">更换登记位置…</button><button data-source-location="revoke" data-location-target="${esc(f.path)}">预览撤销登记</button></div></div>`).join('')}</section>`;
 const history=m.audit?.location_history||[];
 if(history.length)html+=`<details><summary>来源位置登记历史 · ${history.length} 条</summary>${[...history].reverse().map(row=>`<section class="source-recovery-entry"><p>${row.action==='register'?'登记新位置':'撤销登记'} · 版本 ${row.revision} · ${esc(row.created)}<small class="source-path">${esc(row.target.path)}</small></p><button data-source-location="download" data-location-id="${esc(row.id)}">下载位置回执</button></section>`).join('')}</details>`;
 return html;
}
const beforeSourceLocationAction=configurationAction;
configurationAction=async function(button){const action=button.dataset.sourceLocation;if(!action)return beforeSourceLocationAction(button);const m=S.weatherImport;if(!m||m.pending)return true;
 if(action==='cancel'){m.locationChoice=null;m.message='已取消本次位置操作，没有写入登记。';renderWeatherImport();return true;}
 if(action==='download'){const row=m.audit?.location_history.find(r=>r.id===button.dataset.locationId);if(row){const url=URL.createObjectURL(new Blob([JSON.stringify(row,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=row.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}return true;}
 if(action==='choose'||action==='revoke'){const f=m.audit?.files.find(f=>f.path===button.dataset.locationTarget&&!f.roles.includes('计算引擎'));if(!f)return true;m.recovery=null;m.locationChoice={target:f.path,candidate:f.actual_path||'',action:action==='revoke'?'revoke':'register',preview:null};m.message='';renderWeatherImport();if(action==='choose')return true;}
 const r=m.locationChoice;if(!r)return true;const context=weatherContext();m.pending=true;m.message='正在处理…';renderWeatherImport();
 try{
  if(action==='browse'){const result=await api('/api/source-updates/recovery-browse',{path:r.candidate});if(S.weatherImport!==m)return true;if(result.path&&result.path!==r.candidate){r.candidate=result.path;r.preview=null;}m.message=result.cancelled?'已取消选文件。':'';}
  if(action==='preview'||action==='revoke'){r.preview=null;const result=await api('/api/source-updates/location-preview',{id:S.id,revision:S.record.revision,changes:changes(),target:r.target,candidate:r.candidate,action:r.action});if(S.weatherImport!==m||context!==weatherContext())return true;r.preview=result;r.context=context;m.message='预览完成，尚未改变位置登记。';}
  if(action==='apply'){
   if(!r.preview||r.context!==weatherContext()){r.preview=null;throw Error('当前方案或预览已变化，请重新核对。');}
   const result=await api('/api/source-updates/location-commit',{id:S.id,revision:S.record.revision,changes:changes(),target:r.target,candidate:r.candidate,action:r.action,expected_plan:r.preview.plan_sha256});await bootstrap();await refreshCapability();
   const message=result.action==='register'?'新位置已登记。后续生成输入使用新位置；已有输入包和批次保持原绑定。':'位置登记已撤销。后续读取使用原路径，既有输入包保持。';
   if(S.weatherImport!==m){notice(message);return true;}m.locationChoice=null;m.message=message;
   const audit=await api('/api/source-updates/audit',{id:S.id,revision:S.record.revision,changes:changes()});if(S.weatherImport===m)m.audit=audit;
  }
 }catch(e){if(S.weatherImport===m){r.preview=null;m.message=e.message;}}
 finally{if(S.weatherImport===m){m.pending=false;renderWeatherImport();}}
 return true;
};
document.addEventListener('input',e=>{if(!e.target.matches('[data-location-candidate]'))return;const r=S.weatherImport?.locationChoice;if(r){r.candidate=e.target.value;r.preview=null;weatherDialog().querySelector('.source-location-preview')?.remove();}});
