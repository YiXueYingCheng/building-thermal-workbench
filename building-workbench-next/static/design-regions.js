/* Regional selections and saved groups belong to the source research design. */
const regionDrafts = new Map();
const regionPlanPositions = new Map();

function openRegionPlans(button,id,group){
 const dialog=readingDialog(button,'地区组计算方案'),body=dialog.querySelector('.rs-month-body');
 const req={action:'preview-region-plans',id,group},key=JSON.stringify(req);
 const position=recentCandidate(regionPlanPositions,key,{open:new Set(),y:0},12);
 dialog.classList.add('region-design');
 dialog.querySelector('[data-close]').textContent='返回地区组';
 body.addEventListener('scroll',()=>{if(dialog.open&&body.clientHeight&&body.querySelector('[data-plan-list]'))position.y=body.scrollTop;});
 body.addEventListener('toggle',e=>{
  const section=e.target.dataset.regionSection;if(!section||!dialog.open)return;
  if(e.target.open)position.open.add(section);else position.open.delete(section);
 },true);
 const restore=k=>position.open.has(k)?' open':'';
 function failure(err){
  if(!dialog.open)return;
  body.innerHTML='<p role="alert">'+esc(err.message)+'</p><button type="button">重新核对</button>';
  body.querySelector('button').onclick=()=>read(true);
 }
 async function read(force=false){
  body.textContent='正在核对缺项、当地日历和可复用方案…';
  try{const data=await cachedCandidateRead(key,()=>api('/api/reading-collections',req),force);if(dialog.open)show(data);}
  catch(err){failure(err);}
 }
 function show(data){
  const items=[...data.plans,...data.previous],pending=data.plans.filter(p=>!p.linked);
  const openButton=(p,i)=>'<button type="button" data-open-region-plan="'+i+'">'+(p.daily?'准备逐日参考':'打开计算安排')+'</button>';
  const scopes=p=>p.sites.map(s=>S.boot.sites[s]?.name||s).join('、');
  const blocks=data.plans.map((p,i)=>{
   const name=p.version?esc(p.version.name)+' · v'+p.version.revision:esc(p.label);
   const status=p.linked?'已关联方案':p.version?'已有匹配版本，可关联':'待派生';
   return '<article class="region-plan"><div><h3>'+name+'</h3><p>'+esc(status)+' · '+p.sites.length+' 地点 · '+p.step+' min</p>'+
    '<details data-region-section="'+esc(p.slot)+'"'+restore(p.slot)+'><summary>来源与地点</summary><p>'+esc(p.source.name)+' · v'+p.source.revision+'</p><p>'+esc(scopes(p))+'</p></details></div>'+
    (p.linked?openButton(p,i):'')+'</article>';
  }).join('');
  body.innerHTML='<div data-plan-list>'+blocks+'</div>'+
   data.waiting.map(w=>'<p class="region-plan-wait"><strong>'+esc(w.label)+'</strong> · '+w.count+' 地点<br>'+esc(w.reason)+'</p>').join('')+
   (data.warnings||[]).map(s=>'<p class="warning">'+esc(s)+'</p>').join('')+
   (data.counts.reuse?'<p class="muted">'+data.counts.reuse+' 项已有核验结果已排除。</p>':'')+
   (data.counts.existing||data.counts.check?'<p class="muted">已有任务 '+(data.counts.existing||0)+' 项，待核对 '+(data.counts.check||0)+' 项。</p>':'')+
   (!data.plans.length&&!data.waiting.length?'<p>当前范围没有可派生的缺项。</p>':'')+
   (pending.length?'<button type="button" data-save-plans class="primary">确认派生或关联 '+pending.length+' 份方案</button>':'')+
   (data.previous.length?'<details data-region-section="previous"'+restore('previous')+'><summary>此前已关联的版本</summary>'+data.previous.map((p,j)=>'<p>'+esc(p.version.name)+' · v'+p.version.revision+' '+openButton(p,data.plans.length+j)+'</p>').join('')+'</details>':'')+
   '<p data-notice role="status">'+(pending.length?'本次只保存方案版本。生成输入、核对预算和提交计算另行操作。':'')+'</p>';
  body.scrollTop=position.y;
  const notice=body.querySelector('[data-notice]'),save=body.querySelector('[data-save-plans]');
  if(save)save.onclick=async()=>{
   if(save.disabled)return;
   save.disabled=true;notice.textContent='正在重新核对并保存方案…';
   try{
    const saved=await api('/api/reading-collections',{action:'derive-region-plans',id,group,preview_key:data.preview_key});
    await bootstrap();
    if(dialog.open)show(saved);
   }catch(err){failure(err);}
  };
  body.querySelectorAll('[data-open-region-plan]').forEach(el=>el.onclick=async()=>{
   if(el.disabled)return;
   const p=items[Number(el.dataset.openRegionPlan)];
   el.disabled=true;
   try{
    rsGuard();
    if(!await loadRecord(p.version.id,p.version.revision,()=>dialog.open&&el.isConnected))return;
    if(p.daily)await openDailyReference();else openInputFlow(true,null,null,el);
   }catch(err){notice.textContent=err.message;}finally{el.disabled=false;}
  });
 }
 void read();
}

