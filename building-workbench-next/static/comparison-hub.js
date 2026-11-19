/* Keep navigation state separate from pinned configurations and result choices. */
S.comparePage='overview';S.comparisonLibraryPage=0;
function coverageStudyLinks(){
 const list=S.boot.coverage_comparisons||[];
 return list.length?'<section class="well"><h2>铺设范围对照</h2><div class="actions">'+list.map(x=>'<button data-coverage-compare="'+esc(x.id)+'">'+esc(x.name)+'</button>').join('')+'</div></section>':'';
}
function comparisonWorkspaceView(){
 const page=S.comparePage||'overview';
 if(page==='overview')return `<section class="section"><h1>对照总览</h1><p class="muted">两两比较固定双方保存版本；研究对比集在各自集内管理计算与结果。</p><div class="grid2"><article class="well"><h2>两两比较</h2><p>可比较不同方案，也可比较同一方案的不同版本。</p><button class="primary" data-comparison-page="config">选择版本，建立比较</button></article><article class="well"><h2>研究对比集</h2><p>按共同条件管理多个工况，查看组内结果。</p><button data-rs="open">打开研究对比集</button><button data-rs="new">新建对比集</button></article></div></section>`+coverageStudyLinks()+comparisonLibraryView();
 const tabs=`<section class="section comparison-page-tabs"><button data-comparison-page="overview">返回对照总览</button><div class="actions" aria-label="比较内容"><button data-comparison-page="config" aria-pressed="${page==='config'}">配置差异</button><button data-comparison-page="results" aria-pressed="${page==='results'}">结果与图表</button></div></section>`;
 if(page==='config'){
  const t=document.createElement('template');t.innerHTML=comparisonView();t.content.querySelectorAll('.rs-entry,.comparison-library').forEach(el=>el.remove());
  const title=t.content.querySelector('h1');if(title)title.textContent='选择版本与核对配置';
  return tabs+t.innerHTML;
 }
 const c=S.comparison,summary=c&&!S.resultComparison?`<section class="section"><h1>${esc(S.resultComparison?.comparison.name||'结果与图表')}</h1><div class="grid2">${['left','right'].map(side=>`<div><strong>${side==='left'?'基准':'研究'}：${esc(c[side].name)}</strong>${versionNoteMarkup(c[side])}</div>`).join('')}</div></section>`:'';
 return tabs+summary+(comparisonResultsView()||'<section class="section"><p>请先打开一条已保存的两两比较，再选择双方计算批次。</p><button data-comparison-page="config">返回配置差异</button><button data-comparison-page="overview">选择已保存比较</button></section>');
}
async function comparisonHubAction(button){
 if(button.dataset.coverageCompare){
  const origin=S.view;
  await openSavedComparison(button.dataset.coverageCompare,true);
  S.coverageOrigin=origin;
  const item=(S.boot.coverage_comparisons||[]).find(x=>x.id===button.dataset.coverageCompare);
  S.comparisonSources={left:item.left,right:item.right,mode:'controlled'};
  await comparisonResultAction({dataset:{action:'read-comparison-results'}});
  render();return true;
 }
 if(button.dataset.action==='return-coverage'){
  S.comparisonData=null;S.resultComparison=null;S.view=S.coverageOrigin||'compare';S.comparePage='overview';S.coverageOrigin=null;render();return true;
 }
 if(button.dataset.comparisonPage){
  capturePlanComparisonDraft();const page=button.dataset.comparisonPage;
  if(!['overview','config','results'].includes(page))return true;
  if(page==='config'&&!S.comparison)await loadComparison();
  if(page==='results'&&!S.resultComparison){const match=exactComparisonMatch();if(match)await openSavedComparison(match.id,true);}
  S.comparePage=page;S.view='compare';render();return true;
 }
 if(button.dataset.comparisonListPage!==undefined){S.comparisonLibraryPage=Math.max(0,Number(button.dataset.comparisonListPage)||0);document.getElementById('comparison-library-rows').innerHTML=comparisonLibraryRows();return true;}
 return false;
}
