/* In-page navigation only: no requests, draft changes, or persistent settings. */
const sectionNavigation=document.getElementById('section-navigation'),workspaceLayout=document.getElementById('workspace-layout');
const narrowSectionNavigation=matchMedia('(max-width:1000px)'),sectionOpenStates=new Map();
let sectionEntries=[],sectionFrame=0,sectionSignature='',sectionCurrent='',sectionMode='';
function sectionHash(text){let n=0;for(const c of text)n=(n*31+c.codePointAt(0))>>>0;return n.toString(36);}
function visibleSection(el){
 if(!el||!el.getClientRects().length||el.closest('dialog,.sidebar,#section-navigation,[hidden]'))return false;
 // A closed details can retain descendant geometry in Chromium; only its summary is visible.
 for(let parent=el.parentElement;parent&&parent!==app;parent=parent.parentElement){
  if(parent.tagName==='DETAILS'&&!parent.open&&!parent.querySelector(':scope>summary')?.contains(el))return false;
 }
 return true;
}
function collectPageSections(){
 const entries=new Map(),add=(el,label)=>{if(visibleSection(el))entries.set(el,label.trim());};
 // Material names identify the selection, not a new page section.
 app.querySelectorAll('h1,h2').forEach(el=>{if(!el.closest('#mc-detail'))add(el,el.textContent);});
 const extras=[
  ['.factor-nav','四因素配置'],['#mc-detail','材料详情'],['#execution-batches','批次与进度'],
  ['#calculation-budget','计算预算'],['#storage-budget','磁盘空间预算'],['#performance-history','运行实测'],['#disk-observations','磁盘采样'],
  ['#comparison-results .result-source-cards','选择配对批次'],['#comparison-results .comparison-map','气候结果地图'],
  ['#comparison-table-slot',S.comparisonTable==='classes'?'气候类型汇总':'地点与排除原因'],
  ['#comparison-site-detail','地点比较明细'],['#comparison-site-detail .comparison-review','来源与复核说明'],
  ['#batch-detail','算例明细'],['#input-detail','输入字段明细'],['#legacy-result-table','历史数值表'],
  ['#source-purpose','本页用途'],['#source-inputs','已生成的输入包'],
  ['#source-overview-rows','方案来源列表'],['#source-legacy-records','原平台迁移与输入']
 ];
 for(const [selector,label] of extras){
  const el=app.querySelector(selector);if(!el||[...entries.values()].includes(label))continue;
  const heading=el.querySelector(':scope>h1,:scope>h2,:scope>.row>h1,:scope>.row>h2');
  if(heading&&entries.has(heading))entries.set(heading,label);else add(el,label);
 }
 app.querySelectorAll('#comparison-site-detail>h4,#batch-detail>h3,#source-overview-rows>article h3').forEach(el=>add(el,el.textContent));
 for(const [selector,label] of [['[data-action="export-comparison"]','图表与数据导出'],['[data-action="export-batch"]','本批数据导出']])add(app.querySelector(selector)?.closest('.actions'),label);
 // A root heading already identifies its section; prefer the shorter, explicit entry.
 for(const [selector,label] of [['#comparison-results h2','配对结果'],['#execution-results h2','本批计算结果'],['#plan-activity h2','本版本的计算与结果']]){
  const el=app.querySelector(selector);if(entries.has(el))entries.set(el,label);
 }
 const counts=new Map();return [...entries].sort(([a],[b])=>a===b?0:a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1).map(([el,label])=>{
  const key=sectionHash(label),n=counts.get(key)||0;counts.set(key,n+1);
  if(!el.id)el.id=`page-${S.view}-${key}-${n}`;
  el.dataset.pageAnchor='';return {el,id:el.id,label};
 });
}
function measurePageNavigation(){
 const height=nav.getBoundingClientRect().height;
 document.documentElement.style.setProperty('--main-nav-height',height+'px');
 const second=narrowSectionNavigation.matches&&!sectionNavigation.hidden?sectionNavigation.querySelector('summary')?.getBoundingClientRect().height||0:0;
 document.documentElement.style.setProperty('--page-anchor-offset',(height+second+18)+'px');
}
function highlightPageSection(){
 const offset=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--page-anchor-offset'))||80;
 const shown=sectionEntries.filter(x=>x.el.isConnected&&x.el.getClientRects().length);
 let active=shown[0];for(const e of shown){if(e.el.getBoundingClientRect().top<=offset+24)active=e;else break;}
 if(scrollY>0&&scrollY+innerHeight>=document.documentElement.scrollHeight-2&&shown.at(-1)?.el.getBoundingClientRect().top<innerHeight)active=shown.at(-1);
 sectionCurrent=active?.id||'';
 sectionNavigation.querySelectorAll('[data-section-jump]').forEach(link=>{if(link.dataset.sectionJump===sectionCurrent)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});
}
function syncPageSections(){
 sectionFrame=0;if(!S.boot)return;
 const narrow=narrowSectionNavigation.matches,editor=S.view==='editor'&&!narrow;
 workspaceLayout.dataset.view=editor?'editor':S.view;workspaceLayout.classList.toggle('wide-section-nav',!narrow&&!editor);
 const host=editor?app.querySelector('.sidebar'):workspaceLayout;
 if(host&&sectionNavigation.parentElement!==host)host.prepend(sectionNavigation);
 sectionEntries=collectPageSections();sectionNavigation.hidden=!sectionEntries.length;
 const mode=S.view+':'+(narrow?'narrow':'wide'),signature=JSON.stringify([mode,sectionEntries.map(e=>[e.id,e.label])]);
 if(signature!==sectionSignature){
  const previous=sectionNavigation.querySelector('details');if(previous&&sectionMode)sectionOpenStates.set(sectionMode,previous.open);
  sectionMode=mode;sectionSignature=signature;
  const open=sectionOpenStates.get(mode)??(!narrow&&!editor);
  sectionNavigation.innerHTML=`<details class="section-nav-details"${open?' open':''}><summary>本页导航<span class="section-nav-count">${sectionEntries.length} 个区块</span></summary><nav aria-label="当前页面的功能区块"><div class="section-nav-links">${sectionEntries.map(e=>`<a href="#${esc(e.id)}" data-section-jump="${esc(e.id)}">${esc(e.label)}</a>`).join('')}</div><a class="section-nav-top" href="#navigation" data-section-top>回到页面顶部 ↑</a></nav></details>`;
  sectionNavigation.querySelector('details').addEventListener('toggle',event=>{sectionOpenStates.set(sectionMode,event.target.open);measurePageNavigation();});
 }
 measurePageNavigation();highlightPageSection();
}
function schedulePageSections(){if(!sectionFrame)sectionFrame=requestAnimationFrame(syncPageSections);}
const renderBeforePageNavigation=render;
render=function(){
 const rail=S.view==='editor'?app.querySelector('.sidebar .record-list'):null;
 const sidebar=rail?.closest('.sidebar');
 const saved=sidebar?{sidebar:sidebar.scrollTop,list:rail.scrollTop,page:window.scrollY,
  focused:sidebar.contains(document.activeElement)?document.activeElement.dataset.record:null}:null;
 renderBeforePageNavigation();
 syncPageSections();
 if(saved){
  const list=app.querySelector('.sidebar .record-list'),side=list?.closest('.sidebar');
  if(side){
   if(saved.focused)Array.from(list.querySelectorAll('[data-record]')).find(b=>b.dataset.record===saved.focused)?.focus({preventScroll:true});
   list.scrollTop=saved.list;side.scrollTop=saved.sidebar;
   if(window.scrollY!==saved.page)window.scrollTo({top:saved.page,behavior:'instant'});
  }
 }
};
const actionBeforePageNavigation=action;
action=async function(button){const previous=S.view;await actionBeforePageNavigation(button);if(button.dataset.view&&S.view!==previous){window.scrollTo({top:0,behavior:'instant'});syncPageSections();}};
document.addEventListener('click',event=>{
 const link=event.target.closest('a[data-section-jump],a[data-section-top]');if(!link)return;
 event.preventDefault();event.stopPropagation();if(S.busy)return;
 if(narrowSectionNavigation.matches)sectionNavigation.querySelector('details').open=false;
 measurePageNavigation();
 if(link.hasAttribute('data-section-top')){window.scrollTo({top:0,behavior:'instant'});nav.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});return;}
 const target=document.getElementById(link.dataset.sectionJump);if(!target)return;
 if(target.tagName==='DETAILS')target.open=true;
 for(let p=target.parentElement;p&&p!==app;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
 target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'start',behavior:'instant'});highlightPageSection();
},true);
let scrollSectionFrame=0;window.addEventListener('scroll',()=>{if(!scrollSectionFrame)scrollSectionFrame=requestAnimationFrame(()=>{scrollSectionFrame=0;highlightPageSection();});},{passive:true});
window.addEventListener('resize',schedulePageSections,{passive:true});narrowSectionNavigation.addEventListener('change',schedulePageSections);
new ResizeObserver(()=>{measurePageNavigation();highlightPageSection();}).observe(nav);
new MutationObserver(records=>{if(records.some(r=>!sectionNavigation.contains(r.target)&&[...r.addedNodes,...r.removedNodes].some(n=>n!==sectionNavigation)))schedulePageSections();}).observe(app,{childList:true,subtree:true});
app.addEventListener('toggle',event=>{if(event.target.tagName==='DETAILS'&&!sectionNavigation.contains(event.target))schedulePageSections();},true);
schedulePageSections();
