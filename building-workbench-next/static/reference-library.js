S.referenceLibrary={data:null,kind:'daily_profiles',query:'',page:0,selected:null,detail:null,day:1,error:'',message:'',pending:false};
const rlNames={daily_profiles:'日作息',annual_schedules:'全年时刻表',room_templates:'房间配置',materials:'材料参考',constructions:'构造参考',construction_versions:'我的构造版本'};
function rl(){return S.referenceLibrary;}
function rlRows(){const v=rl(),q=v.query.toLowerCase();return (v.data?.[v.kind]||[]).filter(r=>[r.name,r.category,r.use,r.id].join(' ').toLowerCase().includes(q));}
function rlSelected(){return (rl().data?.[rl().kind]||[]).find(r=>(r.id+(r.revision?':'+r.revision:''))===rl().selected);}
function rlTable(pairs){return `<div class="viewer-table"><table class="table"><tbody>${pairs.map(([k,v])=>`<tr><th>${esc(k)}</th><td>${esc(v??'待补')}</td></tr>`).join('')}</tbody></table></div>`;}
function rlOrigins(row){return (row.origins||[]).map(o=>{const source=rl().data.sources.find(s=>s.id===o.source_id);return (source?.name||o.source_id)+' · '+o.table+' · '+o.original_id;}).join('；');}
function rlDetails(){const v=rl(),r=rlSelected();if(!r)return '<h2>选择一条参考</h2><p>查看名称、完整参数与来源后，再复制使用。</p>';let body='';
 if(v.kind==='materials'){body=rlTable([['类别',r.category],['导热率 / W/(m·K)',r.conductivity_W_mK],['密度 / kg/m³',r.density_kg_m3],['比热 / J/(kg·K)',r.specific_heat_J_kgK],['默认厚度 / mm',r.default_thickness_mm],['原太阳反射率',r.solar_reflectance],['长波发射率',r.longwave_emissivity]])+'<button data-rl="material">复制到新建材料表单</button><p>不会根据反射率自行假设透射率为零；厚度和覆盖后的光学参数需补齐。</p>';}
 if(v.kind==='daily_profiles')return '<button data-daily-open="" data-daily-public="true">打开统一日计划库</button>';
 if(v.kind==='annual_schedules'){body=rlTable([['类型',r.kind],['单位',r.unit],['最小／最大',r.min+' / '+r.max],['不同日曲线数量',r.unique_days],['每日编辑兼容性',r.current_excel_compatible]])+'<p>保留 8760 个小时原值，1 月 1 日按原库为周一；不合并季节或特殊日。</p>';if(v.detail?.id===r.id){const vals=v.detail.values.slice((v.day-1)*24,v.day*24);body+=`<label class="field">查看第几天（1–365）<input type="number" min="1" max="365" data-rl-day value="${v.day}"></label>`+scheduleChart({weekday:vals,weekend:vals},r.unit)+rlTable(vals.map((x,h)=>[h+':00–'+(h+1)+':00',x]));}body+='<button data-rl="annual">读取全年曲线</button><button data-rl="download-annual"'+(v.detail?.id===r.id?'':' disabled')+'>导出完整全年 CSV</button>';}
 if(v.kind==='room_templates'){const gains=['people','lighting','equipment'].map((k,i)=>[['人数','照明','设备'][i],r[k+'_min']+'–'+r[k+'_max']+' '+r[k+'_mode']]);body=rlTable([...gains,['人员显热 / W/人',r.people_sensible_W_person],['人员时刻表',r.O_SCHEDULE],['照明时刻表',r.L_SCHEDULE],['设备时刻表',r.E_SCHEDULE]])+'<p>能精确还原为工作日／周末的配置已加入 ACCDB 导入时的“配置来源”。只映射人数、照明、设备和显热参数，保留目标建筑的空调与温控。</p>';}
 if(['constructions','construction_versions'].includes(v.kind)){const c=v.kind==='construction_versions'?r.content:v.detail?.reference_id===r.id?v.detail:null;body=`<p>${esc(r.category||c?.category)} · ${esc(c?.orientation||r.orientation)}</p>`;if(c)body+=`<div class="viewer-table"><table class="table"><thead><tr><th>原层号</th><th>材料名称</th><th>厚度 mm</th><th>导热率</th><th>密度</th><th>比热</th></tr></thead><tbody>${c.layers.map(l=>`<tr><td>${l.sequence}</td><td>${esc(l.material.name)}</td><td>${l.thickness_mm}</td><td>${l.material.conductivity_W_mK??'待补'}</td><td>${l.material.density_kg_m3??'待补'}</td><td>${l.material.specific_heat_J_kgK??'待补'}</td></tr>`).join('')}</tbody></table></div>`;body+='<p>原层号顺序不自动认定为室外到室内；使用时核对朝向、适用构件和表面光学。</p>'+(v.kind==='constructions'?'<button data-rl="construction">读取层序与材料名称</button><button data-rl="copy-construction">复制为我的构造版本</button>':'<button data-rl="download-construction">导出构造参数</button>');}
 return `<h2>${esc(r.name)}${r.revision?' · v'+r.revision:''}</h2>${body}<p>${esc(r.notes||r.content?.note||'')}</p><details><summary>来源与版本</summary><p>${esc(rlOrigins(r.content||r))}</p><p>参考库 ${esc(v.data.version)}；编号 ${esc(r.id)}</p><p>${esc(v.data.notice)}</p></details>`;
}
function rlItemsMarkup(){const v=rl(),rows=rlRows(),size=20,start=v.page*size;return `${rows.slice(start,start+size).map(r=>{const id=r.id+(r.revision?':'+r.revision:'');return `<button class="mc-item" data-rl-select="${esc(id)}" aria-pressed="${v.selected===id}"><strong>${esc(r.name)}</strong><span>${esc(r.category||r.use||r.kind||'参考')} ${r.revision?'· v'+r.revision:''}</span><small>${esc(r.id)}</small></button>`;}).join('')}`;}
function rlPaginationMarkup(){const v=rl(),rows=rlRows(),size=20,start=v.page*size;return `<button data-rl="prev"${v.page===0?' disabled':''}>上一页</button><span>${rows.length? v.page+1:0} / ${Math.ceil(rows.length/size)}</span><button data-rl="next"${start+size>=rows.length?' disabled':''}>下一页</button>`;}
function rlView(){const v=rl();if(v.kind==='daily_profiles')return rlDailyEntry();return `<section class="section mc-page"><h1>公用作息、材料与构造库</h1><p>来自早期 Excel 库，保留原名称和来源。参考数据只读，复制后建立自己的版本；不会自动更新任何方案。</p><div class="actions">${Object.entries(rlNames).map(([k,n])=>`<button data-rl-kind="${k}" aria-pressed="${v.kind===k}">${n} ${v.data?.[k]?.length??''}</button>`).join('')}</div>${v.error?'<p class="warning" role="alert">'+esc(v.error)+'</p>':''}${v.message?'<p role="status">'+esc(v.message)+'</p>':''}${v.pending?'<p role="status">正在读取…</p>':''}<div class="mc-layout"><aside class="mc-list-panel"><label class="field">查找名称或类别<input id="rl-search" value="${esc(v.query)}"></label><div id="rl-items">${rlItemsMarkup()}</div><div class="actions" id="rl-pagination">${rlPaginationMarkup()}</div></aside><article class="mc-detail" id="rl-detail">${rlDetails()}</article></div></section>`;}
function rlDownload(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function rlChooseKind(kind){if(!Object.hasOwn(rlNames,kind))throw Error('参考类别无效。');const v=rl();v.kind=kind;v.query='';v.page=0;v.selected=null;v.detail=null;v.day=1;}
async function rlAction(b){const v=rl();if(v.pending)return;v.error='';v.message='';try{
 if(b.dataset.view==='reference-library'){if(b.dataset.rlKind)rlChooseKind(b.dataset.rlKind);S.view='reference-library';if(!v.data){v.pending=true;render();v.data=await api('/api/reference-library');}return;}
 if(b.dataset.rlKind){rlChooseKind(b.dataset.rlKind);return;}
 if(b.dataset.rlSelect){v.selected=b.dataset.rlSelect;v.detail=null;v.day=1;return;}
 const op=b.dataset.rl,r=rlSelected();if(op==='prev'){v.page--;return;}if(op==='next'){v.page++;return;}if(!r)throw Error('请先选择参考条目。');
 if(op==='annual'){v.pending=true;render();v.detail=await api('/api/reference-library/annual/'+encodeURIComponent(r.id));return;}
 if(op==='construction'){v.pending=true;render();v.detail=await api('/api/reference-library/construction/'+encodeURIComponent(r.id));return;}
 if(op==='copy-construction'){v.pending=true;render();const result=await api('/api/reference-library/copy-construction',{id:r.id,name:r.name+' · 我的构造'});v.data=await api('/api/reference-library');v.kind='construction_versions';v.query='';v.page=0;v.selected=result.id+':'+result.revision;v.message='已复制独立构造版本，原参考及方案保持。';return;}
 if(op==='daily'){await rlOpenDaily();return;}
 if(op==='material'){mcCheckDraft();v.pending=true;render();const draft=await api('/api/reference-library/material/'+encodeURIComponent(r.id));await openMaterialCatalog();mc().draft=draft;mc().parent=null;mc().exampleOrigin=null;mc().dirty=false;return;}
 if(op==='download-annual'){const a=v.detail;rlDownload(r.name+'.csv','\uFEFF小时序号,值,单位\r\n'+a.values.map((x,i)=>[i+1,x,a.unit].join(',')).join('\r\n'),'text/csv;charset=utf-8');return;}
 if(op==='download-construction')rlDownload(r.name+'.json',JSON.stringify(r,null,2),'application/json');
 }catch(e){v.error=e.message;}finally{v.pending=false;render();}}
const rlOldNav=renderNav;renderNav=function(){rlOldNav();const b=document.createElement('button');b.dataset.view='reference-library';b.textContent='公用参考库';b.setAttribute('aria-pressed',String(S.view==='reference-library'));nav.append(b);};
const rlOldRender=render;render=function(){if(S.view==='reference-library'){renderNav();app.innerHTML=rlView();syncPageSections();}else rlOldRender();};
const rlOldAction=action;action=async function(b){if(b.dataset.view==='reference-library'||b.dataset.rl||b.dataset.rlKind||b.dataset.rlSelect)return rlAction(b);return rlOldAction(b);};
// Preserve the composing input node and caret; only committed text filters the list.
const rlComposingInputs=new WeakSet();
function rlSearchChanged(input){
 if(!input.isConnected||S.view!=='reference-library')return;
 rl().query=input.value;rl().page=0;
 document.getElementById('rl-items').innerHTML=rlItemsMarkup();
 document.getElementById('rl-pagination').innerHTML=rlPaginationMarkup();
}
document.addEventListener('compositionstart',e=>{if(e.target.id==='rl-search')rlComposingInputs.add(e.target);});
document.addEventListener('compositionend',e=>{if(e.target.id==='rl-search'){rlComposingInputs.delete(e.target);rlSearchChanged(e.target);}});
document.addEventListener('input',e=>{if(e.target.id==='rl-search'&&!e.isComposing&&!rlComposingInputs.has(e.target))rlSearchChanged(e.target);});
document.addEventListener('change',e=>{if(e.target.hasAttribute('data-rl-day')){rl().day=Math.max(1,Math.min(365,Math.floor(Number(e.target.value)||1)));document.getElementById('rl-detail').innerHTML=rlDetails();}});

async function rlOpenDaily(){const b=document.createElement('button');b.dataset.dailyOpen='';b.dataset.dailyPublic='true';await openDailyManager(b);}
function rlDailyEntry(){const v=rl();return `<section class="section mc-page"><h1>公用作息、材料与构造库</h1><p>日作息统一在日计划库查看、复制、编辑和保存；原参考保持只读。</p><div class="actions">${Object.entries(rlNames).map(([k,n])=>`<button data-rl-kind="${k}" aria-pressed="${v.kind===k}">${n} ${v.data?.[k]?.length??''}</button>`).join('')}</div><section class="well"><h2>日计划库</h2><p>使用一条比例曲线与 24 小时网格核对作息。复制前命名，保存时保留来源；选入房间的工作日或周末需另行确认。</p><button class="primary" data-daily-open="" data-daily-public="true">打开统一日计划库</button><p class="muted">关闭后保留搜索、选择和已暂存编辑；当前标签页刷新前请保存。</p></section>${v.error?'<p class="warning">'+esc(v.error)+'</p>':''}</section>`;}
