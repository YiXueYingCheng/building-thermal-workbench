/* Browse existing surfaces; edits still use the original per-surface handlers. */
const envelopeViews=new Map();
function envelopeView(){const key=S.id+':'+S.saved.revision;if(!envelopeViews.has(key))envelopeViews.set(key,{query:'',kind:'',room:'',floor:'',scope:'',review:false});return envelopeViews.get(key);}
function envelopeKind(row){return row.type==='Wall'?(row.boundary==='Outdoors'?'exterior-wall':'interior-wall'):row.type;}
const envelopeKinds={'exterior-wall':'外墙','interior-wall':'内墙',Roof:'屋顶',Floor:'楼板',Ceiling:'顶板',Window:'窗',Door:'门'};
const envelopeBoundaries={Outdoors:'室外',Surface:'相邻表面',Foundation:'地基',Ground:'地面',Adiabatic:'绝热'};
function envelopeDifference(layers,base){return layers.flatMap((layer,i)=>Object.entries(layer.values).filter(([key,v])=>v!==base[i].values[key]).map(([key,after])=>({layer:i,key,before:base[i].values[key],after})));}
function envelopeEffective(all,id,overrides){
 const row=all[id],own=overrides[id],pair=overrides[row.pair];let layers=copy(own?.layers||row.layers),owner=own?id:null;
 if(!own&&pair){owner=row.pair;const other=all[row.pair];for(const change of envelopeDifference(pair.layers,other.layers))layers[layers.length-1-change.layer].values[change.key]=change.after;}
 return {layers,owner,paired:!!owner&&owner!==id,changes:envelopeDifference(layers,row.layers)};
}
function envelopeInfo(all){const overrides=S.record.factors.building.envelope_overrides||{},result={};for(const id of Object.keys(all))result[id]=envelopeEffective(all,id,overrides);return result;}
function envelopeRoomLabel(zone){const r=S.usageDraft?.rooms.find(r=>r.zone===zone),use=r&&S.configuration?.data.usage_sources?.[r.id]?.use;return zone+(use&&!use.includes('�')?' · '+use:'');}
function envelopeFloorData(){const d=geometryState().data;return d?.supported&&d.building_id===S.record.factors.building.id?d:null;}
function envelopeFiltered(all,info){const f=envelopeView(),q=f.query.trim().toLocaleLowerCase(),g=envelopeFloorData(),zones=new Set(g?.rooms.filter(r=>String(r.floor)===f.floor).map(r=>r.zone)||[]),targets=geometryTargets();
 return Object.keys(all).filter(id=>{const r=all[id];return (!q||[id,r.zone,r.construction,envelopeRoomLabel(r.zone)].join(' ').toLocaleLowerCase().includes(q))&&(!f.kind||envelopeKind(r)===f.kind)&&(!f.room||r.zone===f.room)&&(!f.floor||zones.has(r.zone))&&(!f.scope||(f.scope==='changed'?info[id].changes.length:targets.has(id)));});
}
function envelopeTargetOptions(all,ids,selected){return `${!ids.includes(selected)?`<optgroup label="当前查看（不在筛选结果内）"><option value="${esc(selected)}" selected>${esc(envelopeKinds[envelopeKind(all[selected])])} · ${esc(all[selected].zone)} · ${esc(selected)}</option></optgroup>`:''}${ids.map(id=>`<option value="${esc(id)}"${id===selected?' selected':''}>${esc(envelopeKinds[envelopeKind(all[id])])} · ${esc(all[id].zone)} · ${esc(id)}</option>`).join('')}`;}
function envelopeValue(v){return v==null?'未填写':typeof v==='number'?String(Number(v.toPrecision(12))):String(v);}
function envelopeReview(all,info){
 const owners=Object.keys(S.record.factors.building.envelope_overrides||{}).filter(id=>info[id]?.changes.length),affected=Object.keys(info).filter(id=>info[id].changes.length);
 return `<summary>基础构造修改汇总 · ${owners.length} 处设置 / ${affected.length} 个表面受影响</summary><p class="muted">只汇总当前方案基础构造相对建筑来源的实际数值变化；相邻面同步列出。研究材料附加层在材料页单独核对。${S.dirty?'当前页面有未保存方案修改。':'当前为已保存方案设置。'}</p>${owners.length?`<div class="table-scroll"><table class="table envelope-change-table"><thead><tr><th>表面 / 房间</th><th>修改来源</th><th>当前面从外到内的变化</th><th>定位</th></tr></thead><tbody>${affected.map(id=>{const row=all[id],e=info[id];return `<tr><td>${esc(id)}<small>${esc(envelopeRoomLabel(row.zone))}</small></td><td>${e.paired?'由 '+esc(e.owner)+' 同步':'本面设置'}</td><td>${e.changes.map(c=>`<div>第 ${c.layer+1} 层 · ${esc(envelopeLabels[c.key]||c.key)}：${esc(envelopeValue(c.before))} → ${esc(envelopeValue(c.after))}</div>`).join('')}</td><td><button data-envelope-open="${esc(id)}">查看</button></td></tr>`;}).join('')}</tbody></table></div>`:'<p>当前基础构造数值与建筑来源相同。</p>'}`;
}
function envelopeSelectionStatus(row,e){return e.paired?`由相邻面 ${esc(e.owner)} 同步显示；本面只读。`:e.owner?(e.changes.length?'此面有局部修改。':'此面保留局部设置，数值与原值相同。'):'沿用建筑原构造。';}
function envelopeEditor(all){
 const ids=Object.keys(all);if(!ids.length)return '<p>没有已接入的普通构件。</p>';
 if(!all[S.envelopeTarget])S.envelopeTarget=ids[0];const row=all[S.envelopeTarget],f=envelopeView(),info=envelopeInfo(all),e=info[row.id],filtered=envelopeFiltered(all,info),g=envelopeFloorData();
 const kinds=[...new Set(ids.map(id=>envelopeKind(all[id])))],rooms=[...new Set(ids.map(id=>all[id].zone))],material=geometryTargets().has(row.id);
 return `<section class="well" id="ordinary-envelope"><h3>普通构造与局部修改</h3><p class="muted">层序按当前表面从外到内；相邻面从另一侧看为反向层序。修改仅作用于本面及其配对面，同名构造的其他构件保留。当前保留层数、几何和边界。</p>
 <div class="envelope-filters"><label class="field">查找构件<input type="search" id="envelope-query" value="${esc(f.query)}" placeholder="构件、房间或原构造名称"></label><label class="field">构件类型<select data-envelope-filter="kind">${options([['','全部类型'],...kinds.map(k=>[k,envelopeKinds[k]||k])],f.kind)}</select></label><label class="field">所属房间<select data-envelope-filter="room">${options([['','全部房间'],...rooms.map(z=>[z,envelopeRoomLabel(z)])],f.room)}</select></label><label class="field">楼层<select data-envelope-filter="floor"${g?'':' disabled'}>${options([['',g?'全部楼层':'平面标高未接入'],...(g?.floors||[]).map(v=>[String(v.id),`第 ${v.id+1} 层 · 标高 ${format(v.elevation,2)} m`])],f.floor)}</select></label><label class="field">显示范围<select data-envelope-filter="scope">${options([['','全部构件'],['changed','有实际基础构造修改'],['material','研究材料作用构件']],f.scope)}</select></label><button data-envelope-nav="reset">清除筛选</button></div>
 <p class="muted" id="envelope-filter-status">筛选得到 ${filtered.length} / ${ids.length} 个表面。筛选只改变查找列表，当前查看和未保存修改保留。</p>
 <label class="field">当前查看构件<select id="envelope-target">${envelopeTargetOptions(all,filtered,row.id)}</select></label>
 <div class="actions"><button data-envelope-nav="previous"${filtered.indexOf(row.id)<=0?' disabled':''}>上一个</button><button data-envelope-nav="next"${filtered.indexOf(row.id)<0||filtered.indexOf(row.id)>=filtered.length-1?' disabled':''}>下一个</button><button data-envelope-nav="geometry">${['Window','Door'].includes(row.type)?'在平面定位所在墙':row.type==='Wall'?'在平面定位墙面':'在平面定位房间'}</button>${row.pair?`<button data-envelope-open="${esc(row.pair)}">${e.paired?'跳到修改侧':'查看相邻另一侧'}</button>`:''}</div>
 <div class="envelope-current"><strong>${esc(envelopeKinds[envelopeKind(row)]||row.type)} · ${esc(row.id)} · ${esc(envelopeRoomLabel(row.zone))}</strong><p>原构造：${esc(row.construction)}；边界：${esc(envelopeBoundaries[row.boundary]||row.boundary)}${row.pair?'；成对表面：'+esc(row.pair):''}。</p><p id="envelope-selection-status">${envelopeSelectionStatus(row,e)}</p>${material?`<p class="envelope-material-note">此面还有研究材料。以下只编辑原基础层；附加层、状态和朝外面在“材料”核对。</p><button data-envelope-nav="materials">查看研究材料</button>`:''}</div>
 <div id="envelope-clear-slot">${envelopeClearButton(row,e)}</div><details id="envelope-review"${f.review?' open':''}>${envelopeReview(all,info)}</details>
 ${e.layers.map((layer,i)=>`<details open class="envelope-layer"><summary>第 ${i+1} 层 · ${esc(row.layers[i].name)}</summary><div class="grid3">${Object.entries(layer.values).filter(([k])=>envelopeLabels[k]).map(([k,v])=>`<label class="field">${envelopeLabels[k]}<input type="number" step="any" data-envelope-field="${k}" data-envelope-layer="${i}" value="${esc(v??'')}"${readonly()||e.paired?' disabled':''}><small class="envelope-before" data-envelope-before="${i}:${k}">${v!==row.layers[i].values[k]?'原值：'+esc(envelopeValue(row.layers[i].values[k])):''}</small></label>`).join('')}</div></details>`).join('')}
 <p class="muted">修改仍需保存方案版本。查看修改汇总不生成输入或提交计算。</p></section>`;
}
function envelopeClearButton(row,e){return e.owner===row.id?`<button data-envelope-clear${disabled()}>清除此构件修改，恢复原构造</button>`:'';}
function updateEnvelopeFilters(){const all=S.configuration?.data.envelope;if(!all)return;const info=envelopeInfo(all),ids=envelopeFiltered(all,info);document.getElementById('envelope-target').innerHTML=envelopeTargetOptions(all,ids,S.envelopeTarget);document.getElementById('envelope-filter-status').textContent=`筛选得到 ${ids.length} / ${Object.keys(all).length} 个表面。筛选只改变查找列表，当前查看和未保存修改保留。`;const index=ids.indexOf(S.envelopeTarget);document.querySelector('[data-envelope-nav="previous"]').disabled=index<=0;document.querySelector('[data-envelope-nav="next"]').disabled=index<0||index>=ids.length-1;}
function updateEnvelopeStatus(){
 const all=S.configuration?.data.envelope;if(!all||!document.getElementById('ordinary-envelope'))return;const info=envelopeInfo(all),row=all[S.envelopeTarget],e=info[row.id];
 document.getElementById('envelope-selection-status').innerHTML=envelopeSelectionStatus(row,e);document.getElementById('envelope-clear-slot').innerHTML=envelopeClearButton(row,e);
 document.getElementById('envelope-review').innerHTML=envelopeReview(all,info);
 document.querySelectorAll('[data-envelope-before]').forEach(el=>{const [i,k]=el.dataset.envelopeBefore.split(':');el.textContent=e.layers[i].values[k]!==row.layers[i].values[k]?'原值：'+envelopeValue(row.layers[i].values[k]):'';});updateEnvelopeFilters();
}
const beforeEnvelopeNavigation=configurationAction;
configurationAction=async function(button){
 if(button.hasAttribute('data-ordinary-envelope')){const handled=await beforeEnvelopeNavigation(button);if(S.envelopeOpen&&!geometryState().data)await loadGeometry(geometryState());return handled;}
 if(button.dataset.envelopeOpen){const all=S.configuration?.data.envelope;if(!all?.[button.dataset.envelopeOpen])throw Error('未找到此构件。');S.envelopeTarget=button.dataset.envelopeOpen;S.envelopeOpen=true;geometryScroll('#ordinary-envelope');return true;}
 const a=button.dataset.envelopeNav;if(!a)return beforeEnvelopeNavigation(button);
 const f=envelopeView(),all=S.configuration.data.envelope,row=all[S.envelopeTarget];
 if(a==='reset'){Object.assign(f,{query:'',kind:'',room:'',floor:'',scope:''});return true;}
 if(a==='previous'||a==='next'){const ids=envelopeFiltered(all,envelopeInfo(all)),i=ids.indexOf(S.envelopeTarget),target=ids[i+(a==='next'?1:-1)];if(i>=0&&target)S.envelopeTarget=target;return true;}
 if(a==='geometry'){
  const m=geometryState();if(!m.data)await loadGeometry(m);if(!m.data?.supported)throw Error(m.error||m.data?.note||'此来源的平面暂未接入，构造查看仍可使用。');
  const room=m.data.rooms.find(r=>r.zone===row.zone),wall=m.data.walls.find(w=>w.id===row.id)||m.data.walls.find(w=>w.id===m.data.openings.find(o=>o.id===row.id)?.host);
  if(!room)throw Error('没有找到对应房间，未跳转。');m.open=true;m.floor=room.floor;m.room=room.id;m.wall=wall?.id||null;geometryScroll('#building-geometry');return true;
 }
 if(a==='materials'){S.factor='materials';return true;}
 return false;
};
document.addEventListener('input',e=>{if(e.target.id==='envelope-query'){envelopeView().query=e.target.value;updateEnvelopeFilters();}if(e.target.dataset.envelopeField)updateEnvelopeStatus();});
document.addEventListener('change',e=>{if(e.target.dataset.envelopeFilter){envelopeView()[e.target.dataset.envelopeFilter]=e.target.value;updateEnvelopeFilters();}});
document.addEventListener('toggle',e=>{if(e.target.id==='envelope-review'&&e.target.isConnected)envelopeView().review=e.target.open;},true);
