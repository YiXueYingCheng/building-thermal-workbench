/* Full lists and saved input inspection; no generation or submission side effects. */
S.caseLists={};S.inputInspection=null;S.inputDetail=null;S.inputInspectionError='';
function caseListData(key){
 if(key==='preview')return {rows:S.preview?.cases||[],identity:S.preview,mode:S.record.factors.condition.operation.mode,period:S.record.factors.scope.period};
 if(key==='generated')return {rows:S.generated?.cases||[],identity:S.generated?.id,mode:S.saved.factors.condition.operation.mode,period:S.saved.factors.scope.period};
 if(key==='review')return {rows:S.executionReview?.cases||[],identity:S.executionReview?.id};
 const d=S.inputInspection;return {rows:d?.manifest.cases||[],identity:d?.manifest_sha256,mode:d?.operation_mode,period:d?.period};
}
function caseListState(key){const data=caseListData(key);let state=S.caseLists[key];if(!state||state.identity!==data.identity)state=S.caseLists[key]={identity:data.identity,query:'',mode:'',page:0};return state;}
function caseListRows(key){
 const data=caseListData(key),s=caseListState(key),q=s.query.trim().toLocaleLowerCase();
 const rows=data.rows.map((c,index)=>({c,index,mode:c.mode||data.mode,climate:c.climate||S.boot.sites[c.site_id]?.climate||''})).filter(r=>(!s.mode||r.mode===s.mode)&&(!q||[r.c.city,r.climate,r.c.site_id].filter(Boolean).join(' ').toLocaleLowerCase().includes(q)));
 const pages=Math.max(1,Math.ceil(rows.length/20));s.page=Math.min(Math.max(s.page,0),pages-1);
 return `<p class="muted">匹配 ${rows.length} / ${data.rows.length} 个算例 · 第 ${s.page+1} / ${pages} 页。筛选仅用于查看，计算安排仍包含完整清单。</p><div class="table-scroll"><table class="table case-review-table"><thead><tr><th>地点 / 气候</th><th>运行 / 时段</th><th>步长</th><th>${key==='preview'?'历史依据':key==='review'?'序号':'相对源模型'}</th></tr></thead><tbody>${rows.slice(s.page*20,(s.page+1)*20).map(r=>`<tr><td>${esc(r.c.city)}<small>${esc(r.climate||'未登记气候类型')}</small></td><td>${esc(modes[r.mode]||'见绑定方案')}<small>${esc(periodLabel(r.c.period||data.period))}</small></td><td>${r.c.step_minutes??'—'} min${r.c.schedule_counts?`<small>文件作息 ${esc(r.c.schedule_counts.original)} → ${esc(r.c.schedule_counts.retained)} 条</small>`:''}</td><td>${key==='preview'?(r.c.historical_candidate?'原冻结模型及结果':'需生成并验证新模型'):key==='review'?'第 '+(r.index+1)+' 项':`${r.c.exact_input_match?'逐字段相同':(r.c.difference_count??(r.c.differences||[]).length)+' 处变化'}${key==='inspection'?`<button data-input-detail="${r.index}">查看变化与墙面状态</button>`:''}`}</td></tr>`).join('')||'<tr><td colspan="4">没有匹配的算例。</td></tr>'}</tbody></table></div><div class="actions case-pages"><button data-case-page="${key}" data-page="${s.page-1}"${s.page===0?' disabled':''}>上一页</button><button data-case-page="${key}" data-page="${s.page+1}"${s.page>=pages-1?' disabled':''}>下一页</button></div>`;
}
function caseListView(key){const s=caseListState(key);return `<div class="case-list" data-case-list="${key}"><div class="grid2"><label class="field">查找地点或气候<input data-case-search="${key}" value="${esc(s.query)}" placeholder="地点名称、编号或气候类型"></label><label class="field">运行模式<select data-case-mode="${key}">${options([['','全部'],['controlled','温控冷热需求'],['natural','自然室温']],s.mode)}</select></label></div><div data-case-rows="${key}">${caseListRows(key)}</div></div>`;}
function updateCaseList(key){const el=document.querySelector(`[data-case-rows="${key}"]`);if(el)el.innerHTML=caseListRows(key);}
function inputValue(v){const text=v===undefined?'未记录':v===null?'空值':typeof v==='object'?JSON.stringify(v,null,2):String(v);return text.length>180||text.includes('\n')?`<details><summary>展开完整值</summary><pre>${esc(text)}</pre></details>`:esc(text);}
function inputDiffValue(row,side){const p=row[side+'_preview'];return p?`长序列 / 对象 · ${p.items} 项<br><a href="${esc(p.url)}" target="_blank" rel="noopener">查看完整算例详情 ↗</a>`:inputValue(row[side]);}
function inputDetailView(){
 const d=S.inputInspection,c=S.inputDetailData?.key===d?.manifest.id+'|'+S.inputDetail?S.inputDetailData.value:d?.manifest.cases[S.inputDetail];if(!c)return '';
 const stack=c.stack_readback;
 const walls=c.wall_assignments||[],dynamic=c.wall_assignments_basis==='initial_state_only_see_control_groups_for_transitions';
 return `<section class="well input-detail" id="input-detail"><div class="row"><h3>${esc(c.city)} · ${esc(modes[c.mode||d.operation_mode]||'输入明细')}</h3><button data-action="close-input-detail">收起明细</button></div><p>${esc(periodLabel(c.period||d.period))} · ${c.step_minutes} min · ${c.applied_surfaces?c.applied_surfaces.length+' 个已铺构件':(c.drawing_wall_scope?c.drawing_wall_scope.rows.filter(w=>w.covered).length:walls.length)+' 个附加材料墙面'}。</p><p class="muted">以下变化相对该地点生成时使用的源模型。</p><details class="input-field-diffs"><summary>查看逐字段变化 · ${(c.differences||[]).length} 处</summary><p class="muted">这是输入文件的变化记录；空值沿用原清单，不推断为数值零。</p><div class="table-scroll"><table class="table input-diff-table"><thead><tr><th>字段位置</th><th>源模型值</th><th>生成后值</th></tr></thead><tbody>${(c.differences||[]).map(x=>`<tr><td>${esc(x.path.join(' › '))}</td><td>${inputDiffValue(x,"before")}</td><td>${inputDiffValue(x,"after")}</td></tr>`).join('')||'<tr><td colspan="3">没有登记字段变化。</td></tr>'}</tbody></table></div></details>
 ${c.usage_configuration?`<details class="input-usage"><summary>查看实际房间作息与运行覆盖</summary><p>建筑配置：${c.usage_version?esc(c.usage_version.name)+' · 版本 '+c.usage_version.revision:'原冻结默认'}；${Object.keys(c.operation_overrides||{}).length} 间运行覆盖。自然室温模式不接入空调系统。</p><pre>${esc(JSON.stringify(c.usage_configuration,null,2))}</pre></details>`:''}
 ${stackInputReadback(stack)}
 ${c.drawing_wall_scope?drawingInputTable(c.drawing_wall_scope):''}
 <h3${c.drawing_wall_scope||stack?' hidden':''}>${dynamic?'墙面初始状态':'墙面状态与参数'}</h3>${dynamic?'<p class="muted">这里只表示初始状态；运行中的切换由下方控制分组决定。</p>':''}
 ${walls.length?`<div class="table-scroll"><table class="table input-wall-table"><thead><tr><th>墙面</th><th>状态 / 外表面光学参数组</th><th>有效热阻 / m²·K/W</th><th>太阳吸收率</th><th>热发射率</th></tr></thead><tbody>${walls.map(w=>`<tr><td>${esc(w.surface)}</td><td>${esc(w.state_id)} / ${esc(w.face_id)}</td><td>${inputValue(w.effective_R)}</td><td>${inputValue(w.solar_absorptance)}</td><td>${inputValue(w.emissivity)}</td></tr>`).join('')}</tbody></table></div>`:c.drawing_wall_scope||stack?'':c.applied_surfaces?`<details><summary>查看已铺构件</summary><p>${c.applied_surfaces.map(esc).join('、')}</p></details>`:'<p class="muted">此输入未登记附加材料墙面参数。</p>'}
 ${c.control_groups?`<details><summary>查看控制分组与切换记录</summary><pre>${esc(JSON.stringify(c.control_groups,null,2))}</pre></details>`:''}
 <details><summary>查看源模型、气象与作息引用</summary><pre>${esc(JSON.stringify({source_model:c.source_model,weather:c.weather,dependencies:c.dependencies,calendar_binding:c.calendar_binding},null,2))}</pre></details>
 <div class="actions">${c.audit_url?`<a href="${esc(c.audit_url)}" target="_blank" rel="noopener">完整算例详情 ↗</a>`:''}<a href="/api/model-inputs/${esc(d.manifest.id)}/${esc(c.model_file)}" target="_blank" rel="noopener">查看本算例模型 ↗</a></div></section>`;
}
function inputInspectionView(){
 const d=S.inputInspection;if(!d)return '';const m=d.manifest;
 return `<section class="section" id="input-inspection"><div class="row"><h2>已保存输入核对</h2><button data-action="close-input-inspection">收起输入核对</button></div><p><strong>${esc(d.record.name)}</strong> · ${esc(planVersionLabel(d.record))} · ${m.case_count} 个输入</p><p id="input-inspection-error" class="warning">${esc(S.inputInspectionError)}</p><p class="muted">读取于 ${esc(readableTime(d.checked_at))}。</p><p class="muted">已核对绑定保存版与 ${d.checked_models} 个模型文件${d.batch_anchor_count?'，并与原批次冻结清单一致':''}。显示生成时保存的差异与引用；准备计算时仍会核对气象、作息和引擎。</p><div class="actions"><a href="/api/model-inputs/${esc(m.id)}/manifest.json" target="_blank" rel="noopener">完整差异与来源清单 ↗</a></div>${caseListView('inspection')}<div id="input-detail-slot">${inputDetailView()}</div></section>`;
}
async function inputReviewAction(button){
 if(button.dataset.inspectInput){
  try{const d=await api('/api/input-inspection/'+encodeURIComponent(button.dataset.inspectInput));S.inputInspection=d;S.inputDetail=null;S.inputInspectionError='';return true;}
  catch(error){S.inputInspectionError='重新核对未完成；下方保留上次读取记录。'+error.message;const el=document.getElementById('input-inspection-error');if(el)el.textContent=S.inputInspectionError;throw error;}
 }
 if(button.dataset.casePage){const key=button.dataset.casePage;caseListState(key).page=Number(button.dataset.page);updateCaseList(key);return 'local';}
 if(button.dataset.inputDetail!==undefined){const index=Number(button.dataset.inputDetail);if(!Number.isInteger(index)||!S.inputInspection?.manifest.cases[index])throw Error('没有该算例。');const d=S.inputInspection;S.inputDetail=index;if(d.manifest.cases[index].audit){document.getElementById('input-detail-slot').innerHTML='<p role="status">正在读取所选算例详情…</p>';const value=await api('/api/input-inspection/'+d.manifest.id+'/cases/'+index);if(S.inputInspection!==d||S.inputDetail!==index)return 'local';S.inputDetailData={key:d.manifest.id+'|'+index,value};}document.getElementById('input-detail-slot').innerHTML=inputDetailView();document.getElementById('input-detail')?.scrollIntoView({block:'start'});return 'local';}
 if(button.dataset.action==='close-input-detail'){S.inputDetail=null;document.getElementById('input-detail-slot').innerHTML='';return 'local';}
 if(button.dataset.action==='close-input-inspection'){S.inputInspection=null;S.inputDetail=null;S.inputInspectionError='';return true;}
 return false;
}
document.addEventListener('input',e=>{const key=e.target.dataset.caseSearch;if(key){const s=caseListState(key);s.query=e.target.value;s.page=0;updateCaseList(key);}});
document.addEventListener('change',e=>{const key=e.target.dataset.caseMode;if(key){const s=caseListState(key);s.mode=e.target.value;s.page=0;updateCaseList(key);}});
