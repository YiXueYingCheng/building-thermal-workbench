/* A set owns its members. The established four-factor editor edits those copies. */
const rsRoles={baseline:'W00 · 原构造',fixed:'固定 ECA',flip:'ECA 表面光学切换',feedback:'表面光学切换＋热阻调节'};
function rsActiveRoles(){const members=RS.current?.members||{baseline:1,fixed:1,flip:1};return Object.fromEntries(Object.entries(rsRoles).filter(([k])=>Object.hasOwn(members,k)));}
function rsCreateRoles(v){return Object.fromEntries(Object.entries(rsRoles).filter(([role])=>v.memberCount===4||role!=='feedback'));}
const rsShared={building:'建筑、基材与房间使用',operation:'温控与运行作息',scope:'地点与时段',numerics:'步长与数值设置'};
const rsMetrics={total:'冷热需求合计',heating:'供暖显热需求',cooling:'制冷显热需求'};
const RS={current:null,results:null,resultMetric:'total',changeMode:'baseline',changeSite:null,loading:false,error:'',epoch:0,dialog:null,context:null,choices:{},preparations:[],progress:null,progressError:'',poll:null};
function rsOwner(){return S.boot?.records.find(r=>r.id===S.id)?.research_set;}
function rsGuard(){if(S.dirty||S.usageDirty)throw Error('当前编辑尚未保存，请先保存或撤销，再切换。');}
function rsAudit(a){return `<ul class="rs-checks">${a.rows.map(r=>`<li class="${r.equal?'':'warning'}"><span>${r.equal?'✓':'需核对'}</span> ${esc(r.label)}</li>`).join('')}</ul>${a.issues.length?'<p class="warning">'+a.issues.map(esc).join('；')+'</p>':'<p class="muted">共同条件一致，可核对同条件结果。</p>'}`;}
async function rsOpen(id,revision){
 rsGuard();
 const target=id||RS.current?.id;
 const sameRevision=target&&RS.current?.id===target&&RS.current.revision===revision;
 if(!sameRevision){RS.current=null;RS.changeSite=null;RS.choices={};}
 const epoch=++RS.epoch;
 S.view='research-sets';RS.loading=true;RS.error='';RS.results=null;RS.exported=null;
 RS.exporting=false;RS.exportError='';RS.progress=null;RS.progressError='';RS.preparations=[];
 render();
 try{
  const selected=target||(await api('/api/research-sets'))[0]?.id;
  const d=selected?await api('/api/research-sets/'+selected+(revision?'?revision='+revision:'')):null;
  if(epoch!==RS.epoch)return;
  let progress=null,progressError='';
  if(d&&RS.manage){
   try{progress=await api('/api/research-sets/'+d.id+'/progress?revision='+d.revision);}
   catch(e){progressError='进度暂未取得：'+e.message;}
  }
  if(epoch!==RS.epoch)return;
  RS.current=d;RS.progress=progress;RS.progressError=progressError;RS.preparations=progress?.preparations||[];
  rsPoll();
  if(d&&!RS.manage&&d.members.baseline.sites===1&&!RS.results&&RS.autoReading!==epoch)void rsReadOnOpen(d,epoch);
 }catch(e){if(epoch===RS.epoch)RS.error=e.message;}
 finally{
  if(epoch===RS.epoch){RS.loading=false;if(S.view==='research-sets')render();}
 }
}
async function rsReadOnOpen(d,epoch){
 RS.autoReading=epoch;
 try{
  const data=await api('/api/research-sets/'+d.id+'/results?revision='+d.revision+'&monthly=1');
  if(RS.epoch!==epoch)return;
  RS.results=data;
 }catch(e){if(RS.epoch===epoch)RS.error='读取本组结果失败：'+e.message;}
 finally{
  if(RS.autoReading===epoch)RS.autoReading=null;
  if(RS.epoch===epoch&&S.view==='research-sets'){
   if(RS.error)render();else rsRefreshResults();
  }
 }
}
function rsSelected(d){
 const selected={};
 for(const role of Object.keys(rsActiveRoles())){
  const usable=(d.members[role]||[]).filter(b=>b.usable),id=RS.choices[role],siteIds=usable.flatMap(b=>b.results.filter(r=>r.accepted).map(r=>r.site_id));
  selected[role]=id?usable.find(b=>b.batch_id===id):(usable.length===1?usable[0]:usable.length&&new Set(siteIds).size===siteIds.length?{multi:true,results:usable.flatMap(b=>b.results.map(r=>({...r,batch_id:b.batch_id,archived:b.archived}))),counts:{accepted:usable.reduce((n,b)=>n+b.counts.accepted,0),total:usable.reduce((n,b)=>n+b.counts.total,0)},reused_source:usable.every(b=>b.reused_source)}:null);
 }
 return selected;
}
function rsPair(d,selected,role,id,mode){
 const item=k=>selected[k]?.results.find(r=>r.site_id===id&&r.accepted&&(!mode||r.mode===mode)),b=item('baseline'),r=item(role);
 return !!(d.audit.consistent&&S.boot.sites[id]?.eligible!==false&&b&&r&&['passed','reused'].includes(b.status)&&['passed','reused'].includes(r.status)&&['weather_sha256','period','mode','step_minutes','days'].every(k=>JSON.stringify(b[k])===JSON.stringify(r[k])));
}
function rsCoverage(d,selected){
 const ids=d.scope.site_ids,roles=Object.keys(d.members).filter(k=>k!=='baseline'),paired=Object.fromEntries(roles.map(role=>[role,ids.filter(id=>rsPair(d,selected,role,id)).length]));
 return {selected:ids.length,paired,complete:ids.filter(id=>roles.every(k=>rsPair(d,selected,k,id))).length};
}
function rsResultTable(){
 const historyLink='<button data-rs="saved-exports">查看已导出文件</button>';
 const d=RS.results;if(!d)return '<p class="muted">按需读取已完成结果；只纳入输入相符且通过核验的算例。</p>'+historyLink;
 const metric=Object.hasOwn(rsMetrics,RS.resultMetric)?RS.resultMetric:'total';
 const selected=rsSelected(d),cities=new Map(d.scope.site_ids.map(id=>[id,S.boot.sites[id]?.name||id]));
 const picks=Object.entries(rsActiveRoles()).map(([role,label])=>{const all=d.members[role]||[],usable=all.filter(b=>b.usable),picked=selected[role];return `<div class="rs-result-source"><strong>${label}</strong>${usable.length>1&&!picked?.multi?`<label class="field">结果批次<select data-rs-result="${role}">${options([['','请选择批次'],...usable.map(b=>[b.batch_id,b.source.name+' · '+b.batch_id.slice(-8)])],picked?.batch_id||'')}</select></label>`:''}<p>${picked?`${picked.archived?'已核验历史批次':picked.reused_source?'复用来源结果':'本组计算结果'} · ${picked.counts.accepted}/${RS.current.members[role].sites} 地点可用`:'暂无已选可用结果'}</p>${picked?.results.some(r=>r.accepted&&r.evidence?.scientific_review)?'<p class="muted">其中 '+picked.results.filter(r=>r.accepted&&r.evidence?.scientific_review).length+' 项附说明接受；点击数值下方的“复核说明”查看范围。</p>':''}${all.some(b=>b.reason)?'<details><summary>未纳入的旧批次</summary>'+all.filter(b=>b.reason).map(b=>'<p class="muted">'+esc(b.reason)+'</p>').join('')+'</details>':''}${picked&&!picked.multi&&!picked.archived?`<button data-source-batch="${picked.batch_id}">查看批次与复核</button>`:''}</div>`;}).join('');
 const item=(role,id)=>selected[role]?.results.find(r=>r.site_id===id&&r.accepted);
 const value=(role,id)=>item(role,id)?.loads?.[metric+'_kWh'];
 const reviewLink=(role,id)=>{
  const r=item(role,id),review=r?.evidence?.scientific_review,batch=r?.batch_id||selected[role]?.batch_id;
  if(!review||!batch)return '';
  if(r.archived||selected[role]?.archived)return `<button class="rs-review-link" data-rs-archive-review="${esc(role)}" data-site="${esc(id)}">复核说明</button>`;
  return `<button class="rs-review-link" data-open-result-review="${esc(batch)}" data-review-index="${r.index}" data-review-name="${esc(r.city+' · '+rsRoles[role])}">复核说明</button>`;
 };
 const paired=(role,id)=>rsPair(d,selected,role,id),coverage=rsCoverage(d,selected);
 const saving=(base,v)=>base>0&&v!=null?format((base-v)/base*100,2)+'%':base===0&&v!=null?'<span class="muted" title="W00 为 0 kWh，降低率不适用；绝对需求见左侧数值。">不适用</span>':'—';
 return `${rsChangesView(d,selected)}<details class="rs-original" ${cities.size>1?'open':''}><summary>各工况需求、结果来源与复核</summary><div class="rs-coverage" aria-label="当前结果配对覆盖">${Object.keys(rsActiveRoles()).filter(k=>k!=='baseline').map(k=>`<div><strong>${coverage.paired[k]} / ${coverage.selected}</strong><span>${esc(rsRoles[k])} 对照 W00</span></div>`).join('')}<div><strong>${coverage.complete} / ${coverage.selected}</strong><span>全部工况完整配对</span></div></div><p class="muted">仅统计当前选中批次的同条件、已接受结果。未完成或待复核地点保留空缺。</p><details class="rs-sources"><summary>结果来源与复核说明</summary><div class="rs-columns">${picks}</div></details>${cities.size?`<div class="rs-result-controls"><label class="field">需求指标<select id="rs-result-metric">${options(Object.entries(rsMetrics),metric)}</select></label><p class="muted">${esc(periodLabel(RS.current.members.baseline.period))} · 单位 kWh。导出始终包含合计、供暖与制冷。</p></div>${d.members.feedback?'<p class="muted">比较固定 ECA 与仅切换光学参数的工况，可查看表面光学切换的贡献。再与组合工况比较，可查看热阻调节带来的变化。</p>':''}<p class="muted">降低率 =（W00 − 研究）/ W00；负值表示需求增加。基准为零时比例不适用；无数据不记为零。</p><div class="table-scroll" tabindex="0" aria-label="${rsMetrics[metric]}对照，可滚动查看全部地点"><table class="table rs-numbers"><thead><tr><th>地点</th><th>W00</th><th>固定 ECA</th><th>降低率</th><th>ECA 表面光学切换</th><th>降低率</th>${d.members.feedback?'<th>表面光学切换＋热阻调节</th><th>降低率</th><th>热阻反馈新增降低量 / kWh</th>':''}</tr></thead><tbody>${[...cities].map(([id,name])=>{const b=value('baseline',id),f=value('fixed',id),t=value('flip',id),h=value('feedback',id);return `<tr><th>${esc(name)}</th><td>${format(b)}${reviewLink('baseline',id)}</td><td>${format(f)}${reviewLink('fixed',id)}</td><td>${paired('fixed',id)?saving(b,f):b!=null&&f!=null?'条件待核对':'—'}</td><td>${format(t)}${reviewLink('flip',id)}</td><td>${paired('flip',id)?saving(b,t):b!=null&&t!=null?'条件待核对':'—'}</td>${d.members.feedback?`<td>${format(h)}${reviewLink('feedback',id)}</td><td>${paired('feedback',id)?saving(b,h):'—'}</td><td>${paired('feedback',id)&&paired('flip',id)?format(t-h):'—'}</td>`:''}</tr>`;}).join('')}</tbody></table></div>`:''}</details><p class="muted">核对时间：${esc(readableTime(d.checked_at))}</p><div class="actions"><button data-rs="export"${RS.loading||RS.exporting?' disabled':''}>${RS.exporting?'正在生成图表与导出包…':'导出图表与数据'}</button>${historyLink}${RS.exported?`<a href="/api/research-set-exports/${RS.exported.id}/comparison.csv" download="本组工况对照.csv">汇总 CSV</a><a href="/api/research-set-exports/${RS.exported.id}/comparison.zip" download="本组图表与依据.zip">图表、Origin 数据与依据</a>`:''}</div>${RS.exporting?'<p class="muted" role="status">正在核对快照并绘图，可以继续查看本页；不启动计算。</p>':''}${RS.exported?`<p class="muted" role="status">已导出本组 v${RS.exported.revision} · ${RS.exported.figure_pages?.length||0} 页图表 · ${esc(readableTime(RS.exported.created))}。${RS.exported.coverage?`全部工况完整 ${RS.exported.coverage.complete}/${RS.exported.coverage.selected} 地点；空缺已保留。`:''}</p>`:''}${RS.exportError?`<p class="warning" role="alert">${esc(RS.exportError)}</p>`:''}`;
}
function rsArchiveReview(button){
 const role=button.dataset.rsArchiveReview;
 const batch=rsSelected(RS.results)[role];
 const row=batch?.results.find(r=>r.site_id===button.dataset.site&&r.accepted);
 const review=row?.evidence?.scientific_review;
 if(!review||!(row.archived||batch.archived))return;
 const dialog=readingDialog(button,'归档复核说明');
 const fields=[['原批次',row.batch_id||batch.batch_id],['结果校验值',row.evidence.result_sha256],
  ['复核前结果校验值',review.original_result_sha256],['复核依据校验值',review.evidence_sha256]];
 dialog.querySelector('.rs-month-body').innerHTML='<p>'+esc(row.city)+' · '+esc(rsRoles[role])+' · 成员 v'+esc(RS.current.members[role].revision)+'</p>'+
  '<h3>'+esc(review.label||'已登记复核')+'</h3><p>'+esc(review.display_scope||review.scope||'')+'</p><p>'+esc(review.note||'')+'</p>'+
  (review.reviewed_at?'<p>复核时间 '+esc(readableTime(review.reviewed_at))+'</p>':'')+
  '<details class="reading-month-source"><summary>原批次与核验依据</summary>'+fields.filter(([,v])=>v).map(([label,value])=>'<p>'+label+'<br><code>'+esc(value)+'</code></p>').join('')+
  (review.warnings||[]).map(w=>'<p>'+esc(w)+'</p>').join('')+'</details>';
}
async function rsSavedExports(button){
 const {id,revision}=RS.current,dialog=readingDialog(button,'本组已导出文件'),body=dialog.querySelector('.rs-month-body');
 try{
  const report=await api('/api/research-sets/'+encodeURIComponent(id)+'/exports?revision='+encodeURIComponent(revision));
  if(!dialog.open)return;
  body.innerHTML='<p>组版本 '+esc(revision)+' · 已核对 '+report.exports.length+' 份导出</p>'+
   report.exports.map(r=>'<article><strong>'+esc(readableTime(r.created))+'</strong><div class="actions">'+
    ['comparison.csv','comparison.zip'].map((f,i)=>'<a download href="/api/research-set-exports/'+encodeURIComponent(r.id)+'/'+f+'">'+['汇总 CSV','图表、数据与依据 ZIP'][i]+'</a>').join('')+'</div></article>').join('')+
   report.issues.map(e=>'<p class="warning">未能核对 '+esc(e.id)+' · '+esc(e.message)+'</p>').join('');
 }catch(e){if(dialog.open)body.textContent=e.message;}
}
function rsRefreshResults(focusSelector){
 const panel=document.querySelector('#rs-results [data-rs-results-body]');if(!panel)return;
 const refresh=panel.closest('.collection-page')?.querySelector('[data-rs="results"]');
 if(refresh){refresh.disabled=RS.loading;refresh.textContent=RS.results?'重新核对结果':'读取与核对已有结果';}
 const originalOpen=panel.querySelector('.rs-original')?.open;
 const table=panel.querySelector('.rs-numbers')?.closest('.table-scroll'),top=table?.scrollTop||0,left=table?.scrollLeft||0,sourceOpen=panel.querySelector('.rs-sources')?.open;
 panel.innerHTML=rsResultTable();
 if(originalOpen!=null&&panel.querySelector('.rs-original'))panel.querySelector('.rs-original').open=originalOpen;
 panel.querySelector('.rs-numbers')?.closest('.table-scroll')?.scrollTo({top,left});
 if(sourceOpen&&panel.querySelector('.rs-sources'))panel.querySelector('.rs-sources').open=true;
 if(focusSelector)panel.querySelector(focusSelector)?.focus({preventScroll:true});
}
function rsManagement(d){
 const historical=d.revision!==d.latest_revision;
 const versions=options(d.history.map(r=>[r.revision,'v'+r.revision+' · '+readableTime(r.created)+(r.revision===d.latest_revision?' · 最新':'')]),d.revision);
 return `<div class="rs-toolbar"><label class="field">组版本<select id="rs-version">${versions}</select></label>
  <button data-rs="refresh" ${RS.loading?'disabled':''}>刷新管理信息</button></div>
  ${historical?'<p class="muted">正在查看历史组版本。</p>':''}
  <details class="rs-section"><summary>组说明与派生方案</summary>${d.notes?'<p>'+esc(d.notes)+'</p>':''}
   <div class="actions"><button data-rs="metadata" ${historical?'disabled':''}>名称与说明</button>
   ${d.fixed_feedback_experiment&&!historical?'<button data-experiment="open">派生单因素实验</button>':''}</div></details>
  <section class="rs-section"><details><summary>成员版本与配置</summary><div class="rs-columns">${Object.entries(rsActiveRoles()).map(([role,label])=>{const r=d.members[role];return `<article class="rs-member"><span class="tag">${label}</span><h3>${esc(r.name)}</h3><p>${role==='baseline'?'提供同条件基准负荷；全年工况可保留逐日参考':role==='fixed'?'固定热学状态与光学参数组':role==='feedback'?'按日历切换表面光学参数，并启用热阻调节':'固定热学状态、按日历切换表面光学参数'}</p><p class="muted">成员 v${r.revision} · ${r.sites} 地点</p>${versionNoteMarkup(r,true)}<button class="primary" data-rs-member="${role}">${historical?'查看四因素':'查看与编辑四因素'}</button><details><summary>来源版本</summary><p>${esc(r.source_summary?.name||r.source.id)} · v${r.source.revision}</p>${versionNoteMarkup(r.source)}<p class="muted">创建时取值；后续修改仅保存在本组。</p></details></article>`;}).join('')}</div></details></section><section class="rs-section"><div class="row"><h2>共同条件与日历</h2><button data-rs="calendar"${RS.loading?' disabled':''}>核对参考与光学切换日历</button></div>${rsAudit(d.audit)}${d.calendars.map(c=>`<p class="${c.valid?'muted':'warning'}">${esc(rsRoles[c.role])} · 光学切换日历 v${c.revision} · ${c.valid?'已绑定 '+c.sites+' 地点':esc(c.note)}</p>`).join('')}<p class="muted">修改范围后，新增地点须先取得 W00 逐日参考，再生成对应日历。旧版本、旧结果保留。</p></section>${rsExecutionView()}`;
}
function rsDialog(){let d=document.getElementById('research-set-dialog');if(d)return d;d=document.createElement('dialog');d.id='research-set-dialog';document.body.append(d);d.addEventListener('cancel',e=>{e.preventDefault();if(!RS.dialog?.pending)void rsDialogAction('close');});return d;}
function rsDialogDraw(){const v=RS.dialog,d=rsDialog();if(!v)return;
 const preview=v.preview,save=v.kind==='save',create=v.kind==='new';
 d.innerHTML=`<header class="viewer-head"><div><h2>${save?'保存组内修改':create?'用 ECA 工况模板建集':'对比集名称与说明'}</h2><p>${save?'来源方案保持原样；先核对本次影响。':create?'为每个工况选择来源版本，预览后保存为独立成员。':'每次保存都有组版本记录。'}</p></div><button data-rsd="close"${v.pending?' disabled':''}>${create?'返回建立对比集':'关闭'}</button></header><div class="rs-dialog-body">${create?`<label class="field">对比集名称<input id="rs-name" value="${esc(v.name)}" maxlength="100"></label><label class="field">工况组合<select id="rs-member-count">${options([[3,'三工况：原构造、固定 ECA、ECA 表面光学切换'],[4,'四工况：增加表面光学切换＋热阻调节']],v.memberCount)}</select></label><label class="field">查找来源版本<input type="search" id="rs-source-filter" placeholder="名称、备注或批次" value="${esc(v.search||'')}"></label>${Object.entries(rsCreateRoles(v)).map(([role,label])=>themeTemplateField(v,role,label)).join('')}`:save?`<p><strong>${esc(rsRoles[v.role])}</strong> · 当前保存 v${v.recordRevision}${preview?.changed?' → 保存新版本':''}</p>${v.available.length?`<fieldset><legend>以下变化同步到本组全部成员</legend>${v.available.map(k=>`<label class="check"><input type="checkbox" data-rs-share="${k}"${v.shared.includes(k)?' checked':''}>${rsShared[k]}</label>`).join('')}<p class="muted">取消勾选则仅保存当前成员；差异会保留在组内核对清单。</p></fieldset>`:'<p>本次核对范围：当前成员。</p>'}`:`<label class="field">名称<input id="rs-name" maxlength="100" value="${esc(v.name)}"></label><label class="field">说明<textarea id="rs-notes" rows="4" maxlength="2000">${esc(v.notes)}</textarea></label>`}${v.error?`<p class="warning" role="alert">${esc(v.error)}</p>`:''}<div role="status" class="rs-feedback">${v.pending?esc(v.status):preview?(preview.changed===false?'与保存版本相同，无需保存新版本。':'预览完成，请核对下方具体变化。'):'尚未预览。'}</div>${preview?`<div class="well">${rsAudit(preview.audit)}${save?preview.members.map(m=>`<p><strong>${esc(m.label)}</strong>：${m.changed?'v'+m.from_revision+' → v'+m.to_revision:'不变'}<br><span class="muted">${esc(m.result_note)}</span></p>${rsMemberChanges(m)}`).join(''):create?`<p>新建 ${Object.keys(preview.members||{}).length} 个独立成员。来源方案及已有结果保留。</p>`:''}<p>本次不启动计算。</p></div>`:''}</div><footer class="viewer-foot"><div class="actions"><button data-rsd="preview"${v.pending?' disabled':''}>预览保存影响</button><button class="primary" data-rsd="commit"${v.pending||!preview||preview.changed===false?' disabled':''}>${create?'确认创建':'确认保存本组'}</button>${create?'':`<button data-rsd="close"${v.pending?' disabled':''}>返回</button>`}</div></footer>`;
 d.querySelectorAll('input,select,textarea').forEach(el=>el.disabled=v.pending);if(!d.open)d.showModal();
}
function rsRequest(v){return v.kind==='save'?{role:v.role,changes:v.changes,shared:v.shared}:{name:v.name,notes:v.notes};}
function rsMemberChanges(m){
 const d=m.calendar_changes,refs=rows=>rows.map(r=>esc(r.name||'光学切换日历')+' · v'+r.revision).join('；')||'未绑定活动日历';
 const outline=o=>`初始 ${esc(o.initial)}${o.switches.length?'；'+o.switches.map(x=>esc(x.date)+' → '+esc(x.face)).join('；'):'；全年无切换'}`;
 return `<p class="muted">${(m.factors||[]).filter(x=>x.changed).map(x=>esc(x.label)).join('、')||'四因素与计算设置无变化'}</p>${d?.rows.length?`<div class="rs-calendar-change"><p><strong>${d.changed_sites?'日历光学选择变化：'+d.changed_sites+' 地点':d.reference_changed?'日历引用更新，逐日光学选择安排未变':'已绑定相同日历，逐日光学选择安排未变'}</strong></p><p>原：${refs(d.before_refs)}<br>本次：${refs(d.after_refs)}</p><details><summary>查看 ${d.rows.length} 地点的前后日期与光学参数组</summary><div class="table-scroll"><table class="table"><thead><tr><th>地点</th><th>原保存版本</th><th>本次编辑</th><th>变化</th></tr></thead><tbody>${d.rows.map(r=>`<tr><td>${esc(r.city)}</td><td>${outline(r.before)}</td><td>${outline(r.after)}</td><td>${r.changed?(r.changed_days===null?'控制方式变化':r.changed_days+' 天'):'相同'}</td></tr>`).join('')}</tbody></table></div></details></div>`:''}`;
}
function rsSourceRefs(v){return Object.fromEntries(Object.entries(v.selected).filter(([role])=>Object.hasOwn(rsCreateRoles(v),role)).map(([k,x])=>{const [id,rev]=x.split('|');return [k,{id,revision:Number(rev)}];}));}
function rsNew(versions,name,returnToBuilder){
 const allowed=new Set(S.boot.records.filter(r=>!r.research_set&&!r.archived&&r.status==='draft').map(r=>r.id));
 const sources=versions.filter(v=>allowed.has(v.ref.id)).map(v=>({...v}));
 themeLabels(sources);
 RS.dialog={kind:'new',name:name||'三工况研究对比',memberCount:3,selected:{},sources,pending:false,error:'',returnToBuilder};
 rsDialogDraw();
}
async function rsSaveStart(){
 if(S.usageDirty)throw Error('请先保存或撤销房间配置编辑。');if(readonly())throw Error('历史版本只读。');
 const owner=rsOwner(),d=await api('/api/research-sets/'+owner.set_id),member=d.members[owner.role];
 if(member.revision!==S.saved.revision)throw Error('组内成员已有新版本。当前编辑保留，请先核对版本。');
 const c=copy(changes()),before=S.saved.factors,after=c.factors;
 const available=Object.keys(rsShared).filter(k=>JSON.stringify(k==='numerics'?S.saved.numerics:k==='operation'?before.condition.operation:before[k])!==JSON.stringify(k==='numerics'?c.numerics:k==='operation'?after.condition.operation:after[k]));
 RS.dialog={kind:'save',setId:d.id,revision:d.revision,role:owner.role,recordId:S.id,recordRevision:S.saved.revision,stamp:JSON.stringify([S.id,S.saved.revision,changes()]),changes:c,available,shared:[...available],pending:false,error:''};rsDialogDraw();
}
async function rsDialogAction(op){const v=RS.dialog;if(!v||v.pending)return;if(op==='close'){rsDialog().close();if(v.kind==='new'){RS.dialog=null;v.returnToBuilder();return;}if(v.kind==='save'&&v.preview?.changed===false&&v.stamp===JSON.stringify([S.id,S.saved.revision,changes()])&&S.dirty){S.record=copy(S.saved);S.dirty=false;S.preview=null;resetConfiguration();render();notice('与保存版本相同，没有新增版本。');}return;}
 v.pending=true;v.error='';v.status=op==='commit'?'正在保存本组版本，请稍候…':'正在核对保存影响…';rsDialogDraw();
 try{
  if(v.kind==='save'&&v.stamp!==JSON.stringify([S.id,S.saved.revision,changes()]))throw Error('编辑已变化，请返回后重新保存。');
  const create=v.kind==='new',route=create?'/api/research-sets':'/api/research-sets/'+v.setId;
  const body=create?{name:v.name,sources:rsSourceRefs(v)}:{revision:v.revision,request:rsRequest(v)};
  if(op==='preview'){v.preview=await api(route+'/preview',body);return;}
  if(!v.preview)throw Error('请先预览。');const r=await api(route,{...body,preview_sha256:v.preview.preview_sha256});
  rsDialog().close();if(create)RS.dialog=null;if(v.kind==='save'){S.dirty=false;await bootstrap();await loadRecord(v.recordId);RS.context={id:r.id,revision:r.revision};render();notice('已保存本组 v'+r.revision+'；来源方案未改动。');}else{await bootstrap();RS.manage=false;await rsOpen(r.id,r.revision);notice('对比集已保存。');}
 }catch(e){v.error=e.message;}finally{v.pending=false;if(rsDialog().open)rsDialogDraw();}
}
async function rsAction(b){
 if(b.dataset.rsd){await rsDialogAction(b.dataset.rsd);return;}
 if(b.dataset.rsMember){rsGuard();const d=RS.current,role=b.dataset.rsMember,r=d.members[role];await loadRecord(r.id,r.revision);RS.context={id:d.id,revision:d.revision};S.view='editor';render();scrollTo({top:0,behavior:'instant'});return;}
 const op=b.dataset.rs;
 if(op==='saved-exports'){await rsSavedExports(b);return;}
 if(op==='home'){RS.manage=false;clearTimeout(RS.poll);render();scrollTo({top:0,behavior:'instant'});if(!RS.results&&RS.current?.members.baseline.sites===1&&RS.autoReading!==RS.epoch)void rsReadOnOpen(RS.current,RS.epoch);return;}
 if(op==='refresh'){await rsOpen(RS.current?.id,RS.current?.revision);return;}
 if(op==='return'){const owner=rsOwner();await rsOpen(owner?.set_id,RS.context?.id===owner?.set_id?RS.context.revision:undefined);return;}
 if(op==='calendar'){await rsAction({dataset:{rsMember:'flip'}});const launch=document.createElement('button');launch.dataset.calendarLibrary='open';await configurationAction(launch);return;}
 if(op==='metadata'){const d=RS.current;RS.dialog={kind:'metadata',setId:d.id,revision:d.revision,name:d.name,notes:d.notes,pending:false,error:''};rsDialogDraw();return;}
 if(op==='export'){
  if(!RS.results||RS.loading||RS.exporting)return;
  const data=RS.results,choices=copy(RS.choices),epoch=RS.epoch,choiceStamp=JSON.stringify(choices);
  RS.exporting=true;RS.exportError='';rsRefreshResults('[data-rs="export"]');
  try{const receipt=await api('/api/research-set-export',{id:data.id,revision:data.revision,dataset_sha256:data.dataset_sha256,choices});if(epoch===RS.epoch&&JSON.stringify(RS.choices)===choiceStamp)RS.exported=receipt;}
  catch(e){if(epoch===RS.epoch)RS.exportError=e.message;}
  finally{if(epoch===RS.epoch){RS.exporting=false;if(S.view==='research-sets')rsRefreshResults('[data-rs="export"]');}}
  return;
 }
 if(op==='results'){RS.exported=null;RS.exporting=false;RS.exportError='';const d=RS.current,epoch=++RS.epoch;RS.loading=true;RS.error='';render();try{const r=await api('/api/research-sets/'+d.id+'/results?revision='+d.revision+'&monthly=1');if(epoch===RS.epoch)RS.results=r;}catch(e){RS.error=e.message;}finally{if(epoch===RS.epoch){RS.loading=false;if(S.view==='research-sets'){render();document.querySelector('#rs-results h2')?.scrollIntoView({block:'start',behavior:'instant'});}}}}
}
const rsPreviousEditor=editor;editor=function(){const html=rsPreviousEditor(),owner=rsOwner();if(!owner)return html;const t=document.createElement('template');t.innerHTML=html;const main=t.content.querySelector('.two-views');main?.insertAdjacentHTML('afterbegin',`<div class="rs-context"><div><strong>正在编辑对比集内成员 · ${rsRoles[owner.role]}</strong><p>保存仅影响本组；共同条件可在保存时同步到其他成员。</p></div><button data-rs="return">返回对比集</button></div>`);const save=t.content.querySelector('[data-action="save"]');if(save)save.textContent='保存到本组';return t.innerHTML;};
const rsPreviousSidebar=sidebar;sidebar=function(){const owner=rsOwner();return owner?`<aside class="sidebar"><h2>对比集内成员</h2><p>当前为 ${rsRoles[owner.role]}。各成员保持独立四因素。</p><button data-rs="return">返回本组切换成员</button><details><summary>其他方案</summary>${libraryList()}</details></aside>`:rsPreviousSidebar();};
const rsPreviousRender=render;render=function(){if(S.view==='research-sets'){renderNav();nav.querySelector('[data-view="compare"]')?.setAttribute('aria-pressed','true');app.innerHTML=researchSetsView();syncPageSections();}else rsPreviousRender();};
// Capture only these controls: async group reads do not freeze unrelated navigation.
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;if(b.dataset.rsArchiveReview){e.stopImmediatePropagation();rsArchiveReview(b);return;}if(b.dataset.rs||b.dataset.rsd||b.dataset.rsMember||(b.dataset.action==='save'&&rsOwner())){e.stopImmediatePropagation();e.preventDefault();Promise.resolve(b.dataset.action==='save'?rsSaveStart():rsAction(b)).catch(e=>notice(e.message));}},true);
document.addEventListener('change',e=>{const t=e.target,v=RS.dialog;if(t.id==='rs-version'){void rsOpen(RS.current.id,Number(t.value)).catch(e=>notice(e.message));return;}if(t.id==='rs-result-metric'){if(Object.hasOwn(rsMetrics,t.value))RS.resultMetric=t.value;rsRefreshResults('#rs-result-metric');return;}if(t.dataset.rsResult){RS.choices[t.dataset.rsResult]=t.value;RS.exported=null;rsRefreshResults('[data-rs-result="'+t.dataset.rsResult+'"]');return;}if(!v||v.pending)return;if(t.dataset.rsSource)v.selected[t.dataset.rsSource]=t.value;else if(t.dataset.rsShare)v.shared=t.checked?[...v.shared,t.dataset.rsShare]:v.shared.filter(k=>k!==t.dataset.rsShare);else return;v.preview=null;rsDialogDraw();});
document.addEventListener('input',e=>{const v=RS.dialog;if(!v||v.pending)return;if(e.target.id==='rs-name')v.name=e.target.value;else if(e.target.id==='rs-notes')v.notes=e.target.value;else return;v.preview=null;rsDialog().querySelector('[data-rsd="commit"]').disabled=true;rsDialog().querySelector('.rs-feedback').textContent='编辑已变化，请重新预览。';});

