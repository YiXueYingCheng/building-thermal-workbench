'use strict';
const wallMetrics={outside:'墙外表面温度',inside:'墙内表面温度',inward:'内表面导热',air:'所属房间室温'};

function probeLayers(wall){
 const materials=S.record.factors.materials,app=materials.applications.find(a=>a.target_ids.includes(wall)&&materials.definitions.some(d=>d.id===a.material_id&&d.model==='layer_stack_v1'));
 if(!app)return {layers:[]};
 const def=materials.definitions.find(d=>d.id===app.material_id);
 return {app,layers:def.layers.map((layer,i)=>({index:i+1,row:stackSource(layer)}))};
}
function probeSettings(){
 const ex=S.record.execution;
 return {config:ex.wall_observations||{frequency:'Hourly',points:[]},layers:ex.stack_response||[]};
}
function configuredWalls(){
 const {config,layers}=probeSettings();
 return [...new Set([...config.points,...layers].map(p=>p.wall))];
}
function wallProbeRows(ui){
 const {config,layers}=probeSettings();
 return configuredWalls().map(w=>{
   const point=config.points.find(p=>p.wall===w),installed=probeLayers(w).layers;
   const titles=layers.filter(p=>p.wall===w).map(p=>{
     const layer=installed.find(l=>l.index===p.layer&&l.row?.sha256===p.sha256);
     return layer?layer.row.name+' 两侧温度':'第 '+p.layer+' 层（铺设或版本已变）';
   });
   const fields=(point?.fields||[]).map(f=>wallMetrics[f]);
   return '<li><button type="button" data-probe-view="'+esc(w)+'"'+(ui.geometry?.walls.some(r=>r.exterior&&r.id===w)?'':' disabled')+'>'+esc(w)+'</button><span>'+[...fields,...titles].map(esc).join('、')+'</span>'+
     (readonly()?'':'<button data-wall-remove="'+esc(w)+'">移除</button>')+'</li>';
 }).join('');
}
function wallCrossSection(ui){
 const {config,layers:selected}=probeSettings(),wall=ui.wall,entry=ui.geometry.walls.find(w=>w.id===wall&&w.exterior);
 if(!entry)return '<p>此建筑没有可选的外墙。</p>';
 const point=config.points.find(p=>p.wall===wall),{app,layers}=probeLayers(wall),lock=readonly()?' disabled':'';
 const field=f=>'<label><input type="checkbox" data-wall-field="'+f+'"'+(point?.fields.includes(f)?' checked':'')+lock+'> '+wallMetrics[f]+'</label>';
 const part=(type,name,content)=>'<div class="probe-part '+type+'"><strong>'+esc(name)+'</strong>'+content+'</div>';
 const material=layers.map(({index,row})=>row&&row.content.model!=='optical_surface_v1'?
   part('probe-layer','第 '+index+' 层 · '+row.name,'<label><input type="checkbox" data-probe-layer="'+index+'"'+(selected.some(p=>p.wall===wall&&p.layer===index&&p.sha256===row.sha256)?' checked':'')+lock+'> 两侧温度</label>'):
   part('probe-base',row?.name||'未核对材料','<small>'+(row?'表面涂层':'请核对版本')+'</small>')).join('');
 const base=label=>part('probe-base',label,'');
 const middle=app?.position==='interior'?base('原墙构造')+material:app?.position==='between'?
   base('原构造至第 '+app.after_layer+' 层')+material+base('其余原构造'):material+base(app?'原墙构造':'墙体构造');
 return '<div class="probe-direction">室外 → 室内</div><div class="probe-section" aria-label="从室外到室内的测点位置">'+
   part('probe-surface','外表面',field('outside'))+middle+
   part('probe-surface','内表面',field('inside')+field('inward'))+
   part('probe-room',entry.zone||'所属房间',field('air'))+'</div>'+
   (layers.length?'<small class="muted">实体层的两侧温度按求解步保存，生成模型时核对有限差分节点。</small>':'');
}
function probeTiming(ui){
 const {config,layers}=probeSettings(),points=config.points,frequency=points.length?config.frequency:ui.frequency||config.frequency;
 const days=stackDates(S.record.factors.scope.period).length,step=S.record.numerics.step_minutes;
 const zones=new Map((ui.geometry?.walls||[]).map(w=>[w.id,w.zone]));
 const count=new Set(points.flatMap(p=>p.fields.map(f=>f+'|'+(f==='air'?(zones.get(p.wall)||p.zone||p.wall):p.wall)))).size;
 const hasBoth=points.some(p=>layers.some(l=>l.wall===p.wall));
 const perSurface=days*1440/(frequency==='Hourly'?60:step),perLayer=days*1440/step;
 const timing='<label>墙面与房间 · 全部已选墙 <select data-wall-frequency'+(readonly()?' disabled':'')+'>'+options([['Hourly','逐时'],...(days<=31||frequency==='Timestep'?[['Timestep','每 '+step+' 分钟（求解步长）']]:[])],frequency)+'</select></label>';
 const quantities=[...(count?['墙面与房间 '+count+' 条，每条 '+perSurface.toLocaleString()+' 个读数']:[]),...(layers.length?['层两侧温度 '+(2*layers.length)+' 条，每条 '+perLayer.toLocaleString()+' 个读数']:[])];
 return '<div class="probe-timing">'+timing+(layers.length?'<span>材料层 · 每 '+step+' 分钟</span>':'')+'</div>'+
   (days>31&&frequency==='Timestep'?'<p class="warning">逐步墙面测点最多支持连续 31 天，请改为逐时或缩短时段。</p>':'')+
   (hasBoth&&frequency==='Hourly'&&step<60?'<p class="probe-hint">看材料切换前后时，层温每 '+step+' 分钟有读数，墙面和房间每小时有读数。'+(days<=31&&!readonly()?'<button data-probe-align>将墙面与房间也设为每 '+step+' 分钟</button>':'逐步对照需在支持逐步保存的短时段选取相同频率。')+'</p>':'')+
   (quantities.length?'<p class="muted">'+quantities.join('。')+'。</p>':'');
}
function wallEditor(m){
 const building=S.record.factors.building.id;
 if(m.wallEditor?.building!==building)m.wallEditor={building,open:false,wall:null};
 const ui=m.wallEditor,walls=configuredWalls(),g=ui.geometry;
 const changedBuilding=building!==S.saved.factors.building.id;
 const rows=wallProbeRows(ui);
 return '<details class="well" data-wall-editor'+(ui.open?' open':'')+'><summary>墙与材料层测点'+(walls.length?' · '+walls.length+' 面墙':'')+'</summary>'+
   (changedBuilding?'<p>请先保存已选建筑，再读取它的墙面。</p>':g?'<div class="spectral-controls"><label>外墙 <select data-wall-target>'+options(g.walls.filter(w=>w.exterior).map(w=>[w.id,w.id+(w.zone?' · '+w.zone:'')]),ui.wall)+'</select></label>'+
   (g.floors?.length?'<button data-wall-map>从平面图选墙</button>':'')+'</div>'+wallCrossSection(ui)+probeTiming(ui):
   '<p>'+esc(ui.error||'正在读取外墙与房间…')+'</p>'+(ui.error?'<button data-wall-load>重新读取</button>':''))+
   (rows?'<ul class="probe-configured">'+rows+'</ul>':'')+
   (g&&walls.length&&!changedBuilding?'<button data-probe-transfer>将测点用于对照方案…</button>':'')+
   (ui.message?'<p role="status">'+esc(ui.message)+'</p>':'')+'</details>';
}
async function loadProbeGeometry(m){
 const ui=m.wallEditor;
 if(ui.geometry||ui.loading||ui.building!==S.saved.factors.building.id)return;
 const selected=configuredWalls();
 ui.loading=true;ui.error='';
 try{
   let g=await api('/api/building-geometry/'+encodeURIComponent(m.id)+'?revision='+encodeURIComponent(m.revision));
   if(!g.supported||g.unplotted_walls?.length){
     const targets=await api('/api/material-library/targets',{id:m.id,revision:m.revision,changes:{}});
     const listed=new Set((g.walls||[]).map(w=>w.id));
     const additional=targets.filter(t=>t.type==='Wall'&&!listed.has(t.id)).map(t=>({...t,exterior:true}));
     g={...g,walls:[...(g.walls||[]),...additional],floors:g.floors||[]};
   }
   ui.geometry=g;
   const available=g.walls.filter(w=>w.exterior);
   if(!available.some(w=>w.id===ui.wall)){
     ui.wall=available.find(w=>selected.includes(w.id))?.id||available[0]?.id;
   }
 }catch(e){ui.error=e.message;}
 finally{ui.loading=false;if(inputFlowWindow?.model===m&&m.wallEditor===ui)renderInputFlow();}
}
document.addEventListener('toggle',e=>{
 if(!e.target.matches?.('[data-wall-editor]')||!e.target.isConnected||!inputFlowWindow)return;
 const m=inputFlowWindow.model,ui=m.wallEditor;
 ui.open=e.target.open;
 if(ui.open&&!ui.error)void loadProbeGeometry(m);
},true);
function updateProbe(m,field,value,checked){
 if(readonly())return;
 const ui=m.wallEditor,{config,layers}=probeSettings(),wall=ui.wall,ex={...S.record.execution};
 if(config.points.length&&config.building_id!==ui.building&&field!=='remove')throw Error('请先移除上一栋建筑的测点。');
 if(field==='frequency'){
   ui.frequency=value;
   if(config.points.length)ex.wall_observations={...config,frequency:value};
 }else if(field==='layer'){
   const row=probeLayers(wall).layers.find(l=>l.index===value)?.row;
   if(!row||row.content.model==='optical_surface_v1')throw Error('请重新核对所选材料层。');
   const keep=layers.filter(p=>p.wall!==wall||p.layer!==value);
   ex.stack_response=checked?[...keep,{wall,layer:value,sha256:row.sha256}]:keep;
 }else if(field==='wall'){
   const existing=config.points.find(p=>p.wall===wall),fields=new Set(existing?.fields||[]);
   if(checked)fields.add(value);else fields.delete(value);
   const points=config.points.filter(p=>p.wall!==wall);
   if(fields.size)points.push({wall,zone:ui.geometry.walls.find(w=>w.id===wall).zone,fields:[...fields]});
   ex.wall_observations={building_id:ui.building,frequency:config.points.length?config.frequency:ui.frequency||config.frequency,points};
 }else if(field==='remove'){
   if(ex.wall_observations)ex.wall_observations={...config,points:config.points.filter(p=>p.wall!==value)};
   if(ex.stack_response)ex.stack_response=layers.filter(p=>p.wall!==value);
 }
 const page=inputFlowDialog().querySelector('.input-flow-body'),scroll=page.scrollTop;
 const active=document.activeElement;
 const focus=active?.hasAttribute('data-wall-field')?'[data-wall-field="'+active.dataset.wallField+'"]':
   active?.hasAttribute('data-probe-layer')?'[data-probe-layer="'+active.dataset.probeLayer+'"]':
   active?.matches('[data-wall-frequency],[data-probe-align]')?'[data-wall-frequency]':'';
 if(JSON.stringify(ex)!==JSON.stringify(S.record.execution))setPath('execution',ex);
 ui.message='';renderInputFlow();
 const refreshed=inputFlowDialog().querySelector('.input-flow-body');
 if(refreshed){refreshed.scrollTop=scroll;if(focus)refreshed.querySelector(focus)?.focus({preventScroll:true});}
}
document.addEventListener('change',e=>{
 if(!e.target.closest('[data-wall-editor]')||!inputFlowWindow)return;
 const m=inputFlowWindow.model,ui=m.wallEditor,el=e.target;
 try{
   if(el.hasAttribute('data-wall-target')){ui.wall=el.value;ui.message='';renderInputFlow();}
   if(el.hasAttribute('data-wall-field'))updateProbe(m,'wall',el.dataset.wallField,el.checked);
   if(el.hasAttribute('data-probe-layer'))updateProbe(m,'layer',Number(el.dataset.probeLayer),el.checked);
   if(el.hasAttribute('data-wall-frequency'))updateProbe(m,'frequency',el.value);
 }catch(error){ui.message=error.message;renderInputFlow();}
},true);
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-open-wall-probes],[data-wall-load],[data-wall-map],[data-wall-remove],[data-probe-view],[data-probe-align],[data-probe-transfer]');
 if(!b||b.disabled)return;
 e.preventDefault();e.stopImmediatePropagation();
 if(b.hasAttribute('data-open-wall-probes')){
   closeConditionViewer();const m=openInputFlow(false);
   inputFlowWindow.detail=false;m.showInspection=false;renderInputFlow();
   m.wallEditor.open=true;renderInputFlow();document.querySelector('[data-wall-editor]')?.scrollIntoView({block:'center'});return;
 }
 const m=inputFlowWindow?.model;if(!m)return;
 const ui=m.wallEditor;
 if(b.hasAttribute('data-wall-load'))void loadProbeGeometry(m);
 if(b.hasAttribute('data-probe-view')){ui.wall=b.dataset.probeView;ui.message='';renderInputFlow();}
 if(b.hasAttribute('data-wall-map'))openResponseFloor({key:m.key,read:async()=>ui.geometry,walls:ui.geometry.walls.filter(w=>w.exterior).map(w=>w.id),current:ui.wall,select:wall=>{
   if(inputFlowWindow?.model===m){ui.wall=wall;ui.message='';renderInputFlow();}
 }});
 try{
   if(b.hasAttribute('data-wall-remove'))updateProbe(m,'remove',b.dataset.wallRemove);
   if(b.hasAttribute('data-probe-align'))updateProbe(m,'frequency','Timestep');
   if(b.hasAttribute('data-probe-transfer'))openProbeTransfer(m);
 }catch(error){ui.message=error.message;renderInputFlow();}
},true);
