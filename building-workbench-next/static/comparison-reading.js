/* Each response belongs to exactly one loaded pair of saved versions. */
const comparisonReadings = new WeakMap();
const readingMetrics = {total:'供暖、制冷和合计需求', heating:'供暖需求', cooling:'制冷需求', temperature:'室温表现'};

function demandChange(before, after) {
 const value = after - before;
 if (value === 0) return '持平';
 const amount = Math.abs(value) < 0.01 ? '不足 0.01' : format(Math.abs(value), 2);
 return (value > 0 ? '增加 ' : '减少 ') + amount;
}

function demandTableChange(before, after) {
 const delta = after - before;
 if (delta === 0) {
  const bothZero = before === 0 && after === 0;
  const note = bothZero ? '两侧需求均为零' : '两侧需求相等，差额为零';
  return `<span class="demand-delta flat" title="${note}">0${bothZero ? '<sup>*</sup>' : ''}</span>`;
 }
 const magnitude = Math.abs(delta);
 let amount = format(magnitude, 2);
 if (magnitude < 0.01) {
  amount = magnitude < 0.0001 ? magnitude.toExponential(1) : magnitude.toLocaleString('zh-CN', {maximumSignificantDigits: 2});
 }
 return `<span class="demand-delta ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '+' : '−'}${amount}</span>`;
}

function relatedResultCard(item, metric) {
 const [before, after] = item.values;
 const labels = ['供暖','制冷','合计'];
 const selected = {heating:0,cooling:1,total:2}[metric] ?? 2;
 const rows = labels.map((label,i) =>
  `<tr><th scope="row">${label}</th><td>${format(before[i],2)}</td><td>${format(after[i],2)}</td><td>${demandChange(before[i],after[i])}</td></tr>`).join('');
 const link = '/api/research-set-exports/' + encodeURIComponent(item.export_id) + '/comparison.csv';
 const adjacent = (S.boot.adjacent_comparisons||[]).find(entry=>entry.export_id===item.export_id && entry.site_id===item.site_id && entry.topic===item.topic);
 const step = `${esc(periodLabel(item.period))} · ${esc(item.step)} min`;
 const sides = ['参考','研究'].map((role,i)=>
  `<dt>${role}</dt><dd>${esc(item.names[i])}<small>${esc(item.acceptance[i])}</small></dd>`).join('');
 return `<details class="reading-result"><summary>
  <span class="reading-title">${esc(item.title)}</span>
  <span class="reading-change"><span>${labels[selected]}</span><strong>${demandChange(before[selected],after[selected])}</strong>${before[selected]===after[selected]?'':' <small>kWh</small>'}</span>
  </summary><div class="reading-evidence">
  <table class="table"><caption>显热需求 <span>kWh</span></caption><thead><tr><th scope="col">分项</th><th scope="col">参考</th><th scope="col">研究</th><th scope="col">研究侧变化</th></tr></thead><tbody>${rows}</tbody></table>
  <dl class="reading-sides" data-verbatim>${sides}</dl>
  <footer><span>${esc(item.group)} · v${esc(item.revision)}<br>${esc(item.city)} · ${step}</span><a href="${link}" download>下载来源数据 CSV</a></footer>
  ${adjacent?adjacentButton(adjacent,'查看全年与月度差异'):''}
  </div></details>`;
}

function readingMetric() {
 return S.comparePage==='results' ? S.resultComparison?.comparison.metric : currentComparisonDraft().metric;
}

