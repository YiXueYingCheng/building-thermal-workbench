/* A saved-plan overview. All adoption stays in the existing explicit preview workflow. */
S.sourceOverview=null;S.sourceOverviewError='';S.sourceOverviewFilter={query:'',status:'all',archived:false};S.sourceLegacyOpen=false;
let sourceOverviewFlight=null;
function loadSourceOverview(){
 if(sourceOverviewFlight)return sourceOverviewFlight;
 S.sourceOverviewLoading=true;S.sourceOverviewError='';
 sourceOverviewFlight=(async()=>{try{S.sourceOverview=await api('/api/source-overview');}catch(error){S.sourceOverviewError=error.message;}finally{S.sourceOverviewLoading=false;sourceOverviewFlight=null;}})();
 return sourceOverviewFlight;
}
function sourceOverviewMatches(r){
 const f=S.sourceOverviewFilter,q=f.query.trim().toLocaleLowerCase();
 return (f.archived||!r.archived)&&(f.status==='all'||(f.status==='updates'?r.update_count>0:r.needs_attention))&&(!q||[r.name,r.building,r.id,...r.components.flatMap(x=>[x.current?.name,x.latest?.name]),...r.weather_updates.flatMap(x=>[x.name,...x.updates.map(u=>u.name)])].filter(Boolean).join(' ').toLocaleLowerCase().includes(q));
}
function sourceOverviewRows(){
 const all=S.sourceOverview?.records||[],rows=all.filter(sourceOverviewMatches);
 return `<p class="muted" role="status">显示 ${rows.length} / ${all.length} 个方案最新保存版</p>${rows.map(r=>`<article class="source-overview-card" id="source-plan-${esc(r.id)}"><div class="row"><h3>${esc(r.name)}${r.archived?' · 已归档':''}</h3><span class="tag ${r.needs_attention?'warning':''}">${r.needs_attention?'来源需核对':r.update_count?'有 '+r.update_count+' 项登记更新':'暂无登记更新'}</span></div><p class="muted">${esc(planVersionLabel(r))} · ${esc(r.building)} · ${r.site_count} 地点</p><div class="grid2">${r.components.map(c=>`<div><strong>${esc(c.label)}</strong><p>${c.current?esc(c.current.name)+' · v'+c.current.revision:'使用方案内取值 · 未绑定库版本'}</p>${c.status!=='unbound'?`<p class="muted">${esc(c.note)}</p>`:''}${c.status==='update_available'?`<p class="source-new-version">可核对：${esc(c.latest.name)} · v${c.latest.revision}</p>`:''}${c.local_changes?'<p class="warning">方案材料与绑定库版本存在差异；先处理这些修改，再采用库更新。</p>':''}</div>`).join('')}</div>${r.weather_updates.length?`<details class="source-weather-list"><summary>${r.weather_updates.length} 个地点有气象更新登记</summary>${r.weather_updates.map(w=>`<div class="line"><div><strong>${esc(w.name)}</strong>${w.updates.map(u=>`<p>${esc(u.name)}${u.eligible?'':' · 当前不可选用'}</p>`).join('')}${w.reference_required?'<p class="warning">本方案绑定控制参考或日历，换气象前需重新建立对应参考。</p>':''}</div><button data-source-overview="weather" data-source-plan="${esc(r.id)}" data-source-site="${esc(w.id)}">查看此地点更新</button></div>`).join('')}</details>`:'<p class="muted">气象：当前选用地点暂无更新登记。</p>'}${r.issues.map(x=>`<p class="warning">${esc(x)}</p>`).join('')}<div class="actions"><button class="primary" data-source-overview="open" data-source-plan="${esc(r.id)}">核对来源与更新</button><button data-source-overview="plan" data-source-plan="${esc(r.id)}">查看此保存版</button></div></article>`).join('')||'<p class="empty">没有匹配的方案，可调整筛选。</p>'}`;
}
function sourceOverviewView(){
 const d=S.sourceOverview,f=S.sourceOverviewFilter;
 const header='<div class="row"><h1>本工作区方案来源</h1><button data-source-overview="refresh">刷新概览</button></div><p class="muted">集中查看气象、建筑使用配置和材料的登记更新。进入单方案核对差异后，再决定是否采用。</p>'+`<p role="status" class="muted">${esc(S.sourceOverviewError?'读取失败：'+S.sourceOverviewError:S.sourceOverviewLoading?'正在刷新来源摘要，可继续其他操作…':'')}</p>`;
 if(!d)return `<section class="section" id="source-overview">${header}<p class="warning">${esc(S.sourceOverviewError?'概览读取失败：'+S.sourceOverviewError:'正在读取概览…')}</p></section>`;
 return `<section class="section" id="source-overview">${header}<p class="muted">${esc(d.note)} 核对于 ${esc(readableTime(d.checked_at))}。</p>${S.dirty||S.usageDirty?'<p class="warning">当前编辑有未保存修改；概览仍显示保存版本。先保存或撤销，再从此处切换方案。</p>':''}<div class="source-overview-filter"><label class="field">查找方案、建筑或来源<input id="source-overview-query" type="search" value="${esc(f.query)}" placeholder="名称、建筑、配置或气象"></label><label class="field">显示范围<select id="source-overview-status">${options([['all','全部方案'],['updates','有登记更新'],['attention','需核对来源']],f.status)}</select></label><label class="check"><input id="source-overview-archived" type="checkbox"${f.archived?' checked':''}>包含已归档方案</label><button data-source-overview="clear">清除筛选</button></div><div id="source-overview-rows">${sourceOverviewRows()}</div><p class="muted">采用更新只进入当前编辑，保存后形成新版本；其他方案、旧版本、已排队输入和完成结果保持原绑定。日计划更新先在建筑使用配置中选用。</p></section>`;
}
const sourcesViewBeforeOverview=sourcesView;
sourcesView=function(){return sourceOverviewView()+`<details class="section source-legacy-panel" id="source-legacy-records"${S.sourceLegacyOpen?' open':''}><summary>原平台迁移记录与已有输入包</summary><div class="source-legacy-body">${migrationInputsMarkup()}</div></details>`;};
let migrationInputsFlight=null;
function migrationInputsMarkup(){return S.bundlesLoaded?sourcesViewBeforeOverview().replace('<h1>来源与迁移核对</h1>','<h2>原平台迁移核对</h2>'):`<p role="status">${esc(S.bundlesError||'展开后读取迁移记录与输入包，可继续其他操作。')}</p>${S.bundlesError?'<button data-source-overview="retry-inputs">重试读取输入包</button>':''}`;}
function loadMigrationInputs(){
 if(migrationInputsFlight)return migrationInputsFlight;
 S.bundlesError='';
 migrationInputsFlight=(async()=>{try{S.bundles=await api('/api/model-inputs');S.bundlesLoaded=true;}catch(e){S.bundlesError=e.message;S.bundlesLoaded=false;}finally{migrationInputsFlight=null;const slot=document.querySelector('.source-legacy-body');if(slot)slot.innerHTML=migrationInputsMarkup();}})();return migrationInputsFlight;
}
const renderWeatherBeforeOverview=renderWeatherImport;
renderWeatherImport=function(){renderWeatherBeforeOverview();if(!S.weatherImport?.fromOverview)return;
 const head=weatherDialog().querySelector('.room-tool-head');if(!head)return;
 const back=document.createElement('button');back.dataset.sourceOverview='back';back.textContent='返回来源概览';head.insertBefore(back,head.querySelector('[data-weather-action="close"]'));
};
async function sourceOverviewAction(button){
 const action=button.dataset.sourceOverview;if(!action)return false;
 if(action==='refresh'){await loadSourceOverview();return true;}
 if(action==='clear'){S.sourceOverviewFilter={query:'',status:'all',archived:false};return true;}
 if(action==='retry-inputs'){await loadMigrationInputs();return true;}
 if(action==='back'){closeWeatherImport();S.view='sources';await loadSourceOverview();return true;}
 const r=S.sourceOverview?.records.find(r=>r.id===button.dataset.sourcePlan);if(!r)throw Error('方案概览已变化，请刷新后重试。');
 if(S.dirty||S.usageDirty)throw Error('当前方案或建筑配置还有未保存修改，请先保存或撤销，再切换来源核对对象。');
 const starting=[S.id,S.saved?.revision,S.view],stillHere=()=>S.view===starting[2]&&S.id===starting[0]&&S.saved?.revision===starting[1]&&!S.dirty&&!S.usageDirty;
 await bootstrap();if(!stillHere())return true;const current=S.boot.records.find(x=>x.id===r.id);
 if(!current||current.revision!==r.revision){await loadSourceOverview();render();throw Error('该方案已有新的保存版本，概览已刷新，请重新选择。');}
 if(!await loadRecord(r.id,r.revision,stillHere))return true;S.view='editor';S.resultIndexOrigin=null;render();
 if(action==='plan')return true;
 openWeatherImport('sources');const m=S.weatherImport;m.fromOverview=true;
 if(action==='weather'){
  if(!S.record.factors.scope.site_ids.includes(button.dataset.sourceSite)){closeWeatherImport();throw Error('所选地点已不在该方案中，请刷新概览。');}
  m.old=button.dataset.sourceSite;m.next='';
 }
 await refreshComponentUpdates(m);renderWeatherImport();return true;
}
document.addEventListener('input',event=>{
 if(event.target.id!=='source-overview-query')return;S.sourceOverviewFilter.query=event.target.value;document.getElementById('source-overview-rows').innerHTML=sourceOverviewRows();
});
document.addEventListener('change',event=>{
 if(event.target.id==='source-overview-status')S.sourceOverviewFilter.status=event.target.value;
 else if(event.target.id==='source-overview-archived')S.sourceOverviewFilter.archived=event.target.checked;else return;
 document.getElementById('source-overview-rows').innerHTML=sourceOverviewRows();
});
document.addEventListener('toggle',event=>{if(event.target.id==='source-legacy-records'){S.sourceLegacyOpen=event.target.open;if(event.target.open)void loadMigrationInputs();}},true);
