'use strict';
let rtSequence=0,rtState=null;
const rtFreq={Daily:'逐日',Monthly:'逐月','Run Period':'整个计算时段',Hourly:'逐时','Zone Timestep':'逐步','HVAC System Timestep':'HVAC 系统步'};
function rtDialog(){
 let d=document.getElementById('result-timeline');
 if(!d){d=document.createElement('dialog');d.id='result-timeline';d.setAttribute('aria-labelledby','rt-title');document.body.append(d);d.addEventListener('cancel',e=>{e.preventDefault();rtClose();});}
 return d;
}
function rtClose(){
 const trigger=rtState?.trigger;
 rtSequence++;rtState=null;
 const d=rtDialog();d.close();d.replaceChildren();
 if(trigger?.isConnected)trigger.focus({preventScroll:true});
}
function rtShell(body){
 const d=rtDialog(), back=rtState.context?'返回月度差异':'返回结果';
 const sub=rtState.inventory?.city || rtState.context?.city || '';
 d.innerHTML=`<header class="viewer-head"><div><h2 id="rt-title">输出频率与时序明细</h2>${sub?`<p class="muted">${esc(sub)} · 算例 ${rtState.index+1}</p>`:''}</div><button data-rt-close autofocus>${back}</button></header>${rtState.inventory?rtFrequencyBanner(rtState.inventory):''}<div class="focused-body">${body}</div>`;
 if(!d.open)d.showModal();
 d.querySelector('[data-rt-close]').focus({preventScroll:true});
}
function rtUrl(kind,extra={}){return '/api/result-timeline/'+kind+'?'+new URLSearchParams({batch:rtState.batch,index:rtState.index,...extra});}
function rtOptions(a){return a.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');}
function rtMD(m,d){return [m,d].map(x=>String(x).padStart(2,'0')).join('-');}
function rtMonthRange(){
 const [s,sd,e,ed]=rtState.inventory.period,m=rtState.month;
 const first=m===s?sd:1,last=m===e?ed:new Date(Date.UTC(2025,m,0)).getUTCDate();
 return {start:rtMD(m,first),end:rtMD(m,last),first,last};
}
function rtDateFields(prefix){
 const range=rtMonthRange();
 return `<div class="rt-dates"><label>开始月-日<input id="${prefix}-start" value="${range.start}" maxlength="5"></label><label>结束月-日<input id="${prefix}-end" value="${range.end}" maxlength="5"></label></div>`;
}
function rtFrequencyBanner(d){
 const entries=d.frequencies.filter(f=>f.records>0);
 const step=entries.filter(f=>[-1,0].includes(f.IntervalType)).sort((a,b)=>a.min_minutes-b.min_minutes)[0];
 const finest=step||[1,2,3,4].map(i=>entries.find(f=>f.IntervalType===i)).find(Boolean);
 const label=step?(step.min_minutes===step.max_minutes?`每 ${step.min_minutes} min`:`系统步，${step.min_minutes}–${step.max_minutes} min`):({1:'逐小时',2:'逐日',3:'逐月',4:'整个计算时段'})[finest?.IntervalType];
 const counts=entries.map(f=>esc(f.label)+' '+format(f.records,0)+' 条').join(' · ');
 const note=finest?.IntervalType===3?'可查看每月统计，月内具体时刻未记录。':finest?.IntervalType===4?'本次仅保存整个计算时段的汇总。':entries.length?'各指标可查的频率取决于其实际记录。':'';
 return `<section class="rt-frequency-banner" aria-label="算例实际输出频率"><div><strong>最细输出 · ${esc(label||'无时间记录')}</strong><span>模型求解步长 ${esc(d.step_minutes)} min</span></div><p>${counts?'时间记录：'+counts+'。 ':''}${note}</p></section>`;
}
function rtInventory(d){
 const [start,,end]=d.period, monthChoices=Array.from({length:end-start+1},(_,i)=>[start+i,(start+i)+' 月']);
 const tabs=[['month','月度概览'],...(d.systems.length?[['daily','逐日冷热需求']]:[]),['series','按指标查明细'],['source','输出清单与来源']];
 const sides=rtState.context?.sides;
 const context=sides?`<label>对照工况<select id="rt-side">${options(sides.map((s,i)=>[i,s.name]),rtState.context.side)}</select></label>`:'';
 return `${d.registered_status==='review'?'<p class="warning" role="status">此结果仍待复核。可在「输出清单与来源」查看接受说明。</p>':''}<div class="rt-toolbar">${context}<label>查看月份<select id="rt-month">${options(monthChoices,rtState.month)}</select></label></div>
 <div class="rt-tabs" role="group" aria-label="查看内容">${tabs.map(([k,v])=>`<button data-rt-tab="${k}" aria-pressed="false">${v}</button>`).join('')}</div>
 <section data-rt-panel="month"></section>
 ${d.systems.length?`<section data-rt-panel="daily" hidden><h3>原系统逐日显热需求</h3><div class="rt-fields"><label>系统<select id="rt-system">${rtOptions(d.systems)}</select></label>${rtDateFields('rt')}</div><button class="primary" data-rt-load>读取逐日冷热需求</button><div id="rt-daily" aria-live="polite"></div></section>`:''}
 <section data-rt-panel="series" hidden></section>
 <section data-rt-panel="source" hidden><h3>实际输出频率</h3><p>${esc(d.acceptance_note||'沿用已登记接受范围')}</p><div class="viewer-table"><table class="table"><thead><tr><th>频率</th><th>时间记录数</th></tr></thead><tbody>${d.frequencies.map(f=>`<tr><td>${esc(f.label)}</td><td>${f.records}</td></tr>`).join('')}</tbody></table></div>
 <details><summary>按变量类别查看输出数量</summary><div class="viewer-table"><table class="table"><thead><tr><th>变量类别</th><th>频率</th><th>登记项数</th></tr></thead><tbody>${d.coverage.map(x=>`<tr><td>${esc(x.signal)}</td><td>${esc(rtFreq[x.frequency]||x.frequency)}</td><td>${x.items}</td></tr>`).join('')}</tbody></table></div></details>
 <details><summary>原始变量与对象（${d.dictionary.length} 项）</summary><label>搜索变量或对象<input id="rt-dictionary-search"></label><div id="rt-dictionary"></div></details>
 <details><summary>文件与核对时间</summary><p>SQL 校验值 <code>${esc(d.sql_sha256)}</code></p><p>文件核对 ${format(d.timing.verification_seconds,3)} 秒，读取与登记复查 ${format(d.timing.query_seconds,3)} 秒。</p></details></section>`;
}
function rtMonthView(){
 const d=rtState.inventory,m=rtState.month;
 const row=d.monthly_loads?.find(r=>r.month===m), ctl=d.monthly_controls||{};
 const cards=[], controls=[];
 function card(label,value){return `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;}
 if(row)for(const [key,label] of [['heating_kWh','供暖'],['cooling_kWh','制冷'],['total_kWh','合计']])
    cards.push(card(label,Number.isFinite(row[key])?format(row[key])+' kWh':'无数据'));
 for(const [key,label] of [['face_a','采用 A 的时间占比'],['compressed','压缩时间占比'],['switches','热阻切换次数']]){
   if(!ctl[key])continue;
   const value=ctl[key].months?.[m];
   if(!Number.isFinite(value)){controls.push(card(label,ctl[key].error||'缺少本月读数'));continue;}
   if(key==='face_a')controls.push(card('光学参数组选用时间占比','A '+format(value*100)+'% / B '+format((1-value)*100)+'%'));
   else controls.push(card(label,key==='switches'?format(value,0)+' 次':format(value*100)+'%'));
   if(key==='compressed')controls.push(card('蓬松时间占比',format((1-value)*100)+'%'));
 }
 const finer=d.dictionary.some(r=>['Hourly','Zone Timestep'].includes(r.ReportingFrequency));
 const signals=[...new Set(d.dictionary.filter(r=>r.KeyValue==='EMS' && rtControlName(r.Name) && rtQueryable.includes(r.ReportingFrequency)).map(r=>r.Name))];
 const shortcuts=signals.length>4?`<label>材料控制指标<select id="rt-material-signal">${options(signals.map(n=>[n,rtControlName(n)]),signals[0])}</select></label><button data-rt-tab-jump="series" data-rt-control-picker>查看材料时序</button>`:signals.map(name=>`<button data-rt-tab-jump="series" data-rt-control="${esc(name)}">查看${esc(rtControlName(name))}</button>`).join('');
 const note=signals.length?'按指标查看实际保存的材料状态。区间占比无法还原区间内的具体切换时刻。':'本结果未登记可识别的材料控制时序。';
 const daily=d.systems.length?'本月可查看各系统的逐日供暖、制冷需求。':finer?'可按指标查看已记录的细时段。':'本结果的房间或系统需求明细请按实际输出频率查看。';
 return `<h3>${m} 月建筑显热需求</h3>${cards.length?`<div class="rt-cards">${cards.join('')}</div>`:'<p>本结果没有建筑月度冷热需求汇总。</p>'}
 ${controls.length?`<h3>材料控制的月度记录</h3><div class="rt-cards rt-controls">${controls.join('')}</div>`:''}
 <p class="muted">${note} ${daily}</p><div class="actions">${shortcuts}${d.systems.length?'<button data-rt-tab-jump="daily">查看本月逐日需求</button>':''}</div>
 ${!finer?`<details class="rt-estimate"><summary>如需补算 · 估算新计算的短时段记录量</summary><div class="rt-toolbar"><label>起始日<select id="rt-est-start">${rtOptions(Array.from({length:rtMonthRange().last-rtMonthRange().first+1},(_,i)=>String(rtMonthRange().first+i)))}</select></label>
 <label>天数<input id="rt-est-days" type="number" min="1" max="31" value="${Math.min(7,rtMonthRange().last-rtMonthRange().first+1)}"></label>
 <label>计划输出<select id="rt-est-frequency"><option value="step">逐步</option><option value="hour">逐时</option><option value="day">逐日</option></select></label></div><p id="rt-est-output" aria-live="polite"></p>
 <p class="muted">需要补算时，在研究方案中选定短时段，再到「计算安排」选保存频率、核对预算并提交。这里仅估算记录数。</p></details>`:''}
 <details><summary>结果接受说明</summary><p>${esc(d.acceptance_note||'沿用原结果接受范围')}</p></details>`;
}
function rtEstimate(){
 const d=rtDialog(),out=d.querySelector('#rt-est-output');if(!out)return;
 const day=Number(d.querySelector('#rt-est-start').value),days=Number(d.querySelector('#rt-est-days').value);
 const max=Math.min(31,rtMonthRange().last-day+1);
 d.querySelector('#rt-est-days').max=max;
 if(!Number.isInteger(days)||days<1||days>max){out.textContent=`请选择 1 至 ${max} 天。`;return;}
 const freq=d.querySelector('#rt-est-frequency').value,n=freq==='day'?1:freq==='hour'?24:1440/rtState.inventory.step_minutes;
 out.textContent=`${rtMD(rtState.month,day)} 至 ${rtMD(rtState.month,day+days-1)}，每个变量、每个对象预计 ${format(days*n,0)} 个读数。实际文件大小还取决于输出对象数量。`;
}
function rtDictionary(){
 const target=rtDialog().querySelector('#rt-dictionary');if(!target)return;
 const q=rtDialog().querySelector('#rt-dictionary-search').value.trim().toLowerCase();
 const rows=rtState.inventory.dictionary.filter(r=>[rtVariableName(r.Name),r.Name,r.KeyValue,r.ReportingFrequency].join(' ').toLowerCase().includes(q));
 target.innerHTML=`<p>匹配 ${rows.length} 项，显示前 ${Math.min(rows.length,100)} 项。</p><div class="viewer-table"><table class="table"><thead><tr><th>原变量</th><th>原对象</th><th>频率</th><th>单位／统计</th></tr></thead><tbody>${rows.slice(0,100).map(r=>`<tr><td>${esc(r.Name)}</td><td>${esc(r.KeyValue)}</td><td>${esc(rtFreq[r.ReportingFrequency]||r.ReportingFrequency)}</td><td>${esc(r.Units||'无量纲')} · ${esc(r.Type)}</td></tr>`).join('')}</tbody></table></div>`;
}
function rtShowTab(tab){
 const d=rtDialog(),panel=d.querySelector(`[data-rt-panel="${tab}"]`);if(!panel)return;
 for(const p of d.querySelectorAll('[data-rt-panel]'))p.hidden=p!==panel;
 for(const b of d.querySelectorAll('[data-rt-tab]'))b.setAttribute('aria-pressed',String(b.dataset.rtTab===tab));
 rtState.tab=tab;
 if(tab==='month' && panel.dataset.month!==String(rtState.month)){
   panel.innerHTML=rtMonthView();panel.dataset.month=rtState.month;rtEstimate();
 }
 if(tab==='series'&&!panel.children.length)rtSeriesSetup(panel);
 if(tab==='source'&&!d.querySelector('#rt-dictionary').children.length)rtDictionary();
}
async function rtOpen(batch,index,context=null,trigger=document.activeElement){
 const state={batch,index,context,trigger,month:context?.month,seq:++rtSequence};
 rtState=state;rtShell('<p role="status">正在读取当前算例实际保存的频率与时段…</p>');
 try{
   const d=await api(rtUrl('inventory'));if(rtState!==state)return;
   const expected=context?.sides[context.side];
   if(expected && (expected.sha!==d.summary_sha256 || !['passed','reused'].includes(d.registered_status)))throw Error('已有结果登记发生变化，请返回对比集重新读取。');
   state.inventory=d;
   state.month=state.month>=d.period[0]&&state.month<=d.period[2]?state.month:d.period[0];
   rtShell(rtInventory(d));rtShowTab((d.monthly_loads?.length||Object.keys(d.monthly_controls||{}).length)?'month':'series');
 }catch(e){if(rtState===state)rtShell(`<p class="warning" role="alert">${esc(e.message)}</p><p>可返回结果检查原始资料。</p>`);}
}
function rtInvalidate(){
 if(!rtState)return;rtSequence++;rtState.daily=null;
 const b=rtDialog().querySelector('[data-rt-load]');if(b)b.disabled=false;
 const t=rtDialog().querySelector('#rt-daily');if(t)t.textContent='请读取所选系统与日期。';
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-rt-batch],[data-rt-close],[data-rt-load],[data-rt-export],[data-rt-day],[data-rt-tab],[data-rt-tab-jump]');
 if(!b)return;e.preventDefault();e.stopImmediatePropagation();
 if(b.dataset.rtTab||b.dataset.rtTabJump){
   rtShowTab(b.dataset.rtTab||b.dataset.rtTabJump);
   const d=rtDialog(),name=b.dataset.rtControl||(b.hasAttribute('data-rt-control-picker') && d.querySelector('#rt-material-signal')?.value);
   if(name){
     d.querySelector('#rt-variable-name').value=name;
     d.querySelector('#rs-search').value='';
     rtSeriesOptions(true);
     const freq=d.querySelector('#rs-frequency');
     freq.value=['Zone Timestep','Hourly','Daily','Monthly','Run Period'].find(f=>[...freq.options].some(o=>o.value===f));
     rtSeriesOptions(false);rtSeriesDates();rtSeriesInvalidate();rtReadSeries();
   }
 }
 else if(b.hasAttribute('data-rt-close'))rtClose();
 else if(b.hasAttribute('data-rt-load'))rtLoad();
 else if(b.hasAttribute('data-rt-export'))rtExport();
 else if(b.hasAttribute('data-rt-day'))rtSelectDay(Number(b.dataset.rtDay));
 else rtOpen(b.dataset.rtBatch,Number(b.dataset.rtIndex),null,b);
},true);
document.addEventListener('input',e=>{
 if(e.target.id==='rt-dictionary-search')rtDictionary();
 else if(e.target.id==='rt-est-days')rtEstimate();
 else if(['rt-start','rt-end'].includes(e.target.id))rtInvalidate();
});
document.addEventListener('change',e=>{
 const t=e.target;
 if(['rt-est-start','rt-est-frequency'].includes(t.id))rtEstimate();
 else if(t.id==='rt-day')rtSelectDay(t.selectedIndex);
 else if(t.id==='rt-system')rtInvalidate();
 else if(t.id==='rt-side'){
   const ctx={...rtState.context,side:Number(t.value),month:rtState.month},side=ctx.sides[ctx.side];
   rtOpen(side.batch,side.index,ctx,rtState.trigger);
 }else if(t.id==='rt-month'){
   rtState.month=Number(t.value);rtInvalidate();
   const range=rtMonthRange();
   if(rtDialog().querySelector('#rt-start')){
     rtDialog().querySelector('#rt-start').value=range.start;rtDialog().querySelector('#rt-end').value=range.end;
   }
   rtSeriesDates();rtShowTab(rtState.tab);
 }
});
function rtChart(data){const max=Math.max(...data.rows.flatMap(r=>[r.heating_kWh,r.cooling_kWh]),0);const scale=max||1,width=760,height=210,step=width/data.rows.length;return `<p>供暖（棕色）／制冷（蓝色）· 日累积量 / kWh。柱高上限 ${format(max,3)}；选择日期查看双列数值。</p><svg class="rt-chart" viewBox="0 0 800 255" role="img" aria-label="逐日供暖与制冷需求柱图"><text x="0" y="15">${format(max,3)}</text><line x1="35" y1="225" x2="795" y2="225" class="rt-axis"/>${data.rows.map((r,i)=>{const x=35+i*step,h=r.heating_kWh/scale*height,c=r.cooling_kWh/scale*height;return `<g><title>${esc(r.date)}：供暖 ${format(r.heating_kWh,3)}；制冷 ${format(r.cooling_kWh,3)} kWh</title><rect class="rt-heat" x="${x+step*.12}" y="${225-h}" width="${step*.32}" height="${h}"/><rect class="rt-cool" x="${x+step*.48}" y="${225-c}" width="${step*.32}" height="${c}"/>${i===0||i===data.rows.length-1?`<text x="${Math.min(x,748)}" y="247">${esc(r.date)}</text>`:''}</g>`;}).join('')}</svg>`;}
function rtDaily(d){return `<h4>${esc(d.system)} · ${esc(d.start)} 至 ${esc(d.end)}</h4><p>${esc(d.meaning)}</p><p>${esc(d.acceptance_note||'')}</p>${rtChart(d)}<p>本次范围：供暖 ${format(d.sums.heating_kWh,3)} · 制冷 ${format(d.sums.cooling_kWh,3)} · 合计 ${format(d.sums.total_kWh,3)} kWh</p><label>联动查看日期<select id="rt-day">${rtOptions(d.rows.map(r=>r.date))}</select></label><p id="rt-selected" role="status"></p><button data-rt-export>导出当前范围 CSV</button><div class="viewer-table"><table class="table"><thead><tr><th>月-日</th><th>供暖 / kWh</th><th>制冷 / kWh</th><th>合计 / kWh</th></tr></thead><tbody>${d.rows.map((r,i)=>`<tr data-rt-row="${i}"><td><button data-rt-day="${i}">${esc(r.date)}</button></td><td>${format(r.heating_kWh,6)}</td><td>${format(r.cooling_kWh,6)}</td><td>${format(r.total_kWh,6)}</td></tr>`).join('')}</tbody></table></div><p class="muted">SQL 原始年字段：${[...new Set(d.rows.map(r=>r.time.Year))].join('、')}；按原模拟日历展示。完整数值及来源校验值随 CSV 保留。</p>`;}
function rtSelectDay(i){const d=rtState?.daily;if(!d)return;const r=d.rows[i];if(!r)return;rtDialog().querySelector('#rt-day').value=r.date;rtDialog().querySelector('#rt-selected').textContent=`${r.date}：供暖 ${format(r.heating_kWh,6)}，制冷 ${format(r.cooling_kWh,6)}，合计 ${format(r.total_kWh,6)} kWh`;rtDialog().querySelectorAll('[data-rt-row]').forEach(row=>row.classList.toggle('rt-selected',Number(row.dataset.rtRow)===i));}
async function rtLoad(){const seq=++rtSequence,target=rtDialog().querySelector('#rt-daily'),button=rtDialog().querySelector('[data-rt-load]');const params={system:rtDialog().querySelector('#rt-system').value,start:rtDialog().querySelector('#rt-start').value.trim(),end:rtDialog().querySelector('#rt-end').value.trim()};rtState.daily=null;button.disabled=true;target.innerHTML='<p role="status">正在读取所选范围…</p>';try{const d=await api(rtUrl('daily',params));if(seq!==rtSequence||!rtDialog().open)return;if(d.summary_sha256!==rtState.inventory.summary_sha256||d.sql_sha256!==rtState.inventory.sql_sha256)throw Error('结果资料已更新，请重新打开。');rtState.daily=d;target.innerHTML=rtDaily(d);rtSelectDay(0);}catch(e){if(seq===rtSequence&&rtDialog().open)target.innerHTML=`<p class="warning" role="alert">${esc(e.message)}</p>`;}finally{if(seq===rtSequence&&rtDialog().open)button.disabled=false;}}
function rtExport(){const d=rtState?.daily;if(!d)return;const cell=v=>'"'+String(typeof v==='string'&&/^[=+@-]/.test(v)?"'"+v:v??'').replaceAll('"','""')+'"';const lines=[['batch','case_index','identity','summary_sha256','sql_sha256','registered_status','acceptance_note','system','frequency','aggregation','source_units','display_units','month_day','sql_year','time_index','interval_minutes','heating_kWh','cooling_kWh','total_kWh'],...d.rows.map(r=>[d.batch,d.index,d.identity,d.summary_sha256,d.sql_sha256,d.registered_status,d.acceptance_note,/^[=+@-]/.test(d.system)?"'"+d.system:d.system,d.frequency,d.aggregation,d.source_units,d.units,r.date,r.time.Year,r.time.TimeIndex,r.time.Interval,r.heating_kWh,r.cooling_kWh,r.total_kWh])];const url=URL.createObjectURL(new Blob(['\uFEFF'+lines.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`daily-loads-${d.index+1}-${d.start}-${d.end}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

const rtPriorView=resultViewContent;
resultViewContent=function(v){const d=rtPriorView(v);if(d&&v.kind==='batch'){const row=S.executionResults.results.find(r=>r.index===S.batchSelected);d.groups.summary+=`<p><button data-rt-batch="${esc(row.evidence.batch_id)}" data-rt-index="${row.evidence.index}">查看输出频率与时序明细 ↗</button></p>`;}return d;};
const rtPriorReport=raReport;
raReport=function(r){return rtPriorReport(r)+`<p><button data-rt-batch="${esc(r.batch)}" data-rt-index="${r.index}">查看输出频率与时序明细 ↗</button></p>`;};

