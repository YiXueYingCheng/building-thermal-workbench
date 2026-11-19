/* A read-only result view; choosing sources cannot submit or resume computations. */
S.resultComparison=null; S.comparisonData=null; S.comparisonExport=null; S.comparisonSources={left:'',right:'',mode:'controlled'};
S.mapMetric='total'; S.comparisonTable='classes'; S.mapAssets=null; S.climateFilter='';
const metricNames={total:'总冷热需求',heating:'供暖需求',cooling:'制冷需求',temperature:'室温'};
function comparisonRequest(){return {id:S.resultComparison.comparison.id,left_source:S.comparisonSources.left,right_source:S.comparisonSources.right,mode:S.comparisonSources.mode};}
function comparisonClimateView(d){return d.metric!=='temperature'&&d.selected_sites>1&&d.classes.some(c=>c.valid_sites>0);}
function initializeComparisonView(d){
 resetComparisonDetails();S.mapMetric=d.metric;S.climateFilter='';S.comparisonTable=comparisonClimateView(d)?'classes':'sites';
 if(d.wall_coverage&&d.paired_sites===1)S.comparisonSelected=d.sites.find(s=>s.status==='paired').site_id;
 else if(d.selected_sites===1&&d.sites.length===1)S.comparisonSelected=d.sites[0].site_id;
}
function comparisonResultsView(){
 const c=S.resultComparison;if(!c)return '';
 const d=S.comparisonData,metric=S.mapMetric,unit=d?.normalized?'MJ_m2':'kWh',unitLabel=d?.normalized?'MJ/m²':'kWh';
 const choices=side=>options([['','请选择结果来源'],...c[side].map(x=>[x.id,x.name])],S.comparisonSources[side]);
 const exportLink=(name,label)=>`<a class="button" download="${esc(name)}" href="/api/comparison-exports/${esc(S.comparisonExport.id)}/${encodeURIComponent(name)}">${label}</a>`;
 if(!S.showFullCoverage&&d?.wall_coverage&&d.paired_sites===1&&d.left.kind==='observed'&&d.right.kind==='observed'){
  const site=d.sites.find(s=>s.status==='paired');
  return `<section class="section" id="comparison-results"><div class="row"><h2>${esc(c.comparison.name)}</h2><div class="actions"><button data-action="full-coverage-results">结果来源与完整对照</button><button data-action="return-coverage">${S.coverageOrigin==='research-sets'?'返回研究对比集':'返回对照总览'}</button></div></div><p>参考 · ${esc(d.records.left.name)} v${d.records.left.revision}<br>研究 · ${esc(d.records.right.name)} v${d.records.right.revision}</p><p class="muted">已核对独立实算 · ${d.paired_sites} / ${d.selected_sites} 个方案地点有配对结果</p>${sourceComparisonDetail(d,site.site_id)}</section>`;
 }
 return `<section class="section" id="comparison-results"><div class="row"><h2>${esc(c.comparison.name)} · 结果与图表</h2><button data-action="close-comparison-results">关闭结果</button></div>
 <p class="muted">下面两张卡片分别对应此比较关系固定的基准与研究方案。选择已有计算批次后读取配对结果；查看时不会启动计算。</p>
 <div class="grid2 result-source-cards">${resultSourceCard("left",c)}${resultSourceCard("right",c)}</div><p class="muted">方案 → 保存版本 → 计算批次 → 结果。只有绑定该侧保存版本的批次可选；批次状态来自队列，读取配对结果时核验结果文件。</p>
 ${!c.left.length||!c.right.length?'<p class="warning">至少一侧没有对应版本的计算结果。修改后的方案不会沿用旧版本结果。</p>':''}
 <div class="actions"><label>运行模式 <select id="comparison-operation">${options([['controlled','温控冷热需求'],['natural','自然室温']],S.comparisonSources.mode)}</select></label><button class="primary" data-action="read-comparison-results" ${!S.comparisonSources.left||!S.comparisonSources.right?'disabled':''}>读取配对结果</button></div>
 ${exportHistoryView('comparison',c.comparison.id)}
 ${d?`${d.pairing_summaries?`<p>严格配对 <strong>${d.pairing_summaries[0].paired_sites}</strong> 个地点 · 含已确认豁免 <strong>${d.pairing_summaries[1].paired_sites}</strong> 个地点。下方图表采用含豁免口径，导出提供两套汇总。</p>`:''}<div class="metrics"><span><strong>${d.paired_sites} / ${d.selected_sites}</strong>有效配对地点</span><span><strong>${d.metric==='temperature'?d.rooms.length:d.selected_sites===1?d.monthly.length:d.classes.filter(c=>c.valid_sites).length+' / '+d.classes.length}</strong>${d.metric==='temperature'?'配对房间':d.selected_sites===1?'有结果月份':'有数据气候类型'}</span><span><strong>${esc(d.step_label)}</strong>求解步长</span></div>
 <p>${d.annual?'全年':esc(d.period[0]+'月'+d.period[1]+'日 至 '+d.period[2]+'月'+d.period[3]+'日')} · ${esc(d.difference)}${d.metric!=='temperature'?(d.normalized?' · MJ/m²，温控面积 '+format(d.conditioned_area_m2,2)+' m²':' · 仅按 kWh 比较，尚无核实温控面积'):''}。</p>
 ${d.blocked.length?`<p class="warning">本次不能汇总：${esc(d.blocked.join('；'))}。双方结果仍保留在原批次。</p>`:''}
 <p class="muted">${esc(d.metric==='temperature'||comparisonClimateView(d)?d.note:'逐地点比较已配对结果；未分类地点仍可读取全年或所选时段及月度结果，未纳入气候类型汇总。')}</p>
 ${d.metric!=='temperature'?(d.selected_sites===1?`<div class="actions"><button data-comparison-site="${esc(d.sites[0].site_id)}">查看${d.annual?'年度':'时段'}与月度明细</button></div>`:`<div class="actions">${['total','heating','cooling'].map(m=>`<button data-map-metric="${m}" aria-pressed="${m===metric}">${metricNames[m]}降低</button>`).join('')}</div>
 ${comparisonClimateView(d)&&d.normalized?`<div class="comparison-map"><canvas id="comparison-map-canvas" width="1440" height="720" role="img" aria-label="气候类型代表结果地图；数值可在下方表格读取"></canvas></div>
 <p id="map-readout" aria-live="polite" class="muted">将指针移到地图可读气候类型；点击可筛选对应地点。灰色表示无配对数据，地图采用既有 0.5° 气候展示网格。</p>
 <div class="map-legend"><span>−${comparisonColorLimit(d)}</span><span class="map-gradient"></span><span>+${comparisonColorLimit(d)} MJ/m²</span><span>灰色：无数据</span></div>`:!d.normalized?'<p class="muted">该建筑尚未登记核实温控面积，当前保留 kWh 汇总，不生成面积归一化地图。</p>':'<p class="muted">本次没有可汇总的气候类型，按地点查看已有结果。</p>'}
 <div class="actions">${comparisonClimateView(d)?`<button data-comparison-table="classes" aria-pressed="${S.comparisonTable==='classes'}">气候类型汇总</button>`:''}<button data-comparison-table="sites" aria-pressed="${S.comparisonTable==='sites'}">地点与排除原因</button>${S.climateFilter?`<button data-action="clear-climate-filter">清除 ${esc(S.climateFilter)} 筛选</button>`:''}</div>
 ${comparisonFilters(d)}<div id="comparison-table-slot">${comparisonDataTable(d,metric,unit,unitLabel)}</div>`):
 `<div class="table-scroll"><table class="table"><thead><tr><th>地点 / 房间</th><th>参考均温 / °C</th><th>研究均温 / °C</th><th>均温差 / °C</th></tr></thead><tbody>${d.rooms.map(r=>`<tr><td><button data-comparison-site="${esc(r.site_id)}">${esc(r.city)}</button> / ${esc(r.zone)}<small>参考 ${r.left_step_minutes??'—'} min · 研究 ${r.right_step_minutes??'—'} min</small></td><td>${format(r.left_mean_C)}</td><td>${format(r.right_mean_C)}</td><td>${format(r.right_minus_left_mean_C)}</td></tr>`).join('')}</tbody></table></div><p class="muted">${d.sites.filter(r=>r.reason).map(r=>esc(r.city+'：'+r.reason)).join('；')}</p>`}
 <div id="comparison-detail-slot">${comparisonSiteDetail(d)}</div>
 <div class="actions"><button class="primary" data-action="export-comparison" ${d.blocked.length||!d.paired_sites?'disabled':''}>导出图表与 Origin 数据包</button>${S.comparisonExport?exportLink('comparison.zip','下载完整数据包')+exportLink('dataset.json','数据与来源')+['svg','pdf','png'].filter(ext=>S.comparisonExport.files['figure.'+ext]).map(ext=>exportLink('figure.'+ext,ext.toUpperCase())).join('')+exportLink('编辑说明.txt','编辑说明'):''}</div>
 <p class="muted">数据标识 ${esc(d.dataset_sha256.slice(0,16))}。导出固定本次快照，不修改计算结果。</p>`:''}</section>`;
}
async function comparisonResultAction(button){
 if(button.dataset.sourceBatch){await loadExecution();await loadBatchResults(button.dataset.sourceBatch,true);S.view="execution";return true;}
 if(comparisonDetailAction(button))return true;
 if(button.dataset.comparisonResults){
  resetComparisonDetails();S.showFullCoverage=false;S.coverageOrigin=null;
  const selected=await api('/api/comparisons/'+button.dataset.comparisonResults+'/sources');await alignResultComparison(selected);S.resultComparison=selected;S.comparisonData=null;S.comparisonExport=null;
  for(const side of ['left','right'])S.comparisonSources[side]=S.resultComparison[side].length===1?S.resultComparison[side][0].id:'';
  S.comparePage='results';S.comparisonSources.mode=S.resultComparison.comparison.metric==='temperature'?'natural':'controlled';S.climateFilter='';return true;
 }
 if(button.dataset.mapMetric){S.mapMetric=button.dataset.mapMetric;S.comparisonSelected=null;return true;}
 if(button.dataset.comparisonTable){S.comparisonTable=button.dataset.comparisonTable;S.comparisonSelected=null;return true;}
 if(button.dataset.climateFilter){selectComparisonClimate(button.dataset.climateFilter);return true;}
 switch(button.dataset.action){
  case 'full-coverage-results':S.showFullCoverage=true;return true;
  case 'close-comparison-results':S.showFullCoverage=false;resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;return true;
  case 'clear-climate-filter':S.climateFilter='';S.comparisonSelected=null;return true;
  case 'read-comparison-results':notice('正在校验双方结果与来源…');S.comparisonData=await api('/api/comparison-results',comparisonRequest());S.comparisonExport=null;initializeComparisonView(S.comparisonData);if(comparisonClimateView(S.comparisonData)&&S.comparisonData.normalized&&!S.mapAssets)S.mapAssets=await api('/api/comparison-map');notice('已读取配对结果。');return true;
  case 'export-comparison':notice('正在生成汇总表与论文图…');S.comparisonExport=await api('/api/comparison-export',{...comparisonRequest(),expected_dataset_sha256:S.comparisonData.dataset_sha256});if(S.comparisonExport.dataset_sha256!==S.comparisonData.dataset_sha256){S.comparisonData=await api('/api/comparison-results',comparisonRequest());notice('计算进度已有变化；导出固定了生成时的快照，请以包内数据为准。');}else notice('图表与数据包已生成，可下载并按说明编辑。');await refreshOpenExportHistory('comparison',S.resultComparison.comparison.id);return true;
 }return false;
}
document.addEventListener('change',event=>{
 const id=event.target.id,side=id==='comparison-source-left'?'left':id==='comparison-source-right'?'right':id==='comparison-operation'?'mode':null;
 if(side){resetComparisonDetails();S.comparisonSources[side]=event.target.value;S.comparisonData=null;S.comparisonExport=null;render();}
});
function comparisonColorLimit(d){const vals=d.classes.flatMap(c=>['heating','cooling','total'].map(m=>Math.abs(c[m+'_saved_MJ_m2_mean']||0)));return Math.max(1,Math.ceil(Math.max(1,...vals)/5)*5);}
function comparisonColor(value,limit){if(value===null||!Number.isFinite(value))return [209,213,219];const t=Math.min(1,Math.abs(value)/limit),to=value<0?[33,102,172]:[178,24,43];return [247,247,247].map((c,i)=>Math.round(c+(to[i]-c)*t));}
function drawComparisonMap(){
 const canvas=document.getElementById('comparison-map-canvas'),d=S.comparisonData,a=S.mapAssets;if(!canvas||!d||!a)return;
 const g=a.grid,pixels=Uint8Array.from(atob(g.data),c=>c.charCodeAt(0)),byId=new Map(d.classes.map(c=>[c.id,c])),limit=comparisonColorLimit(d);
 const off=document.createElement('canvas');off.width=g.width;off.height=g.height;const ctx=off.getContext('2d'),im=ctx.createImageData(g.width,g.height);
 for(let i=0;i<pixels.length;i++){const c=byId.get(pixels[i]),v=c?c[S.mapMetric+'_saved_MJ_m2_mean']:null,col=pixels[i]===0?[255,255,255]:comparisonColor(v,limit);im.data.set([...col,255],i*4);}ctx.putImageData(im,0,0);
 const c=canvas.getContext('2d');c.imageSmoothingEnabled=false;c.drawImage(off,0,0,canvas.width,canvas.height);c.strokeStyle='#68747d';c.lineWidth=.6;
 for(const poly of a.land.coordinates)for(const ring of poly){c.beginPath();ring.forEach(([lon,lat],i)=>{const x=(lon+180)/360*canvas.width,y=(90-lat)/180*canvas.height;if(i===0)c.moveTo(x,y);else c.lineTo(x,y);});c.stroke();}
 const hit=e=>{const r=canvas.getBoundingClientRect(),x=Math.floor((e.clientX-r.left)/r.width*g.width),y=Math.floor((e.clientY-r.top)/r.height*g.height);return x>=0&&x<g.width&&y>=0&&y<g.height?byId.get(pixels[y*g.width+x]):null;};
 canvas.onmousemove=e=>{const row=hit(e),el=document.getElementById('map-readout');el.textContent=row?`${row.climate} · ${row.name}：${format(row[S.mapMetric+'_saved_MJ_m2_mean'])} MJ/m²；有效地点 ${row.valid_sites} / ${row.selected_sites}${row.valid_sites?'':'（无配对数据）'}`:'无气候分类像元；小面积类型请查下方表格。';};
 canvas.onclick=e=>{const row=hit(e);if(row){selectComparisonClimate(row.climate);render();}};
}

const comparisonBeforeInputNotes=comparisonResultsView;comparisonResultsView=function(){const html=comparisonBeforeInputNotes(),notes=S.comparisonData?.research_input_notes;if(!html||!notes||(!S.showFullCoverage&&S.comparisonData?.wall_coverage&&S.comparisonData.left.kind==='observed'&&S.comparisonData.right.kind==='observed'))return html;const text=['left','right'].filter(side=>notes[side]).map(side=>'<div class="comparison-input-note"><p class="muted">'+(side==='left'?'参考版本':'研究版本')+'</p>'+researchInputNoteMarkup(notes[side],true)+'</div>').join('');return html.replace('</div>','</div>'+text);};
