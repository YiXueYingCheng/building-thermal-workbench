/* A read-only view of questions supported by the selected set revision. */
function candidateQuestion(data) {
 return readingQuestion(data.question,data.metric,data.periods[0]);
}

function candidateAnswerLine(data) {
 if(data.sites.length!==1)return esc(data.sites.length)+' 个地点有配对结果';
 const site=data.sites[0];
 if(!site.values)return esc(site.city)+' · '+site.rooms+' 间房的室温可逐间对照';
 const i={total:2,heating:0,cooling:1}[data.metric];
 return esc(site.city)+' · '+esc({total:'合计',heating:'供暖',cooling:'制冷'}[data.metric])+' '+demandTableChange(site.values[0][i],site.values[1][i])+' kWh';
}

function candidateDirection(sides,steps=[]) {
 const labels=sides.map((s,i)=>({name:s.name,ref:s.ref,step:steps[i],building_key:'pair'}));
 themeLabels(labels);
 return '<small class="candidate-direction">'+labels.map((v,i)=>'<span><b>'+(i?'研究':'参考')+'</b> '+esc(v.label)+'</span>').join('<i aria-hidden="true">→</i>')+'</small>';
}

function candidateSources(sides) {
 return '<dl class="candidate-sources">'+sides.map((s,i)=>'<div><dt>'+(i?'研究':'参考')+'</dt><dd><span data-verbatim>'+esc(s.name)+'</span> · '+esc(themeVersion(s.ref))+'<small>'+esc(s.note)+'</small></dd></div>').join('')+'</dl>';
}

function archiveCitation(data) {
 const title=data.export_name?esc(data.export_name)+' · v'+esc(data.export_revision):'计算型对比集';
 return '<p>'+title+' · 两侧均取自同一份已核验导出</p>'+
  '<a href="/api/research-set-exports/'+encodeURIComponent(data.export)+'/comparison.csv" download>下载来源数据 CSV</a>';
}

async function openArchivePair(trigger,id,revision,item,afterChange){
 const dialog=readingDialog(trigger,'核对归档结果'),body=dialog.querySelector('.rs-month-body');
 const d=item.data;
 const request={group:id,revision,left:d.sides[0].ref,right:d.sides[1].ref,metric:d.metric,
  comparison:item.relation,left_source:d.export,right_source:d.export};
 try{
  const checked=await api('/api/reading-collections',{...request,action:'preview-pair'});
  if(!dialog.open)return;
  if(JSON.stringify(checked.data.sites.map(s=>s.keys))!==JSON.stringify(d.sites.map(s=>s.keys)))throw Error('归档依据已变化，请返回候选重新核对。');
  body.innerHTML=candidateDirection(d.sides,d.steps)+archiveCitation(d)+pairAnswer(d)+'<button class="primary" data-keep>收录这组归档结果</button><p role="status"></p>';
  const keep=body.querySelector('[data-keep]');
  keep.onclick=async()=>{
   keep.disabled=true;
   try{
    await api('/api/reading-collections',{...request,action:'keep-pair',token:checked.token});
    if(dialog.open)dialog.close();
    afterChange();
   }catch(e){keep.disabled=false;body.querySelector('[role="status"]').textContent=e.message;}
  };
 }catch(e){body.textContent=e.message;}
}

