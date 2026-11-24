/* Membership is a research choice. Each numerical comparison pins its own sources. */
const themeKey=p=>JSON.stringify([p.id,p.revision]);
const themeVersion=p=>typeof p.revision==='number'?'v'+p.revision:'来源版';

function themeLabels(versions){
 const byBuilding=new Map();
 for(const v of versions){
  if(!byBuilding.has(v.building_key))byBuilding.set(v.building_key,[]);
  byBuilding.get(v.building_key).push(v);
 }
 for(const entries of byBuilding.values()){
  const names=entries.map(v=>opticalText(v.name).split(/\s*·\s*/));
  const prefixes=new Map();
  for(const name of new Set(names.map(p=>p.join('·')))){
   const parts=name.split('·');
   for(let n=1;n<parts.length;n++){
    const k=parts.slice(0,n).join('·');prefixes.set(k,(prefixes.get(k)||0)+1);
   }
  }
  for(let i=0;i<entries.length;i++){
   const parts=names[i];
   let cut=0;
   for(let n=1;n<parts.length;n++)if(prefixes.get(parts.slice(0,n).join('·'))>1)cut=n;
   entries[i].short=parts.slice(cut).join(' · ');
  }
 }
 const groups=new Map();
 for(const v of versions){
  const k=v.short;
  if(!groups.has(k))groups.set(k,[]);
  groups.get(k).push(v);
 }
 for(const v of versions){
  const same=groups.get(v.short);
  let label=v.short+' · '+themeVersion(v.ref);
  if(same.length>1&&v.step!=null)label+=' · '+v.step+' min';
  if(same.some(o=>o!==v&&o.ref.revision===v.ref.revision&&o.step===v.step)){
   const extra=v.name.split('·').map(t=>t.trim()).filter(t=>!v.short.includes(t)).slice(-1)[0];
   label+=' · '+(extra||v.building)+' · '+v.ref.id.slice(-6);
  }
  v.label=label;
 }
}

function themeFacts(rows){
 if(!rows.length)return '';
 const common=get=>{const set=new Set(rows.map(get));return set.size===1?[...set][0]:null;};
 const samePlaces=common(v=>JSON.stringify(v.places));
 const places=samePlaces?(rows[0].places.length>2?rows[0].places.length+' 个地点':rows[0].places.join('、')):'多个地点范围';
 return [common(v=>v.building)||'多栋建筑',places,
         common(v=>periodLabel(v.period))||'多个统计时段',common(v=>v.step+' min')||'多个求解步长'].join(' · ');
}

function templateSourceOptions(v,role){
 const current=v.selected[role]||'',q=(v.search||'').trim().toLocaleLowerCase();
 const rows=v.sources.filter(s=>s.ref.id+'|'+s.ref.revision===current||[s.name,s.label,s.building,s.note,s.status,...s.places,...s.sources.map(x=>x.name+' '+x.id)].join(' ').toLocaleLowerCase().includes(q));
 return options([['','请选择'],...rows.map(s=>[s.ref.id+'|'+s.ref.revision,s.label+' · '+s.status])],current);
}

function themeTemplateField(v,role,label){
 const source=v.sources.find(s=>s.ref.id+'|'+s.ref.revision===v.selected[role]);
 return '<section><label class="field">'+esc(label)+' · 来源保存版本<select data-rs-source="'+esc(role)+'">'+templateSourceOptions(v,role)+'</select></label>'+(source?themeDetail(source):'')+'</section>';
}

document.addEventListener('input',event=>{
 if(event.target.id!=='rs-source-filter'||RS.dialog?.kind!=='new')return;
 RS.dialog.search=event.target.value;
 rsDialog().querySelectorAll('[data-rs-source]').forEach(el=>el.innerHTML=templateSourceOptions(RS.dialog,el.dataset.rsSource));
});

function themeDetail(v){
 return '<details class="theme-source"><summary>来源详情</summary><div data-verbatim>'+esc(v.name)+'</div><small>'+esc(themeFacts([v]))+'</small>'+(v.places.length>2?'<p>'+esc(v.places.join('、'))+'</p>':'')+
  (v.note?'<p data-verbatim>'+esc(v.note)+'</p>':'')+v.sources.map(s=>'<p>'+esc(s.status)+' · <span data-verbatim>'+esc(s.name)+'</span><br><small>'+esc(s.id)+'</small></p>').join('')+'</details>';
}

