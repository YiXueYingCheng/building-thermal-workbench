/* Scope library contains values, not live bindings to a scheme or calculation. */
S.scopeFilters={query:'',climate:'',selected:false};S.scopeTool=null;
const previousScopeReset=resetConfiguration;
resetConfiguration=function(){previousScopeReset();S.scopeFilters={query:'',climate:'',selected:false};};
function scopeSites(){return Object.values(S.boot.sites).filter(s=>s.source_kind==='reviewed_global');}
function scopePeriod(p){return p.slice(0,2).join('-')+' 至 '+p.slice(2).join('-');}
function scopeContext(){return JSON.stringify({id:S.id,revision:S.record.revision,scope:S.record.factors.scope});}
function scopeMatches(site){const f=S.scopeFilters,q=f.query.trim().toLocaleLowerCase();return (!q||[site.id,site.name,site.country,site.site_kind].join(' ').toLocaleLowerCase().includes(q))&&(!f.climate||site.climate===f.climate)&&(!f.selected||S.record.factors.scope.site_ids.includes(site.id));}
function scopeCoverageRows(){const sites=scopeSites(),selected=new Set(S.record.factors.scope.site_ids);return (S.boot.climate_classes||[]).map(c=>{const group=sites.filter(s=>s.climate===c.climate),eligible=group.filter(s=>s.eligible&&s.weather);return {...c,selected:eligible.filter(s=>selected.has(s.id)).length,available:eligible.length,held:group.length-eligible.length};});}
function scopeCoverageMarkup(rows){return `<div class="scope-coverage">${rows.map(c=>`<div class="scope-climate ${c.selected?'has-selection':!c.available?'has-gap':''}"><strong>${esc(c.climate)}</strong><span>${esc(c.name)}</span><small>${c.selected} 已选 / ${c.available} 可用${c.held?' · '+c.held+' 暂缓':''}</small><small>${!c.available?'暂无可用代表点':!c.selected?'本方案未选':'已选代表地点'}</small></div>`).join('')}</div>`;}
const originalScopePanel=scopePanel;
scopePanel=function(){
 if(!['global_frozen_v011','ordinary_building_v1'].includes(S.record.provenance.adapter))return originalScopePanel();
 const p=S.record.factors.scope,selected=new Set(p.site_ids),f=S.scopeFilters,rows=scopeCoverageRows(),sites=scopeSites();
 return `<h2>地点与时段</h2><div class="grid2"><label class="field">开始（月-日）<input data-period="start" value="${p.period.slice(0,2).map(v=>String(v).padStart(2,'0')).join('-')}" placeholder="01-01"${disabled()}></label><label class="field">结束（月-日）<input data-period="end" value="${p.period.slice(2).map(v=>String(v).padStart(2,'0')).join('-')}" placeholder="12-31"${disabled()}></label></div>
 <div class="actions scope-tools"><button data-scope-tool="save">保存地点与时段组合</button><button data-scope-tool="library">打开范围组合库</button></div>
 <p class="muted">组合只复用地点与时段；应用后需保存方案版本。原汇总方式、建筑、材料、工况和求解步长保留。</p>
 <details class="scope-coverage-detail"><summary>气候覆盖 · 已选 ${rows.filter(c=>c.selected).length} / ${rows.length} 类 · ${selected.size} 个地点</summary><p class="muted">这里只统计当前选择，不表示计算已经完成。${rows.filter(c=>!c.available).map(c=>esc(c.climate)).join('、')||'无'} 暂无可用代表点；未计算地区在结果地图中仍保留无数据。</p>${scopeCoverageMarkup(rows)}</details>
 <div class="scope-filters"><label class="field">查找地点<input id="scope-search" type="search" value="${esc(f.query)}" placeholder="城市、国家/地区、站点编号"></label><label class="field">气候类型<select id="scope-climate">${options([['','全部气候类型'],...(S.boot.climate_classes||[]).map(c=>[c.climate,c.climate+' · '+c.name])],f.climate)}</select></label><label class="check"><input type="checkbox" id="scope-selected"${f.selected?' checked':''}>仅看已选</label></div>
 <div class="row"><span id="scope-filter-count">显示 ${sites.filter(scopeMatches).length} / ${sites.length} 个候选 · 已选 ${selected.size}</span><div class="actions"><button data-scope-tool="select-filtered"${disabled()}>选中筛选内可用地点</button><button data-scope-tool="remove-filtered"${disabled()}>移除筛选内已选地点</button></div></div>
 <p class="muted">筛选只改变显示。上面两个按钮只修改筛选内地点，筛选外选择保留。</p>
 <div class="scope-site-list">${sites.map(s=>`<div class="scope-site" data-scope-row="${esc(s.id)}"${scopeMatches(s)?'':' hidden'}><label class="check"><input type="checkbox" data-site="${esc(s.id)}"${selected.has(s.id)?' checked':''}${readonly()||!s.eligible?' disabled':''}><span><strong>${esc(s.name)} · ${esc(s.climate)}${s.eligible?'':' · 暂缓'}</strong><small>${esc(s.country)} · ${esc(s.site_kind)}</small></span></label><button data-scope-tool="weather" data-weather-site="${esc(s.id)}">气象详情</button></div>`).join('')}</div>
 <details class="scope-presets"><summary>已有范围快捷选择（替换当前全部地点）</summary><div class="actions"><button data-scope="all"${disabled()}>全部已接受地点</button><button data-scope="sample"${disabled()}>8 个步长研究地点</button></div></details><p class="muted">沿用气候类型分组、类内代表点等权。可用气象与区域代表性分别记录。</p>`;
};
function updateScopeFilters(){const sites=scopeSites();for(const row of document.querySelectorAll('[data-scope-row]'))row.hidden=!scopeMatches(S.boot.sites[row.dataset.scopeRow]);document.getElementById('scope-filter-count').textContent=`显示 ${sites.filter(scopeMatches).length} / ${sites.length} 个候选 · 已选 ${S.record.factors.scope.site_ids.length}`;}
function scopeDialog(){let el=document.getElementById('scope-dialog');if(el)return el;el=document.createElement('dialog');el.id='scope-dialog';el.setAttribute('aria-labelledby','scope-tool-title');el.addEventListener('cancel',e=>{e.preventDefault();closeScopeTool();});el.addEventListener('click',e=>{if(e.target.closest('[data-scope-tool="close"]')){e.stopPropagation();closeScopeTool();}});document.body.appendChild(el);return el;}
function closeScopeTool(){scopeDialog().close();scopeDialog().innerHTML='';S.scopeTool=null;}
function scopeRef(){const row=S.scopeTool.rows.find(r=>r.id+':'+r.revision===S.scopeTool.selected);return row?{id:row.id,revision:row.revision}:null;}
function scopeNames(ids){return ids.map(id=>esc(S.boot.sites[id]?.name||id)+' · '+esc(S.boot.sites[id]?.climate||'')).join('；')||'无';}
const weatherStatuses={matches:'文件与登记标识一致',mismatch:'文件内容与登记不一致',missing:'文件不存在或外置盘未连接',unreadable:'文件无法读取',unregistered:'该候选暂无已接受气象文件',too_large:'文件超出本次核对上限',changed_during_read:'读取期间文件发生变化'};
function weatherQualityMarkup(q){
 if(!q)return '';const t=q.timeline,num=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
 return `<section class="well weather-quality"><h3>逐时气象核查 · ${{clear:'未发现所检项目异常',notes:'有数据说明',issues:'有待复核项'}[q.status]}</h3>
 <div class="metrics"><span><strong>${t.records_scanned??'—'}</strong>已扫描记录 / 8760</span><span><strong>${t.complete?'完整':'未确认完整'}</strong>全年月日小时顺序</span><span><strong>${t.missing_hours??'—'} / ${t.duplicate_hours??'—'}</strong>缺少 / 重复小时</span></div>
 <p>分钟标记：${esc(t.minute_markers?.join('、')||'未取得')}；来源年份：${esc(t.source_years?.join('、')||'未取得')}。</p><p class="muted">典型年允许不同月份来自不同年份。顺序完整不等于已排除太阳辐射的小时偏移。</p>
 ${q.issues.length?`<details open><summary>核查发现与数据说明（${q.issues.length} 项）</summary><ul class="weather-issues">${q.issues.map(i=>`<li><strong>${i.severity==='error'?'需核查':'说明'} · ${esc(i.label)}</strong>（${i.count}）${i.examples.length?`<details><summary>查看记录示例</summary>${i.examples.map(e=>`<p>第 ${e.record} 条 · 文件第 ${e.line} 行：${esc(e.observed)}</p>`).join('')}</details>`:''}</li>`).join('')}</ul></details>`:'<p>所检时间与主要字段未发现异常。</p>'}
 <details><summary>主要字段 · 缺测、异常与数值范围</summary><p class="muted">统计排除缺测标记、非有限值和超范围值；不以零替代。长波补算依赖按同一条记录检查。字段范围依据 EPW 文档，不代表地区合理性。</p><div class="table-wrap"><table class="table weather-table"><thead><tr><th>字段 / 单位</th><th>有效条数</th><th>缺测</th><th>非数值</th><th>超范围</th><th>最小</th><th>最大</th></tr></thead><tbody>${q.fields.map(f=>`<tr><td>${esc(f.label)}<small>${esc(f.unit)}</small></td><td>${f.valid}</td><td>${f.missing}</td><td>${f.invalid}</td><td>${f.out_of_range}</td><td>${num(f.minimum)}</td><td>${num(f.maximum)}</td></tr>`).join('')}</tbody></table></div></details>
 <details><summary>月度温度与太阳辐射</summary><p class="muted">月均温仅使用有效值，另列有效小时；辐射仅在该月全部小时有效时累计，否则显示缺失。单位为 kWh/m²，法向直射为法向接收量。</p>${q.monthly.length?`<div class="table-wrap"><table class="table weather-table"><thead><tr><th>月</th><th>温度有效小时</th><th>均温 / °C</th><th>最低 / °C</th><th>最高 / °C</th><th>水平总辐射</th><th>法向直射</th><th>水平散射</th></tr></thead><tbody>${q.monthly.map(m=>`<tr><td>${m.month}</td><td>${m.temperature_hours} / ${m.expected_hours}</td><td>${num(m.temperature_mean_C)}</td><td>${num(m.temperature_min_C)}</td><td>${num(m.temperature_max_C)}</td>${['ghi','dni','dhi'].map(k=>`<td>${num(m.solar[k].energy_kWh_m2)}<small>${m.solar[k].valid_hours} / ${m.expected_hours} h</small></td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p>时间或行结构尚未确认完整，不汇总月度值。</p>'}</details>
 <details><summary>本次检查范围与规则</summary><p>${esc(q.scope)}</p><ul>${q.limits.map(v=>`<li>${esc(v)}</li>`).join('')}</ul><p>核查器 ${esc(q.scanner)} · <a href="${esc(q.format_reference)}" target="_blank" rel="noopener">EnergyPlus EPW 字段文档</a></p></details></section>`;
}
function renderScopeTool(){
 const m=S.scopeTool;if(!m)return;const el=scopeDialog();let content='';
 const versionOptions=()=>m.rows.map(r=>`<option value="${r.id}:${r.revision}"${m.selected===r.id+':'+r.revision?' selected':''}>${esc(r.name)} · v${r.revision} · ${r.scope.site_ids.length} 个地点 · ${scopePeriod(r.scope.period)}</option>`).join('');
 if(m.mode==='weather'){
  const r=m.result,s=r?.site;if(s){const h=r.epw_header;content=`<h3>${esc(s.name)} · ${esc(s.climate)}</h3><p>${esc(s.country)} · ${esc(s.site_kind)} · 登记坐标 ${esc(s.latitude)}, ${esc(s.longitude)}</p><p class="${r.status==='matches'?'':'warning'}"><strong>${weatherStatuses[r.status]}</strong></p><p>核对时间：${esc(r.checked_at)}</p><details open><summary>既有复核说明</summary><p>${esc(s.review_note||'无补充说明')}</p></details>${h?`<details><summary>EPW 文件地点表头</summary><p>${esc(h.city)} · ${esc(h.country)} · ${esc(h.source)} · 站号 ${esc(h.station)}</p><p>纬度 ${esc(h.latitude)}，经度 ${esc(h.longitude)}，时区 UTC ${esc(h.timezone)}，海拔 ${esc(h.elevation)} m</p></details>`:''}<details><summary>文件位置与完整标识</summary><p class="source-path">原引用：${esc(s.weather?.path||'未登记文件')}</p>${r.actual_path?`<p class="source-path">当前读取：${esc(r.actual_path)}</p>`:''}<p class="source-path">登记 SHA-256：${esc(s.weather?.sha256||'无')}</p><p class="source-path">本次 SHA-256：${esc(r.actual_sha256||'未取得')}</p></details><p class="muted">${esc(r.note)}</p>`;}
  if(s)content+=`<div class="actions weather-actions"><button data-scope-tool="quality"${!s.weather||m.qualityPending?' disabled':''}>${m.qualityPending?'正在核查…':r.quality?'重新核查逐时数据':'检查逐时数据'}</button>${r.quality?'<button data-scope-tool="quality-download">下载本次核查 JSON</button>':''}</div>${weatherQualityMarkup(r.quality)}`;
 }else if(m.mode==='save'){
  content=`<p>当前 ${S.record.factors.scope.site_ids.length} 个地点 · ${scopePeriod(S.record.factors.scope.period)}</p><label class="field">组合名称<input id="scope-library-name" maxlength="100" value="${esc(m.name)}"></label><label class="field">保存方式<select id="scope-library-parent"><option value="">另存为新组合</option>${versionOptions()}</select></label><p class="muted">选已有组合则追加版本，旧版本保留；同名同内容重复保存复用原版本。只保存范围组合，不保存当前方案，也不启动计算。</p><button data-scope-tool="save-confirm" class="primary">保存组合</button>`;
 }else{
  content=m.rows.length?`<label class="field">范围组合版本<select id="scope-library-selected">${versionOptions()}</select></label><button data-scope-tool="preview" class="primary">预览复用变化</button>`:'<p>暂无保存的组合。可关闭后保存当前地点与时段。</p>';
  if(m.result){const r=m.result;content+=`<section class="well scope-preview"><h3>${esc(r.reference.name)} · v${r.reference.revision}</h3><p>地点 ${S.record.factors.scope.site_ids.length} → ${r.scope.site_ids.length}；时段 ${scopePeriod(r.period_before)} → ${scopePeriod(r.period_after)}</p><details open><summary>新增 ${r.added.length} 个地点</summary><p>${scopeNames(r.added)}</p></details><details open><summary>移除 ${r.removed.length} 个地点</summary><p>${scopeNames(r.removed)}</p></details><p class="muted">气象标识与登记快照一致；本预览不重新读取文件。实际文件在生成输入时继续按既有流程核对。</p>${scopeCoverageMarkup(r.coverage)}</section>`;}
  content+=`<div class="scope-apply"><button data-scope-tool="apply" class="primary"${!m.result||readonly()?' disabled':''}>应用到当前方案编辑</button><p class="muted">${readonly()?'来源或历史版本只读，请在可编辑研究方案中复用。':'仅替换地点和时段，之后仍需保存方案版本。'}</p></div>`;
 }
 el.innerHTML=`<div class="room-tool-head"><h2 id="scope-tool-title">${{save:'保存地点与时段组合',library:'范围组合库',weather:'气象详情与文件核对'}[m.mode]}</h2><button data-scope-tool="close">关闭</button></div>${content}<p class="scope-message" role="status">${esc(m.message||'')}</p>`;
 if(!el.open)el.showModal();
}
async function previewScope(){const m=S.scopeTool,ref=scopeRef();if(!ref)throw Error('请先选择范围组合。');const key=JSON.stringify(ref),context=scopeContext(),sequence=++m.sequence;m.result=null;m.message='正在核对组合…';renderScopeTool();try{const r=await api('/api/scope-library/preview',{current:S.record.factors.scope,reference:ref});if(S.scopeTool!==m||sequence!==m.sequence||key!==JSON.stringify(scopeRef())||context!==scopeContext())return;m.result=r;m.context=context;m.message='已核对，尚未修改方案。';renderScopeTool();}catch(e){if(S.scopeTool===m&&sequence===m.sequence){m.message=e.message;renderScopeTool();}}}
const previousScopeAction=configurationAction;
configurationAction=async function(button){
 const action=button.dataset.scopeTool;if(!action)return previousScopeAction(button);
 if(action==='close'){closeScopeTool();return true;}
 if(action==='library'||action==='save'){
  const rows=await api('/api/scope-library');S.scopeTool={mode:action,rows,selected:action==='library'&&rows.length?rows[0].id+':'+rows[0].revision:'',name:'',sequence:0,context:scopeContext(),result:null};renderScopeTool();return true;
 }
 if(action==='weather'){
  const m={mode:'weather',message:'正在只读核对气象文件…',result:null};S.scopeTool=m;renderScopeTool();try{const result=await api('/api/scope-weather',{site_id:button.dataset.weatherSite});if(S.scopeTool===m){m.result=result;m.message='';renderScopeTool();}}catch(e){if(S.scopeTool===m){m.message=e.message;renderScopeTool();}}return true;
 }
 if(action==='quality'){
  const m=S.scopeTool;if(!m?.result?.site?.weather||m.qualityPending)return true;
  const ident=m.result.site.id;m.qualityPending=true;m.result.quality=null;m.message='正在读取登记文件并核查逐时数据…';renderScopeTool();
  try{const result=await api('/api/scope-weather/quality',{site_id:ident});if(S.scopeTool===m){m.result=result;m.message=result.quality?'核查完成；地点选择、既有复核和计算结果保持。':'本次未取得与登记一致的文件，未生成逐时核查。';}}
  catch(e){if(S.scopeTool===m)m.message=e.message;}
  finally{if(S.scopeTool===m){m.qualityPending=false;renderScopeTool();}}return true;
 }
 if(action==='quality-download'){
  const r=S.scopeTool?.result;if(!r?.quality||S.scopeTool.qualityPending)return true;
  const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`weather-quality-${r.site.id.replace(/[^a-zA-Z0-9_.-]/g,'_')}-${r.actual_sha256.slice(0,12)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return true;
 }
 if(action==='save-confirm'){
  const m=S.scopeTool;if(m.context!==scopeContext())throw Error('当前范围已变化，请关闭后重新保存。');
  try{const r=await api('/api/scope-library',{name:m.name,scope:S.record.factors.scope,parent:scopeRef()});if(S.scopeTool===m){closeScopeTool();notice(`已保存范围组合“${r.name}” · v${r.revision}；当前方案仍按原保存状态保留。`);}}
  catch(e){if(S.scopeTool===m){m.message=e.message;renderScopeTool();}}return true;
 }
 if(action==='preview'){await previewScope();return true;}
 if(readonly())throw Error('来源或历史版本只读，请在可编辑研究方案中选择范围。');
 if(action==='apply'){
  const m=S.scopeTool;if(!m.result||m.context!==scopeContext()||JSON.stringify(m.result.reference.id+':'+m.result.reference.revision)!==JSON.stringify(m.selected))throw Error('预览已失效，请重新核对。');
  const p=S.record.factors.scope,r=m.result.scope,changed=JSON.stringify(p.site_ids)!==JSON.stringify(r.site_ids)||JSON.stringify(p.period)!==JSON.stringify(r.period);
  if(changed){setPath('factors.scope.site_ids',copy(r.site_ids));setPath('factors.scope.period',copy(r.period));}closeScopeTool();notice(changed?'地点与时段已应用到当前编辑；请保存方案版本。':'地点与时段相同，未修改方案。');return true;
 }
 if(action==='select-filtered'||action==='remove-filtered'){
  const ids=new Set(S.record.factors.scope.site_ids),sites=scopeSites().filter(scopeMatches).filter(s=>s.eligible&&s.weather);
  for(const s of sites)action==='select-filtered'?ids.add(s.id):ids.delete(s.id);
  if(JSON.stringify([...ids])!==JSON.stringify(S.record.factors.scope.site_ids))setPath('factors.scope.site_ids',[...ids]);return true;
 }
 return false;
};
document.addEventListener('input',e=>{const t=e.target;if(t.id==='scope-search'){S.scopeFilters.query=t.value;updateScopeFilters();}if(t.id==='scope-library-name'&&S.scopeTool)S.scopeTool.name=t.value;});
document.addEventListener('change',e=>{
 const t=e.target;if(t.id==='scope-climate'){S.scopeFilters.climate=t.value;updateScopeFilters();}if(t.id==='scope-selected'){S.scopeFilters.selected=t.checked;updateScopeFilters();}
 if(['scope-library-selected','scope-library-parent'].includes(t.id)&&S.scopeTool){const m=S.scopeTool;m.selected=t.value;m.result=null;m.sequence++;m.message='';if(m.mode==='save'){const r=m.rows.find(r=>r.id+':'+r.revision===t.value);if(r)m.name=r.name;}renderScopeTool();}
});
