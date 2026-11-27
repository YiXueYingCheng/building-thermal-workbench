/* Keep navigation state separate from pinned configurations and result choices. */
S.comparePage='overview';S.comparisonLibraryPage=0;
function coverageStudyLinks(){
 const list=S.boot.coverage_comparisons||[];
 return list.length?'<section class="well"><h2>铺设范围对照</h2><div class="actions">'+list.map(x=>'<button data-coverage-compare="'+esc(x.id)+'">'+esc(x.name)+'</button>').join('')+'</div></section>':'';
}
function regionalDailyShortcut(){
 const plans=S.boot.regional_daily_plans||[];
 if(!plans.length)return '';
 const label=p=>esc(p.name)+' · v'+esc(p.revision);
 const pin=p=>' data-plan-id="'+esc(p.id)+'" data-plan-version="'+esc(p.revision)+'"';
 const versions=plans.length===1?'<span>'+label(plans[0])+'</span>':
  '<select aria-label="地区组逐日参考方案">'+plans.map(p=>'<option'+pin(p)+'>'+label(p)+'</option>').join('')+'</select>';
 return '<div class="regional-daily-shortcut"><div><strong>地区组逐日参考</strong>'+versions+'</div><button type="button" data-open-regional-daily'+(plans.length===1?pin(plans[0]):'')+'>查看逐日核对</button></div>';
}
function comparisonWorkspaceView(){
 const page=S.comparePage||'overview';
 if(page==='overview')return `<section class="section"><div class="row"><h1>对照总览</h1><button data-relation-list>管理比较与对比集</button></div><div class="comparison-entry-list">
 <article><h2>两两比较</h2><p>看两个保存版本之间的差异。</p><button data-comparison-page="config">选择两个版本</button></article>
 <article><h2>设计对照</h2><p>从研究问题出发，确定要比较的工况。</p><button data-design-start>先设计对照</button></article>
 <article><h2>对比集</h2><p>把相关方案或已有对照收在一起。</p><div class="actions"><button data-reading-library="">我的对比集</button><button data-theme-build>建立对比集</button></div></article></div>${regionalDailyShortcut()}</section>`+
 comparisonLibraryView()+adjacentStudyLinks()+coverageStudyLinks();
 const back=S.collectionReturn?'<button data-return-collection>← 返回 '+esc(S.collectionReturn.name)+'</button>':'<button data-comparison-page="overview">返回对照总览</button>';
 const tabs=`<section class="section comparison-page-tabs">${back}<div class="actions" aria-label="比较内容"><button data-comparison-page="config" aria-pressed="${page==='config'}">配置差异</button><button data-comparison-page="results" aria-pressed="${page==='results'}">结果与图表</button></div></section>`;
 if(page==='config'){
  const t=document.createElement('template');t.innerHTML=comparisonView();t.content.querySelectorAll('.comparison-library').forEach(el=>el.remove());
  const title=t.content.querySelector('h1');if(title)title.textContent='选择版本与核对配置';
  const reading=comparisonReadingView(S.comparison);
  if(S.comparison)t.content.querySelector('.plan-version-picks')?.insertAdjacentHTML('afterend','<button type="button" data-reverse-pair>交换参考与研究</button>');
  if(S.boot.comparisons.some(sameComparisonPair))return tabs+reading+t.innerHTML;
  t.content.querySelector('.plan-version-picks')?.insertAdjacentHTML('afterend',reading);
  return tabs+t.innerHTML;
 }
 const c=S.comparison,summary=c&&!S.resultComparison?`<section class="section"><h1>${esc(S.resultComparison?.comparison.name||'结果与图表')}</h1><div class="grid2">${['left','right'].map(side=>`<div><strong>${side==='left'?'基准':'研究'}：${esc(c[side].name)}</strong>${versionNoteMarkup(c[side])}</div>`).join('')}</div></section>`:'';
 const reading=S.resultComparison?comparisonReadingView(c):'';
 const results=comparisonResultsView()||'<section class="section"><p>请先打开一条已保存的两两比较，再选择双方计算批次。</p><button data-comparison-page="config">返回配置差异</button><button data-comparison-page="overview">选择已保存比较</button></section>';
 return tabs+summary+(S.comparisonData?results+reading:reading+results);
}
async function comparisonHubAction(button){
 if(button.hasAttribute?.('data-open-regional-daily')){
  rsGuard();
  const pick=button.parentElement.querySelector('select')?.selectedOptions[0]||button;
  const p=S.boot.regional_daily_plans?.find(p=>p.id===pick.dataset.planId&&String(p.revision)===pick.dataset.planVersion);
  if(!p)throw Error('地区组方案已变化，请刷新页面。');
  button.disabled=true;
  try{
   if(!await loadRecord(p.id,p.revision,()=>button.isConnected&&S.view==='compare'))return true;
  }finally{button.disabled=false;}
  button.focus({preventScroll:true});
  await openDailyReference();
  return true;
 }
 if(button.hasAttribute?.('data-reverse-pair')){
  const pair=S.comparison;if(!pair)return true;
  const previous={left:S.left,right:S.right,compareVersions:S.compareVersions,planComparisonDraft:S.planComparisonDraft};
  const metric=readingMetric()||'total';
  try{
   S.left=pair.right.id;S.right=pair.left.id;
   S.compareVersions={left_revision:pair.right.revision,right_revision:pair.left.revision};
   S.planComparisonDraft={name:pair.left.name+' 对照 '+pair.right.name,metric};
   await loadComparison();render();
  }catch(e){Object.assign(S,previous);throw e;}
  return true;
 }
 const paired=(S.boot.adjacent_comparisons||[]).find(item=>item.id===(button.dataset.adjacentStudy||button.dataset.comparisonResults||button.dataset.matchedResults));
 if(paired){openAdjacentStudy(button,paired);return true;}
 if(button.hasAttribute?.('data-reading-retry')){comparisonReadings.delete(S.comparison);render();return true;}
 if(button.dataset.coverageCompare){
  const origin=S.view;
  await openSavedComparison(button.dataset.coverageCompare,true);
  S.coverageOrigin=origin;
  const item=(S.boot.coverage_comparisons||[]).find(x=>x.id===button.dataset.coverageCompare);
  S.comparisonSources={left:item.left,right:item.right,mode:'controlled'};
  const current=S.comparisonData;
  if(current?.comparison.id!==item.id||current.left.id!==item.left||current.right.id!==item.right||current.mode!=='controlled')
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
  if(page==='results'){
   if(!S.resultComparison){const match=exactComparisonMatch();if(match)await openSavedComparison(match.id,true);}
   else if(S.comparisonData)await showComparisonResults();
  }
  S.comparePage=page;S.view='compare';render();return true;
 }
 if(button.dataset.comparisonListPage!==undefined){S.comparisonLibraryPage=Math.max(0,Number(button.dataset.comparisonListPage)||0);document.getElementById('comparison-library-rows').innerHTML=comparisonLibraryRows();return true;}
 return false;
}
