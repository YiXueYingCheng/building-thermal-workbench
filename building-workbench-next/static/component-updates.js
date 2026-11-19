/* Adopt a single pinned library version; never reset applications or control rules. */
function componentUpdateRequest(){return {id:S.id,revision:S.record.revision,changes:changes()};}
function componentTarget(row){return {id:row.id,revision:row.revision,sha256:row.sha256};}
function componentUpdateContext(){return JSON.stringify({record:weatherContext(),usageDirty:S.usageDirty,usageDraft:S.usageDirty?S.usageDraft:null});}
function materialUpdateLabel(path,p){
 const labels={name:'名称',id:'状态编号',kind:'材料类型',model:'传热模型',thermal_input:'热学输入方式',resistance_m2K_W:'热阻 / m²·K/W',thickness_mm:'厚度 / mm',conductivity_W_mK:'导热系数 / W/(m·K)',areal_capacity_J_m2K:'面热容 / J/(m²·K)',optics_depend_on_state:'光学是否随状态变化',solar_absorptance:'太阳吸收率',emissivity:'热发射率',reflectance:'反射率',input_basis:'光学输入方式'};
 return path.map((key,i)=>path[0]==='states'&&i===1?(p.after.content.states[key]?.name||p.before.content.states[key]?.name||key):labels[key]||({states:'热学状态',optics:'光学',A_R:'A 组 · R 态',A_C:'A 组 · C 态',B_R:'B 组 · R 态',B_C:'B 组 · C 态'})[key]||key).join(' / ');
}
function componentUpdatesMarkup(m){const listing=m.components,p=m.componentPreview;
 return `<section class="well component-source-updates"><div class="row"><h3>建筑配置与材料版本</h3><button data-component-update="refresh"${m.pending||m.componentPending?' disabled':''}>${m.componentPending?'读取中…':'刷新库版本'}</button></div><p class="muted">只查看本方案已绑定配置的较新版本；日计划先在建筑配置中选用，再更新建筑配置版本。</p>${m.componentError?`<p class="warning">${esc(m.componentError)}</p>`:''}
 ${listing?listing.components.map(row=>`<div class="component-update-row"><strong>${esc(row.label)}${row.current?' · '+esc(row.current.name)+' · v'+row.current.revision:''}</strong><p>${esc(row.note)}</p>${row.status==='update_available'?`<button data-component-update="preview" data-component-kind="${row.kind}"${m.pending||m.componentPending?' disabled':''}>核对 ${esc(row.latest.name)} · v${row.latest.revision} 的变化</button>`:''}</div>`).join(''):`<p>${m.componentPending?'正在读取当前绑定版本…':'可刷新库版本重新核对。'}</p>`}
 ${p?`<div class="component-update-preview"><h3>${p.kind==='usage'?'建筑使用配置':'材料'} · v${p.before.revision} → v${p.after.revision}</h3><p>${esc(p.before.name)} → ${esc(p.after.name)}</p>${!p.content_changed?'<p>配置内容相同，仅库名称等版本信息变化。</p>':''}${p.room_diff?roomDifferencesMarkup({differences:p.room_diff,notes:p.notes}):`<div class="table-scroll"><table class="table"><thead><tr><th>变化项</th><th>原版本</th><th>新版本</th></tr></thead><tbody>${p.fields.map(f=>`<tr><td>${esc(materialUpdateLabel(f.path,p))}</td><td>${esc(JSON.stringify(f.before)??'未设置')}</td><td>${esc(JSON.stringify(f.after)??'未设置')}</td></tr>`).join('')}</tbody></table></div>${p.notes.map(n=>`<p>${esc(n)}</p>`).join('')}`}<p>${esc(p.note)}</p><button class="primary" data-component-update="apply"${readonly()||m.pending||m.componentPending?' disabled':''}>采用此版本到当前编辑</button>${readonly()?'<p>当前为只读版本，请先另存为研究方案。</p>':''}<button data-component-update="download">下载本次差异记录</button></div>`:''}</section>`;
}
async function refreshComponentUpdates(m){m.components=null;m.componentPreview=null;m.componentError='';m.componentPending=true;const context=componentUpdateContext();renderWeatherImport();try{const r=await api('/api/source-updates/components',componentUpdateRequest());if(S.weatherImport===m&&context===componentUpdateContext())m.components=r;}catch(e){if(S.weatherImport===m)m.componentError=e.message;}finally{if(S.weatherImport===m){m.componentPending=false;renderWeatherImport();}}}
async function openComponentVersionUpdate(row){
 openWeatherImport('sources');const m=S.weatherImport,context=componentUpdateContext();await refreshComponentUpdates(m);
 if(S.weatherImport!==m||context!==componentUpdateContext())return;
 m.componentPending=true;renderWeatherImport();
 try{const p=await api('/api/source-updates/component-preview',{...componentUpdateRequest(),kind:row.kind,target:componentTarget(row)});if(S.weatherImport===m&&context===componentUpdateContext()){m.componentPreview=p;m.componentContext=context;}}
 catch(e){if(S.weatherImport===m)m.componentError=e.message;}
 finally{if(S.weatherImport===m){m.componentPending=false;renderWeatherImport();}}
}
const beforeComponentUpdateAction=configurationAction;
configurationAction=async function(button){
 const action=button.dataset.componentUpdate;
 if(!action){const result=await beforeComponentUpdateAction(button);if(button.dataset.weatherAction==='sources'&&S.weatherImport?.mode==='sources')await refreshComponentUpdates(S.weatherImport);return result;}
 const m=S.weatherImport;if(!m||m.pending||m.componentPending)return true;
 if(action==='refresh'){await refreshComponentUpdates(m);return true;}
 if(action==='download'&&m.componentPreview){const url=URL.createObjectURL(new Blob([JSON.stringify(m.componentPreview,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`component-update-${S.id}-v${S.record.revision}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return true;}
 m.componentError='';
 if(S.usageDirty){m.componentError='建筑配置还有未保存编辑，请先保存或撤销这些编辑，再核对库更新。';m.componentPreview=null;renderWeatherImport();return true;}
 if(action==='apply'&&(readonly()||!m.componentPreview||m.componentContext!==componentUpdateContext())){m.componentPreview=null;m.componentError='方案或配置已变化，请重新预览可编辑方案。';renderWeatherImport();return true;}
 const context=componentUpdateContext(),selected=action==='apply'?m.componentPreview.after:m.components?.components.find(r=>r.kind===button.dataset.componentKind)?.latest;
 if(!selected)return true;
 m.componentPending=true;if(action==='preview')m.componentPreview=null;renderWeatherImport();
 try{
  const p=await api('/api/source-updates/component-preview',{...componentUpdateRequest(),kind:selected.kind,target:componentTarget(selected)});
  if(S.weatherImport!==m||context!==componentUpdateContext())return true;
  if(action==='preview'){m.componentPreview=p;m.componentContext=context;}
  else{
   if(p.kind==='usage'){setPath('factors.building.usage_profile',copy(p.after));if(S.configuration)resetUsageDraft();S.roomUndo=null;}
   else{const materials=copy(S.record.factors.materials);materials.definitions=[copy(p.after.content)];materials.definition_reference=copy(p.after);setPath('factors.materials',materials);S.materialParent=copy(p.after);}
   closeWeatherImport();notice('已采用明确的库版本到当前编辑；请保存方案版本。材料应用和工况规则保持。');return true;
  }
 }catch(e){if(S.weatherImport===m){m.componentPreview=null;m.componentError=e.message;}}
 finally{if(S.weatherImport===m){m.componentPending=false;renderWeatherImport();}}
 return true;
};