function candidateFocus(item,index,scope) {
 const d=item.data,sites=scope?.length?d.sites.filter(s=>scope.includes(s.site)):d.sites;
 const row=sites[0],single=sites.length===1;
 if(!row)return '';
 let summary='';
 if(single&&row.values){
  const [before,after]=row.values;
  summary='<dl class="candidate-measures">'+['供暖','制冷','合计'].map((label,i)=>'<div><dt>'+label+'</dt><dd>'+demandTableChange(before[i],after[i])+'</dd></div>').join('')+'</dl>'+
   (before.some((v,i)=>v===0&&after[i]===0)?'<small>* 双方该项需求均为零。</small>':'');
 }else if(single)summary='<p>已配对 '+esc(row.rooms)+' 间房，可逐间比较室温。</p>';
 else summary=pairAnswer({...d,sites,excluded:[]});
 return '<section class="candidate-focus"><h3>已有结果能回答什么</h3><h4>'+esc(candidateQuestion(d))+'</h4>'+
  (single?'<p class="candidate-condition">'+esc(row.city)+' · '+esc(periodLabel(d.periods[0]))+' · '+esc([...new Set(d.steps)].join(' / '))+' min'+(row.values?' · 研究减参考 / kWh':'')+'</p>':'')+summary+
  '<p class="candidate-evidence-note">'+esc(d.question.basis)+'</p>'+
  '<details class="candidate-answer" data-answer-key="'+esc(JSON.stringify([d.sides.map(s=>s.ref),d.metric,d.condition]))+'"><summary>查看这组对照的版本与来源</summary>'+
  candidateSources(d.sides)+(d.export?archiveCitation(d):'')+'</details>'+
  (canReadCandidateMonths(item)?'<button type="button" data-candidate-month="'+index+'" data-month-scope="'+esc(JSON.stringify(sites.map(s=>s.site)))+'">查看月度差异</button>':'')+'</section>';
}

function candidatePriority(item,memberAction='',slot='priority') {
 const question=readingQuestion({text:item.question},item.metric,item.period);
 const gap=item.gap;
 const labels=item.sides.map((s,i)=>({name:s.name,ref:s.ref,step:item.steps[i],building_key:'pair'}));
 themeLabels(labels);
 const missing=gap?.side==='参考侧'?0:1;
 const cost=gap?'<div class="candidate-gap"><strong>缺 '+esc(gap.count)+' 个地点算例</strong><span>'+esc(labels[missing].label)+'</span><small>'+esc(gap.places.join('、')+' · '+periodLabel(item.period)+' · '+[...new Set(item.steps)].join(' / ')+' min')+'</small><p>可复用已核验的 '+esc(labels[1-missing].label)+'</p></div>':'';
 return '<section class="candidate-priority"><h3>'+(item.answer?'原追问已有答案':item.waiting?'追问进度':'最值得补哪一组')+'</h3><h4>'+esc(question)+'</h4>'+cost+
  (item.waiting?'<p>'+esc(item.waiting)+'</p>':'')+
  (item.answer?pairAnswer(item.answer)+(item.collected?'<p>已收录到本集</p>':candidateKeepButton(item)):
   '<p>'+esc(item.basis)+'</p><div class="candidate-gain"><strong>补完能多知道什么</strong><p>'+esc(item.gain)+'</p></div>')+
  (item.sides.length===2||item.design_target?'<div data-question-designs="'+slot+'" role="status">正在查找对应的已保存设计…</div>':'')+
  (item.draft?'<p>可从组内成员派生该工况。当前尚未找到相同输入的保存版本。</p>':
   '<details><summary>查看已有方案与结果覆盖</summary>'+candidateSources(item.sides)+'</details>')+
  memberAction+(item.relation&&!item.answer?'<button type="button" data-candidate-config>查看这组配置差异</button>':'')+'</section>';
}

function candidateKeepButton(item){
 return item.collection_token?'<button type="button" data-keep-answer="'+esc(item.collection_token)+'">收录这组结果</button>':'';
}

// Share pending work across windows. A completed read needs only a metadata check on reopen.
const candidateReads=new RecentViewReader(24),candidatePositions=new Map();
function recentCandidate(map,key,initial,limit){
 const entry=map.get(key)||initial;
 map.delete(key);map.set(key,entry);
 if(map.size>limit)map.delete(map.keys().next().value);
 return entry;
}
async function cachedCandidateRead(key,load,force=false){
 const view=await candidateReads.read(key,force,async token=>{
  if(token&&(await api('/api/reading-collections?candidate-receipt='+encodeURIComponent(token))).current)return {view_token:token};
  const summary=await load();
  return {summary,view_token:summary.read_receipt};
 });
 return view.summary;
}

