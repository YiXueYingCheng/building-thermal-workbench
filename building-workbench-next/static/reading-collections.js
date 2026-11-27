/* Reading summaries refer to saved comparison inputs and evidence. */
function pairSideStatus(data) {
 return data.sides.map((s,i)=>(i?'研究侧':'参考侧')+' · '+s.note+(s.accepted.length?'（'+s.accepted.length+' 地点）':'')).join('；');
}

function changePercent(before,after) {
 if(before===0)return after===0?'双方均为 0':'参考值为 0，无法计算变化率';
 const change=(after-before)/before*100;
 if(change===0)return '0.00%';
 const sign=change>0?'+':'−',amount=Math.abs(change);
 return amount<0.01?(change>0?'增幅':'降幅')+' < 0.01%':sign+format(amount,2)+'%';
}

function pairedSiteAnswer(row,period) {
 const names=['供暖','制冷','合计'];
 if(row.rooms)return '<p>'+esc(row.city)+' · '+esc(period)+' · 已配对 '+row.rooms+' 个房间，可在结果页逐间查看室温。</p>';
 const [before,after]=row.values;
 return '<p class="muted">'+esc(row.city)+' · '+esc(period)+' · 研究减参考，变化率相对参考值</p>'+
  '<dl class="reading-deltas">'+names.map((label,i)=>'<div><dt>'+label+'</dt><dd>'+demandTableChange(before[i],after[i])+' <small>kWh</small></dd><dd class="reading-percent">'+esc(changePercent(before[i],after[i]))+'</dd></div>').join('')+'</dl>'+
  '<details class="reading-values"><summary>查看参考值与研究值</summary><table class="table"><caption>显热需求 / kWh</caption><thead><tr><th>指标</th><th>参考</th><th>研究</th></tr></thead><tbody>'+names.map((n,i)=>'<tr><th scope="row">'+n+'</th><td>'+format(before[i],2)+'</td><td>'+format(after[i],2)+'</td></tr>').join('')+'</tbody></table></details>';
}

function pairAnswer(data) {
 const excluded=data.excluded||[];
 const failures=excluded.length?'<details class="reading-gaps"><summary>'+excluded.length+' 个地点尚无配对答案</summary><ul>'+excluded.map(r=>'<li><strong>'+esc(r.city||S.boot.sites?.[r.site]?.name||r.site)+'</strong> · '+esc(r.reason)+'</li>').join('')+'</ul></details>':'';
 if(!data.sites.length)return '<p>'+esc(pairSideStatus(data))+'</p>'+failures;
 const sites=data.sites,period=periodLabel(data.periods[0]);
 if(sites.length===1)return pairedSiteAnswer(sites[0],period)+failures;
 const options=sites.map(({site,city,values,rooms})=>'<option value="'+esc(site)+'" data-values="'+esc(JSON.stringify({city,values,rooms}))+'">'+esc(city)+'</option>');
 return '<details class="reading-site-picker"><summary>'+sites.length+' 个地点可查看差异</summary><label class="field">查看地点<select data-reading-site data-period="'+esc(period)+'">'+options.join('')+'</select></label><div data-site-answer>'+pairedSiteAnswer(sites[0],period)+'</div></details>'+failures;
}

document.addEventListener('change',event=>{
 const el=event.target;
 if(!el.matches('[data-reading-site]'))return;
 const row=JSON.parse(el.selectedOptions[0].dataset.values);
 el.closest('.reading-site-picker').querySelector('[data-site-answer]').innerHTML=pairedSiteAnswer(row,el.dataset.period);
});

function linkedReadings(section) {
 const entries=new Map(section.map(row=>[row.id,row]));
 return section.filter(r=>r.metric!=='temperature').flatMap(a=>a.next.map(id=>[a,entries.get(id)]));
}

function readingChainTable(first,second,site) {
 const a=first.sites.find(r=>r.site===site),b=second.sites.find(r=>r.site===site);
 const [start,middle]=a.values,end=b.values[1];
 const zeroPairs=start.some((value,k)=>[value,middle[k],end[k]].filter(x=>x===0).length>=2);
 const row=(label,left,right,net)=>'<tr><th scope="row">'+label+'</th>'+left.map((value,k)=>'<td>'+demandTableChange(value,right[k])+(net?'<small>'+esc(changePercent(value,right[k]))+'</small>':'')+'</td>').join('')+'</tr>';
 return '<table class="table"><caption>'+esc(a.city)+' · 显热需求变化 / kWh</caption><thead><tr><th>比较方向</th><th>供暖</th><th>制冷</th><th>合计</th></tr></thead><tbody>'+
  row('① → ②',start,middle,false)+row('② → ③',middle,end,false)+row('① → ③',start,end,true)+'</tbody></table><small>末行变化率以工况 ① 为参考。'+(zeroPairs?'0* 表示该步两侧需求均为零。':'')+'</small>';
}

