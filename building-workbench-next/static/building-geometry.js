/* Geometry is read-only. Selection follows stable room/surface IDs, not labels. */
const geometryViews=new Map();
function geometryKey(){return S.id+':'+S.saved.revision;}
function geometryState(){const key=geometryKey();if(!geometryViews.has(key))geometryViews.set(key,{open:false,data:null,floor:0,room:null,wall:null,error:''});return geometryViews.get(key);}
function geometryTargets(){return new Set(S.record.factors.materials.applications.flatMap(a=>a.target_ids));}
function geometryRoomName(r){const use=S.configuration?.data.usage_sources?.[r.id]?.use;return (use&&!use.includes('�')?use+' · ':'')+r.zone;}
function geometryControl(w){
 const apps=S.record.factors.materials.applications.filter(a=>a.target_ids.includes(w.id));
 if(!apps.length)return '未应用研究材料';
 return apps.map(a=>{const d=S.record.factors.materials.definitions.find(x=>x.id===a.material_id),controls=S.record.factors.condition.controls.filter(c=>c.target_ids.includes(w.id));
  return (d?.name||a.material_id)+' · '+({exterior:'外侧附加',interior:'内侧',between:'层间'}[a.position]||a.position)+'；'+controls.map(c=>c.channel==='thermal'?(c.mode==='fixed'?'固定 '+(d?.states.find(x=>x.id===c.state_id)?.name||c.state_id):'传热反馈'):(c.mode==='fixed'?'固定 '+c.face_id:'按日历切换表面光学参数')).join('；');
 }).join(' / ');
}
function geometrySVG(m){
 const d=m.data,f=d.floors[m.floor],rooms=d.rooms.filter(r=>r.floor===m.floor),walls=d.walls.filter(w=>w.floor===m.floor),targets=geometryTargets();
 const [x0,y0,x1,y1]=f.bounds,scale=Math.min(672/Math.max(x1-x0,.01),440/Math.max(y1-y0,.01));
 const px=p=>[54+(672-(x1-x0)*scale)/2+(p[0]-x0)*scale,64+(440-(y1-y0)*scale)/2+(y1-p[1])*scale];
 const points=poly=>poly.map(p=>px(p).map(v=>v.toFixed(3)).join(',')).join(' ');
 const line=(l,cls,extra='')=>`<line class="${cls}" x1="${px(l[0])[0]}" y1="${px(l[0])[1]}" x2="${px(l[1])[0]}" y2="${px(l[1])[1]}" ${extra}/>`;
 const scaleM=[.5,1,2,5,10,20,50].filter(x=>x*scale<=125).at(-1)||.5;
 return `<svg class="geometry-plan" viewBox="0 0 780 570" aria-label="建筑平面，北向朝上。可选择房间与外墙。"><text x="26" y="28" class="geometry-caption">标高 ${format(f.elevation,2)} m · ${rooms.length} 间</text><path d="M742 76V32m-8 14 8-14 8 14" class="geometry-north"/><text x="742" y="22" text-anchor="middle" class="geometry-caption">N 北</text>
 ${rooms.map(r=>`<g role="button" tabindex="0" data-geometry-node="room" data-geometry-id="${esc(r.id)}" aria-label="选择房间 ${esc(geometryRoomName(r))}" aria-pressed="${m.room===r.id}" class="geometry-room ${r.conditioned?'conditioned':'unconditioned'} ${m.room===r.id?'selected':''}">${r.polygons.map(p=>`<polygon points="${points(p)}"/>`).join('')}<title>${esc(geometryRoomName(r))} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</title></g>`).join('')}
 ${walls.filter(w=>!w.exterior).map(w=>line(w.line,'geometry-inner')).join('')}
 ${walls.filter(w=>w.exterior).map(w=>`<g role="button" tabindex="0" data-geometry-node="wall" data-geometry-id="${esc(w.id)}" aria-label="选择外墙 ${esc(w.id)}" aria-pressed="${m.wall===w.id}" class="geometry-wall ${targets.has(w.id)?'targeted':''} ${m.wall===w.id?'selected':''}">${line(w.line,'geometry-wall-hit')}${line(w.line,'geometry-wall-visible')}<title>${esc(w.id)} · ${esc(w.direction)} · ${esc(geometryControl(w))}</title></g>`).join('')}
 ${d.openings.filter(o=>o.floor===m.floor).map(o=>line(o.line,'geometry-opening '+(o.kind==='Window'?'window':'door'))).join('')}
 ${rooms.map(r=>`<text x="${px(r.label)[0]}" y="${px(r.label)[1]}" class="geometry-room-label" text-anchor="middle">${esc(r.zone)}</text>`).join('')}
 <path d="M54 534v8h${scaleM*scale}v-8" class="geometry-scale"/><text x="${54+scaleM*scale/2}" y="560" text-anchor="middle" class="geometry-caption">${scaleM} m</text></svg>`;
}
function geometryPanel(){
 if(!configurationSupported())return '';
 const m=geometryState();let html=`<div class="configuration-toolbar geometry-toolbar"><button data-geometry="toggle">${m.open?'收起':'查看'}建筑平面与材料位置</button><span class="muted">按楼层定位房间与外墙</span></div>`;
 if(!m.open)return html;
 return html+geometryContents();
}
function geometryContents(inWindow=false){
 const m=geometryState();let html=`<section class="well geometry-panel" id="building-geometry">${inWindow?'':`<div class="row"><h3>建筑平面与材料位置</h3><button data-geometry="refresh">重新核对几何</button></div>`}`;
 if(m.error||!m.data?.supported)return html+`<p role="status">${esc(m.error||m.data?.note||'正在读取几何…')}</p></section>`;
 const d=m.data,r=d.rooms.find(r=>r.id===m.room),w=d.walls.find(w=>w.id===m.wall),targets=geometryTargets(),visible=new Set(d.walls.map(w=>w.id)),missing=[...targets].filter(id=>!visible.has(id));
 html+=`<p class="muted">${esc(d.note)}${S.dirty?' 方案有未保存编辑；材料标记按当前草稿显示。':''}</p><div class="grid2"><label class="field">楼层（按地面标高）<select id="geometry-floor">${d.floors.map((f,i)=>`<option value="${f.id}"${m.floor===f.id?' selected':''}>第 ${i+1} 层 · 标高 ${format(f.elevation,2)} m · ${f.room_count} 间</option>`).join('')}</select></label><label class="field">定位房间<select id="geometry-room"><option value="">选择房间</option>${d.rooms.map(r=>`<option value="${esc(r.id)}"${r.id===m.room?' selected':''}>${esc(geometryRoomName(r))} · 第 ${r.floor+1} 层</option>`).join('')}</select></label></div>
 <div class="geometry-legend"><span class="geo-conditioned">空调房</span><span class="geo-unconditioned">非空调房</span><span class="geo-target">研究材料作用墙</span><span class="geo-window">窗</span><span class="geo-door">门</span></div>
 ${missing.length?`<p class="warning">有 ${missing.length} 个材料目标不能在此平面定位，不能将当前图视为完整应用范围：${missing.map(esc).join('、')}</p>`:''}
 <p class="geometry-mobile-hint muted">平面可左右滑动；也可用房间列表定位。</p><div class="geometry-layout"><div class="geometry-canvas" tabindex="0" aria-label="建筑平面查看区域">${geometrySVG(m)}</div><div class="geometry-inspector" aria-live="polite"><h4>${r?esc(geometryRoomName(r)):'选择房间或外墙'}</h4>${r?`<p>${r.conditioned?'空调房':'非空调房'} · 输入面积 ${format(r.area_m2,2)} m²</p><p>几何投影 ${format(r.projected_area_m2,2)} m²</p><button data-geometry="room-config">查看此房间配置</button><label class="field">本房间墙面<select id="geometry-wall"><option value="">选择墙面</option>${d.walls.filter(x=>x.room_id===r.id).map(x=>`<option value="${esc(x.id)}"${w?.id===x.id?' selected':''}>${x.exterior?'外墙':'内墙'} · ${esc(x.direction)} · ${esc(x.id)}</option>`).join('')}</select></label>`:'<p>点击平面，或从上方列表定位。查看和切换不会修改方案。</p>'}
 ${w?`<div class="geometry-wall-detail"><h4>${esc(w.id)} · ${w.exterior?'外墙':'内墙'}</h4><p>${esc(w.direction)} · ${format(w.azimuth,1)}°</p><p>净墙面积 ${format(w.net_area_m2,2)} m²<br>含洞口毛面积 ${format(w.gross_area_m2,2)} m²</p><p>原构造：${esc(w.construction)}</p><p class="geometry-application">${esc(geometryControl(w))}</p>${(inWindow||S.record.provenance.adapter==='ordinary_building_v1')?'<button data-geometry="wall-config">查看此墙构造</button>':'<button data-geometry="material-config">查看材料与构造</button>'}</div>`:''}</div></div>
 <p class="muted">全楼 ${d.counts.rooms} 间 · ${d.counts.exterior_walls} 面外墙 · 外墙净面积 ${format(d.counts.exterior_net_area_m2,2)} m²；当前方案 ${targets.size} 个材料目标，已定位 ${[...targets].filter(id=>visible.has(id)).length} 个。</p>
 <details><summary>几何来源与核对说明${d.warnings.length?' · '+d.warnings.length+' 项说明':''}</summary><p>${esc(d.building_name)} · 保存版本 v${d.revision}。本次几何核对：${esc(d.checked_at)}。房间用途与研究材料随当前编辑显示。地面标高分层不等同于建筑楼层命名。</p><p class="source-path">模型 SHA-256：${esc(d.source_sha256)}</p>${d.warnings.map(x=>`<p>${esc(x)}</p>`).join('')}<p>仅支持世界坐标、零建筑北轴及水平地面。未显示的屋顶和楼板不代表不存在；构造层序仍在原构造入口核对。</p></details></section>`;
 return html;
}
const beforeGeometryBuilding=buildingPanel,beforeGeometryMaterials=materialsPanel;
buildingPanel=function(){return geometryPanel()+beforeGeometryBuilding();};
materialsPanel=function(){return geometryPanel()+beforeGeometryMaterials();};
async function loadGeometry(m){
 const key=geometryKey();m.error='';
 try{const d=await api('/api/building-geometry/'+encodeURIComponent(S.id)+'?revision='+encodeURIComponent(S.saved.revision));if(geometryKey()!==key)return;m.data=d;if(d.supported){if(!d.floors[m.floor])m.floor=0;if(!d.rooms.some(r=>r.id===m.room)){m.room=null;m.wall=null;}}}
 catch(e){if(geometryKey()===key){m.error=e.message;m.data=null;}}
}
function geometrySelect(kind,id){const m=geometryState(),d=m.data;if(!d?.supported)return;const w=kind==='wall'?d.walls.find(x=>x.id===id):null,r=d.rooms.find(x=>x.id===(w?w.room_id:id));if(!r)return;m.floor=r.floor;m.room=r.id;m.wall=w?.id||null;render();}
function geometryScroll(selector){requestAnimationFrame(()=>requestAnimationFrame(()=>document.querySelector(selector)?.scrollIntoView({block:'start'})));}
const beforeGeometryAction=configurationAction;
configurationAction=async function(button){
 const a=button.dataset.geometry;if(!a)return beforeGeometryAction(button);
 const m=geometryState();
 if(a==='toggle'){m.open=!m.open;if(m.open&&!m.data){await loadConfiguration();await loadGeometry(m);}return true;}
 if(a==='refresh'){await loadGeometry(m);return true;}
 if(a==='room-config'){await loadConfiguration();const i=S.usageDraft.rooms.findIndex(r=>r.id===m.room);if(i<0)throw Error('此房间配置暂未接入。');S.usageRoom=i;S.factor='building';geometryScroll('.usage-editor');return true;}
 if(a==='wall-config'){await loadConfiguration();if(!S.configuration.data.envelope?.[m.wall])throw Error('此墙构造暂未接入。');S.envelopeOpen=true;S.envelopeTarget=m.wall;S.factor='building';geometryScroll('#ordinary-envelope');return true;}
 if(a==='material-config'){await loadConfiguration();S.factor='materials';S.constructionOpen=true;geometryScroll('.configuration-construction');return true;}
 return false;
};
document.addEventListener('change',e=>{if(!['geometry-floor','geometry-room','geometry-wall'].includes(e.target.id))return;const m=geometryState();if(e.target.id==='geometry-floor'){m.floor=Number(e.target.value);m.room=null;m.wall=null;render();}if(e.target.id==='geometry-room')geometrySelect('room',e.target.value);if(e.target.id==='geometry-wall'){if(e.target.value)geometrySelect('wall',e.target.value);else{m.wall=null;render();}}});
document.addEventListener('click',e=>{const node=e.target.closest('[data-geometry-node]');if(node)geometrySelect(node.dataset.geometryNode,node.dataset.geometryId);});
document.addEventListener('keydown',e=>{const node=e.target.closest('[data-geometry-node]');if(node&&['Enter',' '].includes(e.key)){e.preventDefault();const id=node.dataset.geometryId,kind=node.dataset.geometryNode;geometrySelect(kind,id);Array.from(document.querySelectorAll('[data-geometry-node]')).find(x=>x.dataset.geometryNode===kind&&x.dataset.geometryId===id)?.focus({preventScroll:true});}});
