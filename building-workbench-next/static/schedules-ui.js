/* Daily editing: explicit units, source-verified bounds, immutable profile references. */
S.dailyProfiles=null;
const scheduleDays={weekday:'工作日',weekend:'周末'},scheduleUnits={people:'人/间','people/m2':'人/m²',W:'W/间','W/m2':'W/m²'};
const beforeScheduleLoad=loadConfiguration;
loadConfiguration=async function(){await beforeScheduleLoad();if(!S.dailyProfiles)S.dailyProfiles=await api('/api/daily-profiles');};
function selectedUsage(){const room=S.usageDraft.rooms[S.usageRoom],channel=room.hvac?S.usageChannel:S.usageChannel==='available'?'people':S.usageChannel;return {room,channel,rule:channel==='available'?room.hvac.available:room.loads[channel]};}
function actualSchedule(rule,area){if(rule.kind!=='scaled')return {weekday:rule.weekday,weekend:rule.weekend};const scale=rule.unit.endsWith('/m2')?area:1;return Object.fromEntries(Object.keys(scheduleDays).map(day=>[day,rule[day].map(v=>[rule.minimum,rule.maximum,v].every(Number.isFinite)?scale*(rule.minimum+v*(rule.maximum-rule.minimum)):null)]));}
function cleanScheduleReference(rule,day){if(rule.references){delete rule.references[day];if(!Object.keys(rule.references).length)delete rule.references;}}
function markScheduleDirty(){S.usageDirty=true;const el=document.getElementById('usage-edit-status');if(el)el.textContent='配置有未保存修改';updateSchedulePreview();}
function scheduleTarget(target){if(target.startsWith('operation:')){const id=target.slice(10);return S.record.factors.condition.operation.overrides[id].available;}return selectedUsage().rule;}
function scheduleTargetChanged(target){if(target.startsWith('operation:')){setPath('factors.condition.operation.overrides',copy(S.record.factors.condition.operation.overrides));updateDirtyStatus();}else markScheduleDirty();}
function scheduleChart(pair,unit){
 if(Object.values(pair).some(a=>a.some(v=>!Number.isFinite(v))))return '<p class="warning">请补齐有效数值后查看曲线。</p>';
 const max=Math.max(1,...pair.weekday,...pair.weekend),x=h=>38+h*24,y=v=>138-v/max*106;
 const line=(day,color)=>`<path d="${pair[day].map((v,h)=>(h?'L':'M')+x(h)+' '+y(v)+' L'+x(h+1)+' '+y(v)).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/>`;
 return `<svg class="schedule-chart" viewBox="0 0 650 174" role="img" aria-label="工作日与周末实际值曲线"><title>工作日与周末实际${esc(unit)}，00–24时</title><path d="M38 25 V138 H614" fill="none" stroke="#bacac2"/><text x="4" y="36">${format(max,2)}</text><text x="20" y="143">0</text>${[0,4,8,12,16,20,24].map(h=>`<text x="${x(h)}" y="160" text-anchor="middle">${h}</text>`).join('')}${line('weekday','#315b4b')}${line('weekend','#bc6e24')}</svg><p class="schedule-legend"><span>● 工作日</span><span>● 周末</span> · 实际${esc(unit)}</p>`;
}
function schedulePreview(){
 const {room,channel,rule}=selectedUsage(),p=actualSchedule(rule,room.area_m2),unit=channel==='people'?'人数':channel==='available'?'可用状态':'功率 / W';
 const valid=Object.values(p).every(a=>a.every(Number.isFinite)),total=valid?Object.values(p.weekday).reduce((a,b)=>a+b,0)*261+Object.values(p.weekend).reduce((a,b)=>a+b,0)*104:null;
 const annual=total===null?'待完善':channel==='people'?format(total,2)+' 人·时':channel==='available'?format(total,0)+' 可用小时':format(total/1000,3)+' kWh 输入电量';
 return scheduleChart(p,unit)+`<p class="muted">全年展开：${annual}。沿用原建筑年历，1 月 1 日为周一；261 个工作日、104 个周末日，共 8760 小时。</p>`;
}
function updateSchedulePreview(){
 if(!S.usageDraft)return;const {room,rule}=selectedUsage(),p=actualSchedule(rule,room.area_m2);
 document.querySelectorAll('[data-actual-day]').forEach(el=>{const v=p[el.dataset.actualDay][Number(el.dataset.hour)];el.textContent=Number.isFinite(v)?format(v,3):'待完善';});
 const slot=document.getElementById('schedule-preview');if(slot)slot.innerHTML=schedulePreview();
}
function scheduleControls(target,rule,binary=false){
 const usable=binary||rule.kind==='scaled';
 return `<div class="schedule-controls" data-schedule-target="${esc(target)}"><div class="schedule-fill"><label>填写到<select data-fill-day><option value="weekday">工作日</option><option value="weekend">周末</option><option value="both">两天</option></select></label><label>开始时刻<select data-fill-start>${Array.from({length:24},(_,h)=>`<option value="${h}"${h===8?' selected':''}>${h}:00</option>`).join('')}</select></label><label>结束时刻<select data-fill-end>${Array.from({length:24},(_,h)=>`<option value="${h+1}"${h===17?' selected':''}>${h+1}:00</option>`).join('')}</select></label><label>${binary?'0/1':rule.kind==='scaled'?'比例':'实际值'}<input data-fill-value type="number" value="${binary||rule.kind==='scaled'?1:0}" min="0"${usable?' max="1"':''}></label><button data-schedule-action="fill"${disabled()}>填写时段</button></div><div class="actions"><button data-schedule-action="copy-weekday"${disabled()}>工作日 → 周末</button><button data-schedule-action="copy-weekend"${disabled()}>周末 → 工作日</button></div>${usable?`<section class="daily-library"><p class="muted">比例计划与人数／功率上下限分别保存；日计划的查看、复制和版本管理统一在日计划库进行。</p><label class="field">用于哪一天<select data-profile-day><option value="weekday">工作日</option><option value="weekend">周末</option></select></label><div class="actions"><button data-daily-open="${esc(target)}">查找与管理日计划</button><button data-daily-capture="${esc(target)}"${disabled()}>将当前日计划另存入库</button></div><p class="muted">先在管理器命名并核对，保存不会改变房间；选用工作日／周末需要另行确认。</p></section>`:'<p class="muted">当前编辑实际人数/功率。切换到比例作息后，可选用公共日计划。</p>'}</div>`;
}
function advancedDayTable(rule,room,channel){
 const scaled=rule.kind==='scaled',binary=channel==='available',p=actualSchedule(rule,room.area_m2),label=binary?'0/1':scaled?'比例':channel==='people'?'人数':'功率 / W';
 return `<div class="table-scroll schedule-hours"><table class="table day-editor"><thead><tr><th>时段</th>${Object.entries(scheduleDays).map(([day,labelDay])=>`<th>${labelDay} · ${label}</th>${scaled?'<th>实际'+(channel==='people'?'人数':' W')+'</th>':''}`).join('')}</tr></thead><tbody>${Array.from({length:24},(_,h)=>`<tr><th>${h}:00–${h+1}:00</th>${Object.keys(scheduleDays).map(day=>`<td><input type="number" step="${binary?'1':'any'}" min="0"${scaled||binary?' max="1"':''} data-usage-hour="${channel}" data-day="${day}" data-hour="${h}" value="${esc(displayUsageNumber(rule[day][h]))}" aria-label="${scheduleDays[day]} ${h}点"${disabled()}></td>${scaled?`<td data-actual-day="${day}" data-hour="${h}">${format(p[day][h],3)}</td>`:''}`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
const earlierScheduleBuildingPanel=buildingPanel;
buildingPanel=function(){
 if(!configurationSupported()||!S.configuration||!S.usageDraft)return earlierScheduleBuildingPanel();
 const {room,channel,rule}=selectedUsage(),d=S.configuration.data,profile=S.record.factors.building.usage_profile,source=d.usage_sources?.[room.id],origin=source?.channels?.[channel],scaled=rule.kind==='scaled',binary=channel==='available';
 const gains=room.gain_settings||d.gain_defaults[room.id];
 const references=Object.entries(rule.references||{}).map(([day,r])=>scheduleDays[day]+'：'+r.name+' · v'+r.revision).join('；');
 return originalBuildingPanel()+`<div class="configuration-toolbar"><p>建筑使用配置：${profile?esc(profile.name)+' · 版本 '+profile.revision:'原冻结默认配置'}</p><button data-configuration="usage-list">选择已有建筑配置</button>${S.componentLists.usage.length?`<select data-component-use="usage"${disabled()}>${componentOptions('usage',profile)}</select>`:''}</div><section class="well usage-editor"><div class="row"><h3>房间与每日作息</h3><span id="usage-edit-status">${S.usageDirty?'配置有未保存修改':'配置已读取'}</span></div><p class="muted">${usageMembershipText()}。人员、照明、设备与空调可用计划分别设置。</p><label class="field">配置名称<input id="usage-name" value="${esc(S.usageName)}"${disabled()}></label><div class="grid2"><label class="field">房间<select id="usage-room">${S.usageDraft.rooms.map((r,i)=>`<option value="${i}"${i===S.usageRoom?' selected':''}>${esc(r.zone)} · ${esc(d.usage_sources?.[r.id]?.use||'用途未登记')} · ${format(r.area_m2,2)} m² · ${r.conditioned?'空调房':'非空调房'}</option>`).join('')}</select></label><label class="field">使用计划<select id="usage-channel">${Object.entries(roomChannels).filter(([key])=>key!=='available'||room.hvac).map(([key,v])=>`<option value="${key}"${key===channel?' selected':''}>${v}</option>`).join('')}</select></label></div>${!binary?`<div class="schedule-basis"><label class="field">输入方式<select id="schedule-basis"${disabled()}><option value="actual"${!scaled?' selected':''}>逐小时实际值</option><option value="scaled"${scaled?' selected':''}>上下限 × 比例作息</option></select></label>${!scaled&&origin?.verified&&origin.rule?.kind==='scaled'?`<button data-schedule-action="source-rule"${disabled()}>使用已核对的原上下限与比例</button>`:''}</div><p class="muted">原配置没有比例作息也可创建；切换时先保持当前实际值，再按需要调整上下限和 0–1 比例。</p>${scaled?`<div class="grid3"><label class="field">下限<input type="number" min="0" step="any" data-schedule-bound="minimum" value="${esc(displayUsageNumber(rule.minimum))}"${disabled()}></label><label class="field">上限<input type="number" min="0" step="any" data-schedule-bound="maximum" value="${esc(displayUsageNumber(rule.maximum))}"${disabled()}></label><label class="field">单位<select id="schedule-unit"${disabled()}>${(channel==='people'?['people','people/m2']:['W','W/m2']).map(unit=>`<option value="${unit}"${unit===rule.unit?' selected':''}>${scheduleUnits[unit]}</option>`).join('')}</select></label></div><p class="muted">实际${channel==='people'?'人数':'功率'} = ${rule.unit.endsWith('/m2')?'面积 × ':''}[下限 + 比例 × (上限 − 下限)]。${esc(rule.basis||'本配置输入')}</p>`:''}`:'<p class="muted">空调可用为独立的 0/1 计划，人员为零不会自动关闭空调。</p>'}${references?`<p class="muted">日计划版本：${esc(references)}</p>`:''}${scheduleControls('usage',rule,binary)}<div id="schedule-preview">${schedulePreview()}</div>${advancedDayTable(rule,room,channel)}<details class="usage-gains"><summary>人员与照明得热参数</summary><div class="grid2"><label class="field">人员显热 / W 每人<input type="number" min="0" max="1000" step="any" data-usage-gain="sensible_W_person" value="${esc(displayUsageNumber(gains.sensible_W_person))}"${disabled()}></label><label class="field">照明入室得热比例<input type="number" min="0" max="1" step="any" data-usage-gain="lighting_heat_fraction" value="${esc(displayUsageNumber(gains.lighting_heat_fraction))}"${disabled()}></label></div><p class="muted">人员原潜热 ${format(d.gain_defaults[room.id].latent_W_person,3)} W/人保留；照明原辐射分配沿用。</p></details>${room.hvac?`<details><summary>此房间的默认启停温度</summary><div class="grid2">${Object.entries(temperatureLabels).map(([k,label])=>`<label class="field">${label} / °C<input type="number" step="any" data-usage-temperature="${k}" value="${room.hvac[k]}"${disabled()}></label>`).join('')}</div></details>`:''}${source?`<details><summary>查看原配置说明</summary><p>${esc(source.use)}；${esc(source.basis)}</p>${origin?`<p>工作日：${esc(origin.weekday_name)}；周末：${esc(origin.weekend_name)}。${origin.verified?'已与冻结模型全年实际值核对。':esc(origin.note)}</p>`:''}</details>`:''}<div class="actions"><button data-configuration="usage-save" class="primary"${disabled()}>保存配置版本并用于当前草稿</button><button data-configuration="usage-discard">撤销配置编辑</button></div><p class="muted">之后请保存方案版本。其他方案继续使用各自已选的配置快照。</p></section>`;
};
const beforeScheduleDayTable=dayTable;
dayTable=function(value,attribute,locked=false){const match=attribute.match(/data-operation-hour="([^"]+)"/);return beforeScheduleDayTable(value,attribute,locked)+(match?scheduleControls('operation:'+match[1],value,true):'');};
function convertScheduleBasis(){
 const {room,channel,rule}=selectedUsage();if(channel==='available')return;
 if([...rule.weekday,...rule.weekend].some(v=>!Number.isFinite(v)||v<0)||(rule.kind==='scaled'&&(!Number.isFinite(rule.minimum)||!Number.isFinite(rule.maximum)||rule.minimum<0||rule.minimum>rule.maximum||[...rule.weekday,...rule.weekend].some(v=>v>1))))throw Error('请先补齐当前计划的有效数值，再切换输入方式。');
 if(rule.kind==='scaled'){room.loads[channel]=actualSchedule(rule,room.area_m2);return;}
 const source=S.configuration.data.usage_sources?.[room.id]?.channels?.[channel];
 if(source?.verified&&source.rule?.kind==='scaled'&&Object.keys(scheduleDays).every(day=>actualSchedule(source.rule,room.area_m2)[day].every((v,i)=>Math.abs(v-rule[day][i])<1e-9))){room.loads[channel]=copy(source.rule);}
 else{const max=Math.max(...rule.weekday,...rule.weekend);room.loads[channel]={kind:'scaled',unit:channel==='people'?'people':'W',minimum:0,maximum:max,weekday:rule.weekday.map(v=>max?v/max:0),weekend:rule.weekend.map(v=>max?v/max:0),basis:'由当前实际值等价换算；不是原参数表上下限'};}
 S.usageDraft.schema_version=2;
}
const beforeScheduleAction=configurationAction;
configurationAction=async function(button){
 const action=button.dataset.scheduleAction;if(!action)return beforeScheduleAction(button);
 if(readonly())throw Error('来源或旧版本只读，请另存为研究方案。');
 if(action==='source-rule'){const {room,channel}=selectedUsage(),origin=S.configuration.data.usage_sources?.[room.id]?.channels?.[channel];if(!origin?.verified||origin.rule?.kind!=='scaled')throw Error('原配置没有已核对的上下限与比例；可直接切换输入方式创建自己的比例作息。');room.loads[channel]=copy(origin.rule);S.usageDraft.schema_version=2;markScheduleDirty();return true;}
 const box=button.closest('.schedule-controls'),target=box.dataset.scheduleTarget,rule=scheduleTarget(target),binary=target.startsWith('operation:')||selectedUsage().channel==='available';
 if(action==='fill'){
  const day=box.querySelector('[data-fill-day]').value,start=Number(box.querySelector('[data-fill-start]').value),end=Number(box.querySelector('[data-fill-end]').value),raw=box.querySelector('[data-fill-value]').value,value=raw===''?NaN:Number(raw);
  if(!Number.isInteger(start)||!Number.isInteger(end)||end<=start||start<0||end>24)throw Error('结束时刻须晚于开始时刻；跨午夜请分两段填写。');
  if(!Number.isFinite(value)||value<0||(rule.kind==='scaled'&&value>1)||(binary&&![0,1].includes(value)))throw Error(binary?'空调可用只填 0 或 1。':rule.kind==='scaled'?'比例须在 0–1 之间。':'请输入非负实际值。');
  for(const d of day==='both'?Object.keys(scheduleDays):[day]){rule[d].fill(value,start,end);cleanScheduleReference(rule,d);}
 }else if(action.startsWith('copy-')){const from=action.slice(5),to=from==='weekday'?'weekend':'weekday';rule[to]=copy(rule[from]);cleanScheduleReference(rule,to);if(rule.references?.[from])rule.references[to]=copy(rule.references[from]);}
 else if(action==='apply-profile'){
  const key=box.querySelector('[data-profile-choice]').value,row=S.dailyProfiles.find(r=>r.snapshot.id+':'+r.snapshot.revision===key);if(!row)throw Error('请选择日计划。');if(binary&&!row.binary)throw Error('空调可用需选 0/1 计划。');
  const day=box.querySelector('[data-profile-day]').value;rule[day]=copy(row.snapshot.content.values);rule.references={...rule.references,[day]:copy(row.snapshot)};
  if(target==='usage')S.usageDraft.schema_version=2;
 }else if(action==='save-profile'){
  button.dataset.dailyCapture=target;return configurationAction(button);
 }else return false;
 scheduleTargetChanged(target);return true;
};
document.addEventListener('change',event=>{
 const t=event.target;try{
  if(t.id==='schedule-basis'&&!readonly()){convertScheduleBasis();markScheduleDirty();render();}
  if(t.id==='schedule-unit'&&!readonly()){const {room,rule}=selectedUsage();if(!Number.isFinite(rule.minimum)||!Number.isFinite(rule.maximum)||rule.minimum<0||rule.minimum>rule.maximum){t.value=rule.unit;throw Error('请先补齐有效上下限，再切换单位。');}const before=rule.unit.endsWith('/m2')?room.area_m2:1,after=t.value.endsWith('/m2')?room.area_m2:1;rule.minimum*=before/after;rule.maximum*=before/after;rule.unit=t.value;rule.basis='单位换算；实际计划保持等价';markScheduleDirty();render();}
  if(t.matches('[data-profile-choice]')){const row=S.dailyProfiles.find(r=>r.snapshot.id+':'+r.snapshot.revision===t.value);const el=t.closest('.schedule-controls').querySelector('.profile-description');if(el)el.textContent=row?'来源：'+row.origin+'；别名：'+row.aliases.map(a=>typeof a==='string'?a:a.name).join('、'):'';}
 }catch(error){if(t.id==='schedule-basis')t.value=selectedUsage().rule.kind==='scaled'?'scaled':'actual';notice(error.message,'error');}
});
document.addEventListener('input',event=>{
 const t=event.target;if(readonly())return;
 if(t.dataset.scheduleBound){selectedUsage().rule[t.dataset.scheduleBound]=t.value===''?null:Number(t.value);markScheduleDirty();}
 if(t.dataset.usageHour){cleanScheduleReference(selectedUsage().rule,t.dataset.day);updateSchedulePreview();}
 if(t.dataset.operationHour){const rule=S.record.factors.condition.operation.overrides[t.dataset.operationHour].available;cleanScheduleReference(rule,t.dataset.day);}
 if(t.dataset.usageGain){const {room}=selectedUsage(),defaults=S.configuration.data.gain_defaults[room.id];room.gain_settings={sensible_W_person:defaults.sensible_W_person,lighting_heat_fraction:defaults.lighting_heat_fraction,...room.gain_settings,[t.dataset.usageGain]:t.value===''?null:Number(t.value)};S.usageDraft.schema_version=2;markScheduleDirty();}
});
