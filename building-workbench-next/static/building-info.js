function researchInputNoteMarkup(note,compact=false){
 if(!note)return '';
 return `<aside class="research-input-note ${note.status==='matches'?'input-matches':'input-differs'}"><strong>${esc(note.label)}</strong><p>${esc(note.message)}</p>${compact?'':`<details><summary>查看基材约定与来源说明</summary><p>${esc(note.expected)}</p><p>${esc(note.scope)}</p><p>${esc(note.source_note)}</p><p>修正版起点：方案库中的“五层建筑 · 新方案”保存版本 6，可从该版本另存研究方案。</p><p class="muted">${esc(note.basis)}；此处核对保存配置，不替代生成输入时的文件校验。</p></details>`}</aside>`;
}
/* Readable building provenance. Viewing never adopts an update or changes a draft. */
S.buildingInfo=null;
const buildingInfoPositions=new Map();
const buildingInfoTabs={overview:'当前建筑',notes:'接入与验证说明',files:'来源文件'};
function buildingInfoKey(){return JSON.stringify([S.id,S.saved?.revision,S.record?.factors.building.id]);}
function buildingSourceLabel(){return ({global_frozen_v011:'原平台冻结模型',ordinary_building_v1:'已接入建筑快照'})[S.record.provenance.adapter]||'原平台来源记录';}
function buildingMetrics(){const b=S.record.factors.building;return `<div class="building-summary-metrics"><span><strong>${esc(b.zones??'—')}</strong> 间房间 / 热区</span>${b.floors!=null?`<span><strong>${esc(b.floors)}</strong> 层</span>`:''}<span><strong>${format(b.conditioned_area_m2,2)}</strong> m² 温控面积</span>${b.total_area_m2!=null||b.area_m2!=null?`<span><strong>${format(b.total_area_m2??b.area_m2,2)}</strong> m² 总面积</span>`:''}</div>`;}
function buildingSummaryMarkup(){return `<section class="building-summary"><div class="row"><h2>${esc(S.record.factors.building.name)}</h2><button data-building-info="open">建筑来源与接入说明</button></div>${buildingMetrics()}<p class="muted">几何与房间划分沿用来源快照；房间使用、构造及本方案修改在下方核对。</p></section>`;}
function buildingInfoCurrent(){const m=S.buildingInfo;return m?.key===buildingInfoKey()?m:null;}
function buildingInfoDialog(){
 let d=document.getElementById('building-info-dialog');if(d)return d;
 d=document.createElement('dialog');d.id='building-info-dialog';d.setAttribute('aria-labelledby','building-info-title');document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();closeBuildingInfo();});
 d.addEventListener('click',async e=>{
  const b=e.target.closest('[data-building-info]');if(!b)return;e.stopPropagation();if(b.disabled)return;
  const m=buildingInfoCurrent();if(!m)return;const op=b.dataset.buildingInfo;
  if(op==='close'){closeBuildingInfo();return;}
  if(op==='tab'){rememberBuildingInfo();m.tab=b.dataset.infoTab;renderBuildingInfo(true);return;}
  if(op==='retry'){await loadBuildingInfo(m);return;}
  if(op==='updates'){
   rememberBuildingInfo();m.suspended=true;d.close();
   try{openWeatherImport('sources');await refreshComponentUpdates(S.weatherImport);}catch(error){if(buildingInfoCurrent()===m){m.suspended=false;m.error=error.message;renderBuildingInfo();}}return;
  }
  if(op==='download'){
   const data={building:copy(S.record.factors.building),provenance:copy(S.record.provenance),scheme:{id:S.id,revision:S.saved.revision,name:S.record.name,unsaved_scheme:S.dirty,unsaved_room_configuration:S.usageDirty},source_notes:m.data?.source_notes||[],source_model:m.data?.source_model||null,research_input_note:m.noteRecord===JSON.stringify(S.record)?m.note:null,note:'来源记录与当前方案建筑字段；不是重新校验文件或结果的回执，未保存房间配置不包含在建筑字段中。'};
   const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='building-source-'+S.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
 });
 d.addEventListener('toggle',e=>{const m=buildingInfoCurrent(),key=e.target.dataset.infoDetail;if(m&&key)m.expanded[key]=e.target.open;},true);
 return d;
}
function rememberBuildingInfo(){const m=buildingInfoCurrent();if(m)m.scroll[m.tab]=buildingInfoDialog().querySelector('.building-info-body')?.scrollTop||0;}
function infoDetails(key,title,body){return `<details data-info-detail="${esc(key)}"${buildingInfoCurrent().expanded[key]?' open':''}><summary>${esc(title)}</summary>${body}</details>`;}
function buildingInfoOverview(){
 const m=buildingInfoCurrent(),b=S.record.factors.building,p=b.usage_profile,rooms=m.data?.base?.rooms,edited=Object.keys(b.envelope_overrides||{}).length;
 return `<section class="building-info-overview"><h3>${esc(b.name)}</h3>${buildingMetrics()}<div class="building-info-facts"><div><span>接入来源</span><strong>${esc(buildingSourceLabel())}</strong></div><div><span>房间使用配置</span><strong>${p?esc(p.name)+' · v'+p.revision:'建筑原配置'}</strong></div><div><span>原空调归属</span><strong>${rooms?rooms.filter(r=>r.conditioned).length+' 间空调房 / '+rooms.filter(r=>!r.conditioned).length+' 间非空调房':'见原输入记录'}</strong></div><div><span>本方案基础构造修改</span><strong>${edited?edited+' 处设置':'未设置局部参数修改'}</strong></div><div><span>本方案研究材料</span><strong>${S.record.factors.materials.definitions.length?S.record.factors.materials.definitions.map(d=>esc(d.name)).join('、'):'未添加研究材料'}</strong></div></div><p class="muted">这里显示当前方案建筑摘要。来源说明保留接入时的记录；本方案后续的材料、工况和计算结果分别查看。</p>${S.record.factors.materials.legacy_construction_overrides?'<p class="warning">此方案另有原构造指定，请在材料页核对有效设置。</p>':''}</section>`;
}
function buildingInfoNotes(){
 const m=buildingInfoCurrent(),notes=[...new Set([...(m.data?.source_notes||[]),...(S.record.provenance.notes||[])])];
 return `<section><h3>建筑接入时的核对记录</h3><p class="muted">以下是来源当时的说明，保留原文。后续已保存方案的全年计算、材料应用和复核结论，以相应结果记录为准。</p>${notes.length?`<ol class="building-info-notes">${notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ol>`:'<p>此来源未附单独的接入说明，可在来源文件中核对原记录。</p>'}<div class="building-info-hint"><strong>需要核对当前计算能力时</strong><p>回到方案的流程总览与能力提示；来源曾通过核查，不表示所有新增材料或工况已完成验证。</p></div></section>`;
}
function buildingInfoFiles(){
 const m=buildingInfoCurrent(),b=S.record.factors.building,rows=new Map();
 function add(f,role){if(!f?.path)return;const key=f.path+'|'+(f.sha256||'');if(!rows.has(key))rows.set(key,{...f,roles:[]});const row=rows.get(key);if(!row.roles.includes(role))row.roles.push(role);}
 add(b.input_snapshot,'输入参数快照');add(b.model_snapshot,'建筑模型');add(m.data?.source_model,'配置读取模型');for(const f of S.record.provenance.source_refs||[])add(f,'接入依据');
 const labels={'model.epJSON':'建筑计算模型','model-audit.json':'模型核对记录','input-state.json':'输入配置登记','effective-inputs.json':'实际输入核对','wall-assignment-audit.json':'墙体应用核对','envelope-audit.json':'围护构造核对','orientation-verification.json':'朝向与层序核对','global-source.json':'全球参考建筑来源'};
 const cards=[...rows.values()].map((f,i)=>{const name=f.path.split(/[\\/]/).at(-1);return `<article class="building-source-file"><h4>${esc(labels[name]||name.replace(/\.[^.]+$/,''))}</h4><p class="muted">${esc(f.roles.join(' · '))}</p>${infoDetails('file-'+i,'文件、路径与标识',`<p>${esc(name)}</p><p class="source-path">${esc(f.path)}</p><dl><dt>记录的 SHA-256</dt><dd>${esc(f.sha256||'未登记')}</dd><dt>来源记录状态</dt><dd>${esc(({verified:'来源记录已核对',unverified:'来源记录未核对',missing:'来源记录为缺失'})[f.status]||f.status||'未登记')}</dd></dl>`)}</article>`;}).join('');
 return `<section><div class="row"><h3>建筑来源文件 · ${rows.size} 项</h3><button data-building-info="download">下载来源记录</button></div><p class="muted">仅列建筑接入引用，重复路径与标识已合并。当前未执行逐文件身份核对；气象、组件更新、文件恢复与位置登记请进入“核对本方案来源与更新”。</p><div class="building-source-files">${cards||'<p>此来源没有单独登记文件引用。</p>'}</div>${infoDetails('raw','完整建筑字段与接入记录',`<pre>${esc(JSON.stringify({building:b,provenance:S.record.provenance},null,2))}</pre>`)}</section>`;
}
function renderBuildingInfo(focusTab=false){
 const m=buildingInfoCurrent();if(!m||m.suspended)return;const d=buildingInfoDialog();
 d.innerHTML=`<header class="viewer-head"><div><p class="muted">${esc(S.record.name)} · ${esc(planVersionLabel(S.saved))}</p><h2 id="building-info-title" tabindex="-1">建筑来源与接入说明</h2></div><button data-building-info="close">关闭</button></header><nav class="building-info-tabs" aria-label="建筑信息内容">${Object.entries(buildingInfoTabs).map(([key,label])=>`<button data-building-info="tab" data-info-tab="${key}" aria-pressed="${m.tab===key}">${label}</button>`).join('')}</nav><div class="building-info-body">${m.pending?'<p role="status">正在读取接入说明…</p>':''}${m.error?`<p role="alert" class="warning">接入详情未能读取：${esc(m.error)}</p><button data-building-info="retry">重试读取</button>`:''}${m.noteRecord===JSON.stringify(S.record)?researchInputNoteMarkup(m.note):!m.pending&&!m.error?'<p class="muted">当前配置的研究基材提示尚未核对。<button data-building-info="retry">核对配置</button></p>':''}${m.tab==='notes'?buildingInfoNotes():m.tab==='files'?buildingInfoFiles():buildingInfoOverview()}</div><footer class="viewer-foot"><div><p>${S.dirty||S.usageDirty?'当前有未保存编辑，查看和关闭均保留。':'只读查看 · 不修改方案'}</p><p class="muted">文件核对、来源更新另行操作。</p></div><div class="actions"><button data-building-info="updates">核对本方案来源与更新</button><button data-building-info="close">返回方案</button></div></footer>`;
 if(!d.open)d.showModal();
 const focus=focusTab?d.querySelector('[data-info-tab="'+m.tab+'"]'):d.querySelector('#building-info-title');focus.focus({preventScroll:true});d.querySelector('.building-info-body').scrollTop=m.scroll[m.tab]||0;
}
async function loadBuildingInfo(m){
 if(!configurationSupported())return;m.pending=true;m.error='';renderBuildingInfo();
 try{const record=copy(S.record),key=JSON.stringify(record);const [data,notes]=await Promise.all([m.data?Promise.resolve(m.data):api('/api/configuration/'+encodeURIComponent(S.id)+'?revision='+encodeURIComponent(S.saved.revision)),api('/api/research-input-notes',{record})]);if(buildingInfoCurrent()===m){m.data=data;if(key===JSON.stringify(S.record)){m.note=notes.note;m.noteRecord=key;}}}
 catch(e){if(buildingInfoCurrent()===m)m.error=e.message;}
 finally{if(buildingInfoCurrent()===m){rememberBuildingInfo();m.pending=false;renderBuildingInfo();}}
}
function openBuildingInfo(opener){
 const m={key:buildingInfoKey(),tab:'overview',scroll:{},expanded:{},...buildingInfoPositions.get(buildingInfoKey()),data:S.configuration?.key===S.id+':'+S.saved.revision?S.configuration.data:null,pending:false,error:'',opener,scrollY:scrollY,suspended:false};S.buildingInfo=m;document.documentElement.classList.add('building-info-open');renderBuildingInfo();if(!m.data||!m.noteRecord)void loadBuildingInfo(m);
}
function closeBuildingInfo(restore=true){
 const m=S.buildingInfo;if(!m)return;if(!m.suspended)rememberBuildingInfo();else beforeBuildingInfoWeatherClose();buildingInfoPositions.set(m.key,{tab:m.tab,scroll:m.scroll,expanded:m.expanded});S.buildingInfo=null;const d=buildingInfoDialog();d.close();d.innerHTML='';document.documentElement.classList.remove('building-info-open');
 if(restore)requestAnimationFrame(()=>{window.scrollTo({top:m.scrollY,behavior:'instant'});const b=m.opener?.isConnected?m.opener:document.querySelector('[data-building-info="open"]');b?.focus({preventScroll:true});});
}
const beforeBuildingInfoAction=configurationAction;
configurationAction=async function(b){if(b.dataset.buildingInfo==='open'){openBuildingInfo(b);return true;}return beforeBuildingInfoAction(b);};
const beforeBuildingInfoRender=render;
render=function(){if(S.buildingInfo&&!buildingInfoCurrent())closeBuildingInfo(false);return beforeBuildingInfoRender();};
const beforeBuildingInfoWeatherClose=closeWeatherImport;
closeWeatherImport=function(){beforeBuildingInfoWeatherClose();const m=buildingInfoCurrent();if(m?.suspended){m.suspended=false;renderBuildingInfo();}};
const beforeBuildingInfoWeatherRender=renderWeatherImport;
renderWeatherImport=function(){beforeBuildingInfoWeatherRender();if(buildingInfoCurrent()?.suspended){const b=weatherDialog().querySelector('[data-weather-action="close"]');if(b)b.textContent='返回建筑来源';}};