function themeError(body,msg){
 const err=body.querySelector('[data-theme-message]');
 if(err)err.textContent=msg;
}

async function openTheme(trigger,id='',initial=null){
 const parent=trigger.closest('dialog');
 const fromCandidates=parent?.classList.contains('group-candidates-dialog');
 const reuse=id&&!fromCandidates&&parent?.classList.contains('reading-collection-dialog');
 const dialog=reuse?parent:readingDialog(trigger,id?'管理成员与逐对核对':'建立对比集');
 dialog.classList.add('theme-dialog');
 const body=dialog.querySelector('.rs-month-body');
 try{
  const [catalog,detail]=await Promise.all([api('/api/reading-collections?version-picker=1'),
    id?api('/api/reading-collections?group='+encodeURIComponent(id)):null]);
  if(!dialog.open)return;
  themeLabels(catalog.versions);
  const map=new Map(catalog.versions.map(v=>[themeKey(v.ref),v]));
  const state={id:id||'reading_'+crypto.randomUUID().replaceAll('-',''),name:detail?.group.name||initial?.designName||'',designMembers:initial?.designMembers,snap:detail?.group.membership,
    history:detail?.group.member_history||[],initial:id?initial:null,catalog,map,dialog,body,parent,trigger};
  if(fromCandidates){
   state.fromCandidates=true;
   dialog.querySelector('[data-close]').textContent='返回方案候选';
   dialog.addEventListener('close',()=>{if(state.changed&&parent.open)initial?.afterChange?.();},{once:true});
   if(initial?.revision!==state.snap.revision){
    state.initial=null;
    themeHome(state);
    themeError(body,'成员版本已更新，请重新选择这次要核对的两项。');
    state.changed=true;
    return;
   }
  }
  if(id)themeHome(state);
  else themeEdit(state);
 }catch(e){body.textContent=e.message;}
}