function relatedReadingBody(result,c) {
 if(result.error)return '<p role="alert">'+esc(result.error)+' <button data-reading-retry>重试</button></p>';
 const items=result.items||[];
 let html=items.map(item=>relatedResultCard(item,readingMetric())).join('');
 const different=items.filter(i=>i.step!==c.right.numerics.step_minutes);
 if(different.length)html='<p class="reading-context">当前对照 '+esc(c.right.numerics.step_minutes)+' min。以下另列 '+esc([...new Set(different.map(i=>i.step))].join('、'))+' min 结果。</p>'+html;
 const candidates=[...(result.relations||[]),...(result.candidate?[result.candidate]:[])];
 for(const next of candidates){
  const link=next.relation?'<button data-open-comparison="'+esc(next.relation)+'">查看已有方案对照</button>':
   next.right?'<button data-plan-candidate="'+esc(JSON.stringify([next.left,next.right]))+'">核对已有方案</button>':'';
  const block='<div class="reading-candidate"><small>'+({result:'已有可读结果',saved:'已有保存方案',missing:'可补充的工况'}[next.state])+'</small><h4>'+esc(next.title.replace('{metric}',readingMetrics.total))+'</h4>'+
   (next.evidence?pairAnswer(next.evidence):'<p>'+esc(next.text)+'</p>')+link+'</div>';
  html=next.state==='result'?block+html:html+block;
 }
 if(result.issues)html+='<p>有导出包未通过来源核对。</p>';
 return html||'<p>在已核验的结果和已保存方案中，尚未找到匹配的后续对照。</p>';
}

function readingQuestion(question,metric,period) {
 const demand=metric==='total'?(JSON.stringify(period)==='[1,1,12,31]'?'全年显热需求':'所选时段的显热需求'):readingMetrics[metric];
 return question.text.replace('{metric}',demand);
}

function pairIdentity(c) {
 return JSON.stringify([c.left.id,c.left.revision,c.right.id,c.right.revision]);
}

let activeReading=null;
function currentReading(c){
 const key=pairIdentity(c);
 if(activeReading?.key!==key)activeReading={key,open:true,related:false,answers:new Map()};
 return activeReading;
}

function registryMatch(c) {
 for(const entry of S.boot.adjacent_comparisons||[]){
  const rel=S.boot.comparisons.find(r=>r.id===entry.id);
  if(!rel)continue;
  for(const reverse of [false,true]){
   if(['left','right'].every((side,i)=>{const ref=rel[(reverse?['right','left']:['left','right'])[i]];return ref.id===c[side].id && ref.revision===c[side].revision;}))
    return {entry,reverse};
  }
 }
 return null;
}

function answerRequest(c,metric) {
 const mapped=registryMatch(c);
 let chosen={};
 if(S.comparePage==='results'&&S.resultComparison&&sameComparisonPair(S.resultComparison.comparison))chosen=readingRequest(S.resultComparison.comparison.id);
 else if(mapped)chosen={left_source:mapped.entry[mapped.reverse?'right':'left'],right_source:mapped.entry[mapped.reverse?'left':'right']};
 const relation=(S.comparePage==='results' && S.resultComparison && sameComparisonPair(S.resultComparison.comparison))?S.resultComparison.comparison:S.boot.comparisons.find(r=>sameComparisonPair(r)&&r.metric===metric);
 return {left:c.left.id,left_revision:c.left.revision,right:c.right.id,right_revision:c.right.revision,comparison:relation?.id,metric,...chosen};
}

function readingAnswerView(state,req,c){
 const key=JSON.stringify(req);
 if(!state.answers.has(key)){
  state.answers.set(key,null);
  api('/api/compare/answer',req).then(data=>finish(data)).catch(error=>finish({error:error.message}));
 }
 function finish(value){
  state.answers.set(key,value);
  const el=document.querySelector('#pair-reading [data-answer-key]');
  if(activeReading===state && el?.dataset.answerKey===key)el.innerHTML=body(value);
 }
 function body(data){
  if(!data)return '正在核对所选版本的结果…';
  if(data.error)return '<p role="alert">'+esc(data.error)+'</p>';
  const mapped=registryMatch(c);
  const known=mapped&&data.sides.every((s,i)=>s.source===mapped.entry[(mapped.reverse?['right','left']:['left','right'])[i]]);
  const link=known&&data.sites.length&&req.metric!=='temperature'?adjacentButton(mapped.entry,'查看全年与月度差异',mapped.reverse):'';
  return pairAnswer(data)+link;
 }
 return '<div class="reading-answer" aria-live="polite" data-answer-key="'+esc(key)+'">'+body(state.answers.get(key))+'</div>';
}

