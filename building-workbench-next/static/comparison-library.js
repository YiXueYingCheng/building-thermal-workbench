/* Saved comparisons are immutable links to versions; filters and matches only affect display. */
S.comparisonSearch='';S.comparisonLibraryFilter='all';S.comparisonLibraryOpen=true;
const comparisonMetricLabels={total:'总冷热需求',heating:'供暖需求',cooling:'制冷需求',temperature:'室温表现'};
function currentComparisonDraft(){
 const c=S.comparison;
 return S.planComparisonDraft||{name:c?c.right.name+' 对照 '+c.left.name:'',metric:c&&(c.left.factors.condition.operation.mode==='natural'||c.right.factors.condition.operation.mode==='natural')?'temperature':'total'};
}
function sameComparisonPair(c){return S.comparison&&['left','right'].every(side=>c[side].id===S.comparison[side].id&&c[side].revision===S.comparison[side].revision);}
function matchingComparisons(){return S.boot.comparisons.filter(c=>sameComparisonPair(c)&&c.metric===currentComparisonDraft().metric);}
function exactComparisonMatch(){return matchingComparisons().filter(c=>c.name===currentComparisonDraft().name.trim()).sort((a,b)=>a.created.localeCompare(b.created)||a.id.localeCompare(b.id))[0];}
function comparisonMatchBody(){
 const rows=matchingComparisons();
 if(!rows.length)return '<p class="muted">当前双方版本和指标尚未保存比较关系。填写下方名称并保存后，即可选择已有批次查看结果。</p>';
 return `<p>这两个保存版本已有 ${rows.length} 个${esc(comparisonMetricLabels[currentComparisonDraft().metric])}比较，可直接查看已有结果。</p><div class="comparison-matches">${rows.map(c=>`<div class="row"><span>${esc(savedReadingTitle(c))}</span><button data-matched-results="${esc(c.id)}">选择批次并查看结果</button></div>`).join('')}</div><p class="muted">查看结果会沿用此比较的名称和指标；不需要再次保存。</p>`;
}
function comparisonMatchView(){return `<div class="well" id="comparison-match" aria-live="polite">${comparisonMatchBody()}</div>`;}
function updateComparisonMatch(){
 const el=document.getElementById('comparison-match');if(el)el.innerHTML=comparisonMatchBody();
 const button=document.querySelector('[data-action="save-comparison"]');if(button)button.textContent=exactComparisonMatch()?'复用已保存比较':'保存比较关系';
 const note=document.getElementById('comparison-save-note');if(note)note.textContent=exactComparisonMatch()?'名称、双方版本和指标完全相同，将打开原比较，不新增记录。':'保存后固定双方版本；改变比较名称、任一版本或指标将另存一条记录。';
}
function comparisonSummarySide(c,side){
 const d=c.display?.[side],ref=c[side];
 return `<div><span class="source-role">${side==='left'?'基准':'研究'}</span><p>${esc(d?.name||ref.id)}</p>${versionNoteMarkup(ref)}<small class="muted">${esc(planVersionLabel(ref))}${d&&!d.issue?' · '+esc(periodLabel(d.period))+' · '+d.step_minutes+' min · '+d.site_count+' 地点':''}</small>${d?.issue?'<p class="warning">此绑定版本暂未能读取；请核查原记录。</p>':''}</div>`;
}
function comparisonLibraryRows(){
 const query=S.comparisonSearch.trim().toLocaleLowerCase(),filter=S.comparisonLibraryFilter;
 const rows=S.boot.comparisons.filter(c=>{
  if(filter==='selected'&&!sameComparisonPair(c))return false;
  if(filter==='workspace'&&!['left','right'].every(s=>c.display?.[s]?.group==='workspace'))return false;
  if(filter==='sources'&&!['left','right'].some(s=>['sources','archived'].includes(c.display?.[s]?.group)))return false;
  return !query||opticalSearch([c.name,savedReadingTitle(c),comparisonMetricLabels[c.metric],c.display?.left?.name,c.display?.right?.name,versionNoteText(c.left),versionNoteText(c.right)],query);
 });
 const size=6,pages=Math.max(1,Math.ceil(rows.length/size));S.comparisonLibraryPage=Math.min(S.comparisonLibraryPage||0,pages-1);const start=S.comparisonLibraryPage*size,visible=rows.slice(start,start+size);
 return `<p class="muted">显示 ${rows.length} / ${S.boot.comparisons.length} 个比较。每条均固定自己的双方版本；批次在打开后选择。</p><div class="comparison-library-list">${visible.map(c=>`<article class="comparison-library-card" data-comparison-card="${esc(c.id)}"><div class="row"><h3>${esc(savedReadingTitle(c))}</h3><span class="tag">${esc(comparisonMetricLabels[c.metric])}</span></div><div class="grid2">${comparisonSummarySide(c,'left')}${comparisonSummarySide(c,'right')}</div><div class="row"><small class="muted">保存于 ${esc(readableTime(c.created))}</small><div class="actions"><button data-open-comparison="${esc(c.id)}">查看配置差异</button><button data-collect-pair="${esc(c.id)}">加入对比集</button>${relationButton({kind:"comparison",id:c.id,label:"删除比较"})}<button data-comparison-results="${esc(c.id)}">查看结果与地图</button></div></div></article>`).join('')||'<p class="empty">没有符合条件的比较。可清空搜索或选择“全部比较”。</p>'}</div>${pages>1?`<div class="actions"><button data-comparison-list-page="${S.comparisonLibraryPage-1}"${S.comparisonLibraryPage===0?' disabled':''}>上一页</button><span>第 ${S.comparisonLibraryPage+1} / ${pages} 页</span><button data-comparison-list-page="${S.comparisonLibraryPage+1}"${S.comparisonLibraryPage+1>=pages?' disabled':''}>下一页</button></div>`:''}`;
}
function comparisonLibraryView(){return `<section class="section comparison-library"><details id="comparison-library"${S.comparisonLibraryOpen?' open':''}><summary>已保存的两两比较 · ${S.boot.comparisons.length}</summary><div class="grid2"><label class="field">查找比较<input id="comparison-search" value="${esc(S.comparisonSearch)}" placeholder="比较名称、双方方案或指标"></label><label class="field">显示范围<select id="comparison-library-filter">${options([['all','全部比较'],['workspace','双方均为本工作区方案'],['sources','含原平台或归档来源'],['selected','当前双方保存版本']],S.comparisonLibraryFilter)}</select></label></div><div id="comparison-library-rows">${comparisonLibraryRows()}</div></details></section>`;}
async function openSavedComparison(id,results=false){
 const c=S.boot.comparisons.find(c=>c.id===id);if(!c)throw Error('没有找到该比较，请刷新比较列表。');
 const previous={...S,comparisonSources:{...S.comparisonSources}};
 try{
  if(results)await comparisonResultAction({dataset:{comparisonResults:id}});
  else{
   S.left=c.left.id;S.right=c.right.id;S.compareVersions={left_revision:c.left.revision,right_revision:c.right.revision};S.planComparisonDraft={name:c.name,metric:c.metric};
   await loadComparison(id);
   if(S.resultComparison?.comparison.id!==id){resetComparisonDetails();S.resultComparison=null;S.comparisonData=null;S.comparisonExport=null;}
  }
  S.view='compare';S.comparePage=results?'results':'config';
 }catch(error){Object.assign(S,previous);throw error;}
}
async function comparisonLibraryAction(button){
 if(button.dataset.openComparison||button.dataset.matchedResults||button.dataset.comparisonResults){await openSavedComparison(button.dataset.openComparison||button.dataset.matchedResults||button.dataset.comparisonResults,!!(button.dataset.matchedResults||button.dataset.comparisonResults));return true;}
 return false;
}
document.addEventListener('input',event=>{
 const id=event.target.id;
 if(id==='comparison-search'){S.comparisonSearch=event.target.value;S.comparisonLibraryPage=0;document.getElementById('comparison-library-rows').innerHTML=comparisonLibraryRows();}
 if(['comparison-name','comparison-metric'].includes(id)){capturePlanComparisonDraft();updateComparisonMatch();}
});
document.addEventListener('change',event=>{
 const id=event.target.id;
 if(id==='comparison-library-filter'){S.comparisonLibraryFilter=event.target.value;S.comparisonLibraryPage=0;document.getElementById('comparison-library-rows').innerHTML=comparisonLibraryRows();}
 if(id==='comparison-metric'){capturePlanComparisonDraft();updateComparisonMatch();}
});
document.addEventListener('toggle',event=>{if(event.target.id==='comparison-library')S.comparisonLibraryOpen=event.target.open;},true);
