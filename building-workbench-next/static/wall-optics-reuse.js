/* Explicit optical-only reuse. Existing envelope overrides remain the storage contract. */
const wallOpticsFields=['solar_absorptance','thermal_absorptance','visible_absorptance'];
function woCanonical(value){
 if(Array.isArray(value))return value.map(woCanonical);
 if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,woCanonical(value[k])]));
 return value;
}
function woSignature(row){return JSON.stringify(woCanonical(row.layers.map(l=>({kind:l.kind,values:l.values}))));}
function woReason(row){
 if(!row||row.type!=='Wall'||row.boundary!=='Outdoors'||row.pair)return '只支持不透明外墙';
 if(row.layers?.[0]?.kind!=='Material'||wallOpticsFields.some(k=>!(k in row.layers[0].values)))return '原外层光学参数不完整';
 if(typeof clBound==='function'&&clBound(row.id))return '已绑定库构造';
 if(!viewerCanEdit(row))return '当前墙面只读';
 return '';
}
function woValue(overrides,row,key){return (overrides[row.id]?.layers||row.layers)[0].values[key];}
function woBuild(all,overrides,sourceId,targets,fields,reason=()=> ''){
 const source=all[sourceId];if(!source||reason(source))throw Error('来源墙面不可推广。');
 if(!fields.length||new Set(fields).size!==fields.length||fields.some(k=>!wallOpticsFields.includes(k)))throw Error('请选择要推广的光学参数。');
 if(!targets.length||new Set(targets).size!==targets.length)throw Error('请勾选目标墙面。');
 const values=Object.fromEntries(fields.map(k=>[k,woValue(overrides,source,k)]));
 for(const [k,v] of Object.entries(values))if(typeof v!=='number'||!Number.isFinite(v)||v<0||v>1||(k==='thermal_absorptance'&&(v<=0||v>.99999)))throw Error('来源'+envelopeLabels[k]+'无效，请先完成来源墙面的编辑。');
 const next=copy(overrides),audit=[];
 for(const id of targets){
  const row=all[id];if(!row||id===sourceId||reason(row)||woSignature(row)!==woSignature(source))throw Error('目标墙面已变化或不属于同类原构造，请重新选择。');
  const entry=copy(overrides[id]||{layers:row.layers.map(l=>({kind:l.kind,values:copy(l.values)}))});
  const differences=fields.filter(k=>entry.layers[0].values[k]!==values[k]).map(k=>({key:k,before:entry.layers[0].values[k],after:values[k]}));
  if(differences.length){for(const k of fields)entry.layers[0].values[k]=values[k];next[id]=entry;}
  audit.push({id,zone:row.zone,differences});
 }
 return {overrides:next,audit};
}
function woStamp(){return JSON.stringify([geometryKey(),S.record.factors.building,S.record.factors.materials,S.configuration?.data.envelope]);}
function woCandidates(state){
 const all=S.configuration.data.envelope,source=all[state.source],signature=woSignature(source);
 return Object.values(all).filter(r=>r.id!==source.id&&r.type==='Wall'&&r.boundary==='Outdoors'&&woSignature(r)===signature).map(row=>{
  const wall=geometryState().data?.walls.find(w=>w.id===row.id),room=geometryState().data?.rooms.find(r=>r.zone===row.zone);
  return {row,wall,room,reason:woReason(row)};
 });
}
function woFiltered(state){return woCandidates(state).filter(x=>(!state.direction||x.wall?.direction===state.direction)&&(!state.floor||String(x.room?.floor)===state.floor)&&(!state.room||x.row.zone===state.room));}
function woStart(){
 const v=buildingViewerCurrent(),{row}=viewerWall();if(woReason(row))throw Error(woReason(row));
 v.optics={source:row.id,fields:[...wallOpticsFields],targets:[],direction:'',floor:'',room:'',preview:null};v.view='optics-batch';v.message='';woRender();buildingViewerDialog().querySelector('.viewer-body').scrollTop=0;
}
function woRender(preview=false){
 const d=buildingViewerDialog(),top=d.querySelector('.viewer-body')?.scrollTop||0,listTop=d.querySelector('.wo-targets')?.scrollTop||0;
 renderBuildingViewer();d.querySelector('#building-viewer-title').textContent='推广外表面光学参数';
 d.querySelector('.viewer-body').scrollTop=top;const list=d.querySelector('.wo-targets');if(list)list.scrollTop=listTop;
 if(preview)d.querySelector('[aria-label="推广改动预览"]')?.scrollIntoView({block:'start'});
}
function woWrite(overrides){
 if(Object.keys(overrides).length)setPath('factors.building.envelope_overrides',overrides);
 else{delete S.record.factors.building.envelope_overrides;S.preview=null;S.generated=null;scheduleCapability();S.dirty=JSON.stringify(changes())!==JSON.stringify(Object.fromEntries(['name','factors','numerics','execution'].map(k=>[k,S.saved[k]])));}
 updateDirtyStatus();
}
function woApply(){
 const v=buildingViewerCurrent(),s=v?.optics,p=s?.preview;if(readonly()||!p||p.stamp!==woStamp()||p.selection!==JSON.stringify([s.targets,s.fields]))throw Error('方案或选择已变化，请重新预览后采用。');
 const before=copy(S.record.factors.building.envelope_overrides||{}),data=woBuild(S.configuration.data.envelope,before,s.source,s.targets,s.fields,woReason),changed=data.audit.filter(a=>a.differences.length);
 if(!changed.length)throw Error('所选参数已相同，无需采用。');
 v.opticsUndo={key:geometryKey(),items:changed.map(a=>({id:a.id,before:before[a.id]||null,after:copy(data.overrides[a.id])}))};
 woWrite(data.overrides);v.view='wall';v.optics=null;v.message='已将外表面光学参数推广到 '+changed.length+' 面墙；已进入方案草稿，请返回保存版本。';renderBuildingViewer();
}
function woUndo(){
 const v=buildingViewerCurrent(),u=v?.opticsUndo,x=copy(S.record.factors.building.envelope_overrides||{});
 if(readonly()||!u||u.key!==geometryKey()||u.items.some(a=>JSON.stringify(x[a.id])!==JSON.stringify(a.after)))throw Error('这些墙面已再次变化，未直接撤销，请核对当前草稿。');
 for(const a of u.items){if(a.before)x[a.id]=copy(a.before);else delete x[a.id];}
 woWrite(x);v.opticsUndo=null;v.message='已撤销上次光学推广，来源墙面和其他方案修改保留。';renderBuildingViewer();
}
function wallOpticsAction(button){
 const op=button?.dataset.wallOptics;if(!op)return false;
 const v=buildingViewerCurrent();if(!v)return true;
 if(op==='open'){woStart();return true;}
 if(op==='undo'){woUndo();return true;}
 if(op==='back'){v.view='wall';v.optics=null;v.message='';renderBuildingViewer();return true;}
 const s=v.optics;if(!s||readonly())throw Error('当前方案不可编辑。');v.message='';
 if(op==='select'||op==='clear'){
  const ids=woFiltered(s).filter(x=>!x.reason).map(x=>x.row.id);
  s.targets=op==='select'?[...new Set([...s.targets,...ids])]:s.targets.filter(id=>!ids.includes(id));s.preview=null;
 }
 if(op==='preview'){
  const data=woBuild(S.configuration.data.envelope,S.record.factors.building.envelope_overrides||{},s.source,s.targets,s.fields,woReason);
  s.preview={...data,stamp:woStamp(),selection:JSON.stringify([s.targets,s.fields])};
 }
 if(op==='apply'){woApply();return true;}
 woRender(op==='preview');return true;
}
function wallOpticsChange(input){
 const s=buildingViewerCurrent()?.optics;if(!s||!input.hasAttribute('data-wo'))return false;
 const kind=input.dataset.wo;
 if(['direction','floor','room'].includes(kind))s[kind]=input.value;
 else if(kind==='target')s.targets=input.checked?[...new Set([...s.targets,input.value])]:s.targets.filter(x=>x!==input.value);
 else if(kind==='field')s.fields=input.checked?[...new Set([...s.fields,input.value])]:s.fields.filter(x=>x!==input.value);
 s.preview=null;buildingViewerCurrent().message='';woRender();return true;
}
function woMarkup(){
 const s=buildingViewerCurrent().optics,source=S.configuration.data.envelope[s.source],all=woCandidates(s),rows=woFiltered(s),overrides=S.record.factors.building.envelope_overrides||{},p=s.preview;
 const unique=values=>[...new Set(values)].sort(),select=(kind,label,values)=>`<label class="field">${label}<select data-wo="${kind}" id="wo-${kind}"><option value="">全部</option>${values.map(([v,t])=>`<option value="${esc(v)}"${s[kind]===String(v)?' selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
 return `<section class="viewer-section"><div class="row"><h3>推广外表面光学参数</h3><button data-wall-optics="back">返回来源墙面</button></div>
 <p>来源：${esc(source.id)} · ${esc(source.zone)} · ${esc(source.construction)}</p>
 <p>同类按建筑原构造的层序、材料类别和原始参数一致判定；不同朝向可单独筛选。只复制最外层选中的光学参数，保留各墙厚度、导热率、密度、比热及其余层参数。</p>
 <p class="muted">适用于 W00 基础墙体。已有外侧研究材料时，基础层参数不等于最终暴露表面的参数；研究材料与控制保持原样。已绑定库构造的墙面在列表中说明，不能在此覆盖。</p>
 <fieldset><legend>选择推广参数（来源墙面的当前值）</legend><div class="grid3">${wallOpticsFields.map(k=>`<label class="check"><input type="checkbox" data-wo="field" id="wo-field-${k}" value="${k}"${s.fields.includes(k)?' checked':''}>${esc(envelopeLabels[k])}：${esc(woValue(overrides,source,k))}</label>`).join('')}</div></fieldset>
 <div class="grid3">${select('direction','朝向',unique(all.map(x=>x.wall?.direction).filter(Boolean)).map(v=>[v,v]))}${select('floor','楼层',unique(all.map(x=>x.room?.floor).filter(v=>v!=null)).map(v=>[String(v),'第 '+(v+1)+' 层']))}${select('room','房间',unique(all.map(x=>x.row.zone)).map(v=>[v,envelopeRoomLabel(v)]))}</div>
 <div class="actions"><button data-wall-optics="select">全选当前筛选的可用墙面</button><button data-wall-optics="clear">清除当前筛选的选择</button></div>
 <p>同类 ${all.length} 面（不含来源）；当前显示 ${rows.length} 面；已选 ${s.targets.length} 面${s.targets.some(id=>!rows.some(x=>x.row.id===id))?'，包含其他筛选范围的选择':''}。</p>
 <div class="viewer-table wo-targets" style="max-height:24rem;overflow:auto"><table class="table"><thead><tr><th>选择 / 墙面</th><th>房间 / 朝向</th><th>当前外表面参数</th><th>状态</th></tr></thead><tbody>${rows.map(x=>`<tr><td><label class="check"><input type="checkbox" data-wo="target" id="wo-target-${esc(x.row.id)}" value="${esc(x.row.id)}" aria-label="选择墙面 ${esc(x.row.id)}"${s.targets.includes(x.row.id)?' checked':''}${x.reason?' disabled':''}>${esc(x.row.id)}</label></td><td>${esc(envelopeRoomLabel(x.row.zone))}<br>${esc(x.wall?.direction||'朝向未提供')}</td><td>${wallOpticsFields.map(k=>esc(envelopeLabels[k])+': '+esc(woValue(overrides,x.row,k))).join('；')}</td><td>${esc(x.reason||(geometryTargets().has(x.row.id)?'已应用研究材料；仅改基础层':'可选'))}</td></tr>`).join('')||'<tr><td colspan="4">此范围没有同类墙面。</td></tr>'}</tbody></table></div>
 <div class="actions"><button class="primary" data-wall-optics="preview"${!s.targets.length||!s.fields.length?' disabled':''}>预览推广改动</button></div>
 ${p?`<section class="well" aria-label="推广改动预览"><h3>核对后采用</h3><p>已选 ${p.audit.length} 面；将修改 ${p.audit.filter(a=>a.differences.length).length} 面；原值相同的墙面不增加修改。</p><div class="viewer-table"><table class="table"><thead><tr><th>墙面 / 房间</th><th>第 1 层光学改动：原值 → 新值</th></tr></thead><tbody>${p.audit.map(a=>`<tr><td>${esc(a.id)} / ${esc(a.zone)}</td><td>${a.differences.map(d=>esc(envelopeLabels[d.key])+': '+esc(d.before)+' → '+esc(d.after)).join('<br>')||'已相同，不修改'}</td></tr>`).join('')}</tbody></table></div><button class="primary" data-wall-optics="apply"${!p.audit.some(a=>a.differences.length)?' disabled':''}>确认采用到方案草稿</button></section>`:''}</section>`;
}
const woOriginalMarkup=viewerWallMarkup;
viewerWallMarkup=function(){
 const v=buildingViewerCurrent();if(v?.view==='optics-batch')return woMarkup();
 const html=woOriginalMarkup(),{row}=viewerWall();
 return html+(!woReason(row)?`<section class="viewer-section"><h3>同类外墙光学设置</h3><button data-wall-optics="open">推广外表面光学参数…</button><p class="muted">将此墙当前外表面参数推广到选定的同类墙面；先预览，再确认。</p>${v.opticsUndo?'<button data-wall-optics="undo">撤销上次光学推广</button>':''}</section>`:'');
};