function comparisonReadingView(c) {
 if(!c?.question)return '';
 const state=currentReading(c),metric=readingMetric()||'total';
 const q=readingQuestion(c.question,metric,c.left.factors.scope.period);
 const req=answerRequest(c,metric);
 const eligible=metric!=='temperature' && c.question.kind!=='same';
 const match=S.boot.comparisons.find(r=>sameComparisonPair(r)&&r.metric===metric);
 const related=eligible?'<details class="reading-related" id="reading-options" '+(state.related?'open':'')+'><summary>后续可看的结果与方案</summary><div id="related-reading-body">'+(comparisonReadings.get(c)&&!comparisonReadings.get(c).pending?relatedReadingBody(comparisonReadings.get(c),c):'展开后核对已有结果与保存版本。')+'</div></details>':'';
 if(state.open&&state.related&&eligible)queueMicrotask(()=>loadRelatedReadings(c));
 return '<details class="comparison-reading" id="pair-reading" '+(state.open?'open':'')+'><summary>这组对照可以回答什么</summary><header class="reading-lead"><p class="reading-question">'+esc(q)+'</p>'+readingAnswerView(state,req,c)+'<p class="reading-basis">'+esc(c.question.basis)+'</p></header>'+related+(match?'<footer class="reading-collect"><button data-collect-pair="'+esc(match.id)+'">加入对比集</button></footer>':'')+'</details>';
}

document.addEventListener('click',event=>{
 const summary=event.target.closest('#pair-reading > summary,#reading-options > summary');
 if(!summary||!activeReading)return;
 event.preventDefault();
 const details=summary.parentElement;
 details.open=!details.open;
 if(details.id==='pair-reading')activeReading.open=details.open;
 else {activeReading.related=details.open;if(details.open)loadRelatedReadings(S.comparison);}
},true);

document.addEventListener('toggle',event=>{
 const el=event.target;
 if(!el.isConnected||!activeReading)return;
 if(el.id==='pair-reading')activeReading.open=el.open;
 if(el.id==='reading-options'){
  activeReading.related=el.open;
  if(el.open&&S.comparison)loadRelatedReadings(S.comparison);
 }
},true);

function studyTitle(entry){
 return entry.topic==='orientation'?'固定蓬松时的季节光学切换':'同一光学切换日历下的热阻调节';
}

function savedReadingTitle(comparison) {
 const registered=(S.boot.adjacent_comparisons||[]).find(entry=>entry.id===comparison.id);
 return registered?studyTitle(registered):comparison.name;
}

function adjacentButton(entry,label,reverse=false) {
 return `<button type="button" data-adjacent-study="${esc(entry.id)}" data-reverse="${reverse}">${esc(label)}</button>`;
}

function adjacentStudyLinks() {
 const entries=S.boot.adjacent_comparisons||[];
 if (!entries.length) return '';
 return `<section class="section"><h2>北京 · 相邻工况已有结果</h2><div class="actions">${entries.map(e=>adjacentButton(e,studyTitle(e))).join('')}</div></section>`;
}

function demandDelta(row, key) {
 const before=row['left_'+key+'_kWh'], after=row['right_'+key+'_kWh'];
 if (!Number.isFinite(before) || !Number.isFinite(after)) throw Error('配对结果缺少完整的显热需求数值。');
 return after-before;
}

function annualDemandExplanation(heating,cooling,total) {
 if (heating===0 && cooling===0) return '供暖和制冷的全年需求均持平。';
 if (heating===0 || cooling===0) return heating===0?'全年变化来自制冷，供暖持平。':'全年变化来自供暖，制冷持平。';
 if (Math.sign(heating)!==Math.sign(cooling)) {
  const trend=heating<0?'供暖下降，制冷上升':'供暖上升，制冷下降';
  if (Math.abs(total)<0.01) return trend+(total===0?'，两项变化恰好抵消。':'，两项变化几乎完全抵消。');
  const offset=heating*total<0?'供暖':'制冷';
  return trend+'，'+offset+'变化抵消了部分'+(total<0?'降幅':'增幅')+'。';
 }
 const down=heating<0, trend=down?'供暖和制冷均下降':'供暖和制冷均上升';
 const share=Math.abs(cooling)/(Math.abs(heating)+Math.abs(cooling));
 if (Number((share*100).toFixed(1))===50) return trend+'，两项各占总变化量的约一半。';
 const larger=share>0.5?'制冷':'供暖', percent=100*Math.max(share,1-share);
 return trend+'，其中'+larger+'占总'+(down?'降幅':'增幅')+'的约 '+format(percent,1)+'%。';
}

