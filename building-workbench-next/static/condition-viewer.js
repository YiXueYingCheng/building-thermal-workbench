/* Focused condition review; all edits use the existing scheme draft and handlers. */
S.conditionViewer=null;
const conditionPositions=new Map(),conditionTabs={operation:'建筑运行',controls:'材料控制',calendar:'光学切换与参考'},conditionWatched=new WeakSet();
function conditionKey(){return JSON.stringify([S.id,S.saved?.revision]);}
function conditionCurrent(){return S.conditionViewer?.key===conditionKey()?S.conditionViewer:null;}
function conditionStamp(){return JSON.stringify(S.record.factors.condition);}
function conditionDependencies(){return JSON.stringify([S.record.factors.building,S.record.factors.materials,S.record.factors.scope,S.record.numerics]);}
function conditionChanged(){return conditionStamp()!==JSON.stringify(S.saved.factors.condition);}
function conditionStatus(){return conditionChanged()?'工况有未保存修改':'与本方案保存版一致';}
function conditionRooms(){return (S.record.factors.building.usage_profile?.content||S.configuration?.data.base)?.rooms.filter(r=>r.conditioned&&r.hvac)||[];}
function conditionRoomLabel(r){const use=S.configuration?.data.usage_sources?.[r.id]?.use;return r.zone+(use?' · '+use:'');}
function conditionCheckMarkup(){return S.capability?.key===capabilityKey()&&S.capability.data.supported?'':capabilityStatus();}
function conditionRoom(){const rows=conditionRooms(),v=conditionCurrent();return rows.find(r=>r.id===v.room)||rows[0];}
function conditionCanControl(){return !readonly()&&S.record.provenance.adapter!=='ordinary_building_v1'&&S.record.factors.condition.controls.length>0;}
conditionPanel=function(){const c=S.record.factors.condition;return `<section class="condition-launcher"><div><h2>${esc(modes[c.operation.mode]||c.operation.mode)}</h2><p>${Object.keys(c.operation.overrides||{}).length?Object.keys(c.operation.overrides).length+' 间房设置了本方案运行覆盖':'设定点与空调可用计划继承建筑默认'}</p><p>${materialViewerControlText().map(esc).join('；')||'没有新增材料控制'}</p><p class="muted">${esc(conditionStatus())}</p><div class="condition-binding-summary">${calendarBindingMarkup()}</div></div><button class="primary" data-condition-view="open">查看工况与控制</button></section>`;};
function conditionDialog(){let d=document.getElementById('condition-viewer');if(d)return d;d=document.createElement('dialog');d.id='condition-viewer';d.setAttribute('aria-labelledby','condition-viewer-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeConditionViewer();});
 d.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();const v=conditionCurrent();if(!v||v.pending||b.disabled)return;conditionRemember();v.message='';try{await conditionAction(b,v);}catch(error){if(conditionCurrent()===v){v.message=error.message;renderConditionViewer();}}});
 d.addEventListener('change',e=>{if(e.target.id==='stack-calendar-step'){setStackCalendarStep(e.target.value);return;}if(e.target.id==='condition-room'){e.stopPropagation();conditionRemember();const v=conditionCurrent();v.room=e.target.value;v.mode='view';v.message='';renderConditionViewer();}});
 return d;
}
function conditionRemember(){const v=conditionCurrent();if(!v||v.suspended)return;const d=conditionDialog(),k=v.tab+':'+v.mode+':'+v.room;v.scroll[k]=d.querySelector('.condition-body')?.scrollTop||0;v.expanded[k]=Array.from(d.querySelectorAll('.condition-body details')).map(x=>x.open);}
function conditionAvailability(a){return `<div class="condition-schedule">${scheduleChart({weekday:a.weekday,weekend:a.weekend},'空调可用 0/1')}${a.references?'<p class="muted">日计划版本：'+Object.entries(a.references).map(([day,ref])=>esc(scheduleDays[day]+' · '+ref.name+' · v'+ref.revision)).join('；')+'</p>':''}<details><summary>查看 24 小时数值</summary><div class="viewer-table"><table class="table"><thead><tr><th>时段</th><th>工作日</th><th>周末</th></tr></thead><tbody>${a.weekday.map((n,h)=>`<tr><td>${h}:00–${h+1}:00</td><td>${esc(n)}</td><td>${esc(a.weekend[h])}</td></tr>`).join('')}</tbody></table></div></details></div>`;}
function conditionOperation(){const v=conditionCurrent(),op=S.record.factors.condition.operation,room=conditionRoom(),edit=v.mode==='edit';
 let html=edit?select('建筑运行模式','factors.condition.operation.mode',Object.entries(modes),op.mode):`<h3>${esc(modes[op.mode]||op.mode)}</h3>`;
 html+=`<p class="muted">建筑默认来自${S.record.factors.building.usage_profile?'所选建筑配置版本':'原建筑输入'}。这里的覆盖只用于本方案；人员、照明、设备及建筑默认作息在房间配置中维护。</p>`;
 if(op.mode==='natural')html+='<p class="condition-hint">当前计算自然室温；下列温控设置保留供切回温控使用，不在自然模式中启用。</p>';
 if(S.usageDirty)html+='<p class="warning">房间配置还有独立的未保存编辑；本页默认值仍按方案已选配置显示。请保存配置或撤销后再核对日历。</p>';
 if(!room)return html+`<p>${v.loading?'正在读取建筑默认…':configurationSupported()?'暂无可读取的空调房运行默认。':'此旧来源沿用原运行设置；逐房间覆盖未接通。'}</p>`;
 const overrides=op.overrides||{},o=overrides[room.id],actual={...room.hvac,...o};
 html+=`<label class="field condition-room-picker">查看房间<select id="condition-room">${conditionRooms().map(r=>`<option value="${esc(r.id)}"${r.id===room.id?' selected':''}>${esc(conditionRoomLabel(r))}${overrides[r.id]?' · 本方案覆盖':' · 继承默认'}</option>`).join('')}</select></label><p>${esc(conditionRoomLabel(room))} · ${o?'本方案运行覆盖':'继承建筑默认'}；共 ${conditionRooms().length} 间空调房，${Object.keys(overrides).length} 间有覆盖。</p><div class="viewer-table"><table class="table"><thead><tr><th>启停温度 / °C</th><th>建筑默认</th><th>本方案实际采用</th></tr></thead><tbody>${Object.entries(temperatureLabels).map(([k,label])=>`<tr><th>${label}</th><td>${viewerValue(room.hvac[k],2)}</td><td data-condition-temp="${k}" class="${o&&o[k]!==room.hvac[k]?'changed':''}">${viewerValue(actual[k],2)}</td></tr>`).join('')}</tbody></table></div>`;
 if(edit){html+=o?`<div class="grid2">${Object.entries(temperatureLabels).map(([k,label])=>number(label+' / °C',`factors.condition.operation.overrides.${room.id}.${k}`,actual[k])).join('')}</div><details><summary>编辑本方案空调可用计划</summary>${dayTable(actual.available,'data-operation-hour="'+room.id+'"')}</details><button data-clear-operation="${esc(room.id)}"${disabled()}>清除本房间覆盖，恢复建筑默认</button>`:`<button data-override-operation="${esc(room.id)}"${disabled()}>为本房间设置方案覆盖</button>`;}
 else html+='<h4>本方案空调可用计划</h4>'+conditionAvailability(actual.available);
 return html;
}
function conditionControls(){const v=conditionCurrent(),c=S.record.factors.condition,m=S.record.factors.materials;
 const physical=m.definitions.some(mtPhysical);
 if(!physical&&v.mode==='edit'&&conditionCanControl()){const t=document.createElement('template');t.innerHTML=originalConditionPanel();return (S.record.provenance.adapter==='global_frozen_v011'?controlPresetToolbar():'')+Array.from(t.content.querySelectorAll('.control')).map(e=>e.outerHTML.replace('见下方参考计算','在“光学切换与参考”中核对').replace('求解步长在下方单独设置','求解步长在主页面的计算设置中单独设置')).join('');}
 let html=c.controls.map(control=>{const app=m.applications.find(a=>a.id===control.application_id),d=m.definitions.find(d=>d.id===app?.material_id),thermal=control.channel==='thermal',state=d?.states.find(s=>s.id===control.state_id),feedback=thermal&&control.mode==='feedback';return `<article class="condition-control"><h3>${thermal?'热学状态':'表面光学'} · ${control.target_ids.length} 个构件</h3><p>${esc(d?.name||app?.material_id||'沿用原材料')} · ${thermal?(feedback?(control.layer_number?'反馈调节 · 第 '+esc(control.layer_number)+' 层 · 初始 '+esc(stackInitialName(d,control.layer_number)):'反馈调节，初始状态 '+esc(state?.name||control.state_id)):state?.name==='固定状态'?'固定状态':'固定状态 '+esc(state?.name||control.state_id)):control.mode==='calendar'?'按参考日历切换表面光学参数':d?.model===stackModel?(app.position==='exterior'?'最外层固定 '+esc(stackExterior(d,control).face)+' 组':'室外侧沿用原构造'):'固定 '+esc(control.face_id||'A')}</p>${feedback?`<p>${control.rule==='GROUPED'?'按朝向分组反馈':'统一反馈'} · ${control.update?.kind==='minutes'?'每 '+esc(control.update.minutes)+' min':'每个求解步'}更新</p><div class="viewer-table"><table class="table"><tbody>${[['低温阈值 / °C',control.policy?.cold_C],['高温阈值 / °C',control.policy?.hot_C],['热流死区 / W/m²',control.policy?.flux_deadband_W_m2],['最短保持 / min',control.policy?.minimum_hold_minutes]].map(([label,x])=>`<tr><th>${label}</th><td>${viewerValue(x,3)}</td></tr>`).join('')}</tbody></table></div>`:''}<details><summary>查看作用构件${feedback?'与完整规则':''}</summary><p>${control.target_ids.map(esc).join('、')}</p>${feedback?'<pre>'+esc(JSON.stringify(control,null,2))+'</pre>':''}</details></article>`;}).join('')||'<h3>没有新增材料控制</h3><p>当前沿用原建筑构造与运行方式。</p>';
 if(physical){
   const thermal=c.controls.find(x=>x.channel==='thermal'),feedback=thermal?.mode==='feedback';
   if(m.definitions[0].model==='layer_stack_v1'){
     const app=m.applications[0],optical=c.controls.find(x=>x.channel==='orientation'&&x.application_id===app.id);
     html+=stackOpticsPanel(m.definitions[0],app,optical)+stackFeedbackPanel(m.definitions[0],app,thermal)+'<button data-open-wall-probes>查看或设置测点</button>';
   }
   if(drawingScopeEnabled()&&m.definitions[0].model==='solid_variable_v1'){
     html+='<button class="primary" data-condition-view="wall-scope">选择反馈墙段</button>';
   }
   if(m.definitions[0].model==='solid_variable_v1'&&thermal&&c.controls.filter(x=>x.channel==='thermal').length===1){
     const referenceStep=feedback?thermal.reference_step_minutes:S.record.numerics.step_minutes;
     html+=`<p class="condition-hint">统一热阻反馈用所选构件的净面积汇总室温与热流信号。低于 18 °C 或高于 26 °C 时参与判断，热流死区 1 W/m²，每 5 min 判断，最短保持 60 min。实体层按 1 min 求解，原构造日历按 ${esc(referenceStep)} min 核对。</p><button data-condition-view="surface-feedback"${readonly()?' disabled':''}>${feedback?'恢复固定热阻与参考步长':'启用可调热阻（1 min 求解）'}</button>`;
   }
   if(m.definitions[0].faces?.length>1)html+='<p>要按日历切换表面光学参数，请在“光学切换与参考”核对并采用本方案日历。日历的制冷日用 A 组，供暖日用 B 组。热学状态单独按反馈规则调节。</p>';
 }else if(solidProfile()){
   if(m.definitions.length)html+='<p class="condition-hint">季节光学切换沿用本组 1 min W00 逐日参考。启用热阻调节时，控制器使用上一完整时间步的房温与墙面热流，按 952.0 m² 净墙面积统一判断。预热阶段保持 C，正式时段从 C 开始。</p>';
   html+=solidNote();
 }else if(S.record.provenance.adapter==='ordinary_building_v1'&&m.definitions.length)html+='<p class="condition-hint">固定热学状态和朝外光学组按当前方案的逐墙设置采用。</p>';
 html+='<p class="muted">材料应用指定构件与层位。在本页分别设置表面光学切换和热阻调节。</p><button data-condition-view="material">查看材料与应用</button>';return html;
}
function conditionCalendar(){const c=S.record.factors.condition;return `<h3>本方案光学切换日历</h3><p>表面光学切换按工况规则选用 A 或 B 组参数，将太阳吸收率、长波发射率等用于当前暴露在室外的表面。支持原位改变表面光学性能，构造层序沿用原设置。</p>${stackCalendarReference(S.record)}<div id="calendar-binding-status">${calendarBindingMarkup()}</div><p>${adoptedCalendarSnapshots().length?'可直接查看各地点的光学参数组和已确认的切换日期。':'先核对当前方案的逐日参考，再预览与采用日历。'}</p><button class="primary" data-calendar-library="open">${calendarEntryLabel()}</button>${S.calendarUndo?.after===calendarUndoKey()?'<button data-calendar-library="undo"'+disabled()+'>撤销本次日历采用</button>':''}<section class="condition-reference"><h4>参考数据准备</h4><p>查看原构造参考结果及逐日数据缺口；创建清单和提交计算仍为两个步骤。</p><div class="actions"><button data-reference-readiness="open">核对参考准备</button><button data-daily-reference="open">准备逐日参考</button></div></section>${c.reference_runs.length?`<details><summary>查看已绑定参考与规则</summary><pre>${esc(JSON.stringify(c.reference_runs.map(referenceDisplay),null,2))}</pre></details>`:''}<details><summary>查看换季规则示例</summary><p>Drawing26 北京旧参考，仅用于理解规则，不代表当前建筑的日历。</p><button data-calendar-preview="open">打开北京换季示例</button></details>`;}
function renderConditionViewer(){const v=conditionCurrent();if(!v||v.suspended)return;const d=conditionDialog(),focus=d.contains(document.activeElement)?document.activeElement:null,path=focus?.dataset.path,room=conditionRoom();if(room)v.room=room.id;
 const editable=!readonly()&&(v.tab==='operation'||v.tab==='controls'&&conditionCanControl());
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(S.record.name)} · ${esc(planVersionLabel(S.saved))}${readonly()?' · 只读':''}</p><h2 id="condition-viewer-title" tabindex="-1">${v.mode==='edit'?'编辑工况与控制':'工况与控制'}</h2></div><div class="actions">${v.mode==='edit'?'<button data-condition-view="view">← 返回工况查看</button>':''}<button data-condition-view="close">关闭</button></div></header><nav class="condition-tabs" aria-label="工况内容">${Object.entries(conditionTabs).map(([key,label])=>`<button data-condition-view="tab" data-condition-tab="${key}" aria-pressed="${key===v.tab}">${label}</button>`).join('')}</nav><div class="condition-body">${materialControlSummary(S.record,S.dirty)}${v.loadError?`<p class="warning">默认值读取失败：${esc(v.loadError)}</p><button data-condition-view="retry">重试读取</button>`:''}<div class="condition-edit-entry">${editable&&v.mode==='view'?'<button class="primary" data-condition-view="edit">'+(v.tab==='operation'?'编辑运行设置':'编辑材料控制')+'</button>':''}</div><div class="condition-capability" role="status">${conditionCheckMarkup()}</div>${({operation:conditionOperation,controls:conditionControls,calendar:conditionCalendar})[v.tab]()}</div><footer class="viewer-foot condition-footer"><div><p data-condition-status>${conditionStatus()}</p><p class="muted">关闭保留草稿；回主页面保存方案版本。</p><p data-condition-message role="status"${v.message?'':' hidden'}>${esc(v.message)}</p></div><div class="actions">${v.undo&&v.after&&!readonly()?'<button data-condition-view="undo">撤销本次工况编辑</button>':''}<button data-condition-view="close">关闭并返回方案</button></div></footer>`;
 if(!d.open)d.showModal();const target=path?Array.from(d.querySelectorAll('[data-path]')).find(x=>x.dataset.path===path):focus?.id?d.querySelector('#'+CSS.escape(focus.id)):null;(target||d.querySelector('#condition-viewer-title')).focus({preventScroll:true});const k=v.tab+':'+v.mode+':'+v.room;d.querySelector('.condition-body').scrollTop=v.scroll[k]||0;Array.from(d.querySelectorAll('.condition-body details')).forEach((x,i)=>{if(v.expanded[k]?.[i]!=null)x.open=v.expanded[k][i];});if(v.pending){d.querySelector('.condition-body').inert=true;d.querySelectorAll('button').forEach(b=>b.disabled=true);}
}
async function conditionLoad(v){if(!configurationSupported())return;v.loading=true;v.loadError='';renderConditionViewer();try{const key=S.id+':'+S.saved.revision,data=S.configuration?.key===key?S.configuration.data:await api('/api/configuration/'+encodeURIComponent(S.id)+'?revision='+S.saved.revision);if(conditionCurrent()!==v)return;S.configuration={key,data};if(!S.usageDraft)resetUsageDraft();if(!S.dailyProfiles){const profiles=await api('/api/daily-profiles');if(conditionCurrent()!==v)return;S.dailyProfiles=profiles;}}catch(e){if(conditionCurrent()===v)v.loadError=e.message;}finally{if(conditionCurrent()===v){conditionRemember();v.loading=false;renderConditionViewer();}}}
function openConditionViewer(){const key=conditionKey();S.conditionViewer={key,tab:'operation',mode:'view',room:null,scroll:{},expanded:{},...conditionPositions.get(key),mainY:scrollY,pending:false,suspended:false,message:''};S.conditionViewer.mode='view';document.documentElement.classList.add('condition-viewer-open');renderConditionViewer();void conditionLoad(S.conditionViewer);}
function closeConditionViewer(restore=true){const v=S.conditionViewer;if(!v)return;if(v.pending&&!v.suspended){notice('正在处理，请稍候再关闭。','warning');return;}conditionRemember();conditionPositions.set(v.key,{tab:v.tab,room:v.room,scroll:v.scroll,expanded:v.expanded,undo:v.undo,after:v.after,deps:v.deps});S.conditionViewer=null;conditionDialog().close();conditionDialog().replaceChildren();document.documentElement.classList.remove('condition-viewer-open');if(restore){render();requestAnimationFrame(()=>{scrollTo({top:v.mainY,behavior:'instant'});document.querySelector('[data-condition-view="open"]')?.focus({preventScroll:true});});}}
function conditionBegin(){const v=conditionCurrent();if(!v)return;if(!v.undo||v.deps!==conditionDependencies()||v.after&&v.after!==conditionStamp()){v.undo=copy(S.record.factors.condition);v.deps=conditionDependencies();v.after=null;}}
function conditionTrack(){const v=conditionCurrent();if(!v||v.suspended)return;if(v.undo&&v.deps===conditionDependencies())v.after=JSON.stringify(v.undo)===conditionStamp()?null:conditionStamp();const d=conditionDialog(),room=conditionRoom(),o=S.record.factors.condition.operation.overrides?.[room?.id];if(room)d.querySelectorAll('[data-condition-temp]').forEach(e=>{const k=e.dataset.conditionTemp;e.textContent=viewerValue(o&&k in o?o[k]:room.hvac[k],2);e.classList.toggle('changed',!!o&&o[k]!==room.hvac[k]);});d.querySelector('[data-condition-status]')?.replaceChildren(document.createTextNode(conditionStatus()));if(v.after&&!d.querySelector('[data-condition-view="undo"]')){const b=document.createElement('button');b.dataset.conditionView='undo';b.textContent='撤销本次工况编辑';d.querySelector('.condition-footer>.actions')?.prepend(b);}}
function conditionResume(){const v=conditionCurrent();if(!v?.suspended)return;setTimeout(()=>{if(conditionCurrent()!==v||!v.suspended)return;if(S.busy){conditionResume();return;}if(S.view!=='editor'||S.factor!=='condition'){v.pending=false;closeConditionViewer(false);return;}if(document.querySelector('dialog[open]'))return;v.suspended=false;v.pending=false;v.actionToken=null;v.message=v.message&&!v.message.startsWith('正在')?v.message:'已返回工况，当前草稿保留。';conditionTrack();renderConditionViewer();},25);}
function conditionChild(d,selector){if(!conditionCurrent()?.suspended)return;d.querySelectorAll(selector).forEach(b=>b.textContent='返回工况');if(!conditionWatched.has(d)){conditionWatched.add(d);d.addEventListener('close',conditionResume);}}
async function conditionAction(b,v){const op=b.dataset.conditionView;
 if(op==='stack-optics'){setStackExterior(b.dataset.face,v);return;}
 if(op==='wall-scope'){await openDrawingWalls('feedback');return;}
 if(op==='stack-feedback'||op==='stack-fixed'){await applyStackFeedback(v,op==='stack-fixed');return;}
 if(op==='surface-feedback'){
   if(readonly())return;
   const controls=copy(S.record.factors.condition.controls),thermal=controls.find(c=>c.channel==='thermal');
   if(!thermal||S.record.factors.materials.definitions[0]?.model!=='solid_variable_v1')throw Error('请先选择双状态实体材料。');
   const enabling=thermal.mode==='fixed',step=enabling?1:thermal.reference_step_minutes;
   if(enabling){
     Object.assign(thermal,{mode:'feedback',rule:'UNIFIED',reference_step_minutes:S.record.numerics.step_minutes,
       policy:{cold_C:18,hot_C:26,flux_deadband_W_m2:1,minimum_hold_minutes:60},update:{kind:'minutes',minutes:5}});
   }else{
     thermal.mode='fixed';
     for(const key of ['rule','reference_step_minutes','policy','update'])delete thermal[key];
   }
   v.undo=null;v.after=null;
   setPath('factors.condition.controls',controls);setPath('numerics.step_minutes',step);
   v.message=enabling?'已在草稿启用热阻反馈。可在“光学切换与参考”采用日历，然后保存方案。':'已在草稿恢复固定热阻。';
   render();renderConditionViewer();return;
 }
 if(op==='close'){closeConditionViewer();return;}if(op==='tab'){v.tab=b.dataset.conditionTab;v.mode='view';renderConditionViewer();return;}if(op==='view'){v.mode='view';renderConditionViewer();return;}
 if(op==='edit'){if(readonly())return;conditionBegin();v.mode='edit';renderConditionViewer();return;}if(op==='retry'){await conditionLoad(v);return;}
 if(op==='undo'){if(readonly()||!v.undo||v.after!==conditionStamp()||v.deps!==conditionDependencies())throw Error('相关工况或依赖经过后续修改，不能直接撤销，请先核对。');setPath('factors.condition',copy(v.undo));S.calendarUndo=null;v.undo=null;v.after=null;v.mode='view';S.dirty=JSON.stringify(changes())!==JSON.stringify(Object.fromEntries(['name','factors','numerics','execution'].map(k=>[k,S.saved[k]])));v.message='已恢复本次工况编辑前的配置；建筑、材料和范围保留。';render();return;}
 const child=op==='material'||b.dataset.calendarLibrary==='open'||b.dataset.referenceReadiness||b.dataset.dailyReference||b.dataset.calendarPreview||b.hasAttribute('data-daily-open');
 conditionBegin();if(child){v.suspended=true;conditionDialog().close();}
 const token=Symbol();v.actionToken=token;v.pending=true;v.message='正在读取或处理…';if(!child)renderConditionViewer();
 try{if(op==='material')openMaterialViewer(b);else if(b.dataset.action==='check-capability')await refreshCapability();else await configurationAction(b);if(conditionCurrent()!==v||v.actionToken!==token)return;if(b.dataset.scheduleAction==='save-profile')v.message='已打开统一日计划库；先核对并保存，采用到运行覆盖另行确认。';else v.message='';conditionTrack();}
 finally{if(conditionCurrent()===v&&v.actionToken===token){v.pending=false;if(child)conditionResume();else{conditionTrack();render();}}}
}
const conditionBeforeAction=configurationAction;
configurationAction=async function(b){if(b.dataset.conditionView==='open'||b.dataset.configuration==='operation'){openConditionViewer();return true;}return conditionBeforeAction(b);};
const conditionBeforeRender=render;
render=function(){if(S.conditionViewer&&(!conditionCurrent()||S.view!=='editor'||S.factor!=='condition')){S.conditionViewer.pending=false;closeConditionViewer(false);}conditionBeforeRender();renderConditionViewer();};
const conditionBeforeNotice=notice;
notice=function(text='',kind='status'){conditionBeforeNotice(text,kind);const v=conditionCurrent();if(v&&!v.suspended){v.message=text;const el=conditionDialog().querySelector('[data-condition-message]');if(el){el.textContent=text;el.hidden=!text;}}};
const conditionBeforeCapability=updateCapabilityStatus;
updateCapabilityStatus=function(){conditionBeforeCapability();document.querySelectorAll('.condition-capability').forEach(e=>e.innerHTML=conditionCheckMarkup());document.querySelectorAll('.condition-binding-summary').forEach(e=>e.innerHTML=calendarBindingMarkup());};
for(const type of ['input','change'])document.addEventListener(type,e=>{if(!e.target.closest('#condition-viewer'))return;conditionRemember();const v=conditionCurrent();if(e.target.dataset.path?.startsWith('factors.condition.')||e.target.dataset.operationHour)queueMicrotask(()=>{if(conditionCurrent()===v)conditionTrack();});},true);
const conditionBeforeReset=resetConfiguration;
resetConfiguration=function(){conditionBeforeReset();conditionPositions.delete(conditionKey());const v=conditionCurrent();if(v){v.undo=null;v.after=null;}};
const conditionBeforeCalendar=renderCalendarLibrary;
renderCalendarLibrary=function(){conditionBeforeCalendar();conditionChild(calendarLibraryDialog(),'[data-calendar-library-tool="close"]');};
const conditionBeforeReference=renderReferenceReadiness;
renderReferenceReadiness=function(){conditionBeforeReference();conditionChild(referenceDialog(),'[data-reference-dialog="close"]');};
const conditionBeforeDaily=renderDailyReference;
renderDailyReference=function(){conditionBeforeDaily();conditionChild(dailyReferenceDialog(),'[data-daily-reference-tool="close"]');};
const conditionBeforeExample=renderCalendarPreview;
renderCalendarPreview=function(){conditionBeforeExample();conditionChild(calendarDialog(),'[data-calendar-tool="close"]');};
const conditionBeforeMaterial=renderMaterialViewer;
renderMaterialViewer=function(){conditionBeforeMaterial();conditionChild(materialViewerDialog(),'[data-material-view="close"]');};
const conditionBeforeDailyManager=renderDailyManager;
renderDailyManager=function(){conditionBeforeDailyManager();conditionChild(dailyManagerElement(),'[data-daily-action="close"]');};