function candidatePosition(body){
 const values=new Map(),counts=new Map();
 for(const el of body.querySelectorAll('details,select')){
  const section=el.closest('[data-answer-key],.candidate-priority,.candidate-pending');
  const prefix=section?.dataset.answerKey||section?.querySelector('h4')?.textContent||'';
  const label=el.matches('details')?el.querySelector(':scope > summary')?.textContent:el.hasAttribute('data-strategy-base')?'参考工况':'地点';
  const base=JSON.stringify([prefix,label]),n=counts.get(base)||0;
  counts.set(base,n+1);values.set(base+n,el);
 }
 return values;
}
function rememberCandidatePosition(body,state){
 state.fields=new Map(Array.from(candidatePosition(body),([k,el])=>[k,el.matches('select')?el.value:el.open]));
 if(body.offsetHeight)state.scroll=body.scrollTop;
}
function restoreCandidatePosition(body,state){
 for(const [key,el] of candidatePosition(body)){
  if(!state.fields?.has(key))continue;
  const value=state.fields.get(key);
  if(el.matches('details'))el.open=value;
  else if(Array.from(el.options).some(o=>o.value===value)){
   el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));
  }
 }
 body.scrollTop=state.scroll||0;
}

async function connectQuestionDesigns(body,item,slot){
 const host=body.querySelector('[data-question-designs="'+slot+'"]');
 if(!host||!item||item.sides.length!==2&&!item.design_target)return;
 try{
  const request={action:'question-designs',left:item.sides[0]?.ref||item.design_target.left,right:item.sides[1]?.ref,
   target_recipe:item.design_target?.recipe,target_rules:item.design_target?.rules,
   scope:item.scope,mode:item.mode,steps:item.steps,period:item.period,receipt:true};
  const value=await cachedCandidateRead(JSON.stringify(request),()=>api('/api/reading-collections',request));
  if(host.designResult===value)return;
  const {designs}=value;host.designResult=value;
  if(!host.isConnected)return;
  host.innerHTML=designs.map((d,i)=>{
   const budgetCount=Object.keys(d.budgets).length;
   return '<p>'+esc(d.name)+' · v'+esc(d.revision)+'</p><p><strong>'+d.ready+' / '+d.total+' 格已有核验结果</strong>'+
    (budgetCount?' · '+budgetCount+' 格已有方案及未提交预算':'')+'</p><button type="button" class="primary" data-design-index="'+i+'">继续已有设计</button>';
  }).join('');
  for(const button of host.querySelectorAll('[data-design-index]')){
   const d=designs[Number(button.dataset.designIndex)];
   button.onclick=()=>openComparisonDesign(button,{id:d.id,revision:d.revision,scope:Array.from({length:d.total},(_,i)=>i).join(','),
    cell:Number(Object.keys(d.targets||{})[0]??d.edge.find(i=>d.budgets[i])??d.edge[1]),question:d,matchRequest:request});
  }
 }catch(err){
  if(host.isConnected){host.designResult=null;host.innerHTML='<p>'+esc(err.message)+'</p><button type="button">重新查找设计</button>';
   host.querySelector('button').onclick=()=>connectQuestionDesigns(body,item,slot);}
 }
}

function thermalStrategySection(tables,lead){
 if(!tables?.length)return '';
 const content=(tables.length>1?'<label>查看范围<select data-strategy-scope></select></label>':'')+
  '<p data-strategy-context class="muted"></p><p data-strategy-finding></p>'+
  '<label>比较方式<select data-strategy-base></select></label><div data-strategy-table></div>'+
  '<details class="strategy-sources"><summary>查看这两行的版本与来源</summary><div data-strategy-sources></div></details>';
 return lead?'<section class="candidate-focus candidate-strategies strategy-lead" data-answer-key="thermal-strategies" data-lead="'+esc(lead.id)+'"><h3>已有结果能回答什么</h3><h4 data-strategy-title></h4>'+content+'</section>':
  '<details class="candidate-strategies" data-answer-key="thermal-strategies"><summary>比较三种热阻策略</summary><h4 data-strategy-title></h4>'+content+'</details>';
}

