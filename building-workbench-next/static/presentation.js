/* Visible categories and labels only; stored names, versions and results stay intact. */
S.libraryGroups={workspace:true,sources:false,archived:false};S.compareCatalog='workspace';
const libraryTitles={workspace:'本工作区方案',sources:'原平台来源',archived:'已归档来源'};
function recordGroup(r){return r.research_set?'members':r.archived?'archived':r.status==='draft'?'workspace':'sources';}
function readableTime(value){if(!value)return '原正式来源';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);}
function batchCountSummary(counts){
 const labels={running:'计算中',pending:'排队',review:'待复核',failed:'失败',interrupted:'中断',cancelled:'取消',passed:'通过',reused:'复用'};
 return Object.entries(labels).filter(([key])=>counts[key]>0).map(([key,label])=>counts[key]+' 项'+label).join(' · ')||'暂无算例状态记录';
}
function periodLabel(p){return !p?'时段见来源':JSON.stringify(p)==='[1,1,12,31]'?'全年':`${p[0]}月${p[1]}日—${p[2]}月${p[3]}日`;}
function selectInitialRecord(){
 if(!S.boot.records.some(r=>r.id===S.id))S.id=S.boot.records[0]?.id;
 if(!S.boot.records.some(r=>r.id===S.left))S.left=S.id;
 if(!S.boot.records.some(r=>r.id===S.right))S.right=S.boot.records[1]?.id||S.id;
 const rows=S.boot.records.filter(r=>r.status==='draft'&&r.batch_count>0&&!r.archived).sort((a,b)=>b.latest_batch_created.localeCompare(a.latest_batch_created));
 if(rows.length)S.id=rows[0].id;
 const recent=S.boot.comparisons.find(c=>['left','right'].every(side=>c.display?.[side]?.group==='workspace'&&c.display[side].batch_count>0));
 if(recent){S.left=recent.left.id;S.right=recent.right.id;S.compareVersions={left_revision:recent.left.revision,right_revision:recent.right.revision};S.planComparisonDraft={name:recent.name,metric:recent.metric};}
 if(!S.boot.records.some(r=>recordGroup(r)==='workspace'))S.compareCatalog='sources';
}
function revealRecordGroup(id){const r=S.boot.records.find(x=>x.id===id);if(r){S.libraryGroups[recordGroup(r)]=true;if(r.archived)S.archived=true;}}
function regionalOrigin(r){return S.boot.regional_plan_origins?.find(p=>p.id===r.id&&p.revision===r.revision);}
function isRegionalDaily(r){return regionalOrigin(r)?.daily||S.boot.regional_daily_plans?.some(p=>p.id===r.id&&p.revision===r.revision);}
function regionalOriginNote(r){
 const p=regionalOrigin(r);if(!p)return '';
 const source=p.parent_name?'<p>起始方案 · '+esc(p.parent_name)+' · v'+esc(p.parent_revision)+'</p>':'';
 const group=p.group?'<p>地区组 · '+esc(p.group)+'</p>':'';
 const role=p.daily?'准备当地 W00 逐日参考，供生成光学切换日历使用。':'研究工况为「'+esc(p.label)+'」。';
 return `<details class="version-note"><summary>平台派生 · 查看来源</summary>${group}${source}<p>${p.group_sites?'地区组共 '+esc(p.group_sites)+' 个地点，':''}本版本覆盖 ${esc(p.sites)} 个地点。${role}</p></details>`;
}
function libraryButton(r){return `<button type="button" data-record="${esc(r.id)}" aria-pressed="${S.id===r.id}">${esc(r.name)}<small>${r.status==='draft'?'保存版本 '+r.revision:'只读来源'}${regionalOrigin(r)?' · 平台派生':''}${r.batch_count?' · 已有计算批次':''}</small><small>${r.site_count} 地点 · ${periodLabel(r.period)} · ${r.step_minutes} min</small></button>`;}
function libraryList(){
 const rows=filteredRecords();
 return ['workspace','sources','archived'].map(key=>{
  if(key==='archived'&&!S.archived)return '';
  const all=S.boot.records.filter(r=>recordGroup(r)===key),filtered=rows.filter(r=>recordGroup(r)===key);
  if(key==='workspace')filtered.sort((a,b)=>(b.latest_batch_created||'').localeCompare(a.latest_batch_created||''));
  if(!filtered.length&&S.search)return '';
  return `<details class="library-group" data-library-group="${key}"${S.search||S.libraryGroups[key]?' open':''}><summary>${libraryTitles[key]} <span class="tag">${S.search?filtered.length:all.length}</span></summary>${key==='sources'?'<p class="muted">可另存为本工作区方案；原来源保持只读。</p>':''}${filtered.map(libraryButton).join('')||'<p class="muted">暂无记录。</p>'}</details>`;
 }).join('')||'<p class="empty">没有匹配项；需要时可勾选“包含已归档来源”。</p>';
}
function librarySidebar(){return `<aside class="sidebar"><h2>方案库</h2><p class="muted">当前方案与原来源分开展示。</p><label class="field">查找方案<input id="search" value="${esc(S.search)}" placeholder="名称或建筑"></label><label class="check"><input id="archived" type="checkbox"${S.archived?' checked':''}>包含已归档来源</label><div class="record-list">${libraryList()}</div></aside>`;}
function comparisonCatalogControl(){return `<label class="field comparison-catalog">选择方案的范围<select id="comparison-catalog">${options([['workspace','本工作区方案'],['sources','原平台来源'],['archived','已归档来源'],['all','全部记录']],S.compareCatalog)}</select><small>改变此范围只筛选候选项，已选方案和保存版本保持。</small></label>`;}
function comparisonPlanOptions(side){
 const selected=S[side],rows=S.boot.records.filter(r=>S.compareCatalog==='all'||recordGroup(r)===S.compareCatalog),outside=!rows.some(x=>x.id===selected)&&(S.boot.records.find(r=>r.id===selected)||[S.comparison?.left,S.comparison?.right].find(r=>r?.id===selected));
 return (outside?`<optgroup label="当前已选（保留）">${options([[outside.id,outside.name]],selected)}</optgroup>`:'')+['workspace','sources','archived'].map(key=>{
  const group=rows.filter(r=>recordGroup(r)===key);return group.length?`<optgroup label="${libraryTitles[key]}">${options(group.map(r=>[r.id,r.name]),selected)}</optgroup>`:'';
 }).join('');
}
function sourceOptionLabel(x,multiple=false){
 const d=x.display;if(!d)return x.name;
 const accepted=(d.counts.passed||0)+(d.counts.reused||0);
 return `${d.status} · ${accepted}/${d.case_count} 项通过 · ${d.site_count} 地点 · ${periodLabel(d.period)} · ${esc(d.step_label||d.step_minutes+' min')}${d.created?' · '+readableTime(d.created):''}${multiple&&d.kind==='execution'?' · 批次 '+x.id.slice(-8):''}`;
}
function resultSourceCard(side,c){
 const r=c.record_details?.[side],selected=c[side].find(x=>x.id===S.comparisonSources[side]),d=selected?.display;
 const role=side==='left'?'基准侧':'研究侧';
 const counts=d?.counts;
 const pair=S.comparisonData;
 const site=pair?.comparison?.id===c.comparison.id && pair.left.id===S.comparisonSources.left && pair.right.id===S.comparisonSources.right &&
   pair.mode===S.comparisonSources.mode && pair.sites.length===1 && pair.sites[0].status==='paired'?pair.sites[0]:null;
 const heat=site?.[side+'_heating_kWh'],cool=site?.[side+'_cooling_kWh'];
 const demand=Number.isFinite(heat)&&Number.isFinite(cool)?`<p class="source-demand"><strong>${esc(site.city)} · 时段显热需求</strong><br>供暖 ${format(heat)} kWh　制冷 ${format(cool)} kWh</p>`:'';
 const frequency={monthly_period_v1:'逐月及时段汇总',timeseries_timestep_v1:'按求解步长',timeseries_hourly_v1:'逐小时',timeseries_daily_v1:'逐日',daily_sensible_reference_v1:'逐日参考'}[d?.output_contract];
 return `<section class="result-source-card"><span class="source-role">${role}</span><h3>${esc(r?.name||role+'方案')}</h3><p class="muted">${r?`${esc(planVersionLabel(r))} · ${esc(periodLabel(r.period))} · 方案求解步长 ${r.step_minutes} min · ${r.site_count} 地点`:'版本由此比较关系固定'}</p>
 ${r?versionNoteMarkup(r):''}<label class="field">${role}${selected?.id?.startsWith('observed_')?'结果来源':'计算批次'}${c[side].length===1?'（已自动匹配）':''}<select id="comparison-source-${side}">${options([['','请选择计算批次'],...c[side].map(x=>[x.id,sourceOptionLabel(x,c[side].length>1)])],S.comparisonSources[side])}</select></label>
 ${frequency?`<p class="muted">批次主输出 · ${frequency}${d.extra_probes?'，另有单独设置的测点':''}</p>`:''}${demand}
 ${d?`<div class="source-status"><strong>${esc(d.status)}</strong><span>通过 ${(counts.passed||0)+(counts.reused||0)} / ${d.case_count} 项${counts.review?' · 待复核 '+counts.review:''}${counts.pending?' · 待算 '+counts.pending:''}${counts.running?' · 运行 '+counts.running:''}${counts.failed?' · 失败 '+counts.failed:''}${counts.interrupted?' · 中断 '+counts.interrupted:''}${counts.cancelled?' · 取消 '+counts.cancelled:''}</span></div><div class="actions">${d.kind==='historical'?'<button data-view="results">查看原正式历史结果</button>':`<button data-source-batch="${esc(selected.id)}">单独查看此批结果</button>`}</div>`:c[side].length?'':'<p class="warning">该保存版本尚无可选批次。</p>'}</section>`;
}
function clearUnmatchedResultComparison(){
 const rel=S.resultComparison?.comparison,c=S.comparison;if(!rel||!c)return;
 if(['left','right'].some(side=>rel[side].id!==c[side].id||rel[side].revision!==c[side].revision)){
  resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;
 }
}
async function alignResultComparison(data){
 const c=data.comparison,previous={...S};
 try{
  S.left=c.left.id;S.right=c.right.id;S.compareVersions={left_revision:c.left.revision,right_revision:c.right.revision};
  S.planComparisonDraft={name:c.name,metric:c.metric};
  if(!S.comparison||['left','right'].some(side=>S.comparison[side].id!==c[side].id||S.comparison[side].revision!==c[side].revision))await loadComparison(c.id);
 }catch(error){Object.assign(S,previous);throw error;}
}
document.addEventListener('toggle',event=>{const key=event.target.dataset?.libraryGroup;if(key&&!S.search)S.libraryGroups[key]=event.target.open;},true);
document.addEventListener('change',event=>{if(event.target.id==='comparison-catalog'){capturePlanComparisonDraft();S.compareCatalog=event.target.value;render();}});