function monthEvidenceLink(months,key,label,yearDelta) {
 // Rank in the annual direction, or by absolute change if the year balances at display precision.
 const direction=Math.abs(yearDelta)>=0.01?Math.sign(yearDelta):0;
 const differences=months.map(row=>demandDelta(row,key));
 const scores=differences.map(delta=>{
  const score=direction?direction*delta:Math.abs(delta);
  return score>=0.01?Number(score.toFixed(2)):0;
 });
 const peak=Math.max(...scores);
 if (peak===0) return '';
 const ties=months.filter((_,i)=>scores[i]===peak).map(row=>row.month);
 const range=direction>0?'增幅':direction<0?'降幅':'变幅';
 const text=ties[0]+' 月 · '+label+range+'最大';
 const tip=ties.length>1?'并列月份为 '+ties.join('、')+' 月，定位到 '+ties[0]+' 月':text;
 return `<button type="button" data-evidence-month="${ties[0]}" data-evidence-metric="${key}" title="${esc(tip)}">${esc(text)}${ties.length>1?'（并列）':''}</button>`;
}

function adjacentStudyTables(data,site) {
 const metrics=['heating','cooling','total'], labels=['供暖','制冷','合计'];
 const months=data.monthly.filter(r=>r.site_id===site.site_id).sort((a,b)=>a.month-b.month);
 if (!data.annual || months.length!==12 || months.some((r,i)=>r.month!==i+1)) throw Error('本组结果未覆盖完整的 12 个月。');
 const [heating,cooling,total]=metrics.map(key=>demandDelta(site,key));
 const monthLinks=monthEvidenceLink(months,'heating','供暖',heating)+monthEvidenceLink(months,'cooling','制冷',cooling);
 const reading=`<section class="adjacent-interpretation" aria-label="年度判读"><p><strong>全年合计${demandChange(site.left_total_kWh,site.right_total_kWh)}${total===0?'':' kWh'}</strong></p><p>${esc(annualDemandExplanation(heating,cooling,total))}</p>
  ${monthLinks?'<div class="adjacent-evidence-links" aria-label="查看对应月份">'+monthLinks+'</div>':''}</section>`;
 const annual=metrics.map((k,i)=>{
  const before=site['left_'+k+'_kWh'], after=site['right_'+k+'_kWh'];
  return `<tr><th scope="row">${labels[i]}</th><td>${format(before,2)}</td><td>${format(after,2)}</td><td><strong>${demandTableChange(before,after)}</strong></td></tr>`;
 }).join('');
 const monthly=months.map(m=>`<tr data-adjacent-month="${m.month}"><th scope="row">${m.month} 月</th>${metrics.map(k=>`<td data-metric="${k}" tabindex="-1">${demandTableChange(m['left_'+k+'_kWh'],m['right_'+k+'_kWh'])}</td>`).join('')}</tr>`).join('');
 const legend='<small class="demand-delta-key">+ 增加，− 减少，0 持平。0* 表示参考和研究需求均为零。</small>';
 return reading+`<table class="table adjacent-annual"><caption>全年显热需求 / kWh${legend}</caption><thead><tr><th>分项</th><th>参考</th><th>研究</th><th>变化</th></tr></thead><tbody>${annual}</tbody></table>
  <details class="adjacent-months"><summary>查看月度差异 · 12 个月</summary><table class="table"><caption>相对参考工况的变化 / kWh${legend}</caption><thead><tr><th>月份</th><th>供暖</th><th>制冷</th><th>合计</th></tr></thead><tbody>${monthly}</tbody></table><button type="button" data-back-annual>返回全年对照</button></details>`;
}

