/* Local editing, explicit component saves, then explicit scheme-version saves. */
function usageRoomType(room){
 const source=S.configuration?.data?.usage_sources?.[room.id]||{},name=String(source.use||'').trim();
 return {name:name||'用途未标注',key:name?(source.room_type_id!=null?'id:'+source.room_type_id:'name:'+name):'',legacy:name&&source.room_type_id==null};
}
S.configuration=null;S.usageDraft=null;S.usageDirty=false;S.usageRoom=0;S.usageChannel='people';S.componentLists={usage:[],material:[]};S.materialLibraryOpen=false;
function configurationSupported(){return ['global_frozen_v011','ordinary_building_v1'].includes(S.record?.provenance.adapter);}
function usageMembershipText(){const r=S.usageDraft?.rooms||[];const n=r.filter(x=>x.conditioned).length;return `保持原 ${n} 间空调房、${r.length-n} 间非空调房`; }
function resetConfiguration(){S.configuration=null;S.usageDraft=null;S.usageDirty=false;S.usageRoom=0;S.materialLibraryOpen=false;S.operationOpen=false;S.envelopeTarget=null;S.envelopeOpen=false;S.constructionOpen=false;S.materialParent=S.record?.factors.materials.definition_reference||null;}
function configurationPathChanged(path){
 if(path.startsWith('factors.materials.definitions.')){S.materialParent=S.record.factors.materials.definition_reference||S.materialParent;delete S.record.factors.materials.definition_reference;}
 if(path==='factors.condition.operation.mode'&&S.record.provenance.adapter==='global_frozen_v011')S.record.factors.condition.operation.settings='drawing26_usage';
}
async function loadConfiguration(){
 const key=S.id+':'+S.saved.revision;
 if(S.configuration?.key===key)return;
 const data=await api('/api/configuration/'+encodeURIComponent(S.id)+'?revision='+encodeURIComponent(S.saved.revision));
 S.configuration={key,data};resetUsageDraft();
}
function resetUsageDraft(){const p=S.record.factors.building.usage_profile;S.usageDraft=copy(p?.content||S.configuration.data.base);S.usageName=p?.name||S.record.factors.building.name+' 房间使用';S.usageDirty=false;}
function usagePendingError(intent='切换方案'){
 if(typeof showRoomUnsavedWarning==='function')showRoomUnsavedWarning(intent);
 return new Error(`房间配置与作息尚未保存，暂不能${intent}。请打开“房间配置与作息”，保存全部房间配置并保存方案版本，或明确撤销房间修改。当前编辑仍保留。`);
}
const roomChannels={people:'人员 / 人',lighting:'照明输入 / W 每间',equipment:'设备输入 / W 每间',available:'空调可用 / 0 或 1'};
const temperatureLabels={low:'供暖启动',heat:'供暖停止',cool:'制冷停止',high:'制冷启动'};
function displayUsageNumber(v){return typeof v==='number'?Number(v.toPrecision(12)):v;}
function dayTable(value,attribute,locked=false){return `<div class="table-scroll"><table class="table day-editor"><thead><tr><th>时段</th><th>工作日</th><th>周末</th></tr></thead><tbody>${Array.from({length:24},(_,h)=>`<tr><th>${h}:00–${h+1}:00</th>${['weekday','weekend'].map(day=>`<td><input type="number" step="any" min="0" ${attribute} data-day="${day}" data-hour="${h}" value="${esc(displayUsageNumber(value[day][h]))}"${locked||readonly()?' disabled':''} aria-label="${day==='weekday'?'工作日':'周末'} ${h}点"></td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function componentOptions(kind,selected){return `<option value="">请选择已保存版本</option>${S.componentLists[kind].map((r,i)=>`<option value="${i}"${selected?.id===r.id&&selected?.revision===r.revision?' selected':''}>${esc(r.name)} · 版本 ${r.revision}</option>`).join('')}`;}
const originalBuildingPanel=buildingPanel;
buildingPanel=function(){
 const b=S.record.factors.building,p=b.usage_profile,d=S.configuration?.data;
 if(!configurationSupported())return originalBuildingPanel()+'<p class="muted">此旧来源暂沿用原房间配置；本轮编辑先在 Drawing26 全球来源接通。</p>';
 let html=originalBuildingPanel()+`<div class="configuration-toolbar"><p>建筑使用配置：${p?esc(p.name)+' · 版本 '+p.revision:'原冻结默认配置'}</p><div class="actions"><button data-configuration="load">${d?'重新查看配置':'查看房间与作息'}</button><button data-configuration="usage-list">选择已有建筑配置</button></div>${S.componentLists.usage.length?`<select data-component-use="usage"${disabled()}>${componentOptions('usage',p)}</select>`:''}</div>`;
 if(!d||!S.usageDraft)return html;
 const room=S.usageDraft.rooms[S.usageRoom],channel=room.hvac?S.usageChannel:S.usageChannel==='available'?'people':S.usageChannel;
 const value=channel==='available'?room.hvac.available:room.loads[channel];
 html+=`<section class="well usage-editor"><div class="row"><h3>房间与建筑默认运行</h3><span id="usage-edit-status">${S.usageDirty?'配置有未保存修改':'配置已读取'}</span></div><p class="muted">${usageMembershipText()}。作息输入为该小时的实际人数或功率，空调可用计划独立设置。</p><label class="field">配置名称<input id="usage-name" value="${esc(S.usageName)}"${disabled()}></label><div class="grid2"><label class="field">房间<select id="usage-room">${S.usageDraft.rooms.map((r,i)=>`<option value="${i}"${i===S.usageRoom?' selected':''}>${esc(r.zone)} · ${esc(usageRoomType(r).name)} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</option>`).join('')}</select></label><label class="field">使用计划<select id="usage-channel">${Object.entries(roomChannels).filter(([k])=>k!=='available'||room.hvac).map(([k,v])=>`<option value="${k}"${k===channel?' selected':''}>${v}</option>`).join('')}</select></label></div>${dayTable(value,'data-usage-hour="'+channel+'"')}${room.hvac?`<details><summary>此房间的默认启停温度</summary><div class="grid2">${Object.entries(temperatureLabels).map(([k,v])=>`<label class="field">${v} / °C<input type="number" step="any" data-usage-temperature="${k}" value="${room.hvac[k]}"${disabled()}></label>`).join('')}</div><p class="muted">本模型保留四个启停温度及原回差控制；工况可显式覆盖这些值。</p></details>`:''}<div class="actions"><button data-configuration="usage-save" class="primary"${disabled()}>保存配置版本并用于当前草稿</button><button data-configuration="usage-discard">撤销配置编辑</button></div><p class="muted">这里只保存建筑配置版本；当前方案还需“保存版本”。其他方案不会自动更新。</p></section>`;
 return html;
};
function controlPresetToolbar(){return S.record.factors.materials.definitions.length?`<div class="actions control-presets">${[['fixed','固定'],['calendar','季节翻面'],['feedback','热阻反馈'],['combined','反馈加翻面']].map(([k,label])=>`<button data-control-preset="${k}"${disabled()}>${label}</button>`).join('')}</div><p class="muted">预设只组织工况；缺少本地日历或对应物性时会提示。热学与朝向仍可在工况中分别调整。</p>`:'';}
const originalConditionPanel=conditionPanel;
conditionPanel=function(){
 let html=originalConditionPanel();if(!configurationSupported())return html;
 html=controlPresetToolbar()+html;
 const content=S.record.factors.building.usage_profile?.content||S.configuration?.data.base;
 html+=`<div class="configuration-toolbar"><button data-configuration="operation">查看运行默认值与覆盖</button></div>`;
 if(!content||!S.operationOpen)return html;
 const overrides=S.record.factors.condition.operation.overrides||{};
 return html+`<div class="usage-overrides"><h3>建筑默认与本方案覆盖</h3><p class="muted">默认来自${S.record.factors.building.usage_profile?'所选建筑配置版本':'原冻结建筑'}。人员、照明和设备计划在建筑中维护；清除覆盖后恢复此处默认。</p>${content.rooms.filter(r=>r.conditioned).map(r=>{const o=overrides[r.id],v={...r.hvac,...o};return `<details class="well"><summary>${esc(r.zone)} · ${o?'本方案覆盖':'继承建筑默认'}</summary><p>默认启停：${Object.entries(temperatureLabels).map(([k,label])=>label+' '+r.hvac[k]+' °C').join('，')}</p>${o?`<div class="grid2">${Object.entries(temperatureLabels).map(([k,label])=>number(label+' / °C',`factors.condition.operation.overrides.${r.id}.${k}`,v[k])).join('')}</div><details><summary>本方案的空调可用计划</summary>${dayTable(v.available,'data-operation-hour="'+r.id+'"')}</details><button data-clear-operation="${r.id}"${disabled()}>清除覆盖，恢复建筑默认</button>`:`<button data-override-operation="${r.id}"${disabled()}>为本方案设置覆盖</button>`}</details>`;}).join('')}</div>`;
};
const originalMaterialsPanel=materialsPanel;
materialsPanel=function(){
 if(S.record.provenance.adapter!=='global_frozen_v011')return originalMaterialsPanel()+'<p class="muted">此旧动态来源保留原材料应用与控制。建筑配置和材料库选择先在 Drawing26 全球来源接通。</p>';
 const m=S.record.factors.materials,ref=m.definition_reference;
 const html=`<div class="configuration-toolbar"><div class="actions"><button data-configuration="material-list">选择 / 添加材料</button>${m.definitions.length?`<button data-configuration="material-save"${disabled()}>保存当前材料版本</button><button data-configuration="remove-material"${disabled()}>移除研究层，使用 W00</button>`:''}<button data-configuration="construction">核对基础构造与研究层</button></div>${ref?`<p>材料版本：${esc(ref.name)} · 版本 ${ref.revision}</p>`:'<p class="muted">当前材料物性随方案快照保存。</p>'}${S.materialLibraryOpen?`<div class="well"><button data-configuration="default-material"${disabled()}>选用当前已核实的 ECA 模板</button><label class="field">已保存材料版本<select data-component-use="material"${disabled()}>${componentOptions('material',ref)}</select></label></div>`:''}</div>`;
 const wallData=S.configuration?.data.walls;
 return html+originalMaterialsPanel()+`${m.definitions.length?`<label class="field">材料名称<input data-path="factors.materials.definitions.0.name" value="${esc(m.definitions[0].name)}"${disabled()}></label>`:''}${S.constructionOpen&&wallData?`<details class="well configuration-construction" open><summary>实际构造与作用墙面</summary><p>${m.definitions.length?'基础构造从外到内列出。当前执行接法为原 14 段外墙外侧等效热阻层；所选位置和范围不符时按能力提示待适配。':'W00 不含新增研究层；关闭反馈本身不等于移除材料。'}</p><div class="table-scroll"><table class="table"><thead><tr><th>墙面 / 房间</th><th>基础构造，从外到内</th><th>研究层</th><th>反馈范围</th></tr></thead><tbody>${wallData.map(w=>`<tr><td>${esc(w.id)} / ${esc(w.zone)}</td><td>${w.layers.map(esc).join(' → ')}</td><td>${m.definitions.length&&m.applications.some(a=>a.target_ids.includes(w.id))?esc(m.definitions[0].name)+' · '+esc(({exterior:'外侧等效层',interior:'内侧（待适配）',between:'层间（待适配）'})[m.applications[0]?.position]||'待适配'):'无'}</td><td>${w.feedback_eligible?'原 7 段参与墙':'固定状态'}</td></tr>`).join('')}</tbody></table></div></details>`:''}`;
};
function applyMaterial(definition,reference=null){
 S.materialParent=reference;const d=S.configuration.data,m=copy(d.material_template);m.definitions=[copy(definition)];m.applications[0].material_id=definition.id;
 if(reference)m.definition_reference=copy(reference);setPath('factors.materials',m);
 setPath('factors.condition.controls',copy(d.controls_template));
}
async function configurationAction(button){
 const a=button.dataset.configuration,kind=button.dataset.componentUse;
 if(S.usageDirty&&(['save','copy','discard','preview','generate','prepare-execution'].includes(button.dataset.action)||button.dataset.record||button.dataset.revision))throw usagePendingError(button.dataset.record?'切换方案':button.dataset.revision?'切换版本':({save:'保存方案版本',copy:'另存方案',discard:'撤销方案编辑',preview:'核对计算安排',generate:'生成模型输入','prepare-execution':'准备计算'})[button.dataset.action]);
 if(button.dataset.overrideOperation){await loadConfiguration();const id=button.dataset.overrideOperation,c=S.record.factors.building.usage_profile?.content||S.configuration.data.base;const o=copy(S.record.factors.condition.operation.overrides||{});o[id]=copy(c.rooms.find(r=>r.id===id).hvac);setPath('factors.condition.operation.overrides',o);return true;}
 if(button.dataset.clearOperation){const o=copy(S.record.factors.condition.operation.overrides);delete o[button.dataset.clearOperation];setPath('factors.condition.operation.overrides',o);return true;}
 if(button.dataset.controlPreset){
  const preset=button.dataset.controlPreset;await loadConfiguration();const c=copy(S.configuration.data.controls_template);
  if(['feedback','combined'].includes(preset))Object.assign(c[0],{mode:'feedback',rule:'UNIFIED',policy:copy(S.boot.control_policy),update:{kind:'solver_step'},state_roles:copy(stateRoles())});
  if(['calendar','combined'].includes(preset))Object.assign(c[2],{mode:'calendar',reference_id:S.record.factors.condition.reference_runs[0]?.id||'season_reference'});
  setPath('factors.condition.controls',c);S.factor='condition';return true;
 }
 if(!a)return false;
 if(a==='load'||a==='operation'||a==='construction'){await loadConfiguration();if(a==='operation')S.operationOpen=true;if(a==='construction')S.constructionOpen=!S.constructionOpen;return true;}
 if(a==='usage-discard'){resetUsageDraft();return true;}
 if(a==='usage-list'||a==='material-list'){await loadConfiguration();const k=a==='usage-list'?'usage':'material';S.componentLists[k]=await api('/api/components/'+k);if(k==='usage')S.componentLists[k]=S.componentLists[k].filter(r=>r.content.building_id===S.configuration.data.base.building_id);if(k==='material')S.materialLibraryOpen=!S.materialLibraryOpen;return true;}
 if(a==='usage-save'){
  const old=S.record.factors.building.usage_profile;
  const row=await api('/api/components',{kind:'usage',name:S.usageName,content:S.usageDraft,parent:old?{id:old.id,revision:old.revision}:null});
  setPath('factors.building.usage_profile',row);S.usageDirty=false;notice('建筑配置版本已保存并选入当前草稿；请保存方案版本。');return true;
 }
 if(a==='material-save'){
  const m=S.record.factors.materials,d=m.definitions[0],old=m.definition_reference||S.materialParent;
  const row=await api('/api/components',{kind:'material',name:d.name,content:d,parent:old?{id:old.id,revision:old.revision}:null});
  S.materialParent=row;setPath('factors.materials.definition_reference',row);notice('材料版本已保存；其他方案保持原快照。');return true;
 }
 if(a==='default-material'){await loadConfiguration();applyMaterial(S.configuration.data.material_template.definitions[0]);return true;}
 if(a==='remove-material'){
  if(S.record.provenance.adapter!=='global_frozen_v011')throw Error('此旧动态来源暂未接通 W00 转换，请选全球 W00 来源建立基准。');
  S.materialParent=null;setPath('factors.materials',{definitions:[],applications:[]});setPath('factors.condition.controls',[]);setPath('factors.condition.reference_runs',[]);return true;
 }
 return false;
}
document.addEventListener('change',async event=>{
 const t=event.target;try{
  if(t.id==='usage-room'){S.usageRoom=Number(t.value);render();}
  if(t.id==='usage-channel'){S.usageChannel=t.value;render();}
  if(t.dataset.componentUse&&t.value!==''){
   if(S.usageDirty)throw usagePendingError('替换房间配置');
   const kind=t.dataset.componentUse,row=S.componentLists[kind][Number(t.value)];
   const current=kind==='usage'?S.record.factors.building.usage_profile:S.record.factors.materials.definition_reference;
   if(current?.id===row.id&&current.revision===row.revision&&current.sha256===row.sha256)return;
   if(current?.id===row.id&&row.revision>current.revision&&typeof openComponentVersionUpdate==='function'){t.value=String(S.componentLists[kind].findIndex(v=>v.id===current.id&&v.revision===current.revision&&v.sha256===current.sha256));await openComponentVersionUpdate(row);return;}
   if(kind==='usage'){if(row.content.building_id!==S.configuration.data.base.building_id)throw Error('请选择同一建筑的配置版本。');setPath('factors.building.usage_profile',copy(row));resetUsageDraft();}else applyMaterial(row.content,row);render();
  }
 }catch(error){notice(error.message);}
});
document.addEventListener('input',event=>{
 const t=event.target;if(readonly())return;
 if(t.id==='usage-name'){S.usageName=t.value;S.usageDirty=true;}
 if(t.dataset.usageHour){const room=S.usageDraft.rooms[S.usageRoom],v=t.dataset.usageHour==='available'?room.hvac.available:room.loads[t.dataset.usageHour];v[t.dataset.day][Number(t.dataset.hour)]=t.value===''?null:Number(t.value);S.usageDirty=true;}
 if(t.dataset.usageTemperature){S.usageDraft.rooms[S.usageRoom].hvac[t.dataset.usageTemperature]=t.value===''?null:Number(t.value);S.usageDirty=true;}
 if(t.dataset.operationHour){setPath(`factors.condition.operation.overrides.${t.dataset.operationHour}.available.${t.dataset.day}.${t.dataset.hour}`,t.value===''?null:Number(t.value));updateDirtyStatus();}
 if(t.dataset.path?.startsWith('factors.materials.definitions.'))configurationPathChanged(t.dataset.path);
 if(S.usageDirty&&document.getElementById('usage-edit-status'))document.getElementById('usage-edit-status').textContent='配置有未保存修改';
});
window.addEventListener('beforeunload',event=>{if(S.usageDirty){event.preventDefault();event.returnValue='';}});