function thermalStrategyFinding(t){
 const [a,b,feedback]=t.members;
 const period=periodLabel(t.period)==='全年'?'全年':'该时段';
 const deltas=[a,b].map(m=>feedback.values.map((v,i)=>v-m.values[i]));
 const [x,y]=deltas.map(d=>d[2]);
 const direction=v=>v<0?'低于':v>0?'高于':'等于';
 const title='按反馈调节热阻的'+period+'显热需求'+(direction(x)===direction(y)?direction(x)+'两种固定态':
  direction(x)+a.label+'，'+direction(y)+b.label)+'。';
 const contributions=deltas.map(([heat,cool])=>{
  if(heat>0||cool>0||heat===cool)return '';
  return heat<cool?'供暖':'制冷';
 });
 let note='';
 if(contributions.every(Boolean))note=contributions[0]===contributions[1]?'与两种固定态相比，降幅都主要来自'+contributions[0]+'。':
  '相对'+a.label+'，降幅主要来自'+contributions[0]+'。相对'+b.label+'，降幅主要来自'+contributions[1]+'。';
 return {title,note};
}

function connectThermalStrategies(body,report){
 const section=body.querySelector('.candidate-strategies');
 if(!section)return;
 const tables=report.thermal_tables,place=section.querySelector('[data-strategy-scope]'),base=section.querySelector('[data-strategy-base]');
 const summary=t=>[t.city,periodLabel(t.period),t.step+' min',t.optics].join(' · ');
 if(place)place.replaceChildren(...tables.map(t=>new Option(summary(t)+' · '+t.material+' · '+t.members[2].name+' · '+themeVersion(t.members[2].ref),t.id)));
 if(place&&section.dataset.lead)place.value=section.dataset.lead;
 const selected=()=>tables.find(t=>t.id===place?.value)||tables[0];
 function draw(){
  const t=selected(),members=t.members,ref=members.findIndex(m=>themeKey(m.ref)===base.value);
  const pairs=ref<0?[[0,2],[1,2]]:members.flatMap((m,i)=>i===ref?[]:[[ref,i]]);
  let zero=false;
  const sources=[];
  const rows=pairs.map(([from,to])=>{
   const pair=t.pairs.find(p=>p.left===from&&p.right===to||p.left===to&&p.right===from),d=report.answers[pair.answer];
   const before=members[from],after=members[to],canRead=d.relation&&!d.data.export&&d.data.sites.some(s=>s.site===t.site&&s.monthly_sources);
   const label=ref<0?before.label:after.label;
   const ordered=pair.left===from?d.data.sides:[...d.data.sides].reverse();
   sources.push('<h5>'+esc(before.label+' → '+after.label)+'</h5>'+candidateSources(ordered.map(side=>({...side,note:[side.note,side.source].filter(Boolean).join(' · ')}))));
   const link=canRead?'<button type="button" class="strategy-month" data-strategy-month="'+pair.answer+'" data-reverse="'+(pair.left!==from)+'" aria-label="'+esc(before.label+'到'+after.label+'的月度差异')+'">月度差异</button>':'';
   const cells=before.values.map((v,i)=>{
    zero||=v===0&&after.values[i]===0;
    return '<td>'+demandTableChange(v,after.values[i])+'</td>';
   }).join('');
   return '<tr><th scope="row">'+esc(label)+link+'</th>'+cells+'</tr>';
  });
  section.querySelector('[data-strategy-sources]').innerHTML=sources.join('');
  section.querySelector('[data-strategy-table]').innerHTML='<table class="table"><caption>'+esc(ref<0?'启用反馈后的变化 / kWh':'相对'+members[ref].label+'的变化 / kWh')+'</caption><thead><tr><th scope="col">'+(ref<0?'原热阻策略':'研究工况')+'</th>'+
   ['供暖','制冷','合计'].map(m=>'<th scope="col">'+m+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table>'+(zero?'<small>* 双方该项需求均为零。</small>':'');
 }
 function update(){
  const t=selected(),old=base.value;
  base.replaceChildren(new Option('反馈相对两种固定态','both'),...t.members.map(m=>new Option('以'+m.label+'为参考',themeKey(m.ref))));
  if(Array.from(base.options).some(o=>o.value===old))base.value=old;
  section.querySelector('[data-strategy-context]').textContent=place?t.material:summary(t);
  const finding=thermalStrategyFinding(t);
  section.querySelector('[data-strategy-title]').textContent=finding.title;
  const explanation=section.querySelector('[data-strategy-finding]');
  explanation.textContent=finding.note;explanation.hidden=!finding.note;
  draw();
 }
 base.onchange=draw;
 if(place)place.onchange=update;
 section.onclick=event=>{
  const button=event.target.closest('[data-strategy-month]');
  if(button)openCandidateMonths(button,report.answers[Number(button.dataset.strategyMonth)],selected().site,{reverse:button.dataset.reverse==='true',onlySite:true});
 };
 update();
}

function candidatePanel(report) {
 const review=report.member_review;
 const active=s=>review?.members.some(p=>themeKey(p)===themeKey(s.ref));
 const action=(sides,key,label)=>review&&sides.length===2&&sides.every(active)?'<button type="button" data-member-pair="'+key+'">'+label+'</button>':'';
 const origin=item=>review&&item.origin==='已收录'&&!item.data.sides.every(active)?'已收录 · 含历史成员':item.origin;
 const cards=report.answers.map((item,i)=>{
  const d=item.data;
  return '<details class="candidate-answer" data-answer-key="'+esc(JSON.stringify([d.sides.map(s=>s.ref),d.metric,d.condition]))+'"><summary><span>'+esc(candidateQuestion(d))+'</span>'+candidateDirection(d.sides,d.steps)+'<small>'+candidateAnswerLine(d)+'</small></summary>'+
   '<div><p class="muted">'+esc(origin(item))+(d.export?' · 组版本导出':'')+' · '+esc([...new Set(d.steps)].join(' / '))+' min · '+esc(d.question.basis)+'</p>'+pairAnswer(d)+
   '<details><summary>版本与结果依据</summary>'+candidateSources(d.sides)+(d.export?archiveCitation(d):'')+'</details>'+
   (item.collection_token&&item.origin!=='已收录'?candidateKeepButton(item):item.origin==='成员配对 · 尚未收录'?action(d.sides,'answers:'+i,'核对并收录这组'):'')+
   (canReadCandidateMonths(item)?'<button type="button" data-candidate-month="'+i+'">查看月度差异</button>':'')+'</div></details>';
 });
 const followup=report.priority?.basis_answer!=null?report.priority:report.answered_followup;
 const current=item=>!review||item.data.sides.every(active);
 let featured=followup?.basis_answer;
 if(featured==null){
  featured=report.answers.findIndex(item=>current(item)&&item.data.question.kind!=='combined');
  if(featured<0)featured=report.answers.findIndex(current);
  if(featured<0&&report.answers.length)featured=0;
 }
 const focus=report.answers[featured],scope=followup?.gap?.sites||followup?.scope;
 const tables=report.thermal_tables||[];
 const matched=tables.find(t=>(!scope?.length||scope.includes(t.site))&&t.pairs.some(p=>p.answer===featured));
 const lead=matched||(followup?.basis_answer==null?tables[0]:null);
 const strategies=thermalStrategySection(tables,lead);
 const groups=new Map();
 // Keep the full evidence card accessible for confirmation, other locations and monthly reads.
 report.answers.forEach((item,i)=>{
  const title=item.origin==='关联的已核验对照'?'关联方案的对照':!current(item)?(item.origin==='已收录'?'历史成员的对照':'关联方案的对照'):
   item.data.question.kind==='combined'?'多项设置同时变化 · 整体效果':'组内工况的对照';
  if(!groups.has(title))groups.set(title,[]);
  groups.get(title).push(cards[i]);
 });
 const catalogue=['组内工况的对照','多项设置同时变化 · 整体效果','关联方案的对照','历史成员的对照'].filter(t=>groups.has(t)).map(t=>
  '<details class="candidate-catalogue"><summary>'+esc(t)+' <small>'+groups.get(t).length+' 组</small></summary>'+groups.get(t).join('')+'</details>').join('');
 const pending=report.pending.map((item,i)=>{
  const d=item.data,ambiguous=d.sides.some(s=>s.ambiguous);
  const reason=ambiguous?'有多个结果来源，需选择批次':d.excluded[0]?.reason||'需要核对结果来源';
  return '<details><summary>'+esc(candidateQuestion(d))+candidateDirection(d.sides,d.steps)+'<small>'+esc(reason)+'</small></summary>'+
   pairAnswer(d)+action(d.sides,'pending:'+i,ambiguous?'选择批次并核对':'查看这两项')+'</details>';
 }).join('');
 const choices=(review?.choices||[]).map((item,i)=>'<div>'+candidateDirection(item.sides)+'<p>这两个版本有多条已保存的同向对照，请选择要核对的一条。</p>'+action(item.sides,'choices:'+i,'选择已有对照')+'</div>').join('');
 const noPriority=report.pending.length||choices?'可先处理下方待配对项。':'当前证据还未指向一组有明确增量的补充工况。';
 const library=catalogue?'<section class="candidate-library"><h3>全部已有对照 <small>'+report.answers.length+' 组</small></h3>'+catalogue+'</section>':'';
 const context=review?(review.reference?'共同参考 · '+review.reference_name+' · '+themeVersion(review.reference):review.members.length+' 个成员'):(report.revision?'组版本 v'+report.revision:'按已收录对照的双方版本');
 return '<header class="candidate-group"><h3>'+esc(report.name)+'</h3><p>'+esc(context)+'</p>'+
  (review?.other_buildings?'<p>'+esc(review.other_buildings)+' 个成员来自另一栋建筑，可在各自建筑内配对。</p>':'')+'</header>'+
  '<div class="candidate-columns"><div class="candidate-left">'+(lead?strategies:focus?candidateFocus(focus,featured,scope):'<section class="candidate-focus"><h3>已有结果能回答什么</h3><p>当前范围内尚无通过核验的配对结果。</p></section>')+(lead?'':strategies)+library+'</div>'+
  '<div class="candidate-next">'+(report.answered_followup?candidatePriority(report.answered_followup,'','answered'):'')+(report.priority?candidatePriority(report.priority,action(report.priority.sides,'priority:0','核对这两项')):report.answered_followup?'':'<section class="candidate-empty"><h3>补充建议</h3><p>'+esc(report.notices.find(n=>n.includes('历史组版本'))||noPriority)+'</p></section>')+'</div></div>'+
  (pending||choices?'<details class="candidate-pending" '+(!report.answers.length?'open':'')+'><summary>待配对 · '+(report.pending.length+(review?.choices.length||0))+' 组</summary>'+pending+choices+'</details>':'')+
  report.notices.filter(n=>!n.includes('历史组版本')).map(n=>'<p class="warning">'+esc(n)+'</p>').join('');
}

function candidateMonthly(item) {
 const [a,b]=item.data.sides;
 return !item.data.export&&(S.boot.adjacent_comparisons||[]).find(e=>e.id===item.relation&&e.left===a.source&&e.right===b.source);
}

function canReadCandidateMonths(item){
 return Boolean(candidateMonthly(item)||item.relation&&!item.data.export&&item.data.mode==='controlled'&&item.data.sites.some(s=>s.monthly_sources));
}
function readingMonthsTable(months){
 const rows=months.map(({month,values:[left,right]})=>'<tr><th scope="row">'+esc(month)+' 月</th>'+
  left.map((value,k)=>'<td>'+demandTableChange(value,right[k])+'</td>').join('')+'</tr>').join('');
 const zero=months.some(({values:[left,right]})=>left.some((v,k)=>v===0&&right[k]===0));
 return '<div class="reading-month-table"><table class="table"><caption>研究工况减参考工况 · kWh</caption><thead><tr><th scope="col">月份</th><th scope="col">供暖</th><th scope="col">制冷</th><th scope="col">合计</th></tr></thead><tbody>'+rows+'</tbody></table>'+
  (zero?'<small>* 双方该项需求均为零。</small>':'')+'</div>';
}
async function openCandidateMonths(button,item,siteId=null,{reverse=false,onlySite=false}={}){
 const predefined=candidateMonthly(item);
 if(predefined&&!siteId&&!reverse)return openAdjacentStudy(button,predefined);
 const dialog=readingDialog(button,'查看月度差异'),body=dialog.querySelector('.rs-month-body'),data=item.data;
 try{
  const req={id:item.relation,left_source:data.sides[0].source,right_source:data.sides[1].source,mode:data.mode};
  const result=(await readComparisonView(req)).summary;
  if(!dialog.open)return;
  const eligible=data.sites.filter(s=>(!onlySite||s.site===siteId)&&s.monthly_sources&&result.sites.some(r=>r.site_id===s.site&&r.pairing_basis==='严格配对'&&r.left_evidence?.result_sha256===s.monthly_sources[0]&&r.right_evidence?.result_sha256===s.monthly_sources[1]));
  if(!eligible.length)throw Error('当前月度来源与已核对的结果不一致，请重新核对这组对照。');
  const sides=reverse?[...data.sides].reverse():data.sides,steps=reverse?[...data.steps].reverse():data.steps;
  body.innerHTML=candidateDirection(sides,steps)+(onlySite?'<p>'+esc(eligible[0].city)+'</p>':'<label class="field">地点<select data-place>'+options(eligible.map(s=>[s.site,s.city]),eligible.some(s=>s.site===siteId)?siteId:eligible[0].site)+'</select></label>')+'<div data-months></div>';
  const place=body.querySelector('[data-place]');
  function draw(){
   const months=result.monthly.filter(r=>r.site_id===(onlySite?siteId:place.value)).sort((a,b)=>a.month-b.month);
   body.querySelector('[data-months]').innerHTML=readingMonthsTable(months.map(row=>({month:row.month,
    values:(reverse?['right','left']:['left','right']).map(side=>['heating','cooling','total'].map(k=>row[side+'_'+k+'_kWh']))})));
  }
  if(place)place.onchange=draw;
  draw();
 }catch(err){if(dialog.open)body.textContent=err.message;}
}

async function showGroupCandidates(trigger) {
 const parent=trigger.closest('dialog,.collection-page');
 const dialog=readingDialog(trigger,'已有答案与方案候选');
 const body=dialog.querySelector('.rs-month-body');
 dialog.classList.add('group-candidates-dialog');
 const groupId=trigger.dataset.groupCandidates;
 let changed=false;
 dialog.addEventListener('close',()=>{
  if(changed&&parent?.isConnected&&trigger.closest('.reading-group-head'))showReadingGroup(parent,groupId);
 },{once:true});
 const params=new URLSearchParams({candidates:groupId});
 if(trigger.dataset.candidateContext)params.set('context',trigger.dataset.candidateContext);
 if(trigger.dataset.groupRevision)params.set('revision',trigger.dataset.groupRevision);
 const key=params.toString(),state=recentCandidate(candidatePositions,key,{},8);
 let shown=null,active=null,savedScroll=state.scroll||0;
 const remember=()=>{if(shown){rememberCandidatePosition(body,state);if(!body.offsetHeight)state.scroll=savedScroll;}};
 body.addEventListener('scroll',()=>{if(shown&&body.offsetHeight)savedScroll=state.scroll=body.scrollTop;});
 dialog.addEventListener('close',remember,{once:true});
 dialog.reopenQuestion=()=>{
  const target=trigger.isConnected?trigger:Array.from(document.querySelectorAll('[data-group-candidates]'))
   .find(b=>b.dataset.groupCandidates===groupId&&b.dataset.candidateContext===trigger.dataset.candidateContext&&b.dataset.groupRevision===trigger.dataset.groupRevision);
  if(target)showGroupCandidates(target);
 };
 const refresh=()=>{if(dialog.open&&!document.hidden&&dialog.matches(':modal')&&Array.from(document.querySelectorAll('dialog[open]')).at(-1)===dialog)void load();};
 const timer=setInterval(refresh,15000);
 window.addEventListener('focus',refresh);
 dialog.addEventListener('close',()=>{clearInterval(timer);window.removeEventListener('focus',refresh);},{once:true});
 const read=async()=>{
  if(!shown)body.textContent='正在核对所选版本与已有结果…';
  try {
   const report=await cachedCandidateRead(key,()=>api('/api/reading-collections?'+params+'&receipt=1'));
   if(!dialog.open)return;
   if(shown===report){
    await Promise.all([connectQuestionDesigns(body,report.priority,'priority'),connectQuestionDesigns(body,report.answered_followup,'answered')]);return;
   }
   remember();shown=report;
   body.innerHTML=candidatePanel(report);
   connectThermalStrategies(body,report);
   const designs=Promise.all([connectQuestionDesigns(body,report.priority,'priority'),connectQuestionDesigns(body,report.answered_followup,'answered')]);
   const offset=state.scroll||0;
   restoreCandidatePosition(body,state);
   const initial=body.scrollTop;
   designs.then(()=>{if(dialog.open&&shown===report&&body.scrollTop===initial)body.scrollTop=offset;});
   body.querySelectorAll('[data-keep-answer]').forEach(btn=>btn.onclick=()=>{
    const token=btn.dataset.keepAnswer;
    const item=report.answers.find(v=>v.collection_token===token);
    if(!item)return;
    const confirm=readingDialog(btn,'收录到「'+report.name+'」'),content=confirm.querySelector('.rs-month-body');
    content.innerHTML=candidateDirection(item.data.sides,item.data.steps)+pairAnswer(item.data)+
     '<p>收录将保存这次比较方向、双方版本和结果来源。</p><button type="button" class="primary" data-confirm-keep>确认收录</button><p role="status"></p>';
    const keep=content.querySelector('[data-confirm-keep]');
    keep.onclick=async()=>{
     keep.disabled=true;
     try{
      await api('/api/reading-collections',{action:'collect-answer',group:groupId,
       revision:params.has('revision')?Number(params.get('revision')):null,context:params.get('context'),token});
      changed=true;
      body.querySelectorAll('[data-keep-answer]').forEach(b=>{if(b.dataset.keepAnswer===token){b.disabled=true;b.textContent='已收录到本集';}});
      if(confirm.open)confirm.close();
     }catch(err){if(confirm.open){content.querySelector('[role="status"]').textContent=err.message;keep.disabled=false;}}
    };
   });
   body.querySelectorAll('[data-candidate-month]').forEach(btn=>btn.onclick=()=>{
    const item=report.answers[Number(btn.dataset.candidateMonth)];
    if(!btn.dataset.monthScope)return openCandidateMonths(btn,item);
    const scope=new Set(JSON.parse(btn.dataset.monthScope));
    return openCandidateMonths(btn,{...item,data:{...item.data,sites:item.data.sites.filter(s=>scope.has(s.site))}});
   });
   body.querySelectorAll('[data-member-pair]').forEach(btn=>btn.onclick=()=>{
    const [list,n]=btn.dataset.memberPair.split(':');
    const item=list==='priority'?report.priority:list==='choices'?report.member_review.choices[Number(n)]:report[list][Number(n)];
    const d=item.data||item;
    const afterChange=()=>{changed=true;if(dialog.open)return load();};
    if(d.export){openArchivePair(btn,groupId,report.member_review.revision,item,afterChange);return;}
    openTheme(btn,trigger.dataset.groupCandidates,{left:d.sides[0].ref,right:d.sides[1].ref,metric:d.metric,
     sources:d.sides.map(s=>s.source),relation:item.relation,revision:report.member_review.revision,afterChange});
   });
   const config=body.querySelector('[data-candidate-config]');
   if(config)config.onclick=async()=>{
    config.disabled=true;
    try{
     await openSavedComparison(report.priority.relation);
     dialog.close();
     if(parent?.open)parent.close();
     render();
    }catch(e){const note=document.createElement('p');note.setAttribute('role','alert');note.textContent=e.message;config.after(note);}
    finally{config.disabled=false;}
   };
  }catch(e){
   if(!dialog.open)return;
   remember();shown=null;body.innerHTML='<p role="alert">'+esc(e.message)+'</p><button type="button">重新核对</button>';
   body.querySelector('button').onclick=load;
  }
 };
 const load=()=>active||(active=read().finally(()=>{active=null;}));
 dialog.refreshQuestion=refresh;
 await load();
}

document.addEventListener('click',event=>{
 const trigger=event.target.closest('[data-group-candidates]');
 if(!trigger)return;
 event.stopImmediatePropagation();
 showGroupCandidates(trigger);
},true);