function openDesignRegions(trigger, design, cells, inspected, scope, getVersion, libraryOnly=false){
 const dialog=readingDialog(trigger,'扩展到其他地点'), body=dialog.querySelector('.rs-month-body');
 dialog.classList.add('region-design');
 dialog.querySelector('[data-close]').textContent='返回设计';
 const checked=new Map(inspected.items.map(item=>[item.cell,item.sites]));
 const originalSites=new Set(inspected.items.flatMap(item=>item.sites.map(s=>s.site)));
 const hasResults=i=>checked.get(i)?.some(s=>s.status==='已有核验结果');
 const ready=scope.filter(i=>design.cells[i]&&hasResults(i));
 const selected=scope.length===2?scope.filter(i=>design.cells[i]):ready;
 const state=recentCandidate(regionDrafts,JSON.stringify([design.id,design.revision,scope]),{
  cells:new Set(selected.length>=2?selected:scope.filter(i=>design.cells[i])),
  sites:new Set(originalSites),stage:'cells',query:'',zone:'',gaps:false,offset:0,openSources:new Set(),group:null
 },12);
 const sites=Object.values(S.boot.sites).filter(s=>s.eligible&&s.weather?.sha256);
 const names=new Map(sites.map(s=>[s.id,s]));
 const climateNames=new Map((S.boot.climate_classes||[]).map(c=>[c.climate,c.name]));
 let seq=0;
 const find=k=>body.querySelector('[data-'+k+']');
 function page(stage,html){
  seq++;state.stage=stage;dialog.classList.toggle('region-wide',stage==='report');body.innerHTML=html;body.scrollTop=0;
 }
 function moving(stage){state.offset=0;state.stage=stage;}
 body.addEventListener('scroll',()=>{if(state.stage==='report'&&find('rows')&&body.offsetHeight)state.offset=body.scrollTop;});
 const back='<button type="button" class="design-back" data-back>← 返回</button>';
 const libraryButton='<button type="button" data-library>已派生地区组</button>';
 async function library(){
  page('library',back+'<h3>已派生地区组</h3><div data-list role="status">正在读取…</div>');
  find('back').onclick=()=>{state.group=null;state.offset=0;if(libraryOnly)dialog.close();else if(state.libraryFrom==='report')read();else chooseCells();};
  const list=find('list');
  try{
   const {groups}=await api('/api/reading-collections',{action:'list-design-region-groups',id:design.id});
   if(!list.isConnected)return;
   list.innerHTML=groups.map(g=>'<button type="button" class="region-group-link" data-group="'+esc(g.id)+'"><strong>'+esc(g.name)+'</strong><small>原设计 v'+g.revision+' · '+g.member_count+' 项工况 · '+g.site_count+' 个地点</small></button>').join('')||'<p>这份设计还没有地区组。选好工况和地点后，可以在预览中保存。</p>';
   list.onclick=e=>{const el=e.target.closest('[data-group]');if(el){state.group=el.dataset.group;state.offset=0;read();}};
  }catch(e){if(list.isConnected){list.textContent=e.message;const retry=document.createElement('button');retry.textContent='重新读取';retry.onclick=library;list.append(retry);}}
 }
 function bindLibrary(from){
  find('library').onclick=()=>{state.libraryFrom=from;library();};
 }
 function chooseCells(){
  const choices=cells.map((c,i)=>{
   const pin=design.cells[i],v=pin&&getVersion(pin);
   const label=hasResults(i)?'已有核验结果':pin?'已保存版本':'尚未选择版本';
   return '<label class="region-cell"><input type="checkbox" data-cell-id="'+i+'" '+(state.cells.has(i)?'checked ':'')+(pin?'':'disabled')+'><span><b>'+esc(c.label)+'</b><small>'+esc([pin&&themeVersion(pin),v?.step&&v.step+' min',label].filter(Boolean).join(' · '))+'</small></span></label>';
  });
  page('cells','<div class="region-heading"><h3>选择要比较的工况</h3>'+libraryButton+'</div><p class="muted">'+esc(design.name)+'</p><div class="region-cells">'+choices.join('')+'</div><div class="region-footer"><span data-count></span><button type="button" data-next class="primary">选择地点</button></div>');
  bindLibrary('cells');
  const update=()=>{find('next').disabled=state.cells.size<2;find('count').textContent=state.cells.size<2?'请至少选两项':'已选 '+state.cells.size+' 项工况';};
  body.querySelectorAll('[data-cell-id]').forEach(el=>el.onchange=()=>{const i=Number(el.dataset.cellId);if(el.checked)state.cells.add(i);else state.cells.delete(i);update();});
  find('next').onclick=()=>{moving('sites');chooseSites();};
  update();
 }
 function chooseSites(){
  const zones=new Map();
  const stationKey=site=>JSON.stringify([site.name,site.weather.sha256]);
  for(const site of sites){
   const zone=site.climate||'unclassified';
   if(!zones.has(zone))zones.set(zone,new Map());
   const key=stationKey(site),old=zones.get(zone).get(key);
   if(!old||originalSites.has(site.id)||(!originalSites.has(old.id)&&state.sites.has(site.id)))zones.get(zone).set(key,site);
  }
  page('sites',back+'<h3>选择研究地点</h3><p class="muted">'+esc([...state.cells].sort().map(i=>cells[i].label).join(' ／ '))+'</p>'+
   '<div class="actions"><button type="button" data-preset>选用中国 34 地区预设</button><button type="button" data-clear>清空地点</button></div>'+
   '<div class="region-zone"><label class="field">按气候分区选站 · Köppen–Geiger<select data-zone><option value="">全部气候类型</option>'+[...zones.keys()].sort().map(z=>'<option value="'+esc(z)+'">'+esc(z==='unclassified'?'未标注分区':[z,climateNames.get(z)].filter(Boolean).join(' · '))+'</option>').join('')+'</select></label><button type="button" data-add-zone></button></div>'+
   '<label class="field">查找地点<input type="search" data-search placeholder="地点或气候类型"></label><div class="region-sites" data-sites></div><p role="status" data-message></p>'+
   '<div class="region-footer"><span data-count></span><button type="button" class="primary" data-next>预览地区扩展</button></div>');
  find('back').onclick=()=>{moving('cells');chooseCells();};
  const update=()=>{find('next').disabled=!state.sites.size;find('count').textContent='已选 '+state.sites.size+' 个地点';};
  function zoneSites(zone){
   const picks=new Map(zone);
   for(const id of state.sites){
    const site=names.get(id);
    if(site&&(site.climate||'unclassified')===state.zone)picks.set(stationKey(site),site);
   }
   return [...picks.values()];
  }
  function draw(){
   const q=state.query.toLocaleLowerCase().trim();
   const zone=zones.get(state.zone);
   const list=(zone?zoneSites(zone):sites).filter(s=>[s.name,s.climate,s.id].join(' ').toLocaleLowerCase().includes(q));
   find('add-zone').hidden=!zone;
   find('add-zone').textContent=zone?'加入全部 '+zone.size+' 个地点':'';
   find('sites').innerHTML=list.map(s=>'<label><input type="checkbox" data-site-id="'+esc(s.id)+'" '+(state.sites.has(s.id)?'checked':'')+'><span>'+esc(s.name)+'<small>'+esc([s.climate||'未标注分区',originalSites.has(s.id)?'设计原地点':''].filter(Boolean).join(' · '))+'</small></span></label>').join('')||'<p>没有匹配地点</p>';
   update();
  }
  find('zone').value=state.zone||'';
  find('zone').onchange=e=>{state.zone=e.target.value;find('message').textContent='';draw();};
  find('add-zone').onclick=()=>{for(const site of zoneSites(zones.get(state.zone)))state.sites.add(site.id);state.query='';find('search').value='';draw();find('message').textContent='已加入本区地点，可继续选择其他分区。';};
  find('search').value=state.query;find('search').oninput=e=>{state.query=e.target.value;draw();};
  find('sites').onchange=e=>{const el=e.target.closest('[data-site-id]');if(!el)return;if(el.checked)state.sites.add(el.dataset.siteId);else state.sites.delete(el.dataset.siteId);update();};
  find('clear').onclick=()=>{state.sites.clear();find('message').textContent='';draw();};
  const preset=find('preset');
  preset.onclick=async()=>{
   preset.disabled=true;
   try{
    const data=await api('/api/china-scope');
    if(!preset.isConnected||!dialog.open)return;
    const picks=[],unavailable=[];
    for(const region of data.regions){
     const site=region.candidates.find(s=>s.default);
     if(!site?.available||!names.has(site.site_id)){unavailable.push(region.name);continue;}
     const same=[...originalSites].filter(id=>names.get(id)?.weather.sha256===site.sha256);
     picks.push(same.length===1?same[0]:site.site_id);
    }
    state.sites=new Set(picks);state.query='';state.zone='';find('zone').value='';find('search').value='';draw();
    find('message').textContent='已选 '+state.sites.size+' 个预设地点，同一份气象优先沿用设计原地点。'+(unavailable.length?'尚未登记或需核对：'+unavailable.join('、'):'');
   }catch(e){if(preset.isConnected)find('message').textContent=e.message;}finally{preset.disabled=false;}
  };
  find('next').onclick=()=>{moving('report');read();};draw();
 }
 async function read(force=false){
  page('report',back+'<p role="status">正在核对当地气象、工况结果与日历…</p>');
  const group=state.group,goBack=()=>{if(group){state.group=null;library();}else{moving('sites');chooseSites();}};
  find('back').onclick=goBack;
  const ident=seq;
  const selection=group?{group}:{revision:design.revision,cells:[...state.cells].sort((a,b)=>a-b),sites:[...state.sites].sort()};
  const req={action:'preview-design-regions',id:design.id,...selection};
  try{
   const load=()=>api('/api/reading-collections',req);
   const report=await cachedCandidateRead(JSON.stringify(req),load,force);
   if(!dialog.open||seq!==ident)return;
   const members=report.members,counts=report.counts,labels=new Map(members.map(m=>[m.cell,m.label]));
   body.innerHTML=back+'<div class="region-heading"><div><h3>'+esc(report.group_name||'地区扩展预览')+'</h3><p>'+members.length+' 项工况 · '+report.rows.length+' 个地点</p></div>'+
    (group?'<button type="button" class="primary" data-region-plans>准备计算方案</button>':('<div class="actions">'+libraryButton+'<button type="button" class="primary" data-derive>派生地区组</button></div>'))+'</div><div data-confirm></div>'+
    '<dl class="region-counts">'+[['reuse','可复用结果',counts.reuse||0],['needed','缺研究算例',counts.needed||0],...(counts.existing?[['existing','已有任务',counts.existing]]:[]),...(counts.check?[['check','待核对',counts.check]]:[])].map(([kind,k,v])=>'<div class="'+kind+'"><dt>'+k+'</dt><dd>'+v+'</dd></div>').join('')+'</dl>'+
    (report.calendar_gaps?'<p>另有 '+report.calendar_gaps+' 项当地日历准备，按地点和 W00 参考条件各计一次。</p>':'')+
    (report.warnings||[]).map(s=>'<p class="warning">'+esc(s)+'</p>').join('')+
    '<div class="region-filters"><label><input type="checkbox" data-gaps>仅看有缺项或待核对的地点</label></div><div data-rows></div>';
   find('back').onclick=goBack;
   if(group)find('region-plans').onclick=()=>openRegionPlans(find('region-plans'),design.id,group);
   if(!group){
    bindLibrary('report');
    const derive=find('derive'),confirm=find('confirm');
    derive.onclick=()=>{
     derive.hidden=true;
     confirm.innerHTML='<form class="region-confirm"><label class="field">地区组名称<input data-name required maxlength="100"></label><p>保存 '+members.length+' 份组内工况，共用 '+report.rows.length+' 个地点。方案编辑列表新增 0 项。</p>'+
      (report.uses_calendar?'<p>光学切换按当地气象和 W00 日历核对。</p>':'')+
      '<div class="actions"><button type="submit" class="primary">确认保存地区组</button><button type="button" data-cancel>取消</button></div><p role="status" data-notice></p></form>';
     find('name').value=(design.name+' · '+report.rows.length+' 地点').slice(0,100);
     find('name').focus({preventScroll:true});find('name').select();
     find('cancel').onclick=()=>{confirm.replaceChildren();derive.hidden=false;derive.focus();};
     confirm.querySelector('form').onsubmit=async event=>{
      event.preventDefault();
      const btn=confirm.querySelector('[type=submit]'),notice=find('notice');if(btn.disabled)return;
      btn.disabled=true;find('cancel').disabled=true;notice.textContent='正在核对并保存…';
      try{
       const saved=await api('/api/reading-collections',{...req,action:'derive-design-region-group',preview_key:report.preview_key,name:find('name').value});
       if(!dialog.open||seq!==ident)return;
       state.group=saved.id;state.libraryFrom='cells';state.offset=0;await read();
      }catch(e){
       if(!notice.isConnected)return;
       notice.textContent=e.message;btn.disabled=false;find('cancel').disabled=false;
       if(!confirm.querySelector('[data-refresh]')){const reload=document.createElement('button');reload.type='button';reload.dataset.refresh='';reload.textContent='重新核对预览';reload.onclick=()=>read(true);notice.after(reload);}
      }
     };
    };
   }
   const rows=find('rows'),gaps=find('gaps');gaps.checked=state.gaps;
   const rank=new Map((group?sites.map(s=>s.id):[...state.sites]).map((sid,index)=>[sid,index]));
   const ordered=[...report.rows].sort((a,b)=>Number(b.source_site)-Number(a.source_site)||(rank.get(a.site)??Infinity)-(rank.get(b.site)??Infinity));
   function draw(){
    const shown=ordered.filter(r=>!state.gaps||r.cases.some(c=>c.kind!=='reuse'));
    const items=shown.map(row=>{
     const data=members.map(({cell:i,label})=>{
      const cases=row.cases.filter(c=>c.cell===i);
      const detail=cases.map(c=>{
       const value=esc((cases.length>1?(c.mode==='controlled'?'温控':'自然室温')+' · ':'')+c.status);
       return group?'<button type="button" class="region-status '+c.kind+'" data-local="'+i+'" data-site="'+esc(row.site)+'" aria-label="'+esc(row.city+' · '+label+' · '+c.status+'，查看当地工况')+'">'+value+'</button>':'<span class="region-status '+c.kind+'">'+value+'</span>';
      }).join('');
      return '<td data-label="'+esc(label)+'">'+detail+'</td>';
     }).join('');
     const sources=row.cases.filter(c=>c.origins?.length).map(c=>'<div><dt>'+esc(labels.get(c.cell))+'</dt><dd>'+esc(c.origins.join(' ／ '))+'</dd></div>').join('');
     const open=state.openSources.has(row.site),sourceId='regional-source-'+row.site;
     return '<tr><th scope="row"><b>'+esc(row.city)+'</b>'+(sources?'<button type="button" class="region-source-button" data-source-site="'+esc(row.site)+'" aria-expanded="'+open+'" aria-controls="'+esc(sourceId)+'">结果来源</button>':'')+'</th>'+data+(report.uses_calendar?'<td data-label="当地光学切换日历">'+esc(row.calendars.join(' ／ ')||'待核对')+'</td>':'')+'</tr>'+
      (sources?'<tr class="region-source-row" id="'+esc(sourceId)+'" '+(open?'':'hidden')+'><td colspan="'+(1+members.length+Number(report.uses_calendar))+'"><dl>'+sources+'</dl></td></tr>':'');
    }).join('');
    rows.innerHTML=shown.length?'<table class="region-table"><thead><tr><th scope="col">地点</th>'+members.map(m=>'<th scope="col">'+esc(m.label)+'</th>').join('')+(report.uses_calendar?'<th scope="col">当地光学切换日历</th>':'')+'</tr></thead><tbody>'+items+'</tbody></table>':'<p>所选地点的研究算例均可复用。</p>';
   }
   rows.onclick=e=>{
    const local=e.target.closest('[data-local]');if(local){inspectLocal(local,group);return;}
    const button=e.target.closest('[data-source-site]');if(!button)return;
    const sid=button.dataset.sourceSite,row=document.getElementById(button.getAttribute('aria-controls'));
    row.hidden=!row.hidden;button.setAttribute('aria-expanded',String(!row.hidden));
    if(row.hidden)state.openSources.delete(sid);else state.openSources.add(sid);
   };
   gaps.onchange=()=>{state.gaps=gaps.checked;draw();};
   draw();body.scrollTop=state.offset;
  }catch(e){
   if(!dialog.open||seq!==ident)return;
   body.innerHTML=back+'<p role="alert">'+esc(e.message)+'</p><button type="button" data-retry>重新核对</button>';
   find('back').onclick=goBack;find('retry').onclick=()=>read(true);
  }
 }
 function inspectLocal(button,group){
  const panel=readingDialog(button,'当地工况'),content=panel.querySelector('.rs-month-body');
  panel.classList.add('region-member');
  const req={action:'inspect-design-region-member',id:design.id,group,site:button.dataset.site,cell:Number(button.dataset.local)};
  async function load(){
   content.textContent='正在核对当地工况…';
   try{
    const item=await cachedCandidateRead(JSON.stringify(req),()=>api('/api/reading-collections',req));
    if(!panel.open)return;
    const p=item.period;
    content.innerHTML='<h3>'+esc(item.label)+'</h3><p>'+esc([item.city,item.climate,item.building].filter(Boolean).join(' · '))+'</p><p>'+p[0]+' 月 '+p[1]+' 日至 '+p[2]+' 月 '+p[3]+' 日 · '+item.step+' min</p><p>来源版本　'+esc(item.source)+' · v'+item.revision+'</p>'+
     (item.ready?'<p>'+esc(item.calendar)+'</p><details><summary>工况与气象校验值</summary><p>当地工况　<code>'+esc(item.recipe_sha256)+'</code></p><p>当地气象　<code>'+esc(item.weather)+'</code></p></details>':'<p class="warning">'+esc(item.note)+'</p>');
   }catch(e){if(panel.open){content.innerHTML='<p>'+esc(e.message)+'</p><button type="button">重新核对</button>';content.querySelector('button').onclick=load;}}
  }
  load();
 }
 if(libraryOnly&&!(state.stage==='report'&&state.group))library();else if(state.stage==='report')read();else if(state.stage==='sites')chooseSites();else if(state.stage==='library')library();else chooseCells();
}