const rsStatus={prepared:'已准备 · 未提交',pending:'排队中',running:'计算中',passed:'核验通过',reused:'已复用',review:'待复核',failed:'未通过',interrupted:'已中断',cancelled:'已取消',unknown:'关联待核对'};
function rsPreparationProgress(p){if(p.state!=='preparing'||!p.preparation_progress)return '';const g=p.preparation_progress,eta=p.remaining_range_seconds,minutes=n=>Math.max(1,Math.ceil(n/60));return `<p role="status">${esc(g.label||'')} · ${esc(g.city||'')} · ${esc(g.stage||'准备中')}</p><progress max="${p.plan.cases||1}" value="${p.cases.length}" aria-label="本组输入准备进度"></progress><p class="muted">已用约 ${minutes(p.preparation_elapsed_seconds||0)} 分钟${eta?' · 预计剩余 '+minutes(eta[0])+'—'+minutes(eta[1])+' 分钟（按已完成成员与地点估算）':' · 首项完成后估算剩余时间'}。后台准备可继续，已完成清单保留。</p>`;}
function rsPreparationFinished(p){return p.lifecycle?.finished??(p.state==='submitted'&&p.cases.length===p.plan.cases&&!(p.counts.pending||p.counts.running));}
function rsProgressEntry(c,multiple=false){const origin={member:'成员单独提交',source:'关联来源结果',group:'本组批量安排'}[c.origin]||'';const label=c.paused&&c.status==='pending'?'已暂停':rsStatus[c.status]||c.status;return c.batch_id?`<button class="rs-status-link" data-source-batch="${c.batch_id}">${esc(label)}</button><small class="muted" style="display:block">${esc(origin)}${multiple?' · '+esc(c.batch_id.slice(-8)):''}</small>`:`<span>${esc(label)}</span>`;}
function rsExecutionView(){
 const d=RS.current;if(!d)return '';const historical=d.revision!==d.latest_revision,g=RS.progress,bySite=new Map();
 for(const c of g?.cases||[]){const k=c.site_id+':'+c.role;if(!bySite.has(k))bySite.set(k,[]);bySite.get(k).push(c);}
 const history=RS.preparations.map(p=>{const finished=rsPreparationFinished(p);return `<div class="rs-run-status"><strong>${esc(p.lifecycle?.label||(finished?'本次批量安排已结束':p.message))}</strong><p>${Object.keys(rsActiveRoles()).filter(k=>p.plan.roles?.includes(k)||p.cases.some(c=>c.role===k)).map(k=>esc(rsRoles[k])).join('、')} · 已准备 ${p.cases.length}/${p.plan.cases} 项 · 通过 ${(p.counts.passed||0)+(p.counts.reused||0)} · 排队 ${p.counts.pending||0} · 计算中 ${p.counts.running||0} · 待复核 ${p.counts.review||0} · 未通过 ${p.counts.failed||0}</p>${rsPreparationProgress(p)}${p.lifecycle?`<p>未提交 ${p.lifecycle.unsubmitted} 项 · 待核对 ${p.lifecycle.unknown} 项。队列结束后的结果可用性仍需打开批次核对。</p><details><summary>查看准备与批次关联</summary>${p.cases.map(c=>`<p>${esc(c.city||c.site_id)} · ${esc(rsRoles[c.role])} · ${esc(c.lifecycle.label)} ${(c.lifecycle.batches||[]).map(b=>`<button data-source-batch="${esc(b.id)}">查看批次 ${esc(b.id.slice(-8))}</button>`).join('')}</p>`).join('')}</details>`:''}${p.error?'<p class="warning">'+esc(p.error)+'</p>':''}${!p.lifecycle?.history&&['failed','interrupted','paused'].includes(p.state)?`<button data-rs-resume="${p.id}">${p.state==='paused'?'继续本组后续任务':'继续准备剩余项'}</button>`:''}${p.can_submit?`<button data-rs-submit="${p.id}">提交已准备清单</button>`:''}${!finished&&['preparing','submitted'].includes(p.state)?`<button data-rs-pause="${p.id}">暂停本组后续任务</button>`:''}</div>`;}).join('');
 return `<section class="rs-section" id="rs-execution"><div class="row"><div><h2>本组计算进度</h2><p class="muted">统一查看本组批量安排与成员方案单独提交的任务。</p></div><div class="actions"><button data-rs="prepare"${historical?' disabled':''}>安排本组计算</button></div></div>${RS.progressError?'<p class="warning" role="alert">'+esc(RS.progressError)+'</p>':''}${!g?'<p role="status">'+(RS.progressError?'进度尚未取得；不能据此判断是否已提交。':'正在读取各成员批次状态…')+'</p>':`<div class="rs-coverage" aria-label="关联批次队列状态">${Object.entries(rsActiveRoles()).map(([role,label])=>{const rows=g.cases.filter(c=>c.role===role);return `<div><strong>${rows.filter(c=>['passed','reused'].includes(c.status)).length} / ${rows.length}</strong><span>${label} · 队列登记通过 / 关联算例</span></div>`;}).join('')}</div><p>关联已提交 ${g.submitted} 项 · 通过 ${(g.counts.passed||0)+(g.counts.reused||0)} · 排队 ${g.counts.pending||0} · 计算中 ${g.counts.running||0} · 待复核 ${g.counts.review||0} · 未通过 ${g.counts.failed||0}${g.counts.prepared?' · 已准备未提交 '+g.counts.prepared:''}</p><p class="muted">${esc(g.note)} 多个批次分别保留；配对覆盖见“本组结果”。</p>${g.issues.length?'<p class="warning">'+g.issues.map(esc).join('；')+'</p>':''}<div class="table-scroll rs-progress-table"><table class="table"><thead><tr><th>地点</th>${Object.values(rsActiveRoles()).map(x=>'<th>'+x+'</th>').join('')}</tr></thead><tbody>${d.common.scope.site_ids.map(sid=>`<tr><th>${esc(S.boot.sites[sid]?.name||sid)}</th>${Object.keys(rsActiveRoles()).map(role=>{const rows=bySite.get(sid+':'+role)||[];return `<td>${rows.length>1?`<details><summary>${rows.length} 个批次 / 清单</summary>${rows.map(c=>'<p>'+rsProgressEntry(c,true)+'</p>').join('')}</details>`:rows.length?rsProgressEntry(rows[0]):'无关联任务'}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div><p class="muted">状态读取于 ${esc(readableTime(g.read_at))}</p>`}${history?`<details class="rs-preparation-history"><summary>本组批量安排记录（${RS.preparations.length} 份，不含成员单独提交）</summary>${history}</details>`:''}</section>`;
}
function rsCollectionTools(id,revision){
 return '<button data-group-candidates="'+esc(id)+'" data-group-revision="'+esc(revision)+'">已有答案与方案候选</button>'+
  '<button data-set-pane="manage" data-set-id="'+esc(id)+'" data-set-revision="'+esc(revision)+'">管理计算与成员</button>'+relationButton({kind:'set',id,label:'解散对比集'});
}
async function rsShowSetPane(id,revision,pane){
 rsGuard();
 if(pane==='results'&&!RS.loading&&RS.current?.id===id&&RS.current.revision===revision){
  S.view='research-sets';
  await rsAction({dataset:{rs:'home'}});
  return;
 }
 RS.manage=pane==='manage';
 await rsOpen(id,revision);if(S.view==='research-sets')window.scrollTo({top:0,behavior:'instant'});
}
function rsCollectionTabs(id,revision,pane){
 return '<div class="collection-views" role="group" aria-label="本组内容">'+[['results','成员工况结果'],['saved','已收录对照']].map(([value,label])=>
  '<button data-set-pane="'+value+'" data-set-id="'+esc(id)+'" data-set-revision="'+esc(revision)+'" aria-pressed="'+(pane===value)+'">'+label+'</button>').join('')+'</div>';
}
function researchSetsView(){
 const d=RS.current,error=RS.error?'<p role="alert">'+esc(RS.error)+'</p>':'';
 if(!d){
  const state=error||(RS.loading?'<p role="status">正在读取…</p>':'<p>尚无可打开的组。</p>');
  return collectionFrame('对比集',collectionBack,'',state);
 }
 const meta='<p class="collection-meta">'+Object.keys(d.members).length+' 个成员 · 组版本 '+d.revision+' · '+d.members.baseline.sites+' 个地点 · '+esc(periodLabel(d.members.baseline.period))+' · '+d.members.baseline.step_minutes+' min</p>';
 if(RS.manage){
  const back='<button class="collection-back" data-rs="home">← 返回本组结果</button>';
  return collectionFrame(d.name,back,'',meta+'<h2>管理计算与成员</h2>'+error+rsManagement(d));
 }
 const body='<section id="rs-results"><div class="collection-results-head"><h2>本组结果</h2><button data-rs="results" '+(RS.loading||RS.autoReading===RS.epoch?'disabled':'')+'>'+(RS.autoReading===RS.epoch?'正在读取…':RS.results?'重新核对结果':'读取与核对已有结果')+'</button></div><div data-rs-results-body>'+rsResultTable()+'</div></section>';
 return collectionFrame(d.name,collectionBack,rsCollectionTools(d.id,d.revision),meta+rsCollectionTabs(d.id,d.revision,'results')+error+body);
}
function rsPoll(){clearTimeout(RS.poll);if(S.view!=='research-sets'||!RS.current||!RS.manage)return;RS.poll=setTimeout(async()=>{const key=RS.current.id+':'+RS.current.revision;try{const data=await api('/api/research-sets/'+RS.current.id+'/progress?revision='+RS.current.revision);if(S.view==='research-sets'&&key===RS.current?.id+':'+RS.current?.revision){RS.progress=data;RS.preparations=data.preparations;RS.progressError='';rsRefreshProgress();}}catch(e){if(S.view==='research-sets'&&key===RS.current?.id+':'+RS.current?.revision){RS.progressError='进度暂未刷新，保留上次状态：'+e.message;rsRefreshProgress();}}finally{if(S.view==='research-sets')rsPoll();}},5000);}
function rsRefreshProgress(){const el=document.getElementById('rs-execution');if(!el)return;const stamp=JSON.stringify([RS.progress?.cases,RS.progress?.issues,RS.progressError,RS.preparations.map(p=>[p.id,p.state,p.counts,p.error,p.message,p.lifecycle,p.cases.map(c=>c.lifecycle),p.preparation_progress,p.preparation_elapsed_seconds,p.remaining_range_seconds])]);if(el._rsProgressStamp===stamp)return;const y=el.querySelector('.rs-progress-table')?.scrollTop||0,open=[...el.querySelectorAll('details')].map((d,i)=>d.open?i:-1).filter(i=>i>=0);el.outerHTML=rsExecutionView();const next=document.getElementById('rs-execution');next._rsProgressStamp=stamp;next.querySelector('.rs-progress-table')?.scrollTo({top:y});const details=next.querySelectorAll('details');for(const i of open)if(details[i])details[i].open=true;}
function rsExecutionDialog(){const v=RS.dialog,d=rsDialog(),p=v.preview;d.innerHTML=`<header class="viewer-head"><div><h2>安排本组计算</h2><p>组版本 ${v.revision} · ${esc(RS.current?.name)}</p></div><button data-rsd="close"${v.pending?' disabled':''}>关闭</button></header><div class="rs-dialog-body"><fieldset><legend>本轮安排哪些成员</legend>${Object.entries(rsActiveRoles()).map(([role,label])=>`<label class="check"><input type="checkbox" data-rs-run-role="${role}"${v.roles.includes(role)?' checked':''}${v.pending?' disabled':''}>${label}${role==='baseline'?(RS.current?.common.scope.period.join(',')==='1,1,12,31'?'（同时保留全年逐日参考）':'（所选时段负荷）'):['flip','feedback'].includes(role)?'（需已有匹配日历）':''}</label>`).join('')}</fieldset><div class="rs-feedback" role="status">${v.pending?esc(v.status):p?'范围与空间已核对。':'先核对范围与空间。'}</div>${v.error?'<p role="alert" class="warning">'+esc(v.error)+'</p>':''}${p?`<div class="metrics"><span><strong>${p.site_ids.length}</strong>地点</span><span><strong>${p.cases}</strong>本轮算例</span><span><strong>${format(p.storage.available_bytes/2**30,1)}</strong>可用空间 / GiB</span></div>${outputStorageBudget({destination:p.destination,capacity:p.storage})}<p>${esc(p.note)}</p><p>本轮准备留量约 ${format(p.storage.planning_allowance_bytes/2**30,1)} GiB；磁盘保留 ${format(p.storage.reserve_bytes/2**30,1)} GiB。${p.storage.fits?'当前空间足够按此留量准备。':'当前空间不足。'}</p><p class="muted">${esc(p.storage.note)}</p><p>最多 ${p.policy.max_parallel} 路，保留 ${p.policy.reserve_gib} GiB 内存。实际并行由当时资源决定。</p>`:''}</div><footer class="viewer-foot"><div class="actions"><button data-rsd="check-run"${v.pending?' disabled':''}>核对范围与空间</button><button data-rsd="prepare-run"${v.pending||!p?.storage.fits?' disabled':''}>仅准备清单</button><button class="primary" data-rsd="start-run"${v.pending||!p?.storage.fits?' disabled':''}>准备并提交计算</button></div></footer>`;if(!d.open)d.showModal();}
const rsDrawBeforeExecution=rsDialogDraw;rsDialogDraw=function(){if(RS.dialog?.kind==='execution')rsExecutionDialog();else rsDrawBeforeExecution();};
const rsActionBeforeExecution=rsAction;rsAction=async function(b){
 if(b.dataset.rs==='prepare'){rsGuard();RS.dialog={kind:'execution',setId:RS.current.id,revision:RS.current.revision,roles:['baseline','fixed'],pending:false,error:''};rsDialogDraw();return;}
 if(b.dataset.rsResume||b.dataset.rsSubmit||b.dataset.rsPause){const id=b.dataset.rsResume||b.dataset.rsSubmit||b.dataset.rsPause;await api('/api/research-set-preparations/'+id+'/'+(b.dataset.rsResume?'resume':b.dataset.rsPause?'pause':'submit'),{});await rsOpen(RS.current.id,RS.current.revision);return;}
 const op=b.dataset.rsd,v=RS.dialog;if(v?.kind==='execution'&&op){if(v.pending)return;if(op==='close'){rsDialog().close();if(v.kind==='save'&&v.preview?.changed===false&&v.stamp===JSON.stringify([S.id,S.saved.revision,changes()])&&S.dirty){S.record=copy(S.saved);S.dirty=false;S.preview=null;resetConfiguration();render();notice('与保存版本相同，没有新增版本。');}return;}v.pending=true;v.error='';v.status='正在核对本组范围与资源…';rsDialogDraw();try{if(op==='check-run')v.preview=await api('/api/research-set-preflight',{id:v.setId,revision:v.revision,roles:v.roles});else{if(!v.preview)throw Error('请先核对。');await api('/api/research-set-preparations',{id:v.setId,revision:v.revision,roles:v.roles,set_sha256:v.preview.set_sha256,destination:v.preview.destination,submit:op==='start-run'});rsDialog().close();await rsOpen(v.setId,v.revision);notice(op==='start-run'?'本组已开始准备并依次提交；可离开页面，进度会保留。':'本组正在后台准备；不会自动启动计算。');}}catch(e){v.error=e.message;}finally{v.pending=false;if(rsDialog().open)rsDialogDraw();}return;}
 return rsActionBeforeExecution(b);
};
document.addEventListener('change',e=>{if(!e.target.dataset.rsRunRole||RS.dialog?.pending)return;const v=RS.dialog,k=e.target.dataset.rsRunRole;v.roles=e.target.checked?[...v.roles,k]:v.roles.filter(x=>x!==k);v.preview=null;rsDialogDraw();});
document.addEventListener('click',e=>{const b=e.target.closest('[data-rs-resume],[data-rs-submit],[data-rs-pause]');if(!b||b.disabled)return;e.stopImmediatePropagation();void rsAction(b).catch(e=>notice(e.message));},true);

document.addEventListener('change',event=>{
 if(event.target.id!=='rs-member-count'||RS.dialog?.kind!=='new'||RS.dialog.pending)return;
 const v=RS.dialog;v.memberCount=Number(event.target.value)===4?4:3;
 if(['三工况研究对比','四工况研究对比'].includes(v.name))v.name=v.memberCount===4?'四工况研究对比':'三工况研究对比';
 if(v.memberCount===3)delete v.selected.feedback;
 v.preview=null;v.error='';rsDialogDraw();
});
