'use strict';
const rtControlLabels={
 'NX_SC_StateOutput':'热阻状态 · 压缩 C 时间占比',
 'NX_SC_FaceOutput':'表面光学状态 · A 面朝外时间占比',
 'NX_FiveStorey_Flip_FaceOutput':'采用 A 的时间占比',
 'NX_Fb_StateOutput':'压缩时间占比',
 'NX_Fb_ChangedOutput':'热阻切换次数'
};
function rtControlName(name){
 if(Object.hasOwn(rtControlLabels,name))return rtControlLabels[name];
 const wall=/^NX (\S+) (State|Face)$/.exec(name);
 return wall?wall[1]+(wall[2]==='State'?' · 压缩 C 时间占比':' · A 面朝外时间占比'):'';
}
function rtVariableName(name){
 const labels={
  'Zone Ideal Loads Zone Sensible Heating Energy':'房间系统显热供暖需求',
  'Zone Ideal Loads Zone Sensible Cooling Energy':'房间系统显热制冷需求',
  'Zone Mean Air Temperature':'房间平均空气温度',
  'Zone Operative Temperature':'房间操作温度',
  'Site Outdoor Air Drybulb Temperature':'室外干球温度',
  'Surface Inside Face Temperature':'表面内侧温度','Surface Outside Face Temperature':'表面外侧温度',
  'Surface Inside Face Conduction Heat Transfer Rate per Area':'内侧表面传导热流密度',
  'Surface Outside Face Conduction Heat Transfer Rate per Area':'外侧表面传导热流密度',
  'Schedule Value':'作息或状态数值'
 };
 return rtControlName(name)||labels[name]||name;
}
const rtQueryable=['Daily','Hourly','Zone Timestep','Monthly','Run Period'];
function rtSeriesSetup(panel){
 const d=rtState.inventory;
 const variables=[...new Set(d.dictionary.filter(r=>rtQueryable.includes(r.ReportingFrequency)).map(r=>r.Name))];
 variables.sort((a,b)=>Number(rtVariableName(b)!==b)-Number(rtVariableName(a)!==a)||rtVariableName(a).localeCompare(rtVariableName(b),'zh-CN'));
 if(!variables.length){panel.innerHTML='<p>本结果未保存可按指标读取的记录。</p>';return;}
 const preferred=variables.find(v=>v==='Zone Mean Air Temperature')||variables[0];
 panel.innerHTML=`<h3>按指标查明细</h3><div class="rt-filter-grid"><label>指标<select id="rt-variable-name">${options(variables.map(v=>[v,rtVariableName(v)]),preferred)}</select></label>
 <label>保存频率<select id="rs-frequency"></select></label><label>查找对象<input id="rs-search" type="search" placeholder="输入房间、系统或表面编号"></label>
 <label>对象<select id="rs-variable"></select></label></div><p id="rs-hint" class="muted"></p>
 <div id="rs-range"></div><button class="primary" data-rs-action="load">读取明细</button><div id="rs-content" aria-live="polite"></div>`;
 rtSeriesOptions(true);
 rtSeriesDates();
}
function rtSeriesInvalidate(){
 const s=rtState;if(!s)return;
 s.seriesRequest=(s.seriesRequest||0)+1;s.series=null;
 const panel=rtDialog().querySelector('#rs-content');
 if(panel)panel.replaceChildren();
 const button=rtDialog().querySelector('[data-rs-action="load"]');
 if(button)button.disabled=!rtDialog().querySelector('#rs-variable')?.value;
}
function rtSeriesOptions(resetFrequency){
 const d=rtDialog(),name=d.querySelector('#rt-variable-name').value;
 const all=rtState.inventory.dictionary.filter(r=>r.Name===name);
 const freq=d.querySelector('#rs-frequency');
 if(resetFrequency){
   const allowed=rtQueryable.filter(f=>all.some(r=>r.ReportingFrequency===f));
   freq.innerHTML=options(allowed.map(f=>[f,rtFreq[f]]),allowed[0]);
 }
 const text=d.querySelector('#rs-search').value.trim().toLowerCase();
 const matches=all.filter(r=>r.ReportingFrequency===freq.value && r.KeyValue.toLowerCase().includes(text));
 const obj=d.querySelector('#rs-variable'),previous=obj.value;
 obj.innerHTML=options(matches.map(r=>[r.ReportDataDictionaryIndex,r.KeyValue]),previous);
 obj.disabled=!matches.length;
 d.querySelector('#rs-hint').textContent=matches.length?`${matches.length} 个匹配对象 · 原变量 ${name}`:'没有匹配的对象，请更改搜索。';
}
function rtSeriesDates(){
 const d=rtDialog(),target=d.querySelector('#rs-range');if(!target)return;
 const freq=d.querySelector('#rs-frequency').value;
 if(freq==='Monthly')target.innerHTML='<label>统计范围<select id="rs-month-range"><option value="one">所选月份</option><option value="all">全部已算月份</option></select></label>';
 else if(freq==='Run Period')target.innerHTML='<p class="muted">读取整个计算时段的一个统计值。</p>';
 else{
   target.innerHTML=`<div class="rt-range"><div class="rt-presets"><button data-rs-days="1">首日</button><button data-rs-days="7">前 7 天</button><button data-rs-days="month">本月</button></div>${rtDateFields('rs')}</div><p class="muted" id="rs-size"></p>`;
   const range=rtMonthRange(),perDay=freq==='Daily'?1:freq==='Hourly'?24:1440/rtState.inventory.step_minutes;
   const days=Math.min(31,Math.floor(12000/perDay),range.last-range.first+1);
   d.querySelector('#rs-end').value=rtMD(rtState.month,range.first+days-1);
   rtSeriesSize();
 }
 rtSeriesInvalidate();
}
function rtSeriesSize(){
 const d=rtDialog(),hint=d.querySelector('#rs-size');if(!hint)return;
 const dates=['#rs-start','#rs-end'].map(id=>d.querySelector(id).value);
 const parsed=dates.map(value=>{
   if(!/^\d{2}-\d{2}$/.test(value))return NaN;
   const [m,day]=value.split('-').map(Number),ts=Date.UTC(2025,m-1,day);
   return new Date(ts).getUTCMonth()===m-1?ts:NaN;
 });
 const days=1+(parsed[1]-parsed[0])/86400000,frequency=d.querySelector('#rs-frequency').value;
 const points=days*(frequency==='Hourly'?24:frequency==='Daily'?1:1440/rtState.inventory.step_minutes);
 const [m1,d1,m2,d2]=rtState.inventory.period;
 const valid=days>=1&&days<=31&&points<=12000&&dates[0]>=rtMD(m1,d1)&&dates[1]<=rtMD(m2,d2);
 hint.textContent=valid?`所选范围预计 ${format(points,0)} 个读数。`:'请在已算时段内选择连续 1—31 天，最多 12,000 个读数。';
 return valid;
}
function rtSeriesSelection(){
 const d=rtDialog(),variable=Number(d.querySelector('#rs-variable').value);
 const f=d.querySelector('#rs-frequency').value,whole=f==='Run Period'||(f==='Monthly'&&d.querySelector('#rs-month-range').value==='all');
 if(whole){const [sm,sd,em,ed]=rtState.inventory.period;return {variable,start:rtMD(sm,sd),end:rtMD(em,ed)};}
 if(f==='Monthly'){const r=rtMonthRange();return {variable,start:r.start,end:r.end};}
 if(!rtSeriesSize())throw Error('请先调整日期范围。');
 return {variable,start:d.querySelector('#rs-start').value,end:d.querySelector('#rs-end').value};
}
function rtSeriesChart(rows,unit,scale){
 if(rows.length===1)return `<p class="rt-single"><strong>${format(rows[0].Value*scale,4)}</strong> ${esc(unit)} · ${esc(rows[0].label)}</p>`;
 const values=rows.map(r=>r.Value*scale),min=Math.min(...values),max=Math.max(...values);
 // Draw each saved interval as a step; a constant series stays visible on the centre line.
 const y=v=>max===min?60:108-96*(v-min)/(max-min);
 const x=i=>5+i*710/rows.length;
 let line='M5 '+y(values[0]).toFixed(2);
 for(let i=0;i<values.length;i++)line+=`V${y(values[i]).toFixed(2)}H${x(i+1).toFixed(2)}`;
 return `<figure class="rt-series-chart"><figcaption>最低 ${format(min,3)} · 最高 ${format(max,3)} ${esc(unit)}</figcaption><svg viewBox="0 0 720 120" preserveAspectRatio="none" role="img" aria-label="所选指标的区间读数"><path d="${line}"/><line class="rt-cursor" x1="${x(.5)}" x2="${x(.5)}" y1="0" y2="120"/></svg><div><span>${esc(rows[0].label)}</span><span>${esc(rows.at(-1).label)}</span></div>
 <label>逐点查看<input id="rt-series-cursor" type="range" min="0" max="${rows.length-1}" value="0"></label><output for="rt-series-cursor" data-rt-cursor-output>${esc(rows[0].label)} · ${format(values[0],4)} ${esc(unit)}</output></figure>`;
}
function rtSeriesUnit(v){
 if(v.KeyValue==='EMS' && rtControlName(v.Name) && !v.Units){
   if(v.Type==='Avg')return {unit:'%',scale:100};
   if(v.Name==='NX_Fb_ChangedOutput' && v.Type==='Sum')return {unit:'次',scale:1};
 }
 const sensible=v.Type==='Sum'&&v.Units==='J'&&['Zone Ideal Loads Zone Sensible Heating Energy','Zone Ideal Loads Zone Sensible Cooling Energy'].includes(v.Name);
 return sensible?{unit:'kWh',scale:1/3600000}:{unit:v.Units||'无量纲',scale:1};
}
function rtSeriesCursor(i){
 const data=rtState.series,row=data?.rows[i];if(!row)return;
 const d=rtDialog(),cursor=d.querySelector('#rt-series-cursor'),mark=d.querySelector('.rt-cursor');
 const {scale,unit}=rtSeriesUnit(data.variable),x=5+(i+.5)*710/data.rows.length;
 cursor.value=i;mark.setAttribute('x1',x);mark.setAttribute('x2',x);
 const label=row.label+' · '+format(row.Value*scale,4)+' '+unit;
 d.querySelector('[data-rt-cursor-output]').textContent=label;cursor.setAttribute('aria-valuetext',label);
}
function rtSeriesResult(d){
 const v=d.variable,unit=v.Units||'无量纲',coarse=['Monthly','Run Period'].includes(v.ReportingFrequency);
 const display=rtSeriesUnit(v);
 return `<div class="rt-readout"><h4>${esc(rtVariableName(v.Name))} · ${esc(v.KeyValue)}</h4><p>${esc(rtFreq[v.ReportingFrequency])} · ${v.Type==='Sum'?'区间累积量':v.Type==='Avg'?'区间均值':esc(v.Type)} · 原单位 ${esc(unit)} · ${format(d.rows.length,0)} 个读数</p>
 ${v.SharedSchedule?`<p>原作息 ${esc(v.KeyValue)} 共用 ${esc(v.SharedSchedule)} 的读数。</p>`:''}
 ${display.unit==='%'?'<p>原始值为 0–1。图中显示所选状态在该区间的时间占比。</p>':''}
 ${rtSeriesChart(d.rows,display.unit,display.scale)}<button data-rs-action="export">导出所选时序 CSV</button><details><summary>查看原始数值（${Math.min(300,d.rows.length)} 行）</summary><div class="viewer-table"><table class="table"><thead><tr><th>${coarse?'统计时段':'区间结束时刻'}</th><th>原始数值 / ${esc(unit)}</th></tr></thead><tbody>${d.rows.slice(0,300).map(r=>`<tr><td>${esc(r.label)}</td><td>${r.Value}</td></tr>`).join('')}</tbody></table></div>${d.rows.length>300?'<p>CSV 包含所选范围的全部读数。</p>':''}</details></div>`;
}
async function rtReadSeries(){
 const s=rtState,d=rtDialog(),target=d.querySelector('#rs-content'),button=d.querySelector('[data-rs-action="load"]');
 const seq=(s.seriesRequest||0)+1;s.seriesRequest=seq;s.series=null;
 try{
   const params=rtSeriesSelection();button.disabled=true;target.textContent='正在核对并读取所选输出…';
   const data=await rtDetail('series',params);
   if(rtState!==s||s.seriesRequest!==seq)return;
   if(data.summary_sha256!==s.inventory.summary_sha256||data.sql_sha256!==s.inventory.sql_sha256)throw Error('结果资料已更新，请关闭并重新打开。');
   s.series=data;target.innerHTML=rtSeriesResult(data);if(data.rows.length>1)rtSeriesCursor(0);
 }catch(e){if(rtState===s&&s.seriesRequest===seq)target.textContent=e.message;}
 finally{if(rtState===s&&s.seriesRequest===seq)button.disabled=false;}
}
function rtSeriesExport(){
 const d=rtState?.series;if(!d)return;
 const cell=x=>'"'+String(typeof x==='string'&&/^[=+@-]/.test(x)?"'"+x:x??'').replaceAll('"','""')+'"';
 const coarse=['Monthly','Run Period'].includes(d.variable.ReportingFrequency);
 const display=rtSeriesUnit(d.variable);
 const rows=[['batch','case_index','sql_sha256','status','acceptance_note','variable','object','frequency','units','aggregation',coarse?'period':'interval_end','interval_minutes','value','指标','显示单位','显示值'],...d.rows.map(r=>[d.batch,d.index,d.sql_sha256,d.registered_status,d.acceptance_note,d.variable.Name,d.variable.KeyValue,d.variable.ReportingFrequency,d.variable.Units,d.variable.Type,r.label,r.Interval,r.Value,rtVariableName(d.variable.Name),display.unit,r.Value*display.scale])];
 if(d.variable.SharedSchedule){rows[0].push('共享作息对象');for(const row of rows.slice(1))row.push(d.variable.SharedSchedule);}
 const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=`series-${d.index+1}-${d.start}-${d.end}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.addEventListener('change',e=>{
 if(!rtState||!rtDialog().contains(e.target))return;
 const id=e.target.id;
 if(id==='rt-variable-name'||id==='rs-frequency'){
   if(id==='rt-variable-name')rtDialog().querySelector('#rs-search').value='';
   rtSeriesOptions(id==='rt-variable-name');rtSeriesDates();
 }else if(id==='rs-variable'||id==='rs-month-range')rtSeriesInvalidate();
});
document.addEventListener('input',e=>{
 if(!rtState||!rtDialog().contains(e.target))return;
 if(e.target.id==='rs-search'){rtSeriesOptions(false);rtSeriesInvalidate();}
 else if(e.target.id==='rt-series-cursor')rtSeriesCursor(Number(e.target.value));
 else if(['rs-start','rs-end'].includes(e.target.id)){rtSeriesInvalidate();rtSeriesSize();}
});
document.addEventListener('click',e=>{
 if(!rtState||!rtDialog().contains(e.target))return;
 const chart=e.target.closest('.rt-series-chart svg');
 if(chart&&rtState.series){
   const box=chart.getBoundingClientRect(),n=rtState.series.rows.length;
   const bin=Math.floor((((e.clientX-box.left)/box.width)*720-5)*n/710);
   rtSeriesCursor(Math.max(0,Math.min(n-1,bin)));return;
 }
 const b=e.target.closest('[data-rs-action],[data-rs-days]');if(!b)return;
 e.preventDefault();e.stopImmediatePropagation();
 if(b.dataset.rsDays){
   const r=rtMonthRange();rtDialog().querySelector('#rs-start').value=r.start;
   rtDialog().querySelector('#rs-end').value=b.dataset.rsDays==='month'?r.end:rtMD(rtState.month,Math.min(r.first+Number(b.dataset.rsDays)-1,r.last));
   rtSeriesInvalidate();rtSeriesSize();
 }else if(!b.disabled){if(b.dataset.rsAction==='load')void rtReadSeries();else rtSeriesExport();}
},true);
