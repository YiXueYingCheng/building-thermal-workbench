/* First-use entry points; research inputs remain explicit and version-bound. */
S.enginePath='';
const beforeSetupNav=renderNav;
renderNav=function(){
 libraryTitles.sources=S.boot.workspace?.standalone?'导入来源':'原平台来源';
 if(S.record)beforeSetupNav();
 else nav.innerHTML='<button type="button" data-view="material-library" aria-pressed="'+(S.view==='material-library')+'">公用材料库</button>';
 nav.insertAdjacentHTML('afterbegin','<button type="button" data-view="workspace" aria-pressed="'+(S.view==='workspace')+'">工作区设置</button>');
 const legacy=document.querySelector('.legacy-link');if(legacy)legacy.hidden=!!S.boot.workspace?.standalone;
};
function workspaceSetupView(){
 const w=S.boot.workspace,e=w.engine;
 return `<section class="section"><div class="row"><div><h1>${S.boot.records.length?'工作区设置':'建立你的研究工作区'}</h1><p>先准备计算引擎和气象，再导入建筑，建立自己的研究方案。</p></div><button data-setup="refresh">刷新登记状态</button></div>
 <div class="grid2"><section class="well"><h2>1. 计算引擎</h2><p>${e?'已登记 '+esc(e.version):'尚未登记'}</p><p>当前转换程序使用 EnergyPlus ${esc(w.required_engine)}。</p><label class="field">energyplus.exe 完整路径<input id="setup-engine-path" value="${esc(S.enginePath||e?.executable||'')}" placeholder="选择已安装的 EnergyPlus"></label><div class="actions"><button data-setup="browse-engine">浏览…</button><button data-setup="register-engine" class="primary">核验并登记引擎</button></div><p class="muted">登记只读取版本和文件校验值。新导入建筑使用此次登记；已有方案保留各自绑定。</p></section>
 <section class="well"><h2>2. 气象文件</h2><p>已有 ${w.weather_count} 个可用地点。</p><p>导入自己的 EPW 文件，核对逐时完整性、地点及来源说明。</p><button data-weather-action="open">导入 EPW 气象</button><p class="muted">地点可以暂不分类，之后在方案范围中明确选择。</p></section>
 <section class="well"><h2>3. 建筑模型</h2><p>从已有模型文件读取房间与围护结构，再核对作息和温控配置。</p><p>${buildingImportFormatText()}</p><button data-import-action="open"${!e&&!S.boot.records.length||!w.weather_count?' disabled':''}>导入建筑模型</button>${buildingImportPreparation()}${buildingImportFileHelp()}<p class="muted">${!e&&!S.boot.records.length?'请先登记引擎。 ':''}${!w.weather_count?'请先导入气象。 ':''}转换核对通过后，确认加入建筑列表，再另存为研究方案。</p></section>
 <section class="well"><h2>4. 研究材料</h2><p>独立创建材料并保存版本，再按建筑支持范围预览应用。</p><button data-view="material-library">打开公用材料库</button><p class="muted">双面、双态实体材料可在所选外墙和屋面同时启用表面光学切换和热阻调节。原建筑窗户仍参与计算。</p></section></div>
 ${miSupportMarkup(S.boot.material_support)}${workspacePlanSummary()}</section>`;
}
const beforeSetupRender=render;
render=function(){if(S.view==='workspace'){renderNav();app.innerHTML=workspaceSetupView();syncPageSections();}else beforeSetupRender();};
const beforeSetupSources=sourcesView;
sourcesView=function(){
 if(!S.boot.workspace?.standalone)return beforeSetupSources();
 const v=S.boot.verification;
 return sourceOverviewView()+`<section class="section"><h2>导入来源核对</h2><p>检查已导入建筑、气象及绑定文件；结果验收从对应计算批次进入。</p><button data-action="verify">重新核对来源</button>${v?`<p>${v.passed?'核对通过':'存在待处理差异'} · ${v.check_count} 项检查 · ${esc(v.created)}</p>${v.failures.map(x=>'<p class="warning">'+esc(x)+'</p>').join('')}`:''}</section>`;
};
const beforeSetupAction=action;
action=async function(button){
 if(button.dataset.view==='workspace'){
  if(S.view==='material-library')mcCheckDraft();
  await bootstrap();S.view='workspace';render();return;
 }
 if(button.dataset.setupRecord){if(await loadRecord(button.dataset.setupRecord)===false)return;S.view='editor';S.factor='building';render();await loadConfiguration();render();return;}
 const op=button.dataset.setup;if(!op)return beforeSetupAction(button);
 if(op==='manage-plans'){if(!S.record){const first=S.boot.records.find(r=>!r.archived);if(!first)return;await loadRecord(first.id);}S.view='editor';render();requestAnimationFrame(()=>document.getElementById('search')?.focus());return;}
 if(op==='refresh'){await bootstrap();render();return;}
 const path=document.getElementById('setup-engine-path')?.value||'';S.enginePath=path;
 if(op==='browse-engine'){const result=await api('/api/workspace/engine/browse',{path});if(result.path)S.enginePath=result.path;render();return;}
 if(op==='register-engine'){notice('正在核验引擎版本与文件…');await api('/api/workspace/engine',{path});await bootstrap();render();notice('引擎已登记，可以继续导入气象和建筑。');}
};
document.addEventListener('input',e=>{if(e.target.id==='setup-engine-path')S.enginePath=e.target.value;});

function workspaceRecentIds(){try{return JSON.parse(sessionStorage.getItem('workbench-recent-plans')||'[]');}catch{return [];}}
function workspacePlanSummary(){const rows=S.boot.records,active=rows.filter(r=>!r.archived),recent=[...new Set([S.id,...workspaceRecentIds()])].map(id=>rows.find(r=>r.id===id&&!r.archived)).filter(Boolean).slice(0,3);return `<section id="workspace-plan-summary"><h2>方案入口</h2><p>已登记 ${rows.length} 条记录 · 研究方案 ${active.filter(r=>r.status==='draft').length} · 只读来源 ${active.filter(r=>r.status!=='draft').length}${rows.length-active.length?' · 已归档 '+(rows.length-active.length):''}</p><button class="primary" data-setup="manage-plans"${S.record||active.length?'':' disabled'}>打开方案库与版本</button><p class="muted">在编辑方案左侧统一查找、筛选和打开方案；历史版本、备注及结果仍从对应方案查看。</p>${recent.length?'<h3>最近打开</h3><div class="workspace-recent">'+recent.map(r=>`<button data-setup-record="${esc(r.id)}" title="打开此方案">${esc(r.name)}<small>${r.status==='draft'?'保存版本 '+r.revision:'只读来源'}</small></button>`).join('')+'</div>':'<p>导入建筑后从统一方案库进入。</p>'}</section>`;}
const workspacePreviousLoadRecord=loadRecord;
loadRecord=async function(...args){const value=await workspacePreviousLoadRecord(...args);if(value===false)return value;try{sessionStorage.setItem('workbench-recent-plans',JSON.stringify([S.id,...workspaceRecentIds().filter(id=>id!==S.id)].slice(0,12)));}catch{}return value;};
