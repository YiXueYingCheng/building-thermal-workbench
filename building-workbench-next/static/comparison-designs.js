/* Plan the expected differences first. Actual answers always use two pinned versions. */
// Only explicit, recognisable axis values can produce an exact suggestion.
function designMatches(v,base,axes){
 if(!base||!axes.length||!axes.every(([name,value])=>name&&value))return false;
 const facts=v.design,origin=base.design;
 if(facts.context!==origin.context||facts.material_key!==origin.material_key||!facts.optical_key)return false;
 const fields=new Set();
 for(const [name,value] of axes){
  const field=/^(?:表面)?光学(?:策略|切换|状态)?$/.test(name)?'optical':/^(?:材料)?热阻(?:策略|调节|状态)?$/.test(name)?'thermal':'';
  if(!field||fields.has(field)||facts[field]!==value)return false;
  fields.add(field);
 }
 return ['optical','thermal'].every(field=>fields.has(field)||facts[field+'_key']===origin[field+'_key']);
}
function designPinSummary(v){
 return '<strong>'+esc(v.design.summary)+'</strong><small>'+esc([v.design.material,themeVersion(v.ref),v.status].filter(Boolean).join(' · '))+'</small>';
}
function designPicker(st,trigger,{base,axes,bound,exclude,onPick}){
 const choosingBase=!axes;
 const {dialog,body}=st;
 const previous=document.createDocumentFragment(),scroll=body.scrollTop;
 previous.append(...body.childNodes);
 function back(){
  body.replaceChildren(previous);
  dialog.removeEventListener('cancel',cancel);
  body.scrollTop=scroll;trigger.focus({preventScroll:true});
 }
 function cancel(e){e.preventDefault();back();}
 dialog.addEventListener('cancel',cancel);
 const rows=st.catalog.versions.filter(v=>choosingBase||!base||v.building_key===base.building_key);
 const scopeKey=v=>JSON.stringify([v.building_key,v.places,v.period,v.step,v.mode]);
 const scopeLabel=v=>themeFacts([v])+' · '+({controlled:'温控',natural:'自然室温',both:'两种模式'}[v.mode]||v.mode);
 const scopes=new Map(rows.map(v=>[scopeKey(v),scopeLabel(v)]));
 const matches=rows.filter(v=>!choosingBase&&designMatches(v,base,axes)&&!exclude.has(themeKey(v.ref)));
 const scopeButtons=choosingBase?'<label class="field">建筑与计算范围<select data-scope-choice></select></label>':'';
 body.innerHTML='<button class="design-back" data-picker-back>← 返回设计</button><h3>'+ (choosingBase?'选择起始方案':'选择方案版本')+'</h3><div class="design-picker-head">'+(choosingBase?'':'<h3>'+esc(axes.map(a=>a[1]||a[0]||'待填').join(' · '))+'</h3><p>'+esc(base?scopeLabel(base):'请先选定起始方案')+'</p>')+
 scopeButtons+'<label class="field">查找方案<input type="search" data-search placeholder="工况、原方案名、版本或地点"></label></div><div data-picks></div>';
 const scope=body.querySelector('[data-scope-choice]'),search=body.querySelector('[data-search]'),picks=body.querySelector('[data-picks]');
 if(scope)scope.innerHTML=options([['','请选择计算范围，或直接搜索'],...scopes],base?scopeKey(base):'');
 const searchText=v=>[v.name,v.design.summary,v.design.material,scopeLabel(v),themeVersion(v.ref),v.status,v.note,...v.places].join(' ').toLocaleLowerCase();
 function draw(){
  const query=search.value.trim().toLocaleLowerCase();
  if(choosingBase&&!scope.value&&!query){picks.innerHTML='<p class="muted">选择范围后会列出该范围内的方案。</p>';return;}
  const filtered=rows.filter(v=>(!scope?.value||scopeKey(v)===scope.value)&&(!query||searchText(v).includes(query)));
  const primary=choosingBase?filtered:filtered.filter(v=>matches.includes(v));
  const keys=new Set();
  const latest=primary.slice().sort((a,b)=>Number(b.ref.revision||0)-Number(a.ref.revision||0)).filter(v=>{
   if(keys.has(v.ref.id))return false;
   keys.add(v.ref.id);return true;
  });
  const others=filtered.filter(v=>!latest.includes(v));
  const row=v=>{
   const key=themeKey(v.ref),used=exclude.has(key),selected=key===bound;
   return '<article class="design-pick"><div>'+designPinSummary(v)+'<span data-verbatim>'+esc(v.name)+'</span>'+(!scope?.value&&choosingBase||base&&v.design.context!==base.design.context?'<small>'+esc(scopeLabel(v))+'</small>':'')+'</div><button data-pin="'+esc(key)+'" '+(used?'disabled':'')+'>'+ (used?'其他格已选':selected?'当前选用':'选用')+'</button></article>';
  };
  const list=items=>items.map(row).join('');
  picks.innerHTML='<h3>'+(choosingBase?'可选方案':'符合本格设置')+' · '+latest.length+'</h3>'+
  (latest.length?list(latest):'<p class="muted">'+(choosingBase?'没有符合搜索条件的方案。':'没有找到与起始版本及本格设置完全匹配的方案。可先留空，或手动选择。')+'</p>')+
  (others.length?'<details class="design-others" '+(query?'open':'')+'><summary>'+(choosingBase?'其余保存版本':'手动选择 · 其他工况与历史版本')+' · '+others.length+'</summary>'+list(others)+'</details>':'');
  picks.querySelectorAll('[data-pin]').forEach(b=>b.onclick=()=>{back();onPick(b.dataset.pin);});
 }
 body.querySelector('[data-picker-back]').onclick=back;
 if(scope)scope.onchange=draw;search.oninput=draw;draw();body.scrollTop=0;(scope||search).focus();
}