function adjacentStudyNeighbors(current, entries) {
 if (!current.site_id || !current.export_id) return [];
 const links=[];
 for (const other of entries) {
  if (other.id===current.id || other.site_id!==current.site_id || other.export_id!==current.export_id) continue;
  if (current.right && current.right===other.left) links.push({entry:other, forward:true});
  else if (current.left && current.left===other.right) links.push({entry:other, forward:false});
 }
 return links;
}

let offeredReadingCollection=false;
function openAdjacentStudy(trigger,entry) {
 const reverse=trigger.dataset.reverse==='true';
 const dialog=document.createElement('dialog');
 dialog.className='rs-month-dialog adjacent-study';
 dialog.setAttribute('aria-labelledby','adjacent-title');
 dialog.innerHTML=`<header class="viewer-head"><div><p class="muted">北京五层建筑 · 全年显热需求</p><h2 id="adjacent-title" tabindex="-1"></h2></div><button type="button" data-close-study autofocus>关闭</button></header><div class="rs-month-body"></div><footer class="adjacent-navigation" aria-label="关联对照" hidden></footer>`;
 const entries=S.boot.adjacent_comparisons||[];
 const panes=new Map();
 const heading=dialog.querySelector('h2');
 const nav=dialog.querySelector('.adjacent-navigation');
 let current;
 function showStudy(selected) {
  if (current) current.scrollTop=current.body.scrollTop;
  const previous=dialog.querySelector('.rs-month-body');
  let pane=panes.get(selected.id);
  if (!pane) {
   const body=document.createElement('div');
   body.className='rs-month-body';
   body.setAttribute('aria-live','polite');
   body.textContent='正在核对双方已保存的结果…';
   pane={body,scrollTop:0};
   panes.set(selected.id,pane);
   loadStudy(selected,body).catch(error=>{
    body.textContent=error.message;
    panes.delete(selected.id);
   });
  }
  previous.replaceWith(pane.body);
  heading.textContent=studyTitle(selected)+(reverse?' · 反向比较':'');
  nav.hidden=true;
  nav.replaceChildren();
  if(!reverse)loadNeighbors(selected,pane);
  async function loadNeighbors(selected,selectedPane){
   const possible=adjacentStudyNeighbors(selected,entries);
   const verified=await Promise.all(possible.map(async link=>{
    try {
     const read=async e=>(await readComparisonView({id:e.id,left_source:e.left,right_source:e.right,mode:'controlled'})).summary;
     const [a,b]=await Promise.all([read(selected),read(link.entry)]);
     const rows=[a,b].map(d=>d.sites.find(r=>r.site_id===selected.site_id&&r.pairing_basis==='严格配对'));
     const side=link.forward?['right','left']:['left','right'];
     return rows.every(Boolean)&&a.records[side[0]].sha256===b.records[side[1]].sha256&&a.step_minutes===b.step_minutes&&
      JSON.stringify(a.period)===JSON.stringify(b.period)&&a.mode===b.mode?link:null;
    }catch{return null;}
   }));
   if(current!==selectedPane||!dialog.open)return;
   const links=verified.filter(Boolean);
   nav.hidden=!links.length;
   const offer=links.length&&!offeredReadingCollection;
   if(offer)offeredReadingCollection=true;
   nav.innerHTML=links.map(({entry:neighbor,forward})=>
   `<button type="button" data-switch-study="${esc(neighbor.id)}"><small>${forward?'接着看 · 以本组研究工况为参考':'回看上一组 · 其研究工况是本组参考'}</small><span>${esc(studyTitle(neighbor))} ${forward?'→':'←'}</span></button>`).join('')+(offer?'<small>可在已保存的两两对照中选择“加入对比集”，将这两组结果一起阅读。</small>':'');
  }
  pane.body.scrollTop=pane.scrollTop;
  if (current) heading.focus({preventScroll:true});
  current=pane;
 }
 dialog.querySelector('[data-close-study]').onclick=()=>dialog.close();
 dialog.addEventListener('click',e=>{
  e.stopPropagation();
  const switchButton=e.target.closest('[data-switch-study]');
  if(switchButton){
   showStudy(entries.find(item=>item.id===switchButton.dataset.switchStudy));
   return;
  }
  const link=e.target.closest('[data-evidence-month]');
  if(link){
   const months=dialog.querySelector('.adjacent-months');
   const cell=months.querySelector(`[data-adjacent-month="${link.dataset.evidenceMonth}"] [data-metric="${link.dataset.evidenceMetric}"]`);
   months.open=true;
   cell.focus({preventScroll:true});
   cell.scrollIntoView({block:'center'});
  }
  if(e.target.closest('[data-back-annual]')){
   const months=dialog.querySelector('.adjacent-months');
   months.open=false;
   dialog.querySelector('.rs-month-body').scrollTop=0;
   months.querySelector('summary').focus({preventScroll:true});
  }
 });
 dialog.addEventListener('close',()=>{dialog.remove();if(trigger.isConnected)trigger.focus({preventScroll:true});},{once:true});
 document.body.append(dialog);
 showStudy(entry);
 dialog.showModal();
 async function loadStudy(selected,body) {
  const view=await readComparisonView({id:selected.id,left_source:selected.left,right_source:selected.right,mode:'controlled'});
  if (!dialog.open) return;
  const swap=row=>Object.fromEntries(Object.entries(row).map(([k,v])=>[k.startsWith('left_')?'right_'+k.slice(5):k.startsWith('right_')?'left_'+k.slice(6):k,v]));
  const original=view.summary;
  const d=reverse?{...original,records:{left:original.records.right,right:original.records.left},sites:original.sites.map(swap),monthly:original.monthly.map(swap)}:original;
  const site=d.sites.find(s=>s.site_id===selected.site_id);
  if (!site || site.status!=='paired' || site.pairing_basis!=='严格配对') throw Error(site?.reason||'双方结果未能严格配对。');
  const sides=['left','right'].map((side,i)=>`<dt>${i?'研究':'参考'}</dt><dd>${esc(d.records[side].name)} · v${esc(d.records[side].revision)}</dd>`).join('');
  const reviews=['left','right'].map((side,i)=>{const e=site[side+'_evidence'],review=e.scientific_review;return `<p><strong>${i?'研究':'参考'} · ${esc(review?.label||'核验通过')}</strong><br>${esc(review?.display_scope||review?.scope||'')}<br>批次 ${esc(e.batch_id)}</p>`;}).join('');
  body.innerHTML=`<p class="adjacent-scope">${esc(site.city)} · ${esc(periodLabel(d.period))} · ${esc(d.step_label)} · ${esc(site.pairing_basis)}</p><dl class="adjacent-sides">${sides}</dl>${adjacentStudyTables(d,site)}<details class="adjacent-source"><summary>结果来源与复核说明</summary><dl data-verbatim>${sides}</dl>${reviews}</details>`;
 }
}

async function loadRelatedReadings(c) {
 if (comparisonReadings.has(c) || S.comparison!==c || !document.getElementById('related-reading-body')) return;
 comparisonReadings.set(c,{pending:true});
 let result;
 try {
  result = await api('/api/compare/related-results',{comparison:S.boot.comparisons.find(r=>sameComparisonPair(r))?.id,left:c.left.id,left_revision:c.left.revision,right:c.right.id,right_revision:c.right.revision});
 } catch (error) { result={error:error.message}; }
 comparisonReadings.set(c,result);
 const el=document.getElementById('related-reading-body');
 if (el && S.comparison===c) el.innerHTML=relatedReadingBody(result,c);
}

document.addEventListener('change',event=>{
 if (event.target.id!=='comparison-metric') return;
 const el=document.getElementById('pair-reading');
 if (el && S.comparison) {currentReading(S.comparison).open=el.open;el.outerHTML=comparisonReadingView(S.comparison);}
});
