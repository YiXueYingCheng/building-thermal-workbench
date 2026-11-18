/* Room review uses the building window and the existing configuration draft/save rules. */
const roomViewerChannels={people:'人员',lighting:'照明',equipment:'设备',available:'空调可用'};
const beforeRoomViewerPanel=buildingPanel;
function roomViewerActive(){return ['room','room-edit'].includes(buildingViewerCurrent()?.view);}
function roomViewerBase(){return S.record.factors.building.usage_profile?.content||S.configuration?.data.base;}
function roomViewerChanges(){const base=roomViewerBase();return (S.usageDraft?.rooms||[]).filter(r=>JSON.stringify(r)!==JSON.stringify(base?.rooms.find(b=>b.id===r.id)));}
function roomViewerStatus(){
 if(S.usageDirty)return `未保存 · ${roomViewerChanges().length?roomViewerChanges().length+' 间房间的配置 / 作息有变化':'配置名称等信息有变化'}；关闭窗口不会保存`;
 const p=S.record.factors.building.usage_profile,old=S.saved.factors.building.usage_profile;
 if(JSON.stringify(p)!==JSON.stringify(old))return '建筑配置已保存并选入草稿 · 还需回主页面保存方案版本';
 return p?`方案已绑定建筑配置版本 ${p.revision}`:'沿用方案的建筑原配置';
}
function roomViewerName(r){const use=S.configuration?.data.usage_sources?.[r.id]?.use;return r.zone+(use&&!use.includes('�')?' · '+use:'');}
function roomViewerLauncher(){return `<section class="room-viewer-launcher configuration-toolbar${S.usageDirty?' room-has-unsaved':''}"><div><h3>房间配置与作息</h3><p>${S.usageDraft?S.usageDraft.rooms.length+' 间房间 · '+usageMembershipText():'查看人数、照明、设备、每日作息与默认温控'}</p><p class="muted" data-room-save-status>${S.usageDraft?esc(roomViewerStatus()):'先查看摘要，需要时再进入编辑。'}</p></div><button data-room-view="open">${S.usageDirty?'查看并保存作息':'查看房间配置'}</button></section>`;}
function roomUnsavedDetails(){
 const rooms=roomViewerChanges(),names=rooms.slice(0,3).map(roomViewerName).join('、');
 return rooms.length?`${rooms.length} 间房间已修改：${names}${rooms.length>3?' 等':''}。`:'配置名称等信息已修改。';
}
async function returnToUnsavedRooms(opener){
 await openRoomViewer(opener);
 const v=buildingViewerCurrent();if(v){v.message='未保存的房间配置与作息已保留。请用窗口底部的按钮保存全部房间配置，或撤销修改。';renderBuildingViewer();}
}
function refreshRoomSaveNotice(){
 const pending=!!(S.usageDirty&&S.usageDraft);
 const awaitingPlan=!!(S.dirty&&S.record?.factors.building.usage_profile&&JSON.stringify(S.record.factors.building.usage_profile)!==JSON.stringify(S.saved?.factors.building.usage_profile));
 document.querySelectorAll('[data-room-save-status]').forEach(el=>{if(S.usageDraft)el.textContent=roomViewerStatus();el.classList.toggle('room-unsaved-status',pending);});
 document.querySelectorAll('.room-viewer-launcher,.room-viewer-foot').forEach(el=>el.classList.toggle('room-has-unsaved',pending));
 document.querySelectorAll('.room-viewer-launcher [data-room-view="open"]').forEach(el=>el.textContent=pending?'查看并保存作息':'查看房间配置');
 let banner=document.getElementById('room-unsaved-banner');
 if(!pending&&!awaitingPlan){if(banner)banner.hidden=true;return;}
 if(!banner){
  banner=document.createElement('aside');banner.id='room-unsaved-banner';banner.setAttribute('aria-label','未保存的房间配置与作息');
  banner.innerHTML='<div role="status" aria-live="polite"><strong data-unsaved-title></strong><p data-unsaved-summary></p><p data-unsaved-instruction></p></div><button class="primary" data-unsaved-return></button>';
  document.getElementById('navigation').insertAdjacentElement('afterend',banner);
  banner.addEventListener('click',async e=>{const b=e.target.closest('[data-unsaved-return]');if(!b)return;e.stopPropagation();if(S.busy||b.disabled)return;b.disabled=true;try{if(S.usageDirty)await returnToUnsavedRooms(b);else{S.view='editor';render();const save=document.querySelector('#app [data-action="save"]');save?.scrollIntoView({block:'center'});save?.focus({preventScroll:true});}}catch(error){notice(error.message);}finally{b.disabled=false;}});
 }
 const content={title:pending?'房间配置与作息未保存':'房间配置已保存，还需保存方案版本',summary:pending?roomUnsavedDetails():'新房间配置已选入当前草稿，尚未写入方案版本。',instruction:pending?'先保存房间配置，再保存方案版本；切换方案前需保存或撤销这些修改。':'请回到方案页面点击“保存版本”，完成后再切换方案。',return:pending?'查看并保存作息':'回到方案保存版本'};
 for(const [key,text] of Object.entries(content)){const el=banner.querySelector('[data-unsaved-'+key+']');if(el.textContent!==text)el.textContent=text;}
 banner.hidden=false;
}
function showRoomUnsavedWarning(intent){
 refreshRoomSaveNotice();
 let d=document.getElementById('room-unsaved-dialog');
 if(!d){
  d=document.createElement('dialog');d.id='room-unsaved-dialog';d.setAttribute('role','alertdialog');d.setAttribute('aria-labelledby','room-unsaved-title');d.setAttribute('aria-describedby','room-unsaved-description');document.body.append(d);
  d.addEventListener('cancel',e=>{e.preventDefault();d.close();});
  d.addEventListener('click',async e=>{
   const b=e.target.closest('button');if(!b)return;e.stopPropagation();
   const opener=d.roomOpener;d.close();
   if(b.dataset.unsavedAction==='return'){try{await returnToUnsavedRooms(opener);}catch(error){notice(error.message);}}
   else opener?.isConnected&&opener.focus({preventScroll:true});
  });
 }
 d.roomOpener=document.activeElement;
 d.innerHTML=`<h2 id="room-unsaved-title">房间配置与作息尚未保存</h2><div id="room-unsaved-description"><p><strong>暂未${esc(intent)}，当前修改仍保留。</strong></p><p>当前方案：${esc(S.record.name)}</p><p>${esc(roomUnsavedDetails())}</p><ol><li>返回房间作息，点击“保存全部房间配置并用于草稿”。</li><li>回到方案页面，点击“保存版本”，再继续。</li></ol><p>不需要这些修改时，可在房间窗口选择“撤销全部配置编辑”，确认后再切换。</p></div><div class="actions"><button class="primary" data-unsaved-action="return" autofocus>回到房间作息</button><button data-unsaved-action="stay">留在当前页面</button></div>`;
 if(!d.open)d.showModal();
 d.querySelector('[data-unsaved-action="return"]').focus({preventScroll:true});
}
buildingPanel=function(){
 const html=beforeRoomViewerPanel();if(!configurationSupported())return html;
 const t=document.createElement('template');t.innerHTML=html;
 // Keep the original library selector and all unrelated building/envelope sections.
 const editor=t.content.querySelector('.usage-editor');if(editor)editor.remove();
 t.content.querySelectorAll('.configuration-reuse-tools,.cross-inline-summary').forEach(el=>el.remove());
 t.content.querySelectorAll('.building-reuse-entry').forEach(el=>{if(el.nextElementSibling?.tagName==='P')el.nextElementSibling.remove();el.remove();});
 t.content.querySelectorAll('[data-configuration="load"]').forEach(el=>el.remove());
 const library=t.content.querySelector('[data-configuration="usage-list"]')?.closest('.configuration-toolbar');
 if(library)library.insertAdjacentHTML('afterend',roomViewerLauncher());else t.content.insertBefore(document.createRange().createContextualFragment(roomViewerLauncher()),t.content.firstChild);
 return t.innerHTML;
};
function roomViewerPeriods(pair){return Object.entries(scheduleDays).map(([day,label])=>{
 const groups=[];for(let h=0;h<24;h++){const v=pair[day][h],last=groups.at(-1);if(last&&last.value===v)last.end=h+1;else groups.push({start:h,end:h+1,value:v});}
 return `<div><h4>${label}</h4>${groups.map(g=>`<div class="room-period"><span>${g.start}:00–${g.end}:00</span><strong>${Number.isFinite(g.value)?format(g.value,3):'待完善'}</strong></div>`).join('')}</div>`;
}).join('');}
function roomViewerSummary(){
 const {room,channel,rule}=selectedUsage(),scaled=rule.kind==='scaled',binary=channel==='available',p=actualSchedule(rule,room.area_m2),override=S.record.factors.condition.operation.overrides?.[room.id];
 const refs=Object.entries(rule.references||{}).map(([day,r])=>scheduleDays[day]+'：'+r.name+' · v'+r.revision),g=room.gain_settings||S.configuration.data.gain_defaults[room.id],op=S.record.factors.condition.operation.mode;
 return `<section class="viewer-section"><div class="row"><h3>${roomViewerChannels[channel]} · 当前配置</h3>${readonly()?'':`<button class="primary" data-room-view="edit">编辑此房间配置</button>`}</div>
 <p>${binary?'独立 0/1 可用计划':scaled?`下限 ${viewerValue(rule.minimum)} · 上限 ${viewerValue(rule.maximum)} ${esc(scheduleUnits[rule.unit])}`:'逐小时实际'+(channel==='people'?'人数':'功率（W）')}${scaled?(rule.unit.endsWith('/m2')?'；按当前房间面积换算实际值。':'；按每间实际值使用。'):'。'}</p>
 <div id="schedule-preview">${schedulePreview()}</div><details><summary>查看分时段实际值与日计划来源</summary><div class="room-periods">${roomViewerPeriods(p)}</div><p>${refs.length?esc(refs.join('；')):'当前日期未绑定独立日计划版本。'}</p></details></section>
 <details class="room-operation-summary"><summary>建筑默认温控与本方案运行</summary><p>本方案：${esc(({natural:'自然室温',controlled:'温控冷热需求',both:'自然室温与温控',inherited:'继承原输入'})[op]||op)}。${room.conditioned?'空调归属保持。':'此房间为非空调房。'}</p>${room.hvac?`<div class="viewer-table"><table class="table"><thead><tr><th>启停项 / °C</th><th>建筑配置默认</th><th>本方案${override?'覆盖后的值':'继承默认'}</th></tr></thead><tbody>${Object.entries(temperatureLabels).map(([k,label])=>`<tr><td>${label}</td><td>${viewerValue(room.hvac[k],2)}</td><td>${viewerValue(override?.[k]??room.hvac[k],2)}</td></tr>`).join('')}</tbody></table></div>${override?`<details><summary>本方案覆盖的空调可用时段</summary><div class="room-periods">${roomViewerPeriods(override.available||room.hvac.available)}</div></details>`:''}<p class="muted">此窗口编辑建筑默认；工况覆盖仍在“工况 → 建筑运行”设置。${op==='natural'?'当前自然室温计算不启用温控。':''}</p>`:''}</details>
 <details><summary>得热参数与原配置说明</summary><p>人员显热 ${viewerValue(g.sensible_W_person,3)} W/人；照明入室得热比例 ${viewerValue(g.lighting_heat_fraction,3)}；原人员潜热 ${viewerValue(S.configuration.data.gain_defaults[room.id].latent_W_person,3)} W/人。</p><p>${esc(S.configuration.data.usage_sources?.[room.id]?.basis||'沿用建筑来源。')}</p></details>`;
}
function roomViewerEditor(){
 // Reuse the established editor and its handlers. Do not maintain a second schedule model.
 const t=document.createElement('template');t.innerHTML=beforeRoomViewerPanel();const el=t.content.querySelector('.usage-editor');
 if(!el)return '<p class="warning">当前来源未提供房间编辑。</p>';
 el.querySelector(':scope>.row')?.remove();el.querySelector(':scope>p.muted')?.remove();
 el.querySelector('#usage-name')?.closest('label').remove();el.querySelector('#usage-room')?.closest('.grid2').remove();
 el.querySelector('[data-configuration="usage-save"]')?.closest('.actions').remove();el.querySelector(':scope>p:last-child')?.remove();
 const {channel,rule}=selectedUsage(),formula=Array.from(el.querySelectorAll(':scope>p')).find(p=>p.textContent.startsWith('实际'));
 if(formula){formula.textContent=`实际${channel==='people'?'人数':'功率'} = ${rule.unit?.endsWith('/m2')?'面积 × ':''}[下限 + 比例 × (上限 − 下限)]。`;if(rule.basis){const proof=document.createElement('details');proof.innerHTML='<summary>作息来源与换算依据</summary><p>'+esc(rule.basis)+'</p>';el.append(proof);}}
 const table=el.querySelector('.schedule-hours');if(table){const details=document.createElement('details');details.className='room-hour-details';details.innerHTML='<summary>逐小时微调 · 工作日 / 周末</summary>';table.replaceWith(details);details.append(table);}
 return `<div class="row room-edit-heading"><h3>编辑 ${esc(roomViewerChannels[selectedUsage().channel])}</h3><button data-room-view="detail">完成编辑，查看摘要</button></div>${el.outerHTML}`;
}
function roomViewerTools(){
 const cross=S.record.factors.building.id==='building2_5f_verified';
 return `<details class="room-viewer-tools"><summary>配置名称、复用与差异核对</summary><label class="field">整份建筑配置名称<input id="usage-name" value="${esc(S.usageName)}"${disabled()}></label><div class="actions"><button data-room-action="open-compare">核对全部配置差异</button><button data-room-action="open-reuse"${disabled()}>复用到同建筑房间（可按类型）</button>${S.roomUndo?`<button data-room-action="undo"${disabled()}>撤销上次房间复用</button>`:''}${cross?`<button data-building-reuse="open"${disabled()}>跨建筑复用房间配置</button><button data-building-reuse="open-overview">当前全楼复用状态</button>${S.buildingReuseLast?`<button data-building-reuse="undo"${disabled()}>撤销上次跨建筑复用</button><button data-building-reuse="download-last">下载跨建筑复用记录</button>`:''}`:''}</div><p class="muted">先核对再应用；返回本房间继续查看。配置保存包含所有房间，方案版本另行保存。</p></details>`;
}
function roomViewerRemember(){const v=buildingViewerCurrent();if(!v||!roomViewerActive())return;v.roomScroll=buildingViewerDialog().querySelector('.viewer-body')?.scrollTop||0;}
function roomViewerRecount(){const p=S.record.factors.building.usage_profile;S.usageDirty=JSON.stringify(S.usageDraft)!==JSON.stringify(p?.content||S.configuration.data.base)||S.usageName!==(p?.name||S.record.factors.building.name+' 房间使用');}
function roomViewerEdited(){
 if(!roomViewerActive())return;const v=buildingViewerCurrent(),r=selectedUsage().room,u=v.roomUndo?.[r.id];
 if(u)u.after=JSON.stringify(u.before)===JSON.stringify(r)?null:copy(r);roomViewerRecount();
 refreshRoomSaveNotice();
 const save=buildingViewerDialog().querySelector('[data-configuration="usage-save"]');if(save)save.disabled=readonly()||!S.usageDirty;
 const discard=buildingViewerDialog().querySelector('[data-room-view="discard"]');if(discard)discard.disabled=readonly()||!S.usageDirty;
 const changed=new Set(roomViewerChanges().map(r=>r.id));buildingViewerDialog().querySelectorAll('#usage-room option').forEach((o,i)=>{const r=S.usageDraft.rooms[i];o.textContent=roomViewerName(r)+' · '+format(r.area_m2,2)+' m² · '+(r.conditioned?'空调房':'非空调房')+(changed.has(r.id)?' · 已修改':'');});
}
const beforeRoomViewerRender=renderBuildingViewer;
renderBuildingViewer=function(){
 const v=buildingViewerCurrent();if(!roomViewerActive())return beforeRoomViewerRender();if(v.suspended)return;
 const d=buildingViewerDialog(),old=d.querySelector('.viewer-body'),top=v.roomScroll??old?.scrollTop??0,active=d.contains(document.activeElement)?document.activeElement.id:null;
 const context=v.view+':'+S.usageRoom+':'+S.usageChannel,opened=d.dataset.roomContext===context?Array.from(old?.querySelectorAll('details')||[]).map(el=>el.open):null;d.dataset.roomContext=context;
 const pending=v.pending||!S.usageDraft,room=pending?null:selectedUsage().room,channels=Object.keys(roomViewerChannels).filter(c=>c!=='available'||room?.hvac),undo=room&&v.roomUndo?.[room.id]?.after;
 d.classList.add('room-viewer');
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(S.record.name)} · ${esc(planVersionLabel(S.saved))}${readonly()?' · 只读':''}</p><h2 id="building-viewer-title">${v.view==='room-edit'?'编辑房间配置':'房间配置与作息'}</h2></div><div class="actions">${v.view==='room-edit'?'<button data-room-view="detail">← 返回房间摘要</button>':''}${v.roomOrigin==='plan'?'<button data-room-view="plan">← 返回原平面</button>':''}<button data-viewer="close">关闭</button></div></header>
 <div class="viewer-body">${pending?'<p>正在读取房间配置…</p>':`<div class="room-viewer-selector"><div class="room-context"><label class="field">查看房间<select id="usage-room">${S.usageDraft.rooms.map((r,i)=>`<option value="${i}"${i===S.usageRoom?' selected':''}>${esc(roomViewerName(r))} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}${roomViewerChanges().some(c=>c.id===r.id)?' · 已修改':''}</option>`).join('')}</select></label><span class="tag">${S.usageRoom+1} / ${S.usageDraft.rooms.length} 间</span></div><nav class="room-channel-tabs" aria-label="房间配置内容">${channels.map(c=>`<button data-room-channel="${c}" aria-pressed="${selectedUsage().channel===c}">${roomViewerChannels[c]}</button>`).join('')}</nav></div>${v.view==='room-edit'?roomViewerEditor():roomViewerSummary()}${undo?'<button data-room-view="undo">撤销本次此房间编辑</button>':''}${roomViewerTools()}`}</div>
 <footer class="viewer-foot room-viewer-foot"><div><p class="viewer-message" data-room-message role="status"${v.message?'':' hidden'}>${esc(v.message)}</p><strong id="usage-edit-status" data-room-save-status>${pending?'正在读取':esc(roomViewerStatus())}</strong><p class="muted">关闭保留编辑；先保存建筑配置，再回主页面保存方案版本。</p>${v.roomDiscard?'<p>将撤销全部未保存的房间配置和名称编辑，恢复本方案当前选用配置。</p><div class="actions"><button data-room-view="discard-confirm">确认撤销全部配置编辑</button><button data-room-view="discard-cancel">继续保留</button></div>':''}</div><div class="actions">${pending?'':`<button data-configuration="usage-save" class="primary"${readonly()||!S.usageDirty?' disabled':''}>保存全部房间配置并用于草稿</button><button data-room-view="discard"${readonly()||!S.usageDirty?' disabled':''}>撤销全部配置编辑</button>`}<button data-viewer="close">关闭并返回方案</button></div></footer>`;
 refreshRoomSaveNotice();
 if(!d.open)d.showModal();const focus=active&&d.querySelector('#'+CSS.escape(active));if(focus)focus.focus({preventScroll:true});else{const title=d.querySelector('#building-viewer-title');title.tabIndex=-1;title.focus({preventScroll:true});}
 if(opened)Array.from(d.querySelector('.viewer-body').querySelectorAll('details')).forEach((el,i)=>el.open=!!opened[i]);d.querySelector('.viewer-body').scrollTop=top;v.roomScroll=null;
};
async function openRoomViewer(opener,roomId=null){
 let v=buildingViewerCurrent();if(v){rememberViewerPlan();v.roomOrigin=v.view==='plan'?'plan':v.roomOrigin;v.view='room';v.roomScroll=0;}else{await openBuildingViewer(opener,{view:'room',roomScroll:0});v=buildingViewerCurrent();}
 if(!v)return;
 if(roomId){const index=S.usageDraft.rooms.findIndex(r=>r.id===roomId);if(index<0)throw Error('此房间配置暂未接入。');S.usageRoom=index;}
 v.roomUndo??={};v.message='';renderBuildingViewer();
 if(!S.dailyProfiles){try{const profiles=await api('/api/daily-profiles');if(buildingViewerCurrent()!==v)return;S.dailyProfiles=profiles;renderBuildingViewer();}catch(e){if(buildingViewerCurrent()===v){v.message='日计划库读取失败，可继续核对房间；重新打开时重试。';renderBuildingViewer();}}}
}
async function roomViewerAction(button,node){
 const v=buildingViewerCurrent();if(!v)return false;
 if(button?.dataset.geometry==='room-config'){await openRoomViewer(button,geometryState().room);return true;}
 if(!roomViewerActive()||node)return false;
 const op=button.dataset.roomView;roomViewerRemember();v.message='';
 if(button.dataset.roomChannel){S.usageChannel=button.dataset.roomChannel;v.roomScroll=0;renderBuildingViewer();return true;}
 if(op==='plan'){v.view='plan';buildingViewerDialog().classList.remove('room-viewer');renderBuildingViewer();return true;}
 if(op==='detail'){v.view='room';v.roomScroll=0;renderBuildingViewer();return true;}
 if(op==='edit'){
  if(readonly())throw Error('来源或旧版本只读。');const r=selectedUsage().room;v.roomUndo??={};v.roomUndo[r.id]??={before:copy(r),after:null};v.view='room-edit';v.roomScroll=0;renderBuildingViewer();return true;
 }
 if(op==='undo'){
  const r=selectedUsage().room,u=v.roomUndo?.[r.id];if(!u||JSON.stringify(r)!==JSON.stringify(u.after))throw Error('此房间经过后续复用或其他操作，请先核对差异；未直接撤销。');
  S.usageDraft.rooms[S.usageRoom]=copy(u.before);delete v.roomUndo[r.id];roomViewerRecount();v.view='room';v.message='已恢复本次房间编辑前的值；其他房间与名称编辑保留。';renderBuildingViewer();return true;
 }
 if(op==='discard'||op==='discard-cancel'){v.roomDiscard=op==='discard';renderBuildingViewer();return true;}
 if(op==='discard-confirm'){const b=document.createElement('button');b.dataset.configuration='usage-discard';await configurationAction(b);v.roomUndo={};S.roomUndo=null;v.roomDiscard=false;v.view='room';v.message='已恢复当前方案选用的建筑配置。';renderBuildingViewer();return true;}
 const child=button.hasAttribute('data-daily-open')||['open-reuse','open-compare'].includes(button.dataset.roomAction)||['open','open-overview'].includes(button.dataset.buildingReuse);
 if(child){v.suspended=true;buildingViewerDialog().close();}
 v.pending=true;v.roomSaving=button.dataset.configuration==='usage-save'||button.dataset.scheduleAction==='save-profile';if(v.roomSaving){buildingViewerDialog().querySelector('.viewer-body').inert=true;notice('正在保存配置，请稍候…');}
 try{
  notice();await configurationAction(button);
  if(buildingViewerCurrent()!==v)return true;
  if(button.dataset.configuration==='usage-save'){v.roomUndo={};v.roomDiscard=false;v.view='room';v.roomScroll=0;v.message='已保存全部房间配置并用于方案草稿；请回主页面保存方案版本。';}
  else if(button.dataset.scheduleAction){roomViewerEdited();v.message=message.textContent;}
  if(child&&!document.querySelector('dialog[open]'))v.suspended=false;
 }catch(e){v.message=e.message;if(child)v.suspended=false;}
 finally{if(buildingViewerCurrent()===v){v.pending=false;v.roomSaving=false;renderBuildingViewer();}}
 return true;
}
function roomViewerChange(event){
 const v=buildingViewerCurrent(),t=event.target;if(v.pending){event.stopPropagation();return;}
 if(t.id==='usage-room'){event.stopPropagation();S.usageRoom=Number(t.value);v.view='room';v.roomScroll=0;v.message='';renderBuildingViewer();}
 else {roomViewerRemember();if(['schedule-unit','schedule-basis'].includes(t.id))queueMicrotask(()=>{if(buildingViewerCurrent()===v)roomViewerEdited();});} // Existing schedule handlers handle units, basis and day plan choices.
}
const beforeRoomViewerAction=configurationAction;
configurationAction=async function(button){if(button.dataset.roomView==='open'||button.dataset.configuration==='load'){await openRoomViewer(button);return true;}return beforeRoomViewerAction(button);};
const renderBeforeRoomViewer=render;
render=function(){renderBeforeRoomViewer();if(roomViewerActive()&&!buildingViewerCurrent().suspended)renderBuildingViewer();else if(!roomViewerActive())document.getElementById('building-viewer')?.classList.remove('room-viewer');refreshRoomSaveNotice();};
document.addEventListener('input',event=>{if(event.target.closest('#building-viewer')&&roomViewerActive()){roomViewerEdited();}});
document.addEventListener('change',event=>{if(event.target.closest('#building-viewer')&&roomViewerActive()&&['schedule-unit','schedule-basis'].includes(event.target.id))roomViewerEdited();});
function roomViewerResume(){const v=buildingViewerCurrent();if(!roomViewerActive()||!v.suspended)return;queueMicrotask(()=>{if(buildingViewerCurrent()!==v||document.querySelector('dialog[open]'))return;v.suspended=false;v.pending=false;v.message='已返回原房间；当前编辑与已应用内容保留。';renderBuildingViewer();});}
const closeDailyBeforeRoomViewer=closeDailyManager;
closeDailyManager=function(){const usage=S.dailyManager?.target==='usage';closeDailyBeforeRoomViewer();if(usage&&roomViewerActive())roomViewerEdited();roomViewerResume();};
const closeRoomToolBeforeRoomViewer=closeRoomTool;
closeRoomTool=function(){closeRoomToolBeforeRoomViewer();roomViewerResume();};
const closeCrossBeforeRoomViewer=closeBuildingReuse;
closeBuildingReuse=function(){closeCrossBeforeRoomViewer();roomViewerResume();};
const noticeBeforeRoomViewer=notice;
notice=function(text=''){noticeBeforeRoomViewer(text);const v=buildingViewerCurrent();if(roomViewerActive()&&!v.suspended){v.message=text;const slot=buildingViewerDialog().querySelector('[data-room-message]');if(slot){slot.textContent=text;slot.hidden=!text;}}};

const closeBuildingBeforeRoomViewer=closeBuildingViewer;
closeBuildingViewer=function(restore=true){if(buildingViewerCurrent()?.roomSaving){notice('正在保存配置，请稍候；完成后可关闭。');return;}closeBuildingBeforeRoomViewer(restore);};
function roomViewerToolReturn(element,selector){if(roomViewerActive()&&buildingViewerCurrent().suspended)element.querySelectorAll(selector).forEach(b=>{b.textContent='返回房间配置';if(b.hasAttribute('aria-label'))b.setAttribute('aria-label','返回房间配置');});}
const renderDailyBeforeRoomViewer=renderDailyManager;
renderDailyManager=function(){renderDailyBeforeRoomViewer();roomViewerToolReturn(dailyManagerElement(),'[data-daily-action="close"]');};
const renderRoomToolBeforeRoomViewer=renderRoomTool;
renderRoomTool=function(){renderRoomToolBeforeRoomViewer();roomViewerToolReturn(roomToolElement(),'[data-room-action="close"]');};
const renderCrossBeforeRoomViewer=renderBuildingReuse;
renderBuildingReuse=function(){renderCrossBeforeRoomViewer();roomViewerToolReturn(buildingReuseDialog(),'[data-building-reuse="close"]');};
