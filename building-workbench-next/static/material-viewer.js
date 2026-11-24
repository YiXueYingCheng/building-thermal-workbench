/* Material view/edit shares the scheme draft and the existing adoption/save handlers. */
S.materialViewer=null;
const materialViewerPositions=new Map(),materialViewerTabs={overview:'当前配置',thermal:'热学参数',optics:'表面光学参数',application:'应用与构造',library:'选用与版本'};
const materialsBeforeViewer=materialsPanel;
function materialViewerKey(){return JSON.stringify([S.id,S.saved?.revision]);}
function materialViewerCurrent(){const v=S.materialViewer;return v?.key===materialViewerKey()?v:null;}
function materialViewerFive(){return S.record.factors.building.id==='building2_5f_verified';}
function materialViewerGeneric(){return S.record.provenance.adapter!=='ordinary_building_v1';}
function materialViewerLibrary(){return S.record.provenance.adapter==='global_frozen_v011';}
function canRemoveResearchMaterial(){
 return !readonly()&&['ordinary_building_v1','global_frozen_v011'].includes(S.record.provenance.adapter)&&S.record.factors.materials.definitions.length>0;
}
function materialViewerSnapshot(){const f=S.record.factors;return copy({materials:f.materials,controls:f.condition.controls,references:f.condition.reference_runs,step:S.record.numerics.step_minutes,parent:S.materialParent??null});}
function removeResearchMaterialFromDraft(){
 if(!canRemoveResearchMaterial())throw Error('请在可编辑且已铺研究材料的方案中恢复 W00。');
 const before=materialViewerSnapshot();
 const feedback=before.controls.find(c=>c.channel==='thermal'&&c.mode==='feedback');
 if(feedback?.reference_step_minutes&&before.materials.definitions.some(mtPhysical)){
   setPath('numerics.step_minutes',feedback.reference_step_minutes);
 }
 setPath('factors.materials',{definitions:[],applications:[]});
 setPath('factors.condition.controls',[]);
 setPath('factors.condition.reference_runs',[]);
 S.calendarUndo=null;S.materialParent=null;S.ordinaryMaterialChoice=null;S.ordinaryMaterialUndo=null;
 const key=materialViewerKey(),viewer=materialViewerCurrent();
 const undo={undo:before,after:materialViewerStamp()};
 if(viewer)Object.assign(viewer,undo,{mode:'view',confirmRemove:false});
 else materialViewerPositions.set(key,{...materialViewerPositions.get(key),...undo});
}
function materialViewerStamp(){return JSON.stringify(materialViewerSnapshot());}
function materialViewerChanged(){const f=S.record.factors,b=S.saved.factors;return JSON.stringify([f.materials,f.condition.controls,f.condition.reference_runs])!==JSON.stringify([b.materials,b.condition.controls,b.condition.reference_runs]);}
function materialViewerStatus(){const p=S.record.factors.materials.definition_reference;return (p?`选用材料库版本 v${p.revision}`:'材料参数随方案保存')+(materialViewerChanged()?' · 材料或对应工况有未保存修改':' · 与本方案保存版一致');}
function materialViewerPositionsText(){const apps=S.record.factors.materials.applications;return apps.map(a=>`${({opaque_exterior:'不透明外表面',wall:'墙体',roof:'屋顶',floor:'楼板',window:'窗户'})[a.component]||a.component} · ${a.target_ids.length} 个构件 · ${({exterior:'外侧附加',interior:'内侧',between:'原构造层间',legacy_construction:'来源构造'})[a.position]||a.position}`).join('；');}
function materialViewerControlText(){const m=S.record.factors.materials;return S.record.factors.condition.controls.map(c=>{const a=m.applications.find(a=>a.id===c.application_id),d=m.definitions.find(d=>d.id===a?.material_id);return c.channel==='thermal'?`${c.mode==='fixed'?'固定 '+(d?.states.find(s=>s.id===c.state_id)?.name||c.state_id):c.mode==='feedback'?'热学反馈切换':c.mode} · ${c.target_ids.length} 个构件`:c.channel==='orientation'?`${c.mode==='fixed'?'固定 '+c.face_id:c.mode==='calendar'?'按日历切换表面光学参数':c.mode} · ${c.target_ids.length} 个构件`:'';}).filter(Boolean);}
materialsPanel=function(){const m=S.record.factors.materials;return `<section class="material-launcher"><div><h2>${m.definitions.length?m.definitions.map(d=>esc(d.name)).join('、'):m.legacy_construction_overrides?'原构造指定':'保留原建筑构造'}</h2><p>${esc(materialViewerPositionsText()||'当前未添加研究材料层')}</p>${m.definitions.length?`<p class="muted">${materialViewerControlText().map(esc).join('；')}</p>`:''}<p class="muted">${esc(materialViewerStatus())}</p></div><button class="primary" data-material-view="open">查看材料与应用</button></section>${geometryPanel()}`;};
function materialViewerDialog(){
 let d=document.getElementById('material-viewer');if(d)return d;d=document.createElement('dialog');d.id='material-viewer';d.setAttribute('aria-labelledby','material-viewer-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeMaterialViewer();});
 d.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();const v=materialViewerCurrent();if(!v||b.disabled)return;
  if(b.dataset.materialView==='close'){closeMaterialViewer();return;}if(v.pending)return;rememberMaterialViewer();v.message='';
  try{await materialViewerAction(b,v);}catch(error){if(materialViewerCurrent()===v){v.message=error.message;renderMaterialViewer();}}
 });
 // Existing field listeners keep their conversion and dependency behavior.
 d.addEventListener('input',()=>rememberMaterialViewer());d.addEventListener('change',()=>rememberMaterialViewer());
 return d;
}
function rememberMaterialViewer(){const v=materialViewerCurrent();if(!v||v.suspended)return;const d=materialViewerDialog(),key=v.mode+':'+v.tab;v.scroll[key]=d.querySelector('.material-viewer-body')?.scrollTop||0;v.expanded[key]=Array.from(d.querySelectorAll('.material-viewer-body details')).map(e=>e.open);}
function materialViewerR(s){return s.thermal_input==='conductivity_thickness'?(s.thickness_mm!=null&&s.conductivity_W_mK>0?s.thickness_mm/1000/s.conductivity_W_mK:null):s.resistance_m2K_W;}
function materialViewerAlpha(o){return o?.input_basis==='solar_absorptance'?o.solar_absorptance:o?.reflectance!=null?1-o.reflectance:o?.solar_absorptance;}
function materialViewerThermal(){return S.record.factors.materials.definitions.map(d=>`<section class="material-detail"><h3>${esc(d.name)}</h3><div class="viewer-table"><table class="table"><thead><tr><th>状态</th><th>输入方式</th><th>厚度 mm</th><th>导热系数 W/(m·K)</th><th>热阻 m²·K/W</th></tr></thead><tbody>${d.states.map(s=>`<tr><td>${esc(s.name)} · ${esc(s.id)}</td><td>${s.thermal_input==='conductivity_thickness'?'厚度与导热系数':'直接热阻'}</td><td>${viewerValue(s.thickness_mm,3)}</td><td>${viewerValue(s.conductivity_W_mK,5)}</td><td>${viewerValue(materialViewerR(s),6)}</td></tr>`).join('')}</tbody></table></div><p class="muted">${d.model==='equivalent_resistance_no_layer_storage'?'等效热阻模型，忽略材料层自身蓄热。':'沿用此材料的来源模型。'}这里列出各状态参数，实际采用状态由工况决定。</p></section>`).join('')||'<p>当前没有研究材料热学参数。</p>';}
function materialViewerOptics(){if(!S.record.factors.materials.definitions.length)return '<p>当前没有研究材料光学参数。</p>';return '<p>A、B 是材料定义的两组外表面光学参数，可用于描述原位光学变化。工况决定当前暴露在室外的表面采用哪一组，构造层序由材料应用确定。</p>'+S.record.factors.materials.definitions.map(d=>`<section class="material-detail"><h3>${esc(d.name)} · ${d.optics_depend_on_state?'按热学状态分别配置':'两种热学状态共用光学参数'}</h3><div class="viewer-table"><table class="table"><thead><tr><th>光学参数组 / 热学状态</th><th>太阳反射率</th><th>太阳吸收率</th><th>长波发射率</th></tr></thead><tbody>${(d.optics_depend_on_state?d.states.flatMap(s=>['A','B'].map(f=>f+'_'+s.id)):['A_R','B_R']).map(key=>{const o=d.optics?.[key];return `<tr><td>${esc(key.split('_')[0])} 组 · ${d.optics_depend_on_state?esc(d.states.find(s=>key.endsWith('_'+s.id))?.name||key):'两态共用'}${!o?' · 未提供':''}</td><td>${viewerValue(o?.reflectance,4)}</td><td>${viewerValue(materialViewerAlpha(o),4)}</td><td>${viewerValue(o?.emissivity,4)}</td></tr>`;}).join('')}</tbody></table></div><p class="muted">不透明材料采用反射率输入时，太阳吸收率为 1 − 反射率；缺失值显示“—”。光学参数组及切换规则在工况中设置。</p></section>`).join('');}
function materialViewerOverview(){const m=S.record.factors.materials,ref=m.definition_reference;return `<h3>${m.definitions.length?m.definitions.map(d=>esc(d.name)).join('、'):'当前保留原建筑构造'}</h3><div class="material-overview-grid"><article><h4>应用到哪里</h4><p>${esc(materialViewerPositionsText()||'未添加研究层')}</p></article><article><h4>当前如何使用</h4>${materialViewerControlText().map(t=>'<p>'+esc(t)+'</p>').join('')||'<p>没有研究材料控制</p>'}</article></div><p>${ref?'所选库版本：'+esc(ref.name)+' · v'+ref.revision:'材料参数当前保存在方案内。'}</p>${m.definitions.map(d=>`<details><summary>${esc(d.name)} · 参数来源与模型说明</summary><p>${esc(d.source_note||'见当前方案来源记录。')}</p><p>${d.model==='equivalent_resistance_no_layer_storage'?'采用等效热阻，忽略该材料层自身蓄热。':'沿用来源模型。'}</p></details>`).join('')}${m.legacy_construction_overrides?`<details><summary>查看原构造指定</summary><pre>${esc(JSON.stringify(m.legacy_construction_overrides,null,2))}</pre></details>`:''}<p class="muted">材料条目记录可选属性和状态，材料应用指定构件与层位，工况选择热阻状态、光学参数组或切换规则。</p>`;}
function materialViewerApplication(){const m=S.record.factors.materials;let html=m.applications.map(a=>`<section class="material-detail"><h3>${esc(m.definitions.find(d=>d.id===a.material_id)?.name||a.material_id)}</h3><p>${esc(({exterior:'外侧附加层',interior:'内侧附加层',between:'原构造层间',legacy_construction:'沿用来源构造'})[a.position]||a.position)} · ${a.target_ids.length} 个构件${a.between_layers?' · '+a.between_layers.map(esc).join(' / '):''}</p><details><summary>应用构件清单</summary><p>${a.target_ids.map(esc).join('、')}</p></details></section>`).join('')||'<p>当前没有新增材料应用。</p>';
 if(drawingScopeEnabled())return drawingApplicationMarkup();
 if(materialViewerFive())html+='<button data-ordinary-material="inspect">核对外墙范围与层序</button>';
 else if(materialViewerLibrary()){html+='<button data-configuration="construction">核对基础构造与研究层</button>';const t=document.createElement('template');t.innerHTML=materialsBeforeViewer();html+=t.content.querySelector('.configuration-construction')?.outerHTML||'';}
 return html;
}
function materialViewerLibraryView(){const m=S.record.factors.materials,ref=m.definition_reference;return `<h3>材料选用与版本</h3><p>${ref?'当前选用 '+esc(ref.name)+' · v'+ref.revision:'当前没有绑定材料库版本。'}</p>${materialViewerLibrary()?`<button data-configuration="material-list">读取 / 刷新材料库</button>${S.materialLibraryOpen?`<section class="well"><label class="field">已保存材料版本<select data-component-use="material"${disabled()}>${componentOptions('material',ref)}</select></label><p class="muted">选择版本后，在材料库预览铺设范围，再确认加入草稿。</p></section>`:''}`:materialViewerFive()?'<p>五层建筑通过“应用与构造 → 编辑”预览采用固定 ECA；当前材料参数按已核实版本使用。</p>':'<p>此来源暂保留原材料配置，没有接通材料库替换。</p>'}<p class="muted">保存材料库版本用于复用，只保存材料定义；应用位置和工况随方案版本保存。选用材料后，请回主页面保存方案版本。</p>`;}
function materialViewerCanEdit(){return !readonly()&&(materialViewerFive()?['application'].includes(materialViewerCurrent()?.tab):materialViewerGeneric()&&S.record.factors.materials.definitions.length&&['thermal','optics','application'].includes(materialViewerCurrent()?.tab));}
function materialViewerEditor(){
 const v=materialViewerCurrent();if(materialViewerFive()){
  const t=document.createElement('template');t.innerHTML=materialsBeforeViewer();const well=t.content.querySelector('.well');if(!well)return '<p>此来源的编辑尚未接通。</p>';
  well.querySelectorAll('h3,:scope>p').forEach(e=>e.remove());well.querySelector('[data-configuration="material-save"]')?.remove();return '<h3>编辑固定 ECA 应用</h3><p>选择只形成预览意向；核对并确认采用后，才改变方案草稿。</p>'+well.outerHTML;
 }
 const t=document.createElement('template');t.innerHTML=originalMaterialsPanel();const defs=Array.from(t.content.children).filter(e=>e.querySelector('.state-grid'));
 if(v.tab==='application')return Array.from(t.content.children).filter(e=>e.classList.contains('control')).map(e=>e.outerHTML).join('');
 return defs.map((e,i)=>{const d=S.record.factors.materials.definitions[i];if(v.tab==='thermal')return `<section class="material-detail"><h3>${esc(d.name)}</h3>${i===0?`<label class="field">材料名称<input data-path="factors.materials.definitions.0.name" value="${esc(d.name)}"${disabled()}></label>`:''}${e.querySelector('.state-grid').outerHTML}</section>`;
 const relation=e.querySelector(':scope>.grid2>label'),optics=e.querySelector(':scope>details');optics?.querySelector('summary')?.remove();return `<section class="material-detail"><h3>${esc(d.name)}</h3>${relation?.outerHTML||''}${optics?.innerHTML||''}</section>`;
 }).join('');
}
function materialViewerContent(){const v=materialViewerCurrent();if(v.mode==='edit'&&materialViewerCanEdit())return materialViewerEditor();return ({overview:materialViewerOverview,thermal:materialViewerThermal,optics:materialViewerOptics,application:materialViewerApplication,library:materialViewerLibraryView})[v.tab]();}
function renderMaterialViewer(){
 const v=materialViewerCurrent();if(!v||v.suspended)return;const d=materialViewerDialog(),tabs=Object.entries(materialViewerTabs),m=S.record.factors.materials,focus=d.contains(document.activeElement)?document.activeElement:null,field=focus?.dataset.path;
 const canSave=!readonly()&&m.definitions.length===1&&(materialViewerLibrary()||materialViewerFive());
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(S.record.name)} · ${esc(planVersionLabel(S.saved))}${readonly()?' · 只读':''}</p><h2 id="material-viewer-title" tabindex="-1">${v.mode==='edit'?'编辑材料与应用':'材料与应用'}</h2></div><div class="actions">${v.mode==='edit'?'<button data-material-view="detail">← 返回材料查看</button>':''}<button data-material-view="close">关闭</button></div></header><nav class="material-viewer-tabs" aria-label="材料内容">${tabs.map(([key,label])=>`<button data-material-view="tab" data-material-tab="${key}" aria-pressed="${v.tab===key}">${label}</button>`).join('')}</nav><div class="material-viewer-body">${v.loading?'<p role="status">正在读取构造依据…</p>':''}${v.loadError?`<p class="warning">构造依据读取失败：${esc(v.loadError)}</p><button data-material-view="retry">重试读取</button>`:''}<div class="material-edit-entry">${v.mode==='view'&&materialViewerCanEdit()?'<button class="primary" data-material-view="edit">'+(v.tab==='application'?'编辑材料应用':'编辑本页参数')+'</button>':''}</div>${materialViewerContent()}<div class="material-viewer-capability" role="status">${capabilityStatus()}</div></div><footer class="viewer-foot material-viewer-foot"><div><p data-material-status>${esc(materialViewerStatus())}</p><p class="muted">${materialViewerChanged()?'修改已进入方案草稿；关闭保留，回主页面保存方案版本。':'保存到材料库后，可从「选用与版本」预览并选用该版本。'}</p><p class="viewer-message" role="status" data-material-message${v.message?'':' hidden'}>${esc(v.message)}</p>${v.confirmRemove?'<p>将从当前草稿撤掉研究材料、热阻控制与光学日历绑定，按当前建筑构造计算 W00。已保存的材料、日历和方案版本仍可使用。</p><div class="actions"><button data-material-view="remove-confirm">确认恢复 W00 到草稿</button><button data-material-view="remove-cancel">继续保留</button></div>':''}</div><div class="actions">${canSave?'<button data-configuration="material-save">保存材料库版本</button>':''}${canRemoveResearchMaterial()&&!v.confirmRemove?'<button data-material-view="remove">撤掉材料引用，恢复 W00…</button>':''}${v.undo&&v.after?'<button data-material-view="undo"'+disabled()+'>撤销本次材料编辑</button>':''}<button data-material-view="close">关闭并返回方案</button></div></footer>`;
 if(!d.open)d.showModal();const target=field?Array.from(d.querySelectorAll('[data-path]')).find(e=>e.dataset.path===field):focus?.id?d.querySelector('#'+CSS.escape(focus.id)):null;(target||d.querySelector('#material-viewer-title')).focus({preventScroll:true});
 const key=v.mode+':'+v.tab;Array.from(d.querySelectorAll('.material-viewer-body details')).forEach((e,i)=>{if(v.expanded[key]?.[i]!=null)e.open=v.expanded[key][i];});d.querySelector('.material-viewer-body').scrollTop=v.scroll[key]||0;
 if(v.pending){d.querySelector('.material-viewer-body').inert=true;d.querySelectorAll('button').forEach(b=>b.disabled=true);}
}
function materialViewerBegin(){const v=materialViewerCurrent();if(v&&!v.undo){v.undo=materialViewerSnapshot();v.after=null;}}
function materialViewerTrack(){const v=materialViewerCurrent();if(!v)return;if(v.undo)v.after=materialViewerStamp()===JSON.stringify(v.undo)?null:materialViewerStamp();document.querySelectorAll('[data-material-status]').forEach(e=>e.textContent=materialViewerStatus());const d=materialViewerDialog();if(v.after&&!d.querySelector('[data-material-view="undo"]')){const b=document.createElement('button');b.dataset.materialView='undo';b.textContent='撤销本次材料编辑';d.querySelector('.material-viewer-foot>.actions')?.prepend(b);}}
async function materialViewerLoad(v){
 if(!configurationSupported())return;v.loading=true;v.loadError='';renderMaterialViewer();const key=S.id+':'+S.saved.revision;
 try{const data=await api('/api/configuration/'+encodeURIComponent(S.id)+'?revision='+encodeURIComponent(S.saved.revision));if(materialViewerCurrent()!==v)return;S.configuration={key,data};if(!S.usageDraft)resetUsageDraft();}
 catch(e){if(materialViewerCurrent()===v)v.loadError=e.message;}
 finally{if(materialViewerCurrent()===v){rememberMaterialViewer();v.loading=false;renderMaterialViewer();}}
}
function openMaterialViewer(opener){const key=materialViewerKey(),v={key,mode:'view',tab:'overview',scroll:{},expanded:{},...materialViewerPositions.get(key),opener,mainY:scrollY,message:'',pending:false,suspended:null,confirmRemove:false};v.mode='view';S.materialViewer=v;document.documentElement.classList.add('material-viewer-open');renderMaterialViewer();if(!S.configuration)void materialViewerLoad(v);}
function closeMaterialViewer(restore=true){const v=S.materialViewer;if(!v)return;if(v.pending&&!v.suspended){notice('正在完成操作，请稍候再关闭。');return;}if(!v.suspended)rememberMaterialViewer();materialViewerPositions.set(v.key,{tab:v.tab,scroll:v.scroll,expanded:v.expanded,undo:v.undo,after:v.after});S.materialViewer=null;if(v.suspended==='ordinary')closeOrdinaryMaterial();if(v.suspended==='weather')closeWeatherImport();materialViewerDialog().close();document.documentElement.classList.remove('material-viewer-open');if(restore)render();if(restore)requestAnimationFrame(()=>{window.scrollTo({top:v.mainY,behavior:'instant'});document.querySelector('[data-material-view="open"]')?.focus({preventScroll:true});});}
async function materialViewerAction(b,v){
 const op=b.dataset.materialView;
   if(op==='wall-scope'){await openDrawingWalls('coverage');return;}
 if(op==='tab'){v.mode='view';v.tab=b.dataset.materialTab;v.confirmRemove=false;renderMaterialViewer();return;}
 if(op==='detail'){v.mode='view';renderMaterialViewer();return;}
 if(op==='edit'){if(!materialViewerCanEdit())return;materialViewerBegin();v.mode='edit';renderMaterialViewer();return;}
 if(op==='retry'){await materialViewerLoad(v);return;}
 if(op==='remove'||op==='remove-cancel'){v.confirmRemove=op==='remove';renderMaterialViewer();return;}
 if(op==='remove-confirm'){materialViewerBegin();b=document.createElement('button');b.dataset.configuration='remove-material';v.confirmRemove=false;}
 if(op==='undo'){
  if(readonly()||!v.undo||v.after!==materialViewerStamp())throw Error('材料或对应控制经过后续修改，未直接撤销，请先核对。');const u=v.undo;
  setPath('factors.materials',copy(u.materials));setPath('factors.condition.controls',copy(u.controls));setPath('factors.condition.reference_runs',copy(u.references));setPath('numerics.step_minutes',u.step);S.materialParent=u.parent;S.ordinaryMaterialUndo=null;S.ordinaryMaterialChoice=null;
  S.dirty=JSON.stringify(changes())!==JSON.stringify(Object.fromEntries(['name','factors','numerics','execution'].map(k=>[k,S.saved[k]])));v.undo=null;v.after=null;v.mode='view';v.message='已恢复本次材料编辑前的配置；其他因素保留，已保存的材料库版本仍保留。';render();return;
 }
 if(['adopt','remove','undo'].includes(b.dataset.ordinaryMaterial))materialViewerBegin();
 const child=['adopt','remove','inspect'].includes(b.dataset.ordinaryMaterial);if(child){v.suspended='ordinary';materialViewerDialog().close();}
 const waiting=b.dataset.configuration==='material-save'?'正在保存材料库版本…':'正在读取或处理…';v.pending=true;v.message=waiting;if(!child)renderMaterialViewer();
 try{if(b.dataset.action==='check-capability')await refreshCapability();else await configurationAction(b);if(materialViewerCurrent()!==v)return;materialViewerTrack();if(b.dataset.configuration==='material-save')v.message='已保存到公用材料库。要在当前方案中采用此版本，请预览并确认选用。';if(b.dataset.configuration==='remove-material'){v.mode='view';v.message='当前草稿已恢复 W00。保存为新版本后即可生成模型输入。';}}
 finally{if(materialViewerCurrent()===v){v.pending=false;if(v.message===waiting)v.message='';if(child&&!document.querySelector('dialog[open]'))v.suspended=null;renderMaterialViewer();}}
}
const materialViewerConfigurationAction=configurationAction;
configurationAction=async function(b){if(b.dataset.materialView==='open'){openMaterialViewer(b);return true;}return materialViewerConfigurationAction(b);};
const materialViewerRender=render;
render=function(){if(S.materialViewer&&!materialViewerCurrent()){S.materialViewer.pending=false;closeMaterialViewer(false);}materialViewerRender();if(materialViewerCurrent()&&!materialViewerCurrent().suspended)renderMaterialViewer();};
document.addEventListener('input',e=>{if(e.target.closest('#material-viewer'))materialViewerTrack();});
document.addEventListener('change',e=>{if(e.target.closest('#material-viewer')){materialViewerTrack();}});
// Capture only the pre-change snapshot; established document handlers still do the actual edit.
document.addEventListener('change',e=>{if(!e.target.closest('#material-viewer'))return;const v=materialViewerCurrent();if(e.target.dataset.componentUse==='material')materialViewerBegin();queueMicrotask(()=>{if(materialViewerCurrent()===v)materialViewerTrack();});},true);
const materialViewerNotice=notice;
notice=function(text=''){materialViewerNotice(text);const v=materialViewerCurrent();if(v&&!v.suspended){v.message=text;const el=materialViewerDialog().querySelector('[data-material-message]');if(el){el.textContent=text;el.hidden=!text;}}};
const materialViewerCapability=updateCapabilityStatus;
updateCapabilityStatus=function(){materialViewerCapability();const el=document.querySelector('#material-viewer .material-viewer-capability');if(el)el.innerHTML=capabilityStatus();};
function resumeMaterialViewer(kind){const v=materialViewerCurrent();if(v?.suspended!==kind)return;queueMicrotask(()=>{if(materialViewerCurrent()!==v||document.querySelector('dialog[open]'))return;v.suspended=null;v.pending=false;materialViewerTrack();renderMaterialViewer();});}
const ordinaryCloseBeforeMaterialViewer=closeOrdinaryMaterial;
closeOrdinaryMaterial=function(){ordinaryCloseBeforeMaterialViewer();resumeMaterialViewer('ordinary');};
const ordinaryRenderBeforeMaterialViewer=renderOrdinaryMaterial;
renderOrdinaryMaterial=function(){ordinaryRenderBeforeMaterialViewer();if(materialViewerCurrent()?.suspended==='ordinary')ordinaryMaterialDialog().querySelector('[data-ordinary-material="close"]').textContent='返回材料配置';};
const componentOpenBeforeMaterialViewer=openComponentVersionUpdate;
openComponentVersionUpdate=async function(row){const v=materialViewerCurrent();if(v){rememberMaterialViewer();v.suspended='weather';materialViewerDialog().close();}try{await componentOpenBeforeMaterialViewer(row);}catch(e){resumeMaterialViewer('weather');throw e;}};
const weatherCloseBeforeMaterialViewer=closeWeatherImport;
closeWeatherImport=function(){weatherCloseBeforeMaterialViewer();resumeMaterialViewer('weather');};
const weatherRenderBeforeMaterialViewer=renderWeatherImport;
renderWeatherImport=function(){weatherRenderBeforeMaterialViewer();if(materialViewerCurrent()?.suspended==='weather')weatherDialog().querySelector('[data-weather-action="close"]').textContent='返回材料配置';};

const resetBeforeMaterialViewer=resetConfiguration;
resetConfiguration=function(){resetBeforeMaterialViewer();materialViewerPositions.delete(materialViewerKey());const v=materialViewerCurrent();if(v){v.undo=null;v.after=null;}};