const designReturnKey='workbench-design-budget-return';
try{
 const last=JSON.parse(sessionStorage.getItem(designReturnKey));
 if(last&&typeof last.id==='string'&&Number.isInteger(last.revision)&&Number.isInteger(last.cell)&&typeof last.reviewId==='string')S.designBudgetReturn=last;
}catch{}
function rememberDesignBudget(context){
 S.designBudgetReturn=context;
 try{
  if(context)sessionStorage.setItem(designReturnKey,JSON.stringify(context));
  else sessionStorage.removeItem(designReturnKey);
 }catch{}
}
function resumeCalculationDesign(context){
 rememberDesignBudget(null);
 S.comparePage='overview';S.view='compare';render();
 openComparisonDesign(document.querySelector('[data-design-start]'),context);
}

function designQueueBack(){
 const origin=S.designBudgetReturn;
 if(!origin||(S.executionReview&&S.executionReview.id!==origin.reviewId))return '';
 return '<button type="button" data-resume-calculation-design>返回对照设计</button>';
}

document.addEventListener('click',event=>{
 if(!event.target.closest('[data-resume-calculation-design]')||!S.designBudgetReturn)return;
 event.stopImmediatePropagation();resumeCalculationDesign(S.designBudgetReturn);
},true);

function openComparisonDesign(trigger,resume=null){
 const dialog=readingDialog(trigger,'先设计对照');
 dialog.classList.add('design-workspace');
 const body=dialog.querySelector('.rs-month-body');
 const st={dialog,body};
 const find=k=>body.querySelector('[data-'+k+']');
 const emptyAxis=()=>({name:'',values:['','']});
 const standardAxes={'热阻策略':['固定蓬松','固定压缩','按反馈调节热阻'],'表面光学策略':['固定 A','季节光学切换']};
 let draft,saved,bindings,view=0,catalogRequest;
 function start(record){
  saved=record;
  draft=record?structuredClone(record):{id:'design_'+crypto.randomUUID().replaceAll('-',''),revision:0,name:'',base:null,axes:[emptyAxis()]};
  bindings=new Map();
  if(record)slots().forEach((c,i)=>{if(record.cells[i])bindings.set(c.key,record.cells[i]);});
 }
 function slots(){
  return Array.from({length:2**draft.axes.length},(_,i)=>{
   const values=draft.axes.map((a,j)=>[a.name,a.values[(i>>(draft.axes.length-1-j))&1]]);
   return {key:JSON.stringify([draft.base,values]),values,label:values.map(v=>v[1]).join(' · ')};
  });
 }
 function page(html,focus){
  view++;
  body.innerHTML=html;body.scrollTop=0;
  const target=body.querySelector(focus||'h3');
  if(target){if(!target.matches('input,button,select'))target.tabIndex=-1;target.focus({preventScroll:true});}
 }
 const backButton='<button class="design-back" data-back>← 返回</button>';
 const note='<p role="status" class="warning" data-note></p>';
 function message(text){const el=find('note');if(el)el.textContent=text;}
 async function loadCatalog(){
  if(st.catalog)return;
  if(!catalogRequest)catalogRequest=api('/api/reading-collections?version-picker=1').then(catalog=>{
   themeLabels(catalog.versions);st.catalog=catalog;st.map=new Map(catalog.versions.map(v=>[themeKey(v.ref),v]));
  }).finally(()=>catalogRequest=null);
  await catalogRequest;
 }
 async function withCatalog(button,next){
  const seq=view;
  button.disabled=true;message('正在读取保存版本…');
  try{await loadCatalog();if(dialog.open&&view===seq){message('');next();}}
  catch(err){if(dialog.open&&view===seq)message(err.message);}
  finally{button.disabled=false;}
 }
 function get(ref){return ref&&st.map.get(themeKey(ref));}
 function home(){
  page('<form data-question><label class="field design-question">你想比较什么？<input data-title maxlength="100" required placeholder="例如，压缩后供暖需求怎样变化？"></label><div class="actions"><button class="primary" data-next>下一步</button></div></form>'+
   '<details class="design-library" data-history><summary>继续已保存的设计</summary><div data-list></div></details>'+note,'[data-title]');
  find('title').value=draft.name;
  find('title').oninput=e=>draft.name=e.target.value;
  find('question').onsubmit=e=>{
   e.preventDefault();draft.name=find('title').value.trim();
   if(!draft.name){message('请写下研究问题。');find('title').focus();return;}
   withCatalog(find('next'),()=>{
    if(!draft.base){const current=st.catalog.versions.find(v=>v.ref.id===S.record?.id&&v.ref.revision===S.record?.revision);draft.base=current?.ref||null;}
    setup();
   });
  };
  const history=find('history'),list=find('list');
  history.ontoggle=async()=>{
   if(!history.open||list.childElementCount)return;
   list.textContent='正在读取…';
   try{
    const {designs}=await api('/api/comparison-designs');
    if(!list.isConnected)return;
    list.innerHTML=designs.length?designs.map((d,i)=>'<button class="design-history-row" data-open="'+i+'">'+esc(d.name)+'</button>').join(''):'<p>尚无已保存的设计。</p>';
    list.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>withCatalog(b,()=>{start(designs[Number(b.dataset.open)]);summary();}));
   }catch(err){if(list.isConnected)list.textContent=err.message;}
  };
 }
 function setup(){
  const origin=get(draft.base);
  const axisMarkup=(a,i)=>{
   const values=standardAxes[a.name]||[];
   const kind=a.custom?'custom':values.length?a.name:a.name?'custom':'';
   return '<fieldset data-axis="'+i+'"><legend>'+(i?'第二个变化项':'要改变哪一项？')+'</legend><select aria-label="变化项" data-axis-kind>'+
    options([['','请选择'],...Object.keys(standardAxes).map(k=>[k,k]),['custom','自行填写']],kind)+'</select>'+
    '<label class="field" '+(kind==='custom'?'':'hidden')+'>变化项名称<input maxlength="64" data-name value="'+esc(a.name)+'" placeholder="例如，铺设范围"></label>'+
    '<div class="design-values" '+(kind?'':'hidden')+'>'+a.values.map((v,k)=>'<label class="field">'+(k?'与之比较':'从')+'<input maxlength="64" data-value list="design-values-'+i+'" value="'+esc(v)+'" placeholder="选择或填写"></label>').join('')+'</div><datalist id="design-values-'+i+'">'+values.map(v=>'<option value="'+esc(v)+'"></option>').join('')+'</datalist></fieldset>';
  };
  page(backButton+'<h3>'+esc(draft.name)+'</h3><div class="design-origin">'+(origin?'<div><small>起始方案 · '+esc(themeVersion(origin.ref))+'</small><strong data-verbatim>'+esc(origin.name)+'</strong><small>'+esc(themeFacts([origin]))+'</small></div>':'<span>选一份起始方案，沿用它的条件。</span>')+'<button data-base value="'+esc(draft.base?themeKey(draft.base):'')+'">'+(origin?'更换':'选择起始方案')+'</button></div>'+
    draft.axes.map(axisMarkup).join('')+'<button class="design-axis-toggle" data-toggle-axis>'+(draft.axes.length===1?'＋ 添加第二个变化项':'移除第二个变化项')+'</button>'+
    '<div class="actions"><button class="primary" data-conditions>查看工况</button></div>'+note);
  find('back').onclick=()=>saved?editQuestion():home();
  find('base').onclick=()=>designPicker(st,find('base'),{base:origin,bound:find('base').value,exclude:new Set(),onPick:key=>{draft.base=st.map.get(key).ref;setup();find('base').focus();}});
  body.querySelectorAll('[data-axis]').forEach((box,i)=>{
   const axis=draft.axes[i],name=box.querySelector('[data-name]'),fields=[...box.querySelectorAll('[data-value]')];
   box.querySelector('[data-axis-kind]').onchange=e=>{
    const kind=e.target.value;
    draft.axes[i]=kind&&kind!=='custom'?{name:kind,values:standardAxes[kind].slice(0,2)}:{...emptyAxis(),custom:kind==='custom'};
    setup();body.querySelector('[data-axis="'+i+'"] '+(kind==='custom'?'[data-name]':'[data-axis-kind]')).focus();
   };
   name.oninput=()=>{axis.name=name.value;};
   fields.forEach((el,k)=>el.oninput=()=>{axis.values[k]=el.value;});
  });
  find('toggle-axis').onclick=()=>{if(draft.axes.length===1)draft.axes.push(emptyAxis());else draft.axes.pop();setup();};
  find('conditions').onclick=()=>{
   for(const a of draft.axes){a.name=a.name.trim();a.values=a.values.map(v=>v.trim());}
   if(!draft.base){message('请选择起始方案。');find('base').focus();return;}
   if(draft.axes.some(a=>!a.name||a.values.some(v=>!v)||a.values[0]===a.values[1])||new Set(draft.axes.map(a=>a.name)).size!==draft.axes.length){
    message('每个变化项都需要名称和两种不同的取值。');return;
   }
   conditions();
  };
 }
 function editQuestion(){
  page(backButton+'<label class="field design-question">研究问题<input maxlength="100" data-title></label><div class="actions"><button class="primary" data-next>下一步</button></div>'+note,'[data-title]');
  find('title').value=draft.name;
  find('back').onclick=()=>{start(saved);summary();};
  find('next').onclick=()=>{const name=find('title').value.trim();if(!name){message('请写下研究问题。');return;}draft.name=name;setup();};
 }
 function conditions(){
  const cells=slots(),origin=get(draft.base);
  const used=new Set(cells.map(c=>bindings.get(c.key)).filter(Boolean).map(themeKey));
  page(backButton+'<h3>为工况选版本</h3><p class="muted">缺版本的工况可以留空，稍后接着选。</p><div data-cells>'+
   cells.map((c,i)=>{
    const pin=bindings.get(c.key),picked=get(pin);
    const matches=pin?[]:st.catalog.versions.filter(v=>!used.has(themeKey(v.ref))&&designMatches(v,origin,c.values));
    const only=matches.length===1?matches[0]:null;
    const pickLabel=pin?'更换':only?'其他版本':'选择版本';
    return '<article class="design-slot"><div><h4>'+esc(c.label)+'</h4>'+
     (picked?'<small>'+esc(['已选',picked.design.summary!==c.label?picked.design.summary:'',themeVersion(pin),picked.status].filter(Boolean).join(' · '))+'</small><details><summary>版本详情</summary><p>'+esc(picked.name)+'</p><p>'+esc(picked.design.summary)+'</p></details>':pin?'<small>来源暂不可读</small>':only?'<small>'+esc('匹配到 '+themeVersion(only.ref)+' · '+only.status)+'</small>':'<small>待选版本</small>')+
     '</div><div class="actions">'+(only?'<button data-use="'+esc(themeKey(only.ref))+'" data-index="'+i+'">选用匹配版本</button>':'')+
     '<button data-cell="'+i+'" value="'+esc(pin?themeKey(pin):'')+'">'+pickLabel+'</button>'+(pin?'<button data-clear="'+i+'">移出</button>':'')+'</div></article>';
   }).join('')+'</div><div class="actions"><button class="primary" data-save>保存设计</button></div>'+note);
  find('back').onclick=setup;
  function choose(i,key){
   if(key)bindings.set(cells[i].key,st.map.get(key).ref);else bindings.delete(cells[i].key);
   conditions();body.querySelector('[data-cell="'+i+'"]').focus();
  }
  body.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>choose(Number(b.dataset.index),b.dataset.use));
  body.querySelectorAll('[data-clear]').forEach(b=>b.onclick=()=>choose(Number(b.dataset.clear),''));
  body.querySelectorAll('[data-cell]').forEach(b=>b.onclick=()=>{
   const i=Number(b.dataset.cell),exclude=new Set(used);exclude.delete(b.value);
   designPicker(st,b,{base:origin,axes:cells[i].values,bound:b.value,exclude,onPick:key=>choose(i,key)});
  });
  find('save').onclick=async()=>{
   const seq=view,buttons=[...body.querySelectorAll('button')];
   buttons.forEach(b=>b.disabled=true);message('正在保存…');
   try{
    const result=await api('/api/reading-collections',{action:'save-design',id:draft.id,expected_revision:draft.revision,name:draft.name,base:draft.base,axes:draft.axes.map(({name,values})=>({name,values})),cells:cells.map(c=>bindings.get(c.key)||null)});
    if(dialog.open&&view===seq){start(result);summary('设计 v'+result.revision+' 已保存。');}
   }catch(err){if(view===seq){message(err.message);buttons.forEach(b=>b.disabled=false);}}
  };
 }
 const versionName=v=>esc(opticalText(v.name))+' · '+esc(themeVersion(v.ref));
 function changesTable(changes){
  const display=value=>typeof value==='number'?format(value,5).replace(/(\.\d*?[1-9])0+$|\.0+$/,'$1'):esc(value);
  return '<table class="table"><caption>本次改动</caption><thead><tr><th>项目</th><th>来源版本</th><th>目标工况</th></tr></thead><tbody>'+
   changes.map(c=>'<tr><th scope="row">'+esc(c.label)+'</th><td>'+display(c.before)+'</td><td>'+display(c.after)+'</td></tr>').join('')+'</tbody></table>';
 }
 async function resolveCell(cell,scope,rules={}){
  const context={cell,scope};
  const back=()=>summary('',context);
  page(backButton+'<h3>'+esc(slots()[cell].label)+'</h3><div data-resolution role="status">正在查找与本格输入匹配的保存版本…</div>'+note);
  const seq=view,box=find('resolution');
  find('back').onclick=back;
  const params={id:saved.id,revision:saved.revision,cell,rules};
  try{
   const r=await api('/api/reading-collections',{...params,action:'preview-design-cell'});
   if(!dialog.open||seq!==view)return;
   const source='<p>起始方案　<strong>'+versionName(r.source)+'</strong></p>';
   if(r.kind==='options'){
    box.innerHTML=source+'<p>有多套可用规则，请选择本次沿用的版本。</p>'+Object.entries(r.options).map(([field,opts])=>
     '<label class="field">'+(field==='thermal'?'热阻反馈':'光学切换日历')+'<select data-rule="'+field+'"><option value="">请选择</option>'+opts.map(o=>
      '<option value="'+esc(o.key)+'">'+versionName(o.version)+' · '+esc(o.detail)+'</option>').join('')+'</select></label>').join('')+'<button data-continue>预览所选规则</button>';
    find('continue').onclick=()=>{
     const picked={...rules};for(const select of box.querySelectorAll('[data-rule]')){
      if(!select.value){select.focus();message('请选择要沿用的规则。');return;}
      picked[select.dataset.rule]=select.value;
     }
     resolveCell(cell,scope,picked);
    };return;
   }
   if(r.kind==='existing'){
    box.innerHTML='<h4>已有匹配版本</h4>'+r.matches.map((v,i)=>
     '<label class="check"><input type="radio" name="design-existing" data-choice="'+i+'" '+(r.matches.length===1?'checked':'')+'><span>'+versionName(v)+(v.archived?' · 已归档':'')+(v.detail?'<br><small>'+esc(v.detail)+'</small>':'')+'</span></label>').join('')+
     '<button class="primary" data-confirm>选用已有版本并填回</button>';
   }else{
    const sites=r.sites.map(id=>S.boot.sites[id]?.name||id);
    box.innerHTML='<h4>派生预览</h4>'+source+'<p>新方案　<strong>'+esc(r.name)+' · v1</strong></p>'+
     '<p>'+esc(sites.length===1?sites[0]:sites.length+' 个地点')+' · '+esc(periodLabel(r.period))+' · '+esc(r.step)+' min</p>'+
     '<p>'+esc(r.material)+' · '+esc(r.walls)+' 个构件</p>'+changesTable(r.changes)+
     '<p class="muted">'+esc(r.source_state)+' → '+esc(r.target_state)+'。物性取自该材料的保存版本。</p>'+
     Object.entries(r.origins).map(([f,v])=>'<p>规则来源　'+versionName(v)+'<br><small>'+esc(r.rules[f])+'</small></p>').join('')+
     '<button class="primary" data-confirm>确认保存并填回原格</button>';
   }
   find('confirm').onclick=async e=>{
    const btn=e.currentTarget,chosen=box.querySelector('[data-choice]:checked');
    if(r.kind==='existing'&&!chosen){message('请选择要填入本格的版本。');return;}
    btn.disabled=true;find('back').disabled=true;message('正在保存…');
    let result;
    try{
     result=await api('/api/reading-collections',{...params,action:'confirm-design-cell',token:r.token,
      choice:chosen?r.matches[Number(chosen.dataset.choice)].ref:null});
    }catch(err){
     if(dialog.open&&seq===view){message(err.message);btn.disabled=false;find('back').disabled=false;}
     return;
    }
    try{
     st.catalog=null;await Promise.all([loadCatalog(),r.kind==='derive'?bootstrap():null]);
    }catch(err){
     if(dialog.open&&seq===view){box.textContent='工况已保存，请重新打开设计读取。';message(err.message);find('back').disabled=false;find('back').onclick=home;}
     return;
    }
    if(dialog.open&&seq===view){start(result);summary(r.kind==='derive'?'已保存独立方案并填回原格。':'已填入已有版本。',context);}
   };
  }catch(err){if(dialog.open&&seq===view){box.replaceChildren();message(err.message);}}
 }
 function summary(notice='',originCell=null){
  const cells=slots(),pins=saved.cells,origin=get(saved.base),count=pins.filter(Boolean).length;
  const edges=cells.length===2?[[0,1]]:[[0,1],[2,3],[0,2],[1,3]];
  const groups=[[cells.map((_,i)=>i).join(','),'全部工况'],...(cells.length===4?edges.map(([a,b])=>[a+','+b,cells[a].label+' → '+cells[b].label]):[])];
  const pairs=edges.filter(([a,b])=>get(pins[a])&&get(pins[b])).map(([a,b])=>[a+','+b,cells[a].label+' → '+cells[b].label]);
  page('<button class="design-back" data-home>← 返回设计首页</button><h3>'+esc(saved.name)+'</h3><p class="muted">'+esc(origin?themeFacts([origin]):'起始版本暂不可读')+'</p>'+
   '<p>'+cells.length+' 项工况，已选 '+count+' 项版本。</p>'+
   '<label class="field" '+(groups.length===1?'hidden':'')+'>核对范围<select data-scope>'+options(groups,groups[0][0])+'</select></label><div class="actions"><button class="primary" data-inspect>核对已有结果与缺项</button></div><div data-report aria-live="polite"></div>'+
   '<details class="design-library"><summary>查看或调整设计</summary><ul>'+cells.map((c,i)=>'<li>'+esc(c.label)+' · '+esc(get(pins[i])?.status||(pins[i]?'来源暂不可读':'尚未选择版本'))+'</li>').join('')+'</ul><button data-edit>编辑设计</button></details>'+
   (pairs.length?'<details class="design-library"><summary>比较两项已选工况</summary><label class="field">比较方向<select data-pair>'+options(pairs,pairs[0][0])+'</select></label><button data-read>读取差异</button><div data-answer></div></details>':'')+
   (count>=2?'<details class="design-library"><summary>用于对比集</summary><button data-collect>用已选版本建立对比集</button></details>':'')+'<p role="status" data-note>'+esc(notice)+'</p>');
  find('home').onclick=()=>{start(null);home();};
  find('edit').onclick=editQuestion;
  function request(select,button,box,loading,run,afterRender){
   let requestId=0;
   select.onchange=()=>{requestId++;box.replaceChildren();button.disabled=false;};
   button.onclick=async()=>{
    const id=++requestId;box.textContent=loading;button.disabled=true;
    try{const html=await run(select.value.split(',').map(Number));if(box.isConnected&&id===requestId){box.innerHTML=html;afterRender?.();}}
    catch(err){if(box.isConnected&&id===requestId)box.textContent=err.message;}
    finally{if(id===requestId)button.disabled=false;}
   };
  }
  const scope=find('scope'),report=find('report'),inspect=find('inspect');
  if(originCell&&groups.some(([value])=>value===originCell.scope))scope.value=originCell.scope;
  function siteResult(site){
   const loads=site.loads;
   return '<p>'+esc(site.city)+' · '+(site.mode==='controlled'?'温控':'自然室温')+' · '+esc(site.status)+'</p>'+
    (loads?'<p class="muted">供暖 '+format(loads.heating_kWh,2)+' · 制冷 '+format(loads.cooling_kWh,2)+' · 合计 '+format(loads.total_kWh,2)+' kWh</p>':'');
  }
  function cellReport(item){
   const pin=pins[item.cell],sites=item.sites,missing=sites.filter(s=>s.status==='已有方案，缺结果').length;
   const plan=!pin?'<button type="button" data-resolve-cell="'+item.cell+'">查找版本或预览派生</button>':missing?'<button type="button" data-plan-cell="'+item.cell+'">去计算此版本</button>':'';
   const receipt=saved.cell_origins?.[item.cell];
   const history=receipt?'<details><summary>版本来源</summary>'+(receipt.kind==='derive'?
    '<p>派生自　'+versionName(receipt.source)+'</p>'+changesTable(receipt.changes):'<p>选用已有保存版本。</p>')+'</details>':'';
   const details=sites.length===1?siteResult(sites[0]):sites.length?'<details><summary>地点与模式 · '+sites.length+'</summary>'+sites.map(siteResult).join('')+'</details>':'';
   const partial=plan&&missing<sites.length?'<p class="muted">计算安排将打开此版本的完整范围，请在预算中核对算例。</p>':'';
   return '<article class="design-slot" tabindex="-1" data-report-cell="'+item.cell+'"><div><strong>'+esc(cells[item.cell].label)+'</strong>'+
    (pin?' · '+esc(themeVersion(pin)):'')+(sites.length!==1?'<p>'+esc(item.status||[...new Set(sites.map(s=>s.status))].join('、'))+'</p>':'')+
    details+history+partial+'</div>'+plan+'</article>';
  }
  report.onclick=async event=>{
   const empty=event.target.closest('[data-resolve-cell]');
   if(empty){await resolveCell(Number(empty.dataset.resolveCell),scope.value);return;}
   const button=event.target.closest('[data-plan-cell]');if(!button||button.disabled)return;
   const cell=Number(button.dataset.planCell),pin=pins[cell],seq=view;
   button.disabled=true;
   try{
    rsGuard();
    const ok=await loadRecord(pin.id,pin.revision,()=>dialog.open&&view===seq&&button.isConnected);
    if(!ok)return;
    if(S.saved.id!==pin.id||S.saved.revision!==pin.revision)throw Error('读取的方案版本与本格不一致，请重新核对。');
    const context={id:saved.id,revision:saved.revision,cell,scope:scope.value,label:cells[cell].label};
    dialog.close();openInputFlow(true,context);
   }catch(e){message(e.message);}finally{button.disabled=false;}
  };
  request(scope,inspect,report,'正在核对结果…',async selected=>{
   const result=await api('/api/reading-collections',{action:'inspect-design',id:saved.id,revision:saved.revision,selected});
   return '<p><strong>已确认的缺项　'+result.missing_cases+' 个算例</strong></p>'+result.items.map(cellReport).join('')+result.notices.map(n=>'<p>'+esc(n)+'</p>').join('');
  },()=>{
   if(originCell){report.querySelector('[data-report-cell="'+originCell.cell+'"]')?.focus();originCell=null;}
  });
  inspect.click();
  if(pairs.length)request(find('pair'),find('read'),find('answer'),'正在读取差异…',async([a,b])=>{
   const data=await api('/api/compare/answer',{left:pins[a].id,left_revision:pins[a].revision,right:pins[b].id,right_revision:pins[b].revision,metric:'total'});
   return '<h4>'+esc(candidateQuestion(data))+'</h4><p>'+esc(data.question.basis)+'</p>'+pairAnswer(data);
  });
  if(find('collect'))find('collect').onclick=()=>{
   const initial={designName:saved.name,designMembers:pins.filter(Boolean)};
   dialog.addEventListener('close',()=>openTheme(trigger,'',initial),{once:true});dialog.close();
  };
 }
 start(null);
 if(!resume){home();return;}
 page('<p role="status">正在返回已保存的对照设计…</p>');
 Promise.all([api('/api/comparison-designs'),loadCatalog()]).then(([{designs}])=>{
  if(!dialog.open)return;
  const current=designs.find(d=>d.id===resume.id);
  if(!current)throw Error('原设计已不可用，请选择其他已保存的设计。');
  start(current);
  if(current.revision===resume.revision)summary('',resume);
  else summary('设计已有新版本，已重新核对当前工况。');
 }).catch(e=>{if(dialog.open){home();message(e.message);}});
}