function showReadingChain(el,section) {
 const chains=linkedReadings(section);
 const label=r=>savedReadingTitle({id:r.comparison,name:r.name});
 el.innerHTML='<summary>两步合计变化</summary><p class="muted">按收录时核验的结果比较，两步共用同一份中间结果。</p>'+
  (chains.length>1?'<label class="field">选择连续对照<select data-chain-pick>'+chains.map(([a,b],i)=>'<option value="'+i+'">'+esc(label(a)+' → '+label(b))+'</option>').join('')+'</select></label>':'')+
  '<div data-chain-pane></div>';
 const pick=el.querySelector('[data-chain-pick]'),pane=el.querySelector('[data-chain-pane]');
 function draw(){
  const [a,b]=chains[Number(pick?.value||0)];
  pane.innerHTML='<ol class="chain-stages">'+[a.sides[0],a.sides[1],b.sides[1]].map(s=>'<li>'+esc(opticalText(s.name))+' · v'+esc(s.ref.revision)+'</li>').join('')+'</ol>'+
   (a.sites.length>1?'<label class="field">查看地点<select data-chain-site>'+a.sites.map(s=>'<option value="'+esc(s.site)+'">'+esc(s.city)+'</option>').join('')+'</select></label>':'')+'<div data-chain-values></div>';
  const site=pane.querySelector('[data-chain-site]'),table=pane.querySelector('[data-chain-values]');
  function drawSite(){table.innerHTML=readingChainTable(a,b,site?.value||a.sites[0].site);}
  if(site)site.onchange=drawSite;
  drawSite();
 }
 if(pick)pick.onchange=draw;
 draw();
}

function setReadingTitle(dialog,title) {
 dialog.setAttribute('aria-label',title);
 dialog.querySelector('.viewer-head h2, .collection-title').textContent=title;
}

function collectionFrame(title,back,actions='',content=''){
 return '<section class="section collection-page"><header class="collection-heading">'+back+'<div class="collection-heading-row"><h1 class="collection-title">'+esc(title)+'</h1><div class="actions collection-tools">'+actions+'</div></div></header><div class="collection-content">'+content+'</div></section>';
}
const collectionBack='<button class="collection-back" data-reading-library="">← 我的对比集</button>';
const renderBeforeCollections=render;
render=function(){
 if(S.collectionReturn && (S.view!=='compare'||S.comparePage==='overview'))S.collectionReturn=null;
 if(S.view!=='collection-home'){renderBeforeCollections();return;}
 renderNav();nav.querySelector('[data-view="compare"]')?.setAttribute('aria-pressed','true');
 if(!app.querySelector('.collection-page'))app.innerHTML=collectionFrame('我的对比集','');
 syncPageSections();
};
function collectionPage(origin,title,library=false){
 rsGuard();
 if(origin?.matches('dialog[open]'))origin.close();
 S.view='collection-home';
 const back=library?'<button class="collection-back" data-view="compare">← 对照总览</button>':collectionBack;
 const undo=app.querySelector('.collection-page')?.undoReadings;
 app.innerHTML=collectionFrame(title,back,library?'<button class="primary" data-theme-build>建立对比集</button>':'','<p role="status">正在读取…</p>');
 const page=app.querySelector('.collection-page');
 page.undoReadings=undo;
 render();window.scrollTo({top:0,behavior:'instant'});return page;
}

function readingDialog(trigger,title) {
 const dialog=document.createElement('dialog');
 dialog.className='rs-month-dialog reading-collection-dialog';
 dialog.innerHTML='<header class="viewer-head"><h2>'+esc(title)+'</h2><button type="button" data-close>关闭</button></header><div class="rs-month-body" aria-live="polite">正在读取…</div>';
 dialog.setAttribute('aria-label',title);
 document.body.append(dialog);
 dialog.querySelector('[data-close]').onclick=event=>{event.stopPropagation();dialog.close();};
 dialog.addEventListener('close',()=>{dialog.remove();if(trigger.isConnected)trigger.focus({preventScroll:true});});
 dialog.showModal();
 return dialog;
}

async function openSavedReadingMonths(button,group,row,site) {
 const dialog=readingDialog(button,'月度差异'),body=dialog.querySelector('.rs-month-body');
 dialog.querySelector('[data-close]').textContent='返回对照';
 try{
  group.monthReads??=new DialogReads(24);
  const key=JSON.stringify([row.id,site.site,site.keys]);
  const detail=await group.monthReads.read(key,()=>api('/api/reading-collections',{action:'read-months',group:group.id,entry:row.id,site:site.site}));
  if(!dialog.open)return;
  if(detail.site!==site.site||JSON.stringify(detail.keys)!==JSON.stringify(site.keys))throw Error('当前地点与打开页面时的结果依据不同，请重新打开对比集核对。');
  const refs=detail.evidence.map((ref,i)=>'<p>'+['参考','研究'][i]+' · '+esc(ref.batch_id||row.sides[i].source)+
   (ref.index!=null?' · 算例 '+(Number(ref.index)+1):'')+(ref.result_sha256?'<br><small>结果校验值 '+esc(ref.result_sha256)+'</small>':'')+'</p>').join('');
  body.innerHTML=candidateDirection(row.sides,row.steps)+'<p>'+esc(detail.city)+'</p>'+readingMonthsTable(detail.months)+
   '<details class="reading-month-source"><summary>月度来源</summary>'+(detail.export?'<p>按组导出保存的批次、模型和结果校验值找回了双方的月度明细。</p>':'')+refs+'</details>';
 }catch(e){if(dialog.open)body.textContent=e.message;}
}

