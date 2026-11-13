/* Reuse produces a reviewed room draft; saved versions remain explicit snapshots. */
S.roomTool=null;S.roomUndo=null;
const roomGroupLabels={people:'人员：上下限、单位及两天作息',lighting:'照明：上下限、单位及两天作息',equipment:'设备：上下限、单位及两天作息',sensible:'人员显热 / W 每人',lighting_heat:'照明入室得热比例',available:'空调可用：工作日与周末',temperatures:'四个启停温度'};
const beforeRoomReset=resetConfiguration;
resetConfiguration=function(){beforeRoomReset();S.roomUndo=null;};
const beforeRoomPanel=buildingPanel;
buildingPanel=function(){
 let html=beforeRoomPanel();if(!S.usageDraft||!configurationSupported())return html;
 const tools=`<div class="configuration-reuse-tools"><div class="actions"><button data-room-action="open-reuse"${disabled()}>复用房间配置</button><button data-room-action="open-compare">核对配置差异</button>${S.roomUndo?`<button data-room-action="undo"${disabled()}>撤销上次房间复用</button>`:''}</div><p class="muted">先选择内容和目标房间，核对实际值后再应用到当前编辑。${S.roomUndo?'撤销只影响当前编辑，已保存版本保留。':''}</p>${S.roomUndo?`<details class="room-reuse-last"><summary>本页上次复用</summary><p>来源：${esc(S.roomUndo.source)} → ${esc(S.roomUndo.sourceRoom)}</p><p>目标：${S.roomUndo.targets.map(id=>esc(S.usageDraft.rooms.find(r=>r.id===id).zone)).join('、')}</p><p>内容：${S.roomUndo.groups.map(g=>esc(roomGroupLabels[g])).join('；')}</p><p>${S.roomUndo.basis==='room_totals'?'保留来源每间实际值':'按原单位复用，密度按目标面积换算'}。保存后完整取值进入配置版本；本页撤销记录在切换方案或刷新后结束。</p></details>`:''}</div>`;
 return html.replace('<section class="well usage-editor">',tools+'<section class="well usage-editor">');
};
function roomContext(){return JSON.stringify({id:S.id,revision:S.saved.revision,content:S.usageDraft,operation:S.record.factors.condition.operation});}
function roomToolElement(){
 let el=document.getElementById('room-configuration-dialog');if(el)return el;
 el=document.createElement('dialog');el.id='room-configuration-dialog';el.setAttribute('aria-labelledby','room-tool-title');
 el.addEventListener('cancel',event=>{event.preventDefault();closeRoomTool();});document.body.appendChild(el);return el;
}
function closeRoomTool(){roomToolElement().close();roomToolElement().innerHTML='';S.roomTool=null;}
function roomSource(key){return S.roomTool.sources.find(s=>s.key===key);}
function roomSourceOptions(selected){return S.roomTool.sources.map(s=>`<option value="${esc(s.key)}"${s.key===selected?' selected':''}>${esc(s.name)}</option>`).join('');}
function roomToolRequest(){
 const m=S.roomTool,op=S.record.factors.condition.operation,context={overrides:op.overrides||{},mode:op.mode};
 if(m.mode==='compare')return {action:'compare',before:roomSource(m.before).content,after:roomSource(m.after).content,...context};
 return {action:'reuse',content:S.usageDraft,source:roomSource(m.source).content,source_room:m.sourceRoom,targets:m.targets,groups:m.groups,basis:m.basis,...context};
}
function invalidateRoomPreview(){const m=S.roomTool;m.result=null;m.requestKey=null;m.message='选项已改变，请重新预览。';m.sequence++;}
function roomNumber(value){return typeof value==='number'?String(value):'—';}
function roomRuleSummary(rule,group){
 if(!rule)return '无';
 const input=group==='available'?'0/1 可用状态':rule.kind==='scaled'?`下限 ${roomNumber(rule.minimum)}，上限 ${roomNumber(rule.maximum)} ${scheduleUnits[rule.unit]}`:'逐小时每间实际值';
 const refs=Object.entries(rule.references||{}).map(([d,r])=>scheduleDays[d]+'：'+r.name+' · v'+r.revision).join('；');
 return esc(input)+(refs?'<small>'+esc(refs)+'</small>':'');
}
function roomChangeMarkup(change){
 const c=change,kind=c.group,days=['weekday','weekend'];
 let body='';
 if(c.actual_before){
  const table=hours=>`<div class="table-scroll"><table class="table"><thead><tr><th>日期/时段</th><th>核对前</th><th>核对后</th></tr></thead><tbody>${hours.map(r=>`<tr><td>${scheduleDays[r.day]} ${r.hour}:00–${r.hour+1}:00</td><td>${roomNumber(r.before)}</td><td>${roomNumber(r.after)}</td></tr>`).join('')}</tbody></table></div>`;
  body=`<div class="room-rule-comparison"><div><strong>核对前</strong><p>${roomRuleSummary(c.before,kind)}</p></div><div><strong>核对后</strong><p>${roomRuleSummary(c.after,kind)}</p></div></div><p>全年计划累计：${format(c.annual_before,4)} → ${format(c.annual_after,4)} ${esc(c.annual_unit)}</p>${c.hours.length?table(c.hours):'<p class="muted">实际逐小时值相同，变化仅在输入表达、上下限说明或日计划引用。</p>'}<details><summary>查看两天完整实际值</summary>${table(days.flatMap(day=>Array.from({length:24},(_,hour)=>({day,hour,before:c.actual_before[day][hour],after:c.actual_after[day][hour]}))))}</details>`;
 }else if(kind==='temperatures')body=`<table class="table"><thead><tr><th>温度 / °C</th><th>核对前</th><th>核对后</th></tr></thead><tbody>${Object.entries(temperatureLabels).map(([key,label])=>`<tr><td>${label}</td><td>${roomNumber(c.before[key])}</td><td>${roomNumber(c.after[key])}</td></tr>`).join('')}</tbody></table>`;
 else body=`<p>${roomNumber(c.before)} → ${roomNumber(c.after)} ${kind==='sensible'?'W/人':'（0–1 比例）'}</p>`;
 return `<details class="room-change"><summary>${esc(c.label)} · ${c.actual_changed?'实际值变化':'仅输入表达或引用变化'}</summary>${body}</details>`;
}
function roomDifferencesMarkup(result){
 const d=result.differences;
 return `<div class="room-diff-summary"><strong>${d.room_count} 间房 · ${d.changed_groups} 项配置变化</strong><p>${d.actual_changed_groups} 项涉及实际值；${d.expression_only_groups} 项仅输入表达或引用变化。</p><p class="muted">全年累计为原模拟年历的 261 个工作日、104 个周末日，不是建筑冷热负荷。此处核对建筑默认配置；工况覆盖另行保留。</p></div>${result.notes.map(n=>`<p class="warning">${esc(n)}</p>`).join('')}${d.rooms.map(r=>`<section class="well room-diff-room"><h3>${esc(r.zone)} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</h3>${r.changes.map(roomChangeMarkup).join('')}</section>`).join('')||'<p>两份配置在核查内容中没有差异。</p>'}<details class="muted"><summary>核对范围</summary><p>逐房间比较人员、照明、设备的工作日/周末实际值、人员显热、照明得热、四个启停温度及空调可用时段；几何、面积和空调归属保持。实际值比较使用 1e-9 绝对和 1e-12 相对容差，只用于差异显示，不替代输入身份或结果可比性核验。</p></details>`;
}
function renderRoomTool(){
 const m=S.roomTool;if(!m)return;const el=roomToolElement();
 let controls='';
 if(m.mode==='compare')controls=`<div class="grid2"><label class="field">核对前<select data-room-before>${roomSourceOptions(m.before)}</select></label><label class="field">核对后<select data-room-after>${roomSourceOptions(m.after)}</select></label></div>`;
 else{
  const source=roomSource(m.source),origin=source.content.rooms.find(r=>r.id===m.sourceRoom);
  controls=`<div class="grid2"><label class="field">来源配置<select data-room-source>${roomSourceOptions(m.source)}</select></label><label class="field">来源房间<select data-room-origin>${source.content.rooms.map(r=>`<option value="${esc(r.id)}"${r.id===m.sourceRoom?' selected':''}>${esc(r.zone)} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</option>`).join('')}</select></label></div><fieldset><legend>选择复用内容</legend><div class="room-choice-grid">${Object.entries(roomGroupLabels).map(([key,label])=>`<label><input type="checkbox" data-room-group="${key}"${m.groups.includes(key)?' checked':''}${['available','temperatures'].includes(key)&&!origin.hvac?' disabled':''}> ${label}</label>`).join('')}</div></fieldset><label class="field">不同面积房间的复用方式<select data-room-basis><option value="source_units"${m.basis==='source_units'?' selected':''}>保留原单位：密度按目标面积换算，每间值保持每间值</option><option value="room_totals"${m.basis==='room_totals'?' selected':''}>保留来源房间的每间实际人数/功率</option></select></label><p class="muted">复用整个所选通道，包括上下限与工作日/周末两天作息。每平方米输入在不同面积下可能得到不同实际值。人员潜热保留目标房间原值。</p><fieldset><legend>目标房间（可多选）</legend><div class="room-choice-grid">${S.usageDraft.rooms.map(r=>`<label><input type="checkbox" data-room-target="${esc(r.id)}"${m.targets.includes(r.id)?' checked':''}${m.source==='draft'&&r.id===m.sourceRoom?' disabled':''}> ${esc(r.zone)} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</label>`).join('')}</div></fieldset>`;
 }
 el.innerHTML=`<div class="room-tool-head"><h2 id="room-tool-title">${m.mode==='reuse'?'复用房间配置':'核对配置差异'}</h2><button data-room-action="close">关闭</button></div><p class="muted">${m.mode==='reuse'?'只在当前建筑的已核实房间之间复用使用配置，预览不修改草稿。':'比较当前编辑、原配置或已保存建筑配置版本；仅查看不修改方案。'}</p>${controls}<div class="actions"><button data-room-action="preview" class="primary">${m.mode==='reuse'?'预览目标房间变化':'读取配置差异'}</button></div><p class="room-tool-message" role="status">${esc(m.message||'')}</p>${m.result?`<div class="room-tool-result">${roomDifferencesMarkup(m.result)}</div>`:''}${m.mode==='reuse'?`<div class="room-tool-apply"><button data-room-action="apply" class="primary"${!m.result?.differences.changed_groups||readonly()?' disabled':''}>应用到当前房间配置编辑</button><p class="muted">之后仍需保存建筑配置版本和方案版本，其他方案保持原快照。</p></div>`:''}`;
 if(!el.open)el.showModal();
}
async function openRoomTool(mode){
 await loadConfiguration();const rows=await api('/api/components/usage'),p=S.record.factors.building.usage_profile;
 const sources=[{key:'draft',name:'当前房间配置编辑'+(S.usageDirty?'（未保存）':''),content:copy(S.usageDraft)},{key:'original',name:'原冻结建筑配置',content:copy(S.configuration.data.base)}];
 if(p)sources.push({key:'selected',name:'当前选用：'+p.name+' · v'+p.revision,content:copy(p.content)});
 for(const row of rows){if(row.content.building_id!==S.configuration.data.base.building_id||(row.id===p?.id&&row.revision===p.revision))continue;sources.push({key:row.id+':'+row.revision,name:row.name+' · v'+row.revision,content:copy(row.content)});}
 const room=S.usageDraft.rooms[S.usageRoom],channel=selectedUsage().channel;
 S.roomTool={mode,sources,source:'draft',sourceRoom:room.id,targets:[],groups:[channel],basis:'source_units',before:p?'selected':'original',after:'draft',context:roomContext(),result:null,sequence:0,message:''};renderRoomTool();
 if(mode==='compare')await previewRoomTool();
}
async function previewRoomTool(){
 const m=S.roomTool;if(roomContext()!==m.context)throw Error('当前房间配置已经变化，请关闭后重新核对。');
 const request=roomToolRequest(),key=JSON.stringify(request),sequence=++m.sequence;m.result=null;m.message='正在核对…';renderRoomTool();
 try{
  const result=await api('/api/room-configuration/preview',request);
  if(S.roomTool!==m||sequence!==m.sequence||JSON.stringify(roomToolRequest())!==key)return;
  m.result=result;m.requestKey=key;m.message='核对完成，尚未修改当前配置。';renderRoomTool();
 }catch(error){if(S.roomTool===m&&sequence===m.sequence){m.result=null;m.message=error.message;renderRoomTool();}}
}
function updateUsageDirtyAfterUndo(){const p=S.record.factors.building.usage_profile;S.usageDirty=JSON.stringify(S.usageDraft)!==JSON.stringify(p?.content||S.configuration.data.base)||S.usageName!==(p?.name||'Drawing26 房间使用');updateSchedulePreview();}
const beforeRoomAction=configurationAction;
configurationAction=async function(button){
 const action=button.dataset.roomAction;if(!action)return beforeRoomAction(button);
 if(action==='open-compare'){await openRoomTool('compare');return true;}
 if(action==='close'){closeRoomTool();return true;}
 if(action==='preview'){await previewRoomTool();return true;}
 if(readonly())throw Error('来源或历史版本只读，请从可编辑研究方案复用房间配置。');
 if(action==='open-reuse'){await openRoomTool('reuse');return true;}
 if(action==='apply'){
  const m=S.roomTool;if(!m.result||!m.result.differences.changed_groups||m.requestKey!==JSON.stringify(roomToolRequest())||roomContext()!==m.context)throw Error('预览已失效，请重新核对。');
  S.usageDraft=copy(m.result.content);S.roomUndo={record:S.id,receipt:copy(m.result.undo),source:roomSource(m.source).name,sourceRoom:m.result.source_room.zone,targets:copy(m.targets),groups:copy(m.groups),basis:m.basis};
  markScheduleDirty();closeRoomTool();notice('房间复用已应用到当前编辑，可撤销；请核对并保存配置及方案版本。');return true;
 }
 if(action==='undo'){
  const prior=S.roomUndo,key=roomContext();if(!prior||prior.record!==S.id)throw Error('没有可撤销的本方案房间复用。');
  const result=await api('/api/room-configuration/preview',{action:'undo',content:S.usageDraft,receipt:prior.receipt});
  if(roomContext()!==key)throw Error('等待期间房间配置已变化，未执行撤销。');
  S.usageDraft=copy(result.content);S.roomUndo=null;updateUsageDirtyAfterUndo();notice('已撤销上次房间复用；其他未涉及字段的编辑及已保存版本保留。');return true;
 }
 return false;
};
document.addEventListener('change',event=>{
 const t=event.target,m=S.roomTool;if(!m||!t.closest('#room-configuration-dialog'))return;
 if(t.hasAttribute('data-room-source')){m.source=t.value;m.targets=[];}
 else if(t.hasAttribute('data-room-origin')){m.sourceRoom=t.value;m.targets=m.targets.filter(id=>!(m.source==='draft'&&id===m.sourceRoom));}
 else if(t.hasAttribute('data-room-group'))m.groups=t.checked?[...m.groups,t.dataset.roomGroup]:m.groups.filter(k=>k!==t.dataset.roomGroup);
 else if(t.hasAttribute('data-room-target'))m.targets=t.checked?[...m.targets,t.dataset.roomTarget]:m.targets.filter(k=>k!==t.dataset.roomTarget);
 else if(t.hasAttribute('data-room-basis'))m.basis=t.value;
 else if(t.hasAttribute('data-room-before'))m.before=t.value;
 else if(t.hasAttribute('data-room-after'))m.after=t.value;else return;
 if(m.mode==='reuse'&&!roomSource(m.source).content.rooms.find(r=>r.id===m.sourceRoom).hvac)m.groups=m.groups.filter(g=>!['available','temperatures'].includes(g));
 invalidateRoomPreview();renderRoomTool();
});