function themeEdit(st){
 const {body,map,catalog,snap}=st;
 setReadingTitle(st.dialog,snap?'编辑本组成员':'建立对比集');
 const chosen=new Set((snap?.members||st.designMembers||[]).map(themeKey)),relations=new Set();
 let mode=st.designMembers?.length?'selected':'versions',page=0;
 const buildingNames=new Map(catalog.versions.map(v=>[v.building_key,v.building]));
 const preferred=(snap?.members?.length?map.get(themeKey(snap.members[0])):null)||catalog.versions.find(v=>v.building_id===S.record?.factors?.building?.id);
 body.innerHTML='<div class="theme-question"><label class="field">研究问题<input data-title maxlength="100" placeholder="例如，夏季外墙材料如何影响制冷需求？" '+(snap?'readonly':'')+'></label>'+
  (!snap&&!st.designMembers?'<button type="button" data-eca-template>使用 ECA 工况模板</button>':'')+'</div>'+
  '<div class="theme-controls"><label class="field">建筑<select data-building></select></label><label class="field">查找方案或对照<input data-query type="search" placeholder="名称、版本、备注或批次"></label></div>'+
  '<div class="actions theme-modes"><button data-mode="versions">选方案版本</button><button data-mode="pairs">选已有对照</button><button data-mode="selected">已选成员</button></div><div data-rows></div><div data-pager class="actions"></div>'+
  '<div class="theme-bottom"><label class="field">共同参考（可选）<select data-reference></select></label><div class="actions"><button class="primary" data-save-members>保存成员</button>'+(snap?'<button data-back>返回本组</button>':'')+'</div></div><p role="status" data-theme-message></p>';
 const name=body.querySelector('[data-title]'),building=body.querySelector('[data-building]'),search=body.querySelector('[data-query]'),rows=body.querySelector('[data-rows]');
 name.value=st.name;
 const templateButton=body.querySelector('[data-eca-template]');
 if(templateButton)templateButton.onclick=()=>{
  try{rsGuard();}catch(err){themeError(body,err.message);return;}
  const dialog=st.dialog;
  dialog.addEventListener('close',()=>rsNew(catalog.versions,name.value.trim(),()=>{
   document.body.append(dialog);
   dialog.showModal();
   templateButton.focus({preventScroll:true});
  }),{once:true});
  dialog.close();
 };
 building.innerHTML=options([['','全部建筑'],...buildingNames],preferred?.building_key||'');
 const reference=body.querySelector('[data-reference]');
 function sync(){
  const prev=reference.value;
  const picked=[...chosen].map(k=>map.get(k)).filter(Boolean);
  reference.innerHTML=options([['','逐对指定'],...picked.map(v=>[themeKey(v.ref),v.label])],prev);
  body.querySelector('[data-mode="selected"]').textContent='已选成员 · '+chosen.size;
  body.querySelector('[data-save-members]').disabled=chosen.size<2||!name.value.trim();
 }
 function remove(key){
  chosen.delete(key);
  for(const r of catalog.comparisons)if([themeKey(r.left),themeKey(r.right)].includes(key))relations.delete(r.id);
 }
 function draw(){
  const query=search.value.trim().toLocaleLowerCase(),b=building.value;
  const searchable=v=>[v.name,v.label,v.note,v.building,...v.places,...v.sources.map(s=>s.id+' '+s.name+' '+s.status)].join(' ').toLocaleLowerCase();
  const match=v=>(!b||v.building_key===b)&&(!query||searchable(v).includes(query));
  let list=mode==='pairs'?catalog.comparisons.filter(r=>{
   const a=map.get(themeKey(r.left)),c=map.get(themeKey(r.right));
   return a&&c&&(!b||a.building_key===b||c.building_key===b)&&(!query||(r.name+' '+searchable(a)+' '+searchable(c)).toLocaleLowerCase().includes(query));
  }):catalog.versions.filter(v=>mode==='selected'?chosen.has(themeKey(v.ref)):match(v));
  const pages=Math.max(1,Math.ceil(list.length/12));page=Math.min(page,pages-1);
  rows.innerHTML=list.slice(page*12,page*12+12).map(item=>{
   if(mode==='pairs'){
    const a=map.get(themeKey(item.left)),c=map.get(themeKey(item.right));
    return '<article class="theme-choice"><label><input type="checkbox" data-rel="'+esc(item.id)+'" '+(relations.has(item.id)?'checked':'')+'><span>'+esc(a.label)+' → '+esc(c.label)+'</span></label><small>'+esc(a.status+' / '+c.status)+'</small><details><summary>对照详情</summary><p data-verbatim>'+esc(item.name)+'</p>'+themeDetail(a)+themeDetail(c)+'</details></article>';
   }
   const k=themeKey(item.ref);
   return '<article class="theme-choice"><label><input type="checkbox" data-member="'+esc(k)+'" '+(chosen.has(k)?'checked':'')+'><span>'+esc(item.label)+'</span></label><small class="'+(item.status==='核查未通过'?'warning':'')+'">'+esc(item.status)+'</small>'+themeDetail(item)+'</article>';
  }).join('')||'<p>当前选择下没有匹配项。</p>';
  body.querySelector('[data-pager]').innerHTML=pages>1?'<button data-prev '+(page===0?'disabled':'')+'>上一页</button><small>'+(page+1)+' / '+pages+'</small><button data-next-page '+(page===pages-1?'disabled':'')+'>下一页</button>':'';
  body.querySelectorAll('[data-mode]').forEach(btn=>btn.setAttribute('aria-pressed',String(mode===btn.dataset.mode)));
  sync();
 }
 body.querySelector('[data-pager]').onclick=e=>{if(e.target.closest('[data-prev]'))page--;else if(e.target.closest('[data-next-page]'))page++;else return;draw();};
 rows.onchange=e=>{
  const el=e.target;
  if(el.hasAttribute('data-member')){
   if(el.checked)chosen.add(el.dataset.member);else remove(el.dataset.member);
  }else if(el.hasAttribute('data-rel')){
   if(el.checked){relations.add(el.dataset.rel);const r=catalog.comparisons.find(v=>v.id===el.dataset.rel);chosen.add(themeKey(r.left));chosen.add(themeKey(r.right));}
   else relations.delete(el.dataset.rel);
  }else return;
  if(mode==='selected')draw();else sync();
 };
 building.onchange=search.oninput=()=>{page=0;draw();};name.oninput=sync;
 body.querySelectorAll('[data-mode]').forEach(btn=>btn.onclick=()=>{mode=btn.dataset.mode;page=0;draw();});
 if(snap)body.querySelector('[data-back]').onclick=()=>themeHome(st);
 body.querySelector('[data-save-members]').onclick=async e=>{
  const btn=e.currentTarget;btn.disabled=true;
  try{
   const result=await api('/api/reading-collections',{action:'save-members',group:st.id,name:name.value.trim(),expected_revision:snap?.revision||0,
    members:[...chosen].map(k=>map.get(k).ref),reference:reference.value?map.get(reference.value).ref:null,comparisons:[...relations]});
   st.changed=true;
   if(st.dialog.open)await showReadingGroup(st.dialog,result.group);
  }catch(err){themeError(body,err.message);btn.disabled=false;}
 };
 draw();if(snap?.reference)reference.value=themeKey(snap.reference);
}