function returnToReadingGroup() {
 const context=S.collectionReturn;
 if(!context)return;
 S.collectionReturn=null;
 S.view='collection-home';
 app.replaceChildren(context.page);
 render();window.scrollTo({top:context.scroll,behavior:'instant'});
 context.button.focus({preventScroll:true});
}

async function updateReadingCollection(body){
 const result=await api('/api/reading-collections',body);
 pdReads.entries.clear();
 return result;
}

function readingRequest(comparison) {
 if(S.resultComparison?.comparison.id!==comparison)return {};
 const s=S.comparisonSources;
 return {left_source:s.left,right_source:s.right,mode:s.mode};
}

async function collectPair(trigger,id,dialog=readingDialog(trigger,'加入对比集')) {
 setReadingTitle(dialog,'加入对比集');
 const body=dialog.querySelector('.rs-month-body');
 try {
  const groups=await api('/api/reading-collections?comparison='+encodeURIComponent(id));
  const rel=S.boot.comparisons.find(c=>c.id===id);
  body.innerHTML='<p>'+esc(rel?savedReadingTitle(rel):'已保存的对照')+'</p><label class="field">存入<select data-group>'+options([['','新建对比集'],...groups.map(g=>[g.id,g.name+' · 已收录 '+g.count+' 条对照'])],'')+'</select></label><label class="field" data-name>对比集名称<input maxlength="100" placeholder="例如，北京外墙光学与热阻策略"></label><p>按当前比较方向、指标、版本和结果来源收录。</p><p role="status"></p><button class="primary" data-save>确认加入</button>';
  const pick=body.querySelector('select'), field=body.querySelector('[data-name]'), save=body.querySelector('[data-save]');
  pick.onchange=()=>field.hidden=!!pick.value;
  save.onclick=async()=>{
   save.disabled=true;
   try{
    const reply=await updateReadingCollection({comparison:id,group:pick.value,name:field.querySelector('input').value,...readingRequest(id)});
    if(dialog.open)await showReadingGroup(dialog,reply.group,reply.reused?'已定位到原收录。':'已收录这条对照。',reply.entry);
   }catch(error){body.querySelector('[role="status"]').textContent=error.message;save.disabled=false;}
  };
 }catch(error){body.textContent=error.message;}
}

async function editReadingGroup(dialog,group) {
 setReadingTitle(dialog,'收录已有对照');
 const body=dialog.querySelector('.rs-month-body');
 const epoch=dialog.readEpoch=(dialog.readEpoch||0)+1;
 body.textContent='正在核对本建筑已保存的对照…';
 try{
  const data=await api('/api/reading-collections?options='+encodeURIComponent(group));
  if(!dialog.open||epoch!==dialog.readEpoch)return;
  const choices=data.options.map(r=>{
   const multiple=r.counts.some(n=>n>1);
   const missing=r.counts.map((n,k)=>n===0?['参考侧','研究侧'][k]:null).filter(Boolean);
   const status=r.enrolled?'已收录':multiple?'有多份来源，请从结果页选定后加入':missing.length?missing.join('、')+'暂无结果来源':'双方有结果来源，收录时核验';
   return '<label class="reading-choice"><input type="checkbox" value="'+esc(r.id)+'" '+(multiple||r.enrolled?'disabled':'')+'><span><strong>'+esc(savedReadingTitle(r))+'</strong><small>'+esc(comparisonMetricLabels[r.metric])+' · '+esc(status)+'</small><small>'+r.sides.map((s,k)=>(k?'研究':'参考')+' · '+esc(opticalText(s.name))+' v'+esc(s.revision)).join(' → ')+'</small></span></label>';
  }).join('');
  body.innerHTML='<h3>'+esc(data.name)+'</h3><p>勾选要收录的比较。缺少结果的比较可先收录。需要指定批次时，可从结果页选好来源后加入。</p><fieldset class="reading-picker"><legend>本建筑已保存的对照</legend>'+(choices||'<p>暂无已保存的两两对照。</p>')+'</fieldset><div class="reading-picker-actions"><span role="status"></span><button class="primary" data-bulk-save disabled>收录所选对照</button></div>';
  const field=body.querySelector('fieldset'),submit=body.querySelector('[data-bulk-save]'),status=body.querySelector('[role="status"]');
  const selected=()=>Array.from(field.querySelectorAll('input:checked'),x=>x.value);
  field.onchange=()=>{const count=selected().length;status.textContent='已选 '+count+' 条';submit.disabled=!count;};
  field.onchange();
  submit.onclick=async()=>{
   const values=selected();submit.disabled=true;field.disabled=true;
   status.textContent='正在核对并收录 '+values.length+' 条…';
   try{
    const report=await updateReadingCollection({action:'add-many',group,comparisons:values});
    if(dialog.open&&epoch===dialog.readEpoch)await showReadingGroup(dialog,group,'本次收录 '+report.added+' 条，已有 '+report.reused+' 条。',report.entries?.[0]);
   }catch(error){if(epoch===dialog.readEpoch){status.textContent=error.message;submit.disabled=false;field.disabled=false;}}
  };
 }catch(e){if(epoch===dialog.readEpoch)body.textContent=e.message;}
}

