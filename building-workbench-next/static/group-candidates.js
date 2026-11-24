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

function candidatePriority(item,memberAction='') {
 const question=readingQuestion({text:item.question},item.metric,item.period);
 const gap=item.gap;
 const cost=gap?'<p class="candidate-gap"><strong>已有方案 · 缺 '+gap.count+' 个地点算例</strong><span>'+esc(gap.places.join('、')+' · '+(gap.side==='研究侧'?'参考结果已核验，缺研究侧结果':'研究结果已核验，缺参考侧结果'))+'</span></p>':'';
 return '<section class="candidate-priority"><h3>最值得补哪一组</h3><h4>'+esc(question)+'</h4>'+cost+
  '<p>'+esc(item.basis)+'</p><p><strong>补完能知道什么</strong><br>'+esc(item.gain)+'</p>'+
  (item.draft?'<p>可从组内成员派生该工况。当前尚未找到相同输入的保存版本。</p>':
   '<details><summary>查看已有方案与结果覆盖</summary>'+candidateSources(item.sides)+'</details>')+
  memberAction+(item.relation?'<button type="button" data-candidate-config>查看这组配置差异</button>':'')+'</section>';
}

function candidatePanel(report) {
 const review=report.member_review;
 const active=s=>review?.members.some(p=>themeKey(p)===themeKey(s.ref));
 const action=(sides,key,label)=>review&&sides.length===2&&sides.every(active)?'<button type="button" data-member-pair="'+key+'">'+label+'</button>':'';
 const origin=item=>review&&item.origin==='已收录'&&!item.data.sides.every(active)?'已收录 · 含历史成员':item.origin;
 const cards=report.answers.map((item,i)=>{
  const d=item.data;
  return '<details class="candidate-answer"><summary><span>'+esc(candidateQuestion(d))+'</span>'+candidateDirection(d.sides,d.steps)+'<small>'+candidateAnswerLine(d)+'</small></summary>'+
   '<div><p class="muted">'+esc(origin(item))+(d.export?' · 组版本导出':'')+' · '+esc([...new Set(d.steps)].join(' / '))+' min · '+esc(d.question.basis)+'</p>'+pairAnswer(d)+
   '<details><summary>版本与结果依据</summary>'+candidateSources(d.sides)+(d.export?archiveCitation(d):'')+'</details>'+
   (item.origin==='成员配对 · 尚未收录'?action(d.sides,'answers:'+i,'核对并收录这组'):'')+
   (canReadCandidateMonths(item)?'<button type="button" data-candidate-month="'+i+'">查看月度差异</button>':'')+'</div></details>';
 });
 const sections=new Map();
 const common=review?.reference&&themeKey(review.reference);
 const hasOther=common&&report.answers.some(item=>item.data.sides.every(active)&&themeKey(item.data.sides[0].ref)!==common);
 report.answers.forEach((item,i)=>{
  const internal=hasOther?(themeKey(item.data.sides[0].ref)===common?'相对共同参考':'成员间的其他对照'):'';
  const title=!review||item.data.sides.every(active)?internal:item.origin==='已收录'?'已收录的历史成员对照':
   item.origin==='关联的已核验对照'?'共用已核验结果，还可以接着看':'其他匹配到的已有方案';
  if(!sections.has(title))sections.set(title,[]);
  sections.get(title).push(cards[i]);
 });
 const order=['','相对共同参考','成员间的其他对照','共用已核验结果，还可以接着看','其他匹配到的已有方案','已收录的历史成员对照'];
 const answers=order.filter(title=>sections.has(title)).map(title=>
  (title?'<h4 class="candidate-related">'+esc(title)+'</h4>':'')+sections.get(title).join('')).join('');
 const pending=report.pending.map((item,i)=>{
  const d=item.data,ambiguous=d.sides.some(s=>s.ambiguous);
  const reason=ambiguous?'有多个结果来源，需选择批次':d.excluded[0]?.reason||'需要核对结果来源';
  return '<details><summary>'+esc(candidateQuestion(d))+candidateDirection(d.sides,d.steps)+'<small>'+esc(reason)+'</small></summary>'+
   pairAnswer(d)+action(d.sides,'pending:'+i,ambiguous?'选择批次并核对':'查看这两项')+'</details>';
 }).join('');
 const choices=(review?.choices||[]).map((item,i)=>'<div>'+candidateDirection(item.sides)+'<p>这两个版本有多条已保存的同向对照，请选择要核对的一条。</p>'+action(item.sides,'choices:'+i,'选择已有对照')+'</div>').join('');
 const noPriority=report.pending.length||choices?'可先处理下方待配对项。':'当前证据还未指向一组有明确增量的补充工况。';
 const context=review?(review.reference?'共同参考 · '+review.reference_name+' · '+themeVersion(review.reference):review.members.length===2?'按成员顺序核对这两项':'按成员间已保存的对照核对；也可指定共同参考'):(report.revision?'组版本 v'+report.revision:'按已收录对照的双方版本');
 return '<header class="candidate-group"><h3>'+esc(report.name)+'</h3><p>'+esc(context)+'</p>'+
  (review?.other_buildings?'<p>'+esc(review.other_buildings)+' 个成员来自另一栋建筑，可在各自建筑内配对。</p>':'')+'</header>'+
  '<div class="candidate-columns"><section class="candidate-answers"><h3>已有结果能回答什么</h3>'+
  (answers||(report.pending.some(item=>item.data.sides.some(s=>s.ambiguous))?'<p>先在下方选定批次，再查看配对差额。</p>':'<p>当前选择下尚无可核验的配对结果。</p>'))+'</section>'+
  (report.priority?candidatePriority(report.priority,action(report.priority.sides,'priority:0','核对这两项')):'<section class="candidate-empty"><h3>补充建议</h3><p>'+esc(report.notices.find(n=>n.includes('历史组版本'))||noPriority)+'</p></section>')+'</div>'+
  (pending||choices?'<details class="candidate-pending" '+(!answers?'open':'')+'><summary>待配对 · '+(report.pending.length+(review?.choices.length||0))+' 组</summary>'+pending+choices+'</details>':'')+
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
async function openCandidateMonths(button,item,siteId=null){
 const predefined=candidateMonthly(item);
 if(predefined&&!siteId)return openAdjacentStudy(button,predefined);
 const dialog=readingDialog(button,'查看月度差异'),body=dialog.querySelector('.rs-month-body'),data=item.data;
 try{
  const req={id:item.relation,left_source:data.sides[0].source,right_source:data.sides[1].source,mode:data.mode};
  const result=(await readComparisonView(req)).summary;
  if(!dialog.open)return;
  const eligible=data.sites.filter(s=>s.monthly_sources&&result.sites.some(r=>r.site_id===s.site&&r.pairing_basis==='严格配对'&&r.left_evidence?.result_sha256===s.monthly_sources[0]&&r.right_evidence?.result_sha256===s.monthly_sources[1]));
  if(!eligible.length)throw Error('当前月度来源与已核对的结果不一致，请重新核对这组对照。');
  body.innerHTML=candidateDirection(data.sides,data.steps)+'<label class="field">地点<select data-place>'+options(eligible.map(s=>[s.site,s.city]),eligible.some(s=>s.site===siteId)?siteId:eligible[0].site)+'</select></label><div data-months></div>';
  const place=body.querySelector('[data-place]');
  function draw(){
   const months=result.monthly.filter(r=>r.site_id===place.value).sort((a,b)=>a.month-b.month);
   body.querySelector('[data-months]').innerHTML=readingMonthsTable(months.map(row=>({month:row.month,
    values:['left','right'].map(side=>['heating','cooling','total'].map(k=>row[side+'_'+k+'_kWh']))})));
  }
  place.onchange=draw;draw();
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
 const load=async()=>{
  body.textContent='正在核对所选版本与已有结果…';
  try {
   const report=await api('/api/reading-collections?'+params);
   if(!dialog.open)return;
   body.innerHTML=candidatePanel(report);
   body.querySelectorAll('[data-candidate-month]').forEach(btn=>btn.onclick=()=>openCandidateMonths(btn,report.answers[Number(btn.dataset.candidateMonth)]));
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
   body.innerHTML='<p role="alert">'+esc(e.message)+'</p><button type="button">重新核对</button>';
   body.querySelector('button').onclick=load;
  }
 };
 await load();
}

document.addEventListener('click',event=>{
 const trigger=event.target.closest('[data-group-candidates]');
 if(!trigger)return;
 event.stopImmediatePropagation();
 showGroupCandidates(trigger);
},true);
