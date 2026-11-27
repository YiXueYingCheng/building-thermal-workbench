function wallScopeSource(){
 return ['ordinary_building_v1','global_frozen_v011'].includes(S.record?.provenance?.adapter);
}
function drawingScopeEnabled(){
 const f=S.record?.factors,a=f?.materials?.applications?.[0];
 const envelope=S.configuration?.data?.envelope;
 const wallIds=f?.building.wall_ids;
 const equivalent=f?.materials.definitions[0]?.model==='equivalent_resistance_no_layer_storage'&&
   f.condition.controls.every(c=>c.mode==='fixed')&&!f.condition.reference_runs.length;
 return wallScopeSource()&&
   f.materials.definitions.length===1&&
   (['layer_stack_v1','fixed_surface_material_v1','legacy_outer_equivalent_model','fixed_exterior_movable_v1'].includes(a?.placement_basis)||(equivalent&&a?.position==='exterior'))&&a.target_ids.every(id=>wallIds?.length?wallIds.includes(id):(!envelope||envelope[id]?.type==='Wall'&&envelope[id]?.boundary==='Outdoors'));
}
function drawingApplicationMarkup(){
 const f=S.record.factors,a=f.materials.applications[0],ref=f.materials.definition_reference;
 const count=new Set(f.condition.controls.filter(c=>c.mode==='feedback').flatMap(c=>c.target_ids)).size;
 return `<h3>外墙铺设与控制范围</h3><p>${esc(ref?.name||f.materials.definitions[0].name)}${ref?' · 材料版本 '+esc(ref.revision):''} · 已铺 ${a.target_ids.length} 段${a.placement_basis==='layer_stack_v1'?' · '+(a.position==='between'?'原构造第 '+esc(a.after_layer)+' 层后':a.position==='interior'?'内侧':'外侧'):''}${count?'，其中 '+count+' 段参与反馈':''}。</p><button class="primary" data-material-view="wall-scope">查看与选择铺设墙段</button>`;
}
function currentWallInventory(){
 return api('/api/material-library/wall-inventory',{id:S.id,revision:S.saved.revision,changes:changes()});
}
async function drawingGeometry(){
 const m=geometryState();
 if(!m.data)await loadGeometry(m);
 return m.data?.supported?m.data:null;
}
async function drawingConditionedTargets(available){
 const walls=await currentWallInventory();
 const eligible=new Set(available.filter(t=>t.type==='Wall').map(t=>t.id));
 const targets=walls.filter(w=>eligible.has(w.id)&&w.conditioned===true);
 if(!targets.length)throw Error('当前建筑没有可确认的空调房外墙。');
 return targets.map(w=>w.id);
}
function drawingInputTable(scope){
 return `<details open><summary>逐墙生成核对 · 已铺 ${format(scope.covered_m2,2)} m² · 反馈 ${format(scope.feedback_m2,2)} m²</summary><div class="table-scroll"><table class="table"><thead><tr><th>墙号 / 房间</th><th>净面积 / m²</th><th>热学状态</th><th>表面光学</th><th>输入构造</th></tr></thead><tbody>${scope.rows.map(w=>`<tr><td>${esc(w.id)} · ${esc(w.zone)}</td><td>${format(w.net_m2,2)}</td><td>${!w.covered?'未铺 · 建筑基准':w.thermal==='feedback'?'反馈 · 初始 '+esc(w.state):'固定 '+esc(w.state)}</td><td>${!w.covered?'基准表面':w.optical==='calendar'?'地点日历':'固定 '+esc(w.face)}</td><td><code>${esc(w.construction)}</code></td></tr>`).join('')}</tbody></table></div></details>`;
}
async function openDrawingWalls(initialTab){
 const stamp=()=>JSON.stringify([S.id,S.saved?.revision,changes()]),sourceStamp=stamp();
 const [walls,data]=await Promise.all([currentWallInventory(),drawingGeometry()]);
 if(sourceStamp!==stamp())return;
 const idsInModel=new Set(walls.map(w=>w.id));
 const f=S.record.factors,app=f.materials.applications[0],groups=f.condition.controls;
 if(!app.target_ids.every(id=>idsInModel.has(id)))throw Error('当前应用包含屋面。请在材料库单独选用外墙，再按墙段调整。');
 const original=new Set(app.target_ids),oldFeedback=new Set(groups.filter(c=>c.mode==='feedback').flatMap(c=>c.target_ids));
 const covered=new Set(original),feedback=new Set(oldFeedback);
 const dlg=document.createElement('dialog');
 dlg.className='drawing-wall-dialog';dlg.setAttribute('aria-labelledby','drawing-wall-title');document.body.append(dlg);
 const variable=f.materials.definitions[0].model==='solid_variable_v1';
 let tab=variable?initialTab:'coverage',pending=false,message='',floor=0;
 const readOnly=readonly(),sum=list=>format(list.reduce((a,w)=>a+w.net_m2,0),2);
 const currentSet=()=>tab==='coverage'?covered:feedback;
 const high=f.materials.definitions[0].states.reduce((a,b)=>a.resistance_m2K_W>b.resistance_m2K_W?a:b).id;
 const fixedState=()=>feedback.size&&!oldFeedback.size?high:groups.find(c=>c.channel==='thermal'&&c.mode==='fixed')?.state_id||high;
 const orientations=groups.filter(c=>c.channel==='orientation');
 const opticalFor=w=>orientations.find(c=>c.target_ids.includes(w.id))||
   (orientations.length===1?orientations[0]:{mode:'fixed',face_id:'A'});
 const equivalent=f.materials.definitions[0].model==='equivalent_resistance_no_layer_storage';
 const oldLayer=app.placement_basis==='legacy_outer_equivalent_model';
 const fixedValue=(w,channel,key,defaultValue)=>{
   const controls=groups.filter(c=>c.channel===channel);
   const prior=controls.find(c=>c.target_ids.includes(w.id));
   if(equivalent&&oldLayer&&!prior&&channel==='thermal'&&groups.some(c=>c.mode!=='fixed'))return 'R';
   return prior?.[key]??(new Set(controls.map(c=>c[key])).size===1?controls[0][key]:defaultValue);
 };
 const ids=(list)=>list.map(w=>w.id).join('、');
 const usage=w=>w.conditioned===true?'空调房':w.conditioned===false?'非空调房':'归属待核';
 function opticsPreview(installed){
   if(app.placement_basis==='layer_stack_v1')return stackWallInfo(f.materials.definitions[0],app);
   const groupsByOptics=new Map();
   for(const wall of installed){
     const optical=opticalFor(wall);
     const thermal=feedback.has(wall.id)?{mode:'feedback'}:{mode:'fixed',state_id:equivalent?fixedValue(wall,'thermal','state_id','R'):fixedState()};
     const markup=wallMaterialOptics(f.materials.definitions[0],[{channel:'thermal',...thermal},
       {channel:'orientation',mode:optical.mode,face_id:optical.face_id}],'沿用各墙外表面');
     groupsByOptics.set(markup,(groupsByOptics.get(markup)||0)+1);
   }
   return [...groupsByOptics].map(([markup,count])=>'<div><small>'+count+' 段墙</small>'+markup+'</div>').join('');
 }
 function selectWall(id,on){
   if(readOnly||pending)return;
   if(tab==='feedback'&&!covered.has(id))return;
   if(on)currentSet().add(id);else currentSet().delete(id);
   if(!covered.has(id))feedback.delete(id);
 }
 function draw(){
   const scroll=dlg.querySelector('.dw-body')?.scrollTop||0;
   const added=walls.filter(w=>covered.has(w.id)&&!original.has(w.id)),removed=walls.filter(w=>original.has(w.id)&&!covered.has(w.id));
   const changedFeedback=walls.filter(w=>feedback.has(w.id)!==oldFeedback.has(w.id)),changed=!!(added.length+removed.length+changedFeedback.length);
   const selection=currentSet(),installed=walls.filter(w=>covered.has(w.id)),active=walls.filter(w=>feedback.has(w.id));
   const emptyMessage=covered.size?'':'全部墙段已取消铺设。恢复 W00 将从当前草稿撤掉材料引用、热阻控制及光学日历绑定。';
   const feedbackEntry=feedback.size&&!oldFeedback.size?'启用后按 1 min 求解，每 5 min 判断，初始 C，至少保持 60 min。':'';
   dlg.innerHTML=`<header class="dw-head"><div><h2 id="drawing-wall-title">${variable?'材料铺设与反馈选墙':'选择材料铺设墙段'}</h2><p>${esc(S.record.name)} · 方案 v${esc(S.saved.revision)} · ${esc(f.materials.definitions[0].name)}</p></div><button data-dw="close">返回</button></header>
   ${variable?`<nav class="dw-tabs" aria-label="选择范围">${[['coverage','材料铺设'],['feedback','热阻反馈']].map(([k,title])=>`<button data-dw-tab="${k}" aria-pressed="${k===tab}" class="${k===tab?'primary':''}">${title}</button>`).join('')}</nav>`:''}
   <div class="dw-body">${oldLayer?'<p class="well">保留墙段沿用各自的活动保温层和控制设置，撤掉铺设的墙恢复建筑基础构造。</p>':''}<p><strong>已铺 ${installed.length} 段 · ${sum(installed)} m²</strong>${variable?`　反馈 ${active.length} 段 · ${sum(active)} m²　已铺固定 ${installed.length-active.length} 段`:''}</p>
   ${installed.length?'<details data-dw-optics'+(dlg.querySelector('[data-dw-optics]')?.open?' open':'')+'><summary>所选墙段的光学参数</summary>'+opticsPreview(installed)+'</details>':''}
   <p>${tab==='coverage'?'在平面或清单中选择铺设材料的室外墙段。撤除材料时，其热阻和光学控制一并移除。':'从已铺墙段中选择反馈组。其余已铺墙使用固定热阻；表面光学沿用本方案的设置。'}</p>
   <div class="actions">${[['all',tab==='coverage'?'全部外墙':'全部已铺墙'],['ac','空调房外墙'],['none','清空本栏']].map(([cmd,title])=>`<button data-dw="${cmd}" ${readOnly?'disabled':''}>${title}</button>`).join('')}</div>
   <div class="dw-layout"><div class="dw-plan">${data&&data.floors.length>1?`<label>平面楼层<select data-dw-floor>${data.floors.map((f,i)=>`<option value="${i}" ${floor===i?'selected':''}>第 ${i+1} 层 · 标高 ${format(f.elevation,2)} m</option>`).join('')}</select></label>`:''}<div class="dw-map"></div><small>${data?'绿色粗线为本栏已选墙段。':'当前几何无法绘制平面，请从清单选墙。'}净面积已扣除门窗洞口。</small></div>
   <div class="dw-list"><table class="table"><thead><tr><th>选择 / 墙号</th><th>所属房间</th><th>净面积 m²</th><th>当前设置</th></tr></thead><tbody>${walls.map(w=>`<tr><td><label><input type="checkbox" data-dw-wall="${esc(w.id)}" ${selection.has(w.id)?'checked':''} ${readOnly||tab==='feedback'&&!covered.has(w.id)?'disabled':''}> ${esc(w.id)}</label></td><td>${esc(w.zone)} · ${usage(w)}</td><td>${format(w.net_m2,2)}</td><td>${!covered.has(w.id)?'未铺 · 基准':(feedback.has(w.id)?'反馈':'固定 '+esc(equivalent?fixedValue(w,'thermal','state_id','R'):fixedState()))+' · '+(opticalFor(w).mode==='calendar'?'日历':'固定 '+esc(opticalFor(w).face_id))}</td></tr>`).join('')}</tbody></table></div></div>
   ${changed?`<div class="well"><strong>本次变更</strong>${added.length?`<p>新增铺设 ${added.length} 段（${sum(added)} m²） · ${esc(ids(added))}</p>`:''}${removed.length?`<p>恢复基准 ${removed.length} 段（${sum(removed)} m²） · ${esc(ids(removed))}</p>`:''}<p>${changedFeedback.length?'反馈组变化 · '+esc(ids(changedFeedback)):'共有墙反馈组保持原设置。'} ${esc(feedbackEntry)}</p></div>`:''}</div>
   <footer class="dw-foot"><span role="status">${esc(message||emptyMessage||(changed?'应用到草稿后，可保存或另存为研究方案。':'与打开时一致。'))}</span><button data-dw="close">返回</button><button data-dw="apply" class="primary" ${readOnly||!changed||pending?'disabled':''}>${pending?'正在核对…':covered.size?'应用到草稿':'撤掉材料引用，恢复 W00 到草稿'}</button></footer>`;
   const map=dlg.querySelector('.dw-map');
   if(data)map.innerHTML=geometrySVG({data,floor,room:null,wall:null});
   map.querySelectorAll('[data-geometry-node="room"]').forEach(n=>{n.removeAttribute('role');n.removeAttribute('tabindex');});
   map.querySelectorAll('[data-geometry-node="wall"]').forEach(n=>{
     const id=n.dataset.geometryId,selected=selection.has(id);
     n.classList.toggle('targeted',selected);n.classList.toggle('dw-off',tab==='feedback'&&!covered.has(id));
     n.setAttribute('aria-pressed',String(selected));n.querySelector('title').textContent=id+' · '+(selected?'已选':'未选');
   });
   dlg.querySelector('.dw-body').scrollTop=scroll;
 }
 function close(){dlg.close();}
 dlg.addEventListener('close',()=>{dlg.remove();});
 dlg.addEventListener('cancel',e=>{if(pending)e.preventDefault();});
 dlg.addEventListener('change',e=>{
   if(e.target.matches('[data-dw-floor]')){floor=Number(e.target.value);draw();return;}
   const input=e.target.closest('[data-dw-wall]');if(!input)return;
   selectWall(input.dataset.dwWall,input.checked);draw();
   dlg.querySelector(`[data-dw-wall="${CSS.escape(input.dataset.dwWall)}"]`)?.focus({preventScroll:true});
 });
 dlg.addEventListener('keydown',e=>{
   const node=e.target.closest('[data-geometry-node]');if(!node)return;
   e.stopPropagation();if(node.dataset.geometryNode==='wall'&&['Enter',' '].includes(e.key)){e.preventDefault();node.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
 });
 dlg.addEventListener('click',async e=>{
   e.stopPropagation();if(pending)return;
   const node=e.target.closest('[data-geometry-node="wall"]'),btn=e.target.closest('button');
   if(node){const id=node.dataset.geometryId;selectWall(id,!currentSet().has(id));draw();dlg.querySelector(`[data-geometry-id="${CSS.escape(id)}"]`)?.focus({preventScroll:true});return;}
   if(!btn||btn.disabled)return;
   if(btn.dataset.dwTab){tab=btn.dataset.dwTab;draw();return;}
   const cmd=btn.dataset.dw;
   if(cmd==='close'){close();return;}
   if(readOnly)return;
   if(cmd==='apply'){
     pending=true;message='正在核对墙段和控制范围…';draw();
     try{
       if(sourceStamp!==stamp())throw Error('方案草稿已变化，请返回后重新打开。');
       if(!covered.size){
         removeResearchMaterialFromDraft();
         close();render();notice('当前草稿已恢复 W00。保存为新版本后即可生成模型输入。');
         return;
       }
       const result=await api('/api/material-library/wall-scope',{id:S.id,revision:S.saved.revision,changes:changes(),covered:[...covered],feedback:[...feedback]});
       if(sourceStamp!==stamp())throw Error('方案草稿已变化，请返回后重新打开。');
       setPath('factors.materials',result.materials);setPath('factors.condition.controls',result.controls);setPath('numerics',result.numerics);
       close();render();notice('选墙已应用到草稿。保存版本后即可生成输入。');
     }catch(err){message=err.message;pending=false;draw();}
     return;
   }
   if(['all','ac','none'].includes(cmd)){
     for(const w of walls)selectWall(w.id,cmd==='all'||cmd==='ac'&&w.conditioned===true);
     draw();
   }
 });
 draw();dlg.showModal();
}