function renderGroupTable(el, group, section) {
 const members=new Map();
 for(const row of section){
  for(const side of row.sides)members.set(themeKey(side.ref),{...side,building_key:row.building_key});
 }
 themeLabels([...members.values()]);
 const rootKey=themeKey(section[0].sides[0].ref);
 const common=section.every(r=>themeKey(r.sides[0].ref)===rootKey);
 const commonSource=section.every(r=>r.sides[0].source===section[0].sides[0].source);
 const ordered=group.membership?.members||[];
 const order=[members.get(rootKey),...ordered.filter(p=>themeKey(p)!==rootKey).map(p=>members.get(themeKey(p))).filter(Boolean)];
 const chained=common&&commonSource&&order.length>=3&&order.length===members.size&&section.length===order.length-1&&
  section.every(r=>r.mode==='controlled'&&r.metric===section[0].metric)&&
  (!group.membership.reference||themeKey(group.membership.reference)===rootKey);
 const locations=new Map(section.flatMap(r=>[...r.sites,...r.excluded].map(s=>[s.site,s.city])));
 const citySelect=locations.size>1?'<label>地点 <select data-place>'+options([...locations],locations.keys().next().value)+'</select></label>':'';
 el.innerHTML='<div class="group-table-tools">'+citySelect+(chained?'<div class="actions"><button data-group-view="reference" aria-pressed="true">相对 '+esc(order[0].short)+'</button><button data-group-view="adjacent" aria-pressed="false">相邻工况</button></div>':'')+'</div><div data-values aria-live="polite"></div>';
 let mode='reference', generation=0, adjacent;
 function display(rows){
  const site=el.querySelector('[data-place]')?.value||locations.keys().next().value;
  const label=s=>esc(members.get(themeKey(s.ref))?.label||s.name);
  const shared=rows.length>1&&rows.every(r=>themeKey(r.sides[0].ref)===themeKey(rows[0].sides[0].ref));
  const temperature=rows.every(r=>r.metric==='temperature');
  const markup=rows.map((r,i)=>{
   const result=r.sites.find(s=>s.site===site);
   let reason=r.excluded.find(s=>s.site===site)?.reason||r.reason||'此地点尚无配对结果';
   if(!result&&reason==='缺少一侧结果或未在该侧范围内'){
    const gaps=r.sides.filter(s=>!s.accepted?.includes(site)).map(s=>{
     const label=members.get(themeKey(s.ref))?.label||s.name;
     const state=Array.isArray(s.scope_sites)&&!s.scope_sites.includes(site)?'此版本未选这个地点':s.ambiguous?'有多份结果，请选择批次':s.source?'此地点缺少已核验结果':s.note||'暂无结果来源';
     return label+' · '+state;
    });
    if(gaps.length)reason=gaps.join('；');
   }
   const cells=result?.values?result.values[0].map((v,k)=>'<td data-metric="'+['供暖','制冷','合计'][k]+'">'+demandTableChange(v,result.values[1][k])+'</td>').join(''):
    '<td colspan="'+(temperature?1:3)+'">'+esc(result?.rooms?'已配对 '+result.rooms+' 个房间的室温':reason)+'</td>';
   const item={data:r,relation:r.comparison};
   const savedRelation=r.id||S.boot.comparisons?.some(c=>c.id===r.comparison)||candidateMonthly(item);
   const fromCollection=r.id&&group.id&&r.mode==='controlled'&&r.metric!=='temperature'&&result?.values&&result.keys?.length===2&&r.sides.every(s=>s.source);
   const monthly=fromCollection||savedRelation&&result?.monthly_sources&&canReadCandidateMonths(item)?'<button '+(fromCollection?'data-saved-month':'data-month')+'="'+i+'">月度差异</button>':'';
   const names=(shared?'':'<span class="pair-from">'+label(r.sides[0])+'</span><span class="pair-arrow" aria-label="到"> → </span>')+'<span class="pair-to">'+label(r.sides[1])+'</span>';
   const title=r.id&&el.closest('.reading-section')?'<button class="reading-pair-name" data-entry-link="'+esc(r.id)+'" title="查看研究问题、配置与来源">'+names+'</button>':names;
   return '<tr><th scope="row">'+title+'</th>'+cells+'<td>'+monthly+'</td></tr>';
  }).join('');
  const caption=(shared?'共同参考 · '+label(rows[0].sides[0])+'　':'')+(temperature?'房间室温对照':'研究工况减参考工况 · kWh');
  el.querySelector('[data-values]').innerHTML='<div class="table-scroll"><table class="table group-comparison-table"><caption>'+caption+'</caption><thead><tr><th>'+(shared?'研究工况':'参考 → 研究工况')+'</th>'+(temperature?'<th>配对房间</th>':'<th>供暖</th><th>制冷</th><th>合计</th>')+'<th>明细</th></tr></thead><tbody>'+markup+'</tbody></table></div>';
  el.querySelectorAll('[data-month]').forEach(b=>b.onclick=()=>{const row=rows[Number(b.dataset.month)];openCandidateMonths(b,{data:row,relation:row.comparison},site);});
  el.querySelectorAll('[data-saved-month]').forEach(b=>b.onclick=e=>{e.stopPropagation();const row=rows[Number(b.dataset.savedMonth)];openSavedReadingMonths(b,group,row,row.sites.find(s=>s.site===site));});
 }
 async function draw(){
  const current=++generation;
  el.querySelectorAll('[data-group-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.groupView===mode)));
  if(mode==='reference'){display(section);return;}
  el.querySelector('[data-values]').textContent='正在核对相邻成员的结果…';
  adjacent??=Promise.all(order.slice(1).map(async(right,i)=>{
   const left=order[i], saved=section.find(r=>themeKey(r.sides[0].ref)===themeKey(left.ref)&&themeKey(r.sides[1].ref)===themeKey(right.ref));
   if(saved)return saved;
   try{
    const checked=await api('/api/reading-collections',{action:'preview-pair',group:group.id,revision:group.membership.revision,left:left.ref,right:right.ref,
     metric:section[0].metric,left_source:left.source,right_source:right.source});
    return checked.data;
   }catch(e){return {sides:[left,right],sites:[],excluded:[],reason:e.message};}
  }));
  const rows=await adjacent;
  if(current===generation&&el.isConnected)display(rows);
 }
 el.querySelectorAll('[data-group-view]').forEach(b=>b.onclick=()=>{mode=b.dataset.groupView;void draw();});
 const pick=el.querySelector('[data-place]');if(pick)pick.onchange=draw;
 display(section);
}

async function previewMemberTable(el,group,reference,others,existing=[]) {
 const members=group.membership?.members||[];
 if(members.length<2){el.textContent='选择要收录的对照，或添加两个成员版本。';return;}
 const sections=new Map(), problems=[];
 for(const row of existing){
  const key=JSON.stringify([row.building_key,row.condition,row.metric]);
  if(!sections.has(key))sections.set(key,[]);
  sections.get(key).push(row);
 }
 const name=ref=>((S.boot.records||[]).find(r=>r.id===ref.id)?.name||'方案')+' · '+themeVersion(ref);
 async function modeOf(ref){
  const summary=S.boot.records.find(r=>r.id===ref.id&&r.revision===ref.revision);
  if(summary?.mode)return summary.mode;
  const record=await api('/api/records/'+encodeURIComponent(ref.id)+'?revision='+encodeURIComponent(ref.revision));
  return record.factors.condition.operation.mode;
 }
 let referenceMode;
 for(const right of others){
  if(!el.isConnected)return;
  try{
   referenceMode??=await modeOf(reference);
   const metric=referenceMode==='natural'||await modeOf(right)==='natural'?'temperature':'total';
   const preview=await api('/api/reading-collections',{action:'preview-pair',group:group.id,revision:group.membership.revision,left:reference,right,metric});
   const row=preview.archive_candidate?{...preview.data,...preview.archive_candidate.data}:preview.data;
   const key=JSON.stringify([row.building_key,row.condition,row.metric]);
   if(!sections.has(key))sections.set(key,[]);
   sections.get(key).push(row);
  }catch(e){problems.push(name(reference)+' → '+name(right)+' · '+e.message);}
 }
 if(!el.isConnected)return;
 const lists=[...sections.values()];
 el.innerHTML=lists.map((rows,i)=>'<section><h3>'+esc([rows[0].building,rows[0].locations.length>2?rows[0].locations.length+' 个地点':rows[0].locations.join('、'),...new Set(rows[0].periods.map(periodLabel)),[...new Set(rows[0].steps)].join(' / ')+' min'].join(' · '))+'</h3><div data-preview-table="'+i+'"></div></section>').join('')+
  problems.map(p=>'<p>'+esc(p)+'</p>').join('');
 el.querySelectorAll('[data-preview-table]').forEach((pane,i)=>renderGroupTable(pane,group,lists[i]));
}

async function showReadingGroup(origin,id,message='',focusEntry=null,revision=null) {
 const previous=app.querySelector('.collection-page [data-set-revision]');
 if(!revision&&previous?.dataset.setId===id)revision=Number(previous.dataset.setRevision);
 const dialog=collectionPage(origin,'对比集');
 const body=dialog.querySelector('.collection-content');
 try {
  const epoch=dialog.readEpoch=(dialog.readEpoch||0)+1;
  const {group,sections}=await api('/api/reading-collections?group='+encodeURIComponent(id));
  if(!dialog.isConnected||epoch!==dialog.readEpoch)return;
  setReadingTitle(dialog,group.name);
  const rows=sections.flat();
  const pins=group.membership?.members||[],reference=group.membership?.reference||pins[0];
  const recorded=new Set(rows.flatMap(r=>r.sides.map(s=>themeKey(s.ref))));
  const pending=pins.filter(p=>themeKey(p)!==themeKey(reference)&&
   (group.membership.reference?!rows.some(r=>themeKey(r.sides[0].ref)===themeKey(reference)&&themeKey(r.sides[1].ref)===themeKey(p)):!recorded.has(themeKey(p))));
  dialog.undoReadings??=new Map();
  const undo=dialog.undoReadings;
  rows.forEach(r=>undo.delete(id+'/'+r.id));
  const card=row=>{
   const title=readingQuestion(row.question,row.metric,row.periods[0]);
   const metric=comparisonMetricLabels[row.metric];
   const resultButton=row.sites.length?'<button data-read-evidence="'+esc(row.id)+'">查看已收录结果</button>':'';
   const canChoose=group.membership&&row.sides.some(s=>s.ambiguous)&&row.sides.every(s=>group.membership.members.some(p=>themeKey(p)===themeKey(s.ref)));
   const resolve=canChoose?'<button data-resolve="'+esc(row.id)+'">选择批次并核对</button>':'';
   const update=row.excluded.length&&!canChoose?'<button data-refresh-entry="'+esc(row.id)+'">更新结果覆盖</button>':'';
   const refs=row.sides.map((s,i)=>'<p data-verbatim>'+['参考','研究'][i]+' · '+esc(s.name)+' · v'+esc(s.ref.revision)+'<br><small>'+esc(s.source||'尚无结果引用')+'</small></p>').join('');
   return '<article class="reading-entry" id="link-'+esc(row.id)+'" tabindex="-1"><h4>'+esc(title)+'</h4>'+candidateDirection(row.sides,row.steps)+'<small>'+esc(metric)+'</small>'+pairAnswer(row)+'<details><summary>版本与结果来源</summary><p data-verbatim>'+esc(row.name)+'</p>'+refs+'</details><div class="actions"><button data-read-config="'+esc(row.comparison)+'">查看配置差异</button>'+resultButton+resolve+update+row.next.map(next=>'<button class="reading-next" data-next="'+esc(next)+'" title="'+esc(sections.flat().find(r=>r.id===next).question.text.replace('{metric}',readingMetrics[row.metric]))+'">接着看下一组 →</button>').join('')+'<button class="reading-remove" data-remove="'+esc(row.id)+'">移出汇总</button></div></article>';
  };
  const undos=[...undo.values()].filter(u=>u.group===id);
  const usable=rows.filter(row=>row.sites.length).length;
  const summary=[pins.length?pins.length+' 个成员':'',rows.length?'已收录 '+rows.length+' 条对照':'',rows.length>usable?(rows.length-usable)+' 条待配对':''].filter(Boolean).join(' · ');
  const calculation=group.kind==='calculation',version=revision||group.revision;
  const savedScope=calculation&&version!==group.revision?'收录列表适用于整个对比集。切回成员工况结果将查看组 v'+version+'。':
   rows.length?'每条对照使用收录时的双方版本和结果。':'';
  dialog.querySelector('.collection-tools').innerHTML=calculation?rsCollectionTools(id,version):'<div class="reading-group-head actions"><button data-group-candidates="'+esc(id)+'" data-candidate-context="reading">已有答案与方案候选</button><details><summary>管理对比集</summary><div class="actions">'+(group.membership?'<button data-theme-members="'+esc(id)+'">管理成员与逐对核对</button>':'') +relationButton({kind:'reading',id,label:'解散对比集'})+'<button data-edit-group>收录已有对照</button></div></details></div>';
  body.innerHTML=(calculation?rsCollectionTabs(id,version,'saved')+'<div class="collection-results-head"><h2>已收录对照 · '+rows.length+' 条</h2><button data-edit-group>收录已有对照</button></div>'+(savedScope?'<p class="muted">'+esc(savedScope)+'</p>':''):'<p class="collection-meta">'+esc(summary)+'</p>')+
   (message?'<p role="status">'+esc(message)+'</p>':'')+
   undos.map(u=>'<div class="reading-undo"><span>已移出 '+esc(u.name)+'</span><button data-undo="'+esc(u.entry)+'">撤销移出</button></div>').join('')+
   (pending.length&&rows.length?'<div class="collection-views" role="group" aria-label="展示哪些对照"><button data-pair-list="saved" aria-pressed="true">已收录对照 · '+rows.length+'</button><button data-pair-list="reference" aria-pressed="false">按参考工况比较</button></div>':'')+
   '<div data-saved-pairs>'+sections.map((section,i)=>{
   const row=section[0],places=row.locations.length>2?row.locations.slice(0,2).join('、')+' 等 '+row.locations.length+' 地点':row.locations.join('、');
   const members=new Map(section.flatMap(r=>r.sides.map(s=>[themeKey(s.ref),{...s,building_key:row.building_key}])));
   themeLabels([...members.values()]);
   const picker=section.length>1?'<label class="field">查看哪条对照<select data-entry-pick>'+options(section.map(r=>[r.id,r.sides.map(s=>members.get(themeKey(s.ref)).label).join(' → ')]),row.id)+'</select></label>':'';
   return '<section class="reading-section"><h3>'+esc((row.building?row.building+' · ':'')+places)+' · '+esc([...new Set(row.periods.map(periodLabel))].join(' / '))+' · '+esc([...new Set(row.steps)].join(' / '))+' min</h3>'+'<div data-group-table="'+i+'"></div><details class="group-pair-details"><summary>研究问题、配置与来源</summary>'+picker+section.map(card).join('')+(section.some(r=>r.metric!=='temperature'&&r.next.length)?'<details class="reading-chain" data-chain-section="'+i+'"></details>':'')+'</details></section>';
  }).join('')+'</div>'+(pending.length?'<div data-member-preview '+(rows.length?'hidden':'')+' aria-live="polite">正在核对成员版本…</div>':!rows.length?(calculation?'<p>本组尚未手动收录两两对照。成员的年度和月度比较可在「成员工况结果」查看。</p>':'<p>尚未收录两两对照。</p>'):'');
  body.querySelectorAll('[data-group-table]').forEach(el=>renderGroupTable(el,group,sections[Number(el.dataset.groupTable)]));
  const pane=body.querySelector('[data-member-preview]');
  let previewStarted=false;
  function loadPreview(){
   if(previewStarted||!pane)return;
   previewStarted=true;
   const existing=rows.filter(r=>themeKey(r.sides[0].ref)===themeKey(reference)&&pins.some(p=>themeKey(p)===themeKey(r.sides[1].ref)));
   const covered=new Set(existing.map(r=>themeKey(r.sides[1].ref)));
   const others=pins.filter(p=>themeKey(p)!==themeKey(reference)&&!covered.has(themeKey(p)));
   void previewMemberTable(pane,group,reference,others,existing);
  }
  if(!rows.length)loadPreview();
  body.querySelectorAll('[data-pair-list]').forEach(b=>b.onclick=()=>{
   const saved=b.dataset.pairList==='saved';pane.hidden=saved;body.querySelector('[data-saved-pairs]').hidden=!saved;
   body.querySelectorAll('[data-pair-list]').forEach(tab=>tab.setAttribute('aria-pressed',String(tab===b)));
   if(!saved)loadPreview();
  });
  body.querySelectorAll('[data-resolve]').forEach(btn=>btn.onclick=()=>{
   const row=rows.find(r=>r.id===btn.dataset.resolve);
   openTheme(btn,id,{left:row.sides[0].ref,right:row.sides[1].ref,metric:row.metric,relation:row.comparison,sources:row.sides.map(s=>s.source)});
  });
  dialog.querySelector('[data-edit-group]').onclick=e=>editReadingGroup(readingDialog(e.currentTarget,'收录已有对照'),id);
  body.querySelectorAll('[data-chain-section]').forEach(el=>showReadingChain(el,sections[Number(el.dataset.chainSection)]));
  body.querySelectorAll('[data-refresh-entry]').forEach(btn=>btn.onclick=async()=>{
   btn.disabled=true;btn.textContent='正在核对…';
   try{
    const result=await updateReadingCollection({action:'refresh',group:id,entry:btn.dataset.refreshEntry});
    const current=rows.find(r=>r.id===btn.dataset.refreshEntry);
    if(S.comparison && current && ['left','right'].every((key,i)=>S.comparison[key].id===current.sides[i].ref.id&&S.comparison[key].revision===current.sides[i].ref.revision)){
     const state=currentReading(S.comparison);
     activeReading={...state,answers:new Map()};
     comparisonReadings.delete(S.comparison);
     const panel=document.getElementById('pair-reading');
     if(panel)panel.outerHTML=comparisonReadingView(S.comparison);
    }
    if(dialog.isConnected&&epoch===dialog.readEpoch)await showReadingGroup(dialog,id,'新增配对 '+result.added+' 个地点，现有 '+result.paired+' 个地点可读，待配对 '+result.missing+' 个。');
   }catch(e){btn.disabled=false;btn.textContent='更新结果覆盖';let note=btn.parentNode.querySelector('[role="alert"]');if(!note){note=document.createElement('span');note.setAttribute('role','alert');btn.after(note);}note.textContent=e.message;}
  });
  body.querySelectorAll('[data-remove],[data-undo]').forEach(btn=>btn.onclick=async()=>{
   btn.disabled=true;
   const entry=btn.dataset.remove||btn.dataset.undo;
   try{
    if(btn.dataset.remove){
     const reply=await updateReadingCollection({action:'remove',group:id,entry});
     const row=rows.find(r=>r.id===entry);
     undo.set(id+'/'+entry,{group:id,entry,token:reply.token,name:savedReadingTitle({id:row.comparison,name:row.name})});
    }else{
     await updateReadingCollection({action:'restore',group:id,entry,token:undo.get(id+'/'+entry).token});
     undo.delete(id+'/'+entry);
    }
    if(dialog.isConnected&&epoch===dialog.readEpoch)await showReadingGroup(dialog,id,btn.dataset.remove?'':'已恢复原收录。');
   }catch(e){btn.disabled=false;const note=document.createElement('span');note.setAttribute('role','alert');note.textContent=e.message;btn.after(note);}
  });
  body.querySelectorAll('[data-entry-pick]').forEach(pick=>{
   pick.onchange=()=>pick.closest('details').querySelectorAll('.reading-entry').forEach(entry=>entry.hidden=entry.id!=='link-'+pick.value);
   pick.onchange();
  });
  function locateEntry(id){
   const entry=body.querySelector('#link-'+CSS.escape(id));
   if(!entry)return;
   const details=entry.closest('.group-pair-details'),pick=details.querySelector('[data-entry-pick]');
   details.open=true;if(pick){pick.value=id;pick.onchange();}
   entry.focus({preventScroll:true});entry.scrollIntoView({block:'center'});
  }
  body.addEventListener('click',event=>{
   const btn=event.target.closest('[data-next],[data-entry-link]');if(btn)locateEntry(btn.dataset.entryLink||btn.dataset.next);
  });
  if(focusEntry)locateEntry(focusEntry);
  async function openReadingComparison(btn,row,results=false){
   const origin={page:dialog,button:btn,scroll:window.scrollY,name:group.name};
   await openSavedComparison(row.comparison,results);
   S.collectionReturn=origin;
   if(results){
    S.comparisonSources={left:row.sides[0].source,right:row.sides[1].source,mode:row.mode};
    await showComparisonResults();
   }
   render();app.querySelector('.comparison-page-tabs')?.scrollIntoView({block:'start'});
  }
  body.querySelectorAll('[data-read-evidence]').forEach(btn=>btn.onclick=async e=>{
   e.stopPropagation();
   const row=sections.flat().find(r=>r.id===btn.dataset.readEvidence);
   try{
    const [left,right]=row.sides;
    const verified=await api('/api/compare/answer',{left:left.ref.id,left_revision:left.ref.revision,right:right.ref.id,right_revision:right.ref.revision,
     comparison:row.comparison,metric:row.metric,mode:row.mode,left_source:left.source,right_source:right.source});
    if(JSON.stringify(verified.sites.map(r=>r.keys))!==JSON.stringify(row.sites.map(r=>r.keys)))throw Error('结果来源已发生变化，请回到比较结果页重新核对。');
    if(!dialog.isConnected)return;
    const entry=(S.boot.adjacent_comparisons||[]).find(e=>e.id===row.comparison&&e.left===left.source&&e.right===right.source);
    if(verified.export){
     const detail=readingDialog(btn,'已收录的归档结果');
     detail.querySelector('.rs-month-body').innerHTML=candidateDirection(verified.sides,verified.steps)+archiveCitation(verified)+pairAnswer(verified);
     return;
    }
    if(entry){openAdjacentStudy(btn,entry);return;}
    await openReadingComparison(btn,row,true);
   }catch(e){let msg=body.querySelector('[role="alert"]');if(!msg){msg=document.createElement('p');msg.setAttribute('role','alert');btn.after(msg);}msg.textContent=e.message;}
  });
  body.querySelectorAll('[data-read-config]').forEach(btn=>btn.onclick=async e=>{
   e.stopPropagation();const row=rows.find(r=>'link-'+r.id===btn.closest('.reading-entry').id);
   try{await openReadingComparison(btn,row);}catch(error){notice(error.message,'error');}
  });
 }catch(e){body.textContent=e.message;}
}

async function listReadingGroups(origin) {
 const page=collectionPage(origin,'我的对比集',true),body=page.querySelector('.collection-content');
 try{
  const rows=await api('/api/reading-collections');
  if(!page.isConnected)return;
  body.innerHTML=rows.length?'<div class="collection-library">'+rows.map(row=>'<button class="collection-library-row" data-group="'+esc(row.id)+'"><strong>'+esc(row.name)+'</strong><small>'+esc([row.kind==='calculation'?row.member_count+' 个成员 · 组版本 '+row.revision:'',row.count?row.count+' 条已收录对照':''].filter(Boolean).join(' · '))+'</small><span aria-hidden="true">→</span></button>').join('')+'</div>':'<p>可从「建立对比集」选择方案版本或已有对照。</p>';
  body.querySelectorAll('[data-group]').forEach((btn,i)=>btn.onclick=()=>{
   if(rows[i].kind==='calculation'){RS.manage=false;rsOpen(rows[i].id).catch(e=>notice(e.message,'error'));}
   else showReadingGroup(page,rows[i].id);
  });
 }catch(e){body.textContent=e.message;}
}

document.addEventListener('click',event=>{
 const button=event.target.closest('[data-collect-pair],[data-reading-library],[data-plan-candidate],[data-return-collection],[data-set-pane]');
 if(!button)return;
 event.stopImmediatePropagation();
 if(button.dataset.setPane){
  if(button.getAttribute('aria-pressed')==='true')return;
  const {setPane:pane,setId:id,setRevision}=button.dataset,revision=Number(setRevision);
  if(pane==='saved'){void showReadingGroup(button,id,'',null,revision).catch(e=>notice(e.message,'error'));return;}
  rsShowSetPane(id,revision,pane).catch(e=>notice(e.message,'error'));return;
 }
 if(button.hasAttribute('data-return-collection')){returnToReadingGroup();return;}
 if(button.hasAttribute('data-collect-pair')){collectPair(button,button.dataset.collectPair);return;}
 if(button.hasAttribute('data-plan-candidate')){
  const [left,right]=JSON.parse(button.dataset.planCandidate);
  S.left=left.id;S.right=right.id;S.compareVersions={left_revision:left.revision,right_revision:right.revision};
  S.resultComparison=null;S.comparisonData=null;S.planComparisonDraft=null;
  loadComparison().then(()=>{S.view='compare';S.comparePage='config';render();}).catch(e=>notice(e.message,'error'));return;
 }
 const origin=button.closest('dialog');
 const opening=button.dataset.readingLibrary?showReadingGroup(origin,button.dataset.readingLibrary):listReadingGroups(origin);
 opening.catch(e=>notice(e.message,'error'));
},true);
