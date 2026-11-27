/* One object workspace. Shared scheme draft; view navigation never saves it. */
S.buildingViewer=null;
function buildingViewerCurrent(){const v=S.buildingViewer;return v&&v.key===geometryKey()?v:null;}
function buildingViewerDialog(){
 let d=document.getElementById('building-viewer');if(d)return d;
 d=document.createElement('dialog');d.id='building-viewer';d.setAttribute('aria-labelledby','building-viewer-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeBuildingViewer();});
 d.addEventListener('click',async e=>{
  const b=e.target.closest('button'),node=e.target.closest('[data-geometry-node]');if(!b&&!node)return;e.stopPropagation();
  const v=buildingViewerCurrent();if(!v)return;
  if(b?.dataset.viewer==='close'){closeBuildingViewer();return;}
  if(v.pending||b?.disabled)return;
  try{
   if(typeof wallOpticsAction==='function'&&wallOpticsAction(b))return;
   if(typeof roomViewerAction==='function'&&await roomViewerAction(b,node))return;
   if(node){viewerSelect(node.dataset.geometryNode,node.dataset.geometryId);return;}
   const op=b.dataset.viewer||b.dataset.geometry;
   if(op==='wall-input'){await loadWallInput(v);return;}
   if(op==='back'){v.view='plan';renderBuildingViewer();return;}
   if(op==='wall-config'||op==='material-config'){rememberViewerPlan();v.view='wall';v.wall=geometryState().wall;v.message='';renderBuildingViewer();return;}
   if(op==='edit'){const row=viewerWall().row;if(!viewerCanEdit(row))throw Error('此面当前只读，请从可编辑方案或相邻修改侧操作。');v.undo[row.id]??={before:copy(S.record.factors.building.envelope_overrides?.[row.id]||null),after:null};v.view='edit';renderBuildingViewer();return;}
   if(op==='detail'){v.view='wall';renderBuildingViewer();return;}
   if(op==='undo'){viewerUndo();return;}
   if(op==='pair'){v.wall=b.dataset.target;v.view='wall';v.message='';renderBuildingViewer();return;}
   if(op==='refresh'){await refreshBuildingViewer(v);return;}
   if(op==='room-config'){
    const id=geometryState().room;closeBuildingViewer(false);const i=S.usageDraft.rooms.findIndex(r=>r.id===id);
    if(i<0)throw Error('此房间配置暂未接入。');S.usageRoom=i;S.factor='building';render();geometryScroll('.usage-editor');return;
   }
  }catch(error){v.message=error.message;renderBuildingViewer();}
 });
 d.addEventListener('change',e=>{
  const v=buildingViewerCurrent();if(!v)return;if(typeof roomViewerActive==='function'&&roomViewerActive()){roomViewerChange(e);return;}e.stopPropagation();if(v.pending)return;
  if(typeof wallOpticsChange==='function'&&wallOpticsChange(e.target))return;
  const m=geometryState(),id=e.target.id;
  if(id==='wall-input-bundle'){void loadWallInput(v,e.target.value);return;}
  if(id==='wall-input-case'){void loadWallInput(v,v.wallInput.bundle,Number(e.target.value));return;}
  if(id==='geometry-floor'){rememberViewerPlan();m.floor=Number(e.target.value);m.room=null;m.wall=null;v.planScroll={top:0,left:0};renderBuildingViewer();}
  if(id==='geometry-room')viewerSelect('room',e.target.value);
  if(id==='geometry-wall'){if(e.target.value)viewerSelect('wall',e.target.value);else{m.wall=null;renderBuildingViewer();}}
 });
 d.addEventListener('input',e=>{if(e.target.hasAttribute('data-viewer-field')){e.stopPropagation();viewerEdit(e.target);}});
 d.addEventListener('keydown',e=>{const n=e.target.closest('[data-geometry-node]');if(n&&['Enter',' '].includes(e.key)){e.preventDefault();e.stopPropagation();viewerSelect(n.dataset.geometryNode,n.dataset.geometryId);Array.from(d.querySelectorAll('[data-geometry-node]')).find(x=>x.dataset.geometryNode===n.dataset.geometryNode&&x.dataset.geometryId===n.dataset.geometryId)?.focus({preventScroll:true});}});
 return d;
}
function rememberViewerPlan(){const v=buildingViewerCurrent(),d=buildingViewerDialog();if(v?.view==='plan')v.planScroll={top:d.querySelector('.viewer-body')?.scrollTop||0,left:d.querySelector('.geometry-canvas')?.scrollLeft||0};}
function viewerSelect(kind,id){
 const v=buildingViewerCurrent(),m=geometryState();if(!v||!m.data?.supported)return;rememberViewerPlan();
 const w=kind==='wall'?m.data.walls.find(x=>x.id===id):null,r=m.data.rooms.find(x=>x.id===(w?w.room_id:id));
 if(!r){if(kind==='room'&&!id){m.room=null;m.wall=null;renderBuildingViewer();}return;}
 m.floor=r.floor;m.room=r.id;m.wall=w?.id||null;renderBuildingViewer();
}
function viewerWall(){
 const v=buildingViewerCurrent(),all=S.configuration?.data.envelope,row=all?.[v?.wall];
 if(row)return {row,effective:envelopeEffective(all,row.id,S.record.factors.building.envelope_overrides||{}),editable:true};
 const w=S.configuration?.data.walls?.find(x=>x.id===v?.wall);
 return w?{row:{...w,type:'Wall',boundary:'Outdoors',pair:null,layers:w.layer_details||w.layers.map(name=>({name,values:{},kind:'unavailable'}))},effective:{layers:w.layer_details||[],owner:null,paired:false,changes:[]},editable:false}:{};
}
function viewerCanEdit(row){return !!row&&S.record.provenance.adapter==='ordinary_building_v1'&&!readonly()&&!envelopeEffective(S.configuration.data.envelope,row.id,S.record.factors.building.envelope_overrides||{}).paired;}
function viewerValue(v,digits=4){return v==null||!Number.isFinite(Number(v))?'—':format(v,digits);}
function viewerR(layer){const x=layer.values;if(x.thermal_resistance!=null)return x.thermal_resistance;return x.thickness!=null&&x.conductivity>0?x.thickness/x.conductivity:null;}
function viewerMaterial(wall){
 const apps=S.record.factors.materials.applications.filter(a=>a.target_ids.includes(wall));if(!apps.length)return '<p>此面没有新增研究材料层。</p>';
 return apps.map(a=>{
  const d=S.record.factors.materials.definitions.find(d=>d.id===a.material_id),controls=S.record.factors.condition.controls.filter(c=>c.application_id===a.id && c.target_ids.includes(wall));
  if(!d)return '<p class="warning">材料定义缺失，请回到方案核对。</p>';
  const thermal=controls.find(c=>c.channel==='thermal'),optical=controls.find(c=>c.channel==='orientation');
  const stateLabel=thermal?.mode==='fixed'?'固定 '+(d.states.find(s=>s.id===thermal.state_id)?.name||thermal.state_id):thermal?.mode==='feedback'?'热学状态按反馈切换':'热学状态尚未明确';
  const faceLabel=optical?.mode==='fixed'?'固定 '+optical.face_id:optical?.mode==='calendar'?'按日历切换表面光学参数':'外表面光学参数组尚未明确';
  if(d.model==='layer_stack_v1')return '<article><h4>'+esc(d.name)+'</h4>'+stackWallInfo(d,a)+'</article>';
  if(d.spectral)return '<article><h4>'+esc(d.name)+'</h4><p>'+esc(stateLabel+' · '+faceLabel)+'</p>'+wallMaterialOptics(d,controls)+'</article>';
  const rows=d.states.flatMap(s=>['A','B'].filter(face=>d.optics[face+'_'+s.id]).map(face=>{
   const o=d.optics[face+'_'+s.id],R=s.thermal_input==='conductivity_thickness'?(s.conductivity_W_mK>0&&s.thickness_mm!=null?s.thickness_mm/1000/s.conductivity_W_mK:null):s.resistance_m2K_W;
   const alpha=o.input_basis==='opaque_reflectance'?(o.reflectance==null?null:1-o.reflectance):o.solar_absorptance;
   const current=thermal?.mode==='fixed'&&optical?.mode==='fixed'&&s.id===thermal.state_id&&face===optical.face_id;
   return `<tr${current?' class="viewer-current-material"':''}><td>${esc(s.name||s.id)} / ${face} 组${current?' · 当前固定配置':''}</td><td>${viewerValue(R,6)}</td><td>${viewerValue(alpha,4)}</td><td>${viewerValue(o.emissivity,4)}</td></tr>`;
  }));
  return `<article><h4>${esc(d.name)} · ${esc(({exterior:'外侧附加层',interior:'内侧',between:'原构造层间',legacy_construction:'沿用来源构造'})[a.position]||a.position)}</h4><p>${esc(stateLabel)} · ${esc(faceLabel)}</p><p class="muted">以下为本方案材料参数；动态状态不表示某一时刻的实际取值。${a.position!=='exterior'?'所选层位是否支持执行，以方案能力核对为准。':''}</p><div class="viewer-table"><table class="table"><thead><tr><th>状态 / 表面</th><th>附加热阻 m²·K/W</th><th>太阳吸收率</th><th>热发射率</th></tr></thead><tbody>${rows.filter(x=>x.includes('viewer-current-material')).join('')||'<tr><td colspan="4">运行时按控制规则取值；可展开核对全部状态参数。</td></tr>'}</tbody></table></div><details><summary>全部材料状态参数</summary><div class="viewer-table"><table class="table"><thead><tr><th>状态 / 表面</th><th>附加热阻 m²·K/W</th><th>太阳吸收率</th><th>热发射率</th></tr></thead><tbody>${rows.map(x=>x.replace(' class="viewer-current-material"','')).join('')}</tbody></table></div></details></article>`;
 }).join('');
}
function viewerWallMarkup(){
 const v=buildingViewerCurrent(),{row,effective:e,editable}=viewerWall();if(!row)return '<p class="warning">此来源尚未提供该墙面的构造参数；可返回平面查看几何。</p>';
 const w=geometryState().data?.walls.find(w=>w.id===row.id),layers=e.layers,editing=v.view==='edit'&&viewerCanEdit(row),status=editable?envelopeSelectionStatus(row,e):'沿用来源基础构造；此入口只读。';
 return `<div class="viewer-object"><div><h3>${esc(row.id)} · ${esc(envelopeKind(row)==='exterior-wall'?'外墙':'内墙')} · ${esc(row.zone)}</h3><p>${esc(w?.direction||'')} ${w?viewerValue(w.azimuth,1)+'° · 净墙 '+viewerValue(w.net_area_m2,2)+' m² · ':''}${esc(envelopeBoundaries[row.boundary]||row.boundary)}</p></div><span class="tag">${editing?'正在编辑基础构造':'墙体详情'}</span></div>
 <section class="viewer-section"><div class="row"><h3>基础构造 · ${esc(row.construction)}</h3><div class="actions">${editing?'<button data-viewer="detail">完成编辑，查看详情</button>':viewerCanEdit(row)?'<button data-viewer="edit">编辑此墙基础构造</button>':''}${row.pair?`<button data-viewer="pair" data-target="${esc(row.pair)}">${e.paired?'查看修改侧':'查看相邻另一侧'}</button>`:''}</div></div><p>${row.boundary==='Surface'?'从相邻房间侧到当前参考房间侧；另一侧层序相反。':'基础层从室外侧到室内侧；下方研究附加层另列。'}</p><p class="muted" data-viewer-wall-status>${status}</p>${!editable&&S.record.factors.materials.legacy_construction_overrides?'<p class="warning">此方案另有旧构造指定；下表只列建筑来源基础层，覆盖后的实际输入需在原构造设置核对。</p>':''}
 ${editing?layers.map((l,i)=>`<section class="viewer-layer"><h4>第 ${i+1} 层 · ${esc(row.layers[i].name)}</h4><div class="grid3">${Object.entries(l.values).filter(([k])=>envelopeLabels[k]).map(([k,value])=>`<label class="field">${esc(envelopeLabels[k])}<input type="number" step="any" data-viewer-field="${k}" data-viewer-layer="${i}" value="${esc(value??'')}"><small>建筑原值：${esc(envelopeValue(row.layers[i].values[k]))}</small></label>`).join('')}</div></section>`).join(''):`<div class="viewer-table"><table class="table"><thead><tr><th>顺序 / 材料</th><th>厚度 mm</th><th>导热系数 W/(m·K)</th><th>密度 kg/m³</th><th>比热 J/(kg·K)</th><th>层热阻 m²·K/W</th></tr></thead><tbody>${layers.map((l,i)=>`<tr><td>${i+1} · ${esc(row.layers[i].name)}</td><td>${viewerValue(l.values.thickness==null?null:l.values.thickness*1000,2)}</td><td>${viewerValue(l.values.conductivity)}</td><td>${viewerValue(l.values.density,2)}</td><td>${viewerValue(l.values.specific_heat,2)}</td><td>${viewerValue(viewerR(l),6)}</td></tr>`).join('')}</tbody></table></div><details><summary>逐层光学参数与基础构造修改</summary>${layers.map((l,i)=>`<p>第 ${i+1} 层：太阳吸收率 ${viewerValue(l.values.solar_absorptance)}；热发射率 ${viewerValue(l.values.thermal_absorptance)}。</p>`).join('')}${e.changes.map(c=>`<p>第 ${c.layer+1} 层 · ${esc(envelopeLabels[c.key]||c.key)}：${esc(envelopeValue(c.before))} → ${esc(envelopeValue(c.after))}</p>`).join('')}</details>`}
 ${v.undo[row.id]?.after?'<button data-viewer="undo">撤销本次墙体编辑</button>':''}</section><section class="viewer-section"><h3>研究材料与表面光学</h3>${viewerMaterial(row.id)}</section>`;
}
function viewerEdit(input){
 const v=buildingViewerCurrent(),{row}=viewerWall();if(!v||v.view!=='edit'||!viewerCanEdit(row))return;
 const i=Number(input.dataset.viewerLayer),field=input.dataset.viewerField;if(!row.layers[i]||!envelopeLabels[field])return;
 const x=copy(S.record.factors.building.envelope_overrides||{});x[row.id]??={layers:row.layers.map(l=>({kind:l.kind,values:copy(l.values)}))};
 x[row.id].layers[i].values[field]=input.value===''?null:Number(input.value);setPath('factors.building.envelope_overrides',x);v.undo[row.id].after=copy(x[row.id]);updateDirtyStatus();
 const d=buildingViewerDialog();d.querySelector('[data-viewer-draft]').textContent='已修改当前方案草稿 · 尚未保存版本';d.querySelector('[data-viewer-wall-status]').textContent='此面修改已进入方案草稿；相邻配对面按反向层位同步。';
 if(!d.querySelector('[data-viewer="undo"]')){const b=document.createElement('button');b.dataset.viewer='undo';b.textContent='撤销本次墙体编辑';d.querySelector('.viewer-section').append(b);}
}
function viewerUndo(){
 const v=buildingViewerCurrent(),{row}=viewerWall(),u=v.undo[row.id],x=copy(S.record.factors.building.envelope_overrides||{});
 if(!u||JSON.stringify(x[row.id])!==JSON.stringify(u.after))throw Error('此墙参数已再次变化，未直接撤销，请核对当前草稿。');
 if(u.before)x[row.id]=copy(u.before);else delete x[row.id];
 if(Object.keys(x).length)setPath('factors.building.envelope_overrides',x);else{delete S.record.factors.building.envelope_overrides;S.preview=null;S.generated=null;scheduleCapability();}
 S.dirty=JSON.stringify(changes())!==JSON.stringify(Object.fromEntries(['name','factors','numerics','execution'].map(k=>[k,S.saved[k]])));delete v.undo[row.id];v.view='wall';v.message='已恢复进入本次墙体编辑前的值；其他方案编辑保留。';updateDirtyStatus();renderBuildingViewer();
}
function renderBuildingViewer(){
 const v=buildingViewerCurrent();if(!v)return;const d=buildingViewerDialog(),m=geometryState(),focusId=d.contains(document.activeElement)?document.activeElement.id:null;
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(S.record.name)} · ${esc(planVersionLabel(S.saved))}${readonly()?' · 只读':''}</p><h2 id="building-viewer-title">${v.view==='plan'?'建筑平面与材料位置':v.view==='edit'?'编辑墙体基础构造':v.view==='optics-batch'?'推广外表面光学参数':'墙体构造详情'}</h2></div><div class="actions">${v.view!=='plan'?'<button data-viewer="back">← 返回原平面</button>':''}<button data-viewer="refresh"${v.pending?' disabled':''}>重新核对</button><button data-viewer="close">关闭</button></div></header><div class="viewer-body">${v.message?`<p role="status" class="viewer-message">${esc(v.message)}</p>`:''}${v.pending?'<p>正在读取建筑与构造…</p>':v.view==='plan'?geometryContents(true):viewerWallMarkup()}</div><footer class="viewer-foot"><span data-viewer-draft>${S.dirty?'当前方案草稿有未保存修改；关闭后保留，请回主页面保存版本。':'查看与切换不修改方案。'}${S.usageDirty?' 房间配置另有未保存编辑，继续保留。':''}</span><button data-viewer="close">关闭并返回方案</button></footer>`;
 if(!d.open)d.showModal();
 const focus=focusId&&d.querySelector('#'+CSS.escape(focusId));if(focus)focus.focus({preventScroll:true});else{const title=d.querySelector('#building-viewer-title');title.tabIndex=-1;title.focus({preventScroll:true});}
 if(v.view==='plan'){d.querySelector('.viewer-body').scrollTop=v.planScroll?.top||0;const canvas=d.querySelector('.geometry-canvas');if(canvas)canvas.scrollLeft=v.planScroll?.left||0;}
}
async function refreshBuildingViewer(v){
 rememberViewerPlan();v.wallInput=null;v.pending=true;v.message='';renderBuildingViewer();
 try{
  if(S.configuration?.key!==v.key){const data=await api('/api/configuration/'+encodeURIComponent(S.id)+'?revision='+encodeURIComponent(S.saved.revision));if(buildingViewerCurrent()!==v)return;S.configuration={key:v.key,data};resetUsageDraft();}
  await loadGeometry(geometryState());if(buildingViewerCurrent()!==v)return;v.message=geometryState().error;
 }catch(e){if(buildingViewerCurrent()===v)v.message=e.message;}
 finally{if(buildingViewerCurrent()===v){v.pending=false;renderBuildingViewer();}}
}
async function openBuildingViewer(opener,options={}){
 if(buildingViewerCurrent()){renderBuildingViewer();return;}
 const v={key:geometryKey(),view:'plan',wall:null,pending:false,undo:{},planScroll:{top:0,left:0},scrollY:window.scrollY,opener,message:'',...options};
 S.buildingViewer=v;document.documentElement.classList.add('building-viewer-open');await refreshBuildingViewer(v);
}
function closeBuildingViewer(restore=true){
 const v=S.buildingViewer;if(!v)return;S.buildingViewer=null;const d=buildingViewerDialog();d.close();d.innerHTML='';document.documentElement.classList.remove('building-viewer-open');
 render();if(restore)requestAnimationFrame(()=>{window.scrollTo({top:v.scrollY,behavior:'instant'});const b=v.opener?.isConnected?v.opener:document.querySelector('[data-geometry="toggle"]');b?.focus({preventScroll:true});});
}
geometryPanel=function(){return configurationSupported()?'<div class="configuration-toolbar geometry-toolbar"><button data-geometry="toggle">查看建筑平面与材料位置</button><span class="muted">在查看窗口中定位墙面、核对构造并返回</span></div>':'';};
const beforeBuildingViewerAction=configurationAction;
configurationAction=async function(b){
 if(b.dataset.geometry==='toggle'){await openBuildingViewer(b);return true;}
 if(b.dataset.envelopeNav==='geometry'){
  const row=S.configuration?.data.envelope?.[S.envelopeTarget];if(!row)return beforeBuildingViewerAction(b);
  await openBuildingViewer(b);const v=buildingViewerCurrent(),m=geometryState();if(!v||!m.data?.supported)return true;
  const r=m.data.rooms.find(r=>r.zone===row.zone),w=m.data.walls.find(w=>w.id===row.id)||m.data.walls.find(w=>w.id===m.data.openings.find(o=>o.id===row.id)?.host);
  if(r){m.floor=r.floor;m.room=r.id;m.wall=w?.id||null;renderBuildingViewer();}return true;
 }
 return beforeBuildingViewerAction(b);
};
const beforeBuildingViewerRender=render;
render=function(){if(S.buildingViewer&&S.buildingViewer.key!==geometryKey()){const d=buildingViewerDialog();d.close();d.innerHTML='';S.buildingViewer=null;document.documentElement.classList.remove('building-viewer-open');}return beforeBuildingViewerRender();};