function themeHome(st){
 const {body,map,snap}=st,picked=snap.members.map(p=>map.get(themeKey(p)));
 setReadingTitle(st.dialog,st.name);
 body.innerHTML='<div class="theme-home-head"><div><strong>'+esc(themeFacts(picked))+'</strong><p>'+picked.length+' 个成员 · 成员版本 '+snap.revision+'</p></div><button data-edit>增减成员与共同参考</button></div>'+
  '<h3>选择这次要比较的两项</h3><div class="theme-controls"><label class="field">参考<select data-side="left"></select></label><label class="field">研究<select data-side="right"></select></label></div>'+
  '<div class="theme-controls" data-sources></div><div data-relations></div><label class="field">指标<select data-metric></select></label><div class="actions"><button class="primary" data-preview>核对这两项</button><button data-group-candidates="'+esc(st.id)+'" data-candidate-context="reading">已有答案与方案候选</button><button data-readings>查看已收录对照</button></div><p data-theme-message role="status"></p><div data-result aria-live="polite"></div>'+
  '<details class="theme-history"><summary>成员与版本记录</summary>'+st.history.map(h=>'<p>v'+esc(h.revision)+' · '+h.members.map(p=>esc(map.get(themeKey(p))?.label||p.id)).join('、')+(h.reference?' · 共同参考 '+esc(map.get(themeKey(h.reference))?.label||h.reference.id):'')+'</p>').join('')+'</details>';
 const selects=[...body.querySelectorAll('[data-side]')],metric=body.querySelector('[data-metric]'),preview=body.querySelector('[data-preview]'),result=body.querySelector('[data-result]');
 const initial=st.initial;st.initial=null;
 const left=initial?.left||snap.reference||picked[0].ref,right=initial?.right||picked.find(v=>themeKey(v.ref)!==themeKey(left)).ref;
 for(const [i,s] of selects.entries())s.innerHTML=options(picked.map(v=>[themeKey(v.ref),v.label+' · '+v.status]),themeKey(i?right:left));
 let generation=0;
 function current(){return selects.map(s=>map.get(s.value));}
 function reset(){
  generation++;result.replaceChildren();themeError(body,'');
  const [a,b]=current();
  const invalid=themeKey(a.ref)===themeKey(b.ref)?'请选择两个不同的版本。':a.building_key!==b.building_key?'这两项属于不同建筑。请选择同一栋建筑的两项做定量比较。':'';
  metric.innerHTML=options(a.mode==='natural'||b.mode==='natural'?[['temperature','室温表现']]:[['total','供暖、制冷与合计'],['heating','供暖'],['cooling','制冷'],['temperature','室温表现']],metric.value||'total');
  themeError(body,invalid);preview.disabled=!!invalid;
  function sources(){
   generation++;result.replaceChildren();
   const matches=st.catalog.comparisons.filter(r=>themeKey(r.left)===themeKey(a.ref)&&themeKey(r.right)===themeKey(b.ref)&&r.metric===metric.value);
   body.querySelector('[data-relations]').innerHTML=matches.length>1?'<label class="field">已有两两对照<select data-relation>'+options([['','请选择已有对照'],...matches.map(r=>[r.id,r.name+' · '+r.id.slice(-8)])],initial?.relation||'')+'</select></label>':'';
   const relation=body.querySelector('[data-relation]');
   if(relation)relation.onchange=()=>{generation++;result.replaceChildren();};
   body.querySelector('[data-sources]').innerHTML=[a,b].map((v,i)=>{
    const mode=metric.value==='temperature'&&[a,b].some(x=>x.mode==='natural')?'natural':'controlled';
    const items=v.sources.filter(s=>s.modes.includes(mode));
    const labels=items.map(s=>{
     const date=s.name.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
     return items.length===1?s.status:s.status+' · '+(date?date[0].replace('T',' '):s.id==='historical'?'历史结果':'保存快照');
    });
    const choices=items.map((s,i)=>[s.id,labels[i]+(labels.indexOf(labels[i])!==labels.lastIndexOf(labels[i])?' · '+s.id.slice(-6):'')]);
    return '<section><label class="field">'+(i?'研究':'参考')+'结果来源<select data-batch '+(items.length<2?'disabled':'')+'>'+options([...(items.length===1?[]:[['',items.length?'请选择批次':'尚无来源']]),...choices],items.length===1?items[0].id:'')+'</select></label>'+themeDetail(v)+'</section>';
   }).join('');
   body.querySelectorAll('[data-batch]').forEach(s=>s.onchange=()=>{generation++;result.replaceChildren();});
  }
  sources();metric.onchange=sources;
 }
 selects.forEach(s=>s.onchange=reset);reset();
 if(initial){
  metric.value=initial.metric;metric.onchange();
  body.querySelectorAll('[data-batch]').forEach((s,i)=>{const id=initial.sources[i];if(id&&[...s.options].some(o=>o.value===id))s.value=id;});
 }
 if(st.fromCandidates){
  for(const selector of ['[data-edit]','[data-readings]','[data-group-candidates]','.theme-history'])body.querySelector(selector).remove();
 }else{
  body.querySelector('[data-edit]').onclick=()=>themeEdit(st);
  body.querySelector('[data-readings]').onclick=()=>showReadingGroup(st.dialog,st.id);
 }
 preview.onclick=async()=>{
  const seq=++generation;const [a,b]=current();
  const batches=[...body.querySelectorAll('[data-batch]')];
  const relation=body.querySelector('[data-relation]');
  if(relation&&!relation.value){themeError(body,'请选择要核对的已有对照。');return;}
  if(batches.some(s=>s.options.length>1&&!s.value)){themeError(body,'请选择要核对的批次。');return;}
  const request={group:st.id,revision:snap.revision,left:a.ref,right:b.ref,metric:metric.value,comparison:body.querySelector('[data-relation]')?.value||null,left_source:batches[0].value||null,right_source:batches[1].value||null};
  result.textContent='正在核对逐地点结果…';themeError(body,'');
  try{
   const p=await api('/api/reading-collections',{...request,action:'preview-pair'});
   if(!st.dialog.open||seq!==generation||!result.isConnected)return;
   const eq=p.audit.rows.filter(r=>r.equal),diff=p.audit.rows.filter(r=>!r.equal);
   result.innerHTML='<h3>'+esc(candidateQuestion(p.data))+'</h3><p>'+esc(p.data.question.basis)+'</p><p>共同项 · '+esc(eq.map(r=>r.label).join('、')||'无')+'<br>变化项 · '+esc(diff.map(r=>r.label).join('、')||'无')+'</p>'+pairAnswer(p.data)+'<button data-keep>收录本次核对</button>';
   if(p.archive_candidate){
    const btn=result.querySelector('[data-keep]');
    const note=document.createElement('p');
    note.textContent='同一份组导出保存了双方已核验的显热需求，可以从这份来源读出差额。';
    btn.before(note);
    btn.textContent='核对已有的组导出';
    btn.onclick=()=>openArchivePair(btn,st.id,snap.revision,p.archive_candidate,()=>{
     st.changed=true;
     if(seq===generation&&result.isConnected){btn.textContent='已收录归档结果';btn.disabled=true;}
    });
    return;
   }
   if(p.notices?.length)themeError(body,p.notices.join(' '));
   result.querySelector('[data-keep]').onclick=async e=>{
    const btn=e.currentTarget;btn.disabled=true;
    try{
     const saved=await api('/api/reading-collections',{...request,action:'keep-pair',token:p.token});
     st.changed=true;
     if(seq===generation&&result.isConnected){btn.textContent=saved.added?'已收录':'已在本集';await bootstrap();}
    }catch(err){if(result.isConnected){themeError(body,err.message);btn.disabled=false;}}
   };
  }catch(err){if(seq===generation&&result.isConnected){result.replaceChildren();themeError(body,err.message);}}
 };
}

document.addEventListener('click',e=>{
 const btn=e.target.closest('[data-theme-build],[data-theme-members],[data-design-start]');
 if(!btn)return;
 e.stopImmediatePropagation();
 if(btn.hasAttribute('data-design-start'))openComparisonDesign(btn);
 else openTheme(btn,btn.dataset.themeMembers);
},true);
