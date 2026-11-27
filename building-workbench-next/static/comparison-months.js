const commonMonthMetrics = ['heating','cooling','total'];
const commonMonthChoices = new Map();

function monthPeriodText(p){
 return `${p[0]}月${p[1]}日—${p[2]}月${p[3]}日`;
}
function monthStartText(p,month){
 return p[0]===month && p[1]===1 ? '从本月1日起算并预热' : `从${p[0]}月${p[1]}日开始，连续运行至本月`;
}
function commonMonthSelection(d){
 const choice=commonMonthChoices.get(d.dataset_sha256);
 const month=d.common_months.months.find(m=>m.month===choice?.month);
 const valid=month?.sites.filter(s=>!s.reason)||[];
 return {month,valid,site:valid.find(s=>s.site_id===choice?.site)||valid[0]};
}
function rememberCommonMonth(d,month,site){
 const details=commonMonthChoices.get(d.dataset_sha256)?.details||{};
 commonMonthChoices.delete(d.dataset_sha256);
 commonMonthChoices.set(d.dataset_sha256,{month,site,details});
 if(commonMonthChoices.size>4)commonMonthChoices.delete(commonMonthChoices.keys().next().value);
}
const monthColors={left:'#78929f',right:'#20735d'};
function monthContext(scope,month){
 const a=scope.left_period,b=scope.right_period;
 if(a[0]===b[0]&&a[1]===b[1])return `双方均从${a[0]}月${a[1]}日起算，各自预热。`;
 return `参考${monthStartText(a,month)}，研究${monthStartText(b,month)}。起算日期不同，月初负荷可能受此前运行影响。`;
}
function monthSeries(site){
 const rows=commonMonthMetrics.map(key=>({name:metricNames[key],left:site['left_'+key+'_kWh'],right:site['right_'+key+'_kWh']}));
 const peak=Math.max(...rows.flatMap(r=>[r.left,r.right]));
 return rows.map(r=>({...r,width:side=>peak>0?r[side]/peak:0}));
}
function monthChange(site,metric){
 const delta=site[metric+'_saved_kWh'],percent=site[metric+'_saved_percent'];
 const direction=delta>0?'降低':delta<0?'增加':'持平';
 const relative=delta!==0&&Number.isFinite(percent);
 return {label:`研究侧${metricNames[metric]}${direction}`,direction,
  value:format(Math.abs(relative?percent:delta)),unit:relative?'%':'kWh',
  note:relative?`相差 ${format(Math.abs(delta))} kWh`:delta!==0?'参考需求为零，按绝对差值显示':'两侧需求相同'};
}
function commonMonthChart(d,m,site){
 // Downloadable vector figure. Keep source periods and units with the figure when it leaves the page.
 const scope=d.common_months,change=monthChange(site,d.metric);
 const title=`${site.city} · ${m.month}月建筑显热需求`;
 const lines=title.match(/.{1,32}/gu)||[title];
 const top=34+(lines.length-1)*27;
 const groups=monthSeries(site).map((r,i)=>{
  const y=top+129+i*58;
  const pair=['left','right'].map((side,j)=>{
   const rowY=y+j*20;
   return `<line x1="144" x2="563" y1="${rowY}" y2="${rowY}" stroke="#edf1f1" stroke-width="8"/>
   <rect x="144" y="${rowY-4}" width="${419*r.width(side)}" height="8" rx="2" fill="${monthColors[side]}"/>
   <text x="704" y="${rowY+5}" text-anchor="end">${format(r[side])}</text>`;
  }).join('');
  return `<text x="28" y="${y+13}" font-weight="600">${r.name}</text>${pair}`;
 }).join('');
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 736 ${top+383}" width="736" height="${top+383}" role="img" aria-label="${esc(title)}" font-family="Segoe UI,Microsoft YaHei,sans-serif" font-size="14" fill="#203934">
 <title>${esc(title)}</title><rect width="100%" height="100%" fill="#fff"/>
 ${lines.map((line,i)=>`<text x="28" y="${34+27*i}" font-size="22" font-weight="650">${esc(line)}</text>`).join('')}
 <text x="28" y="${top+29}">${m.month}月1日至${m.month}月${m.days}日 · ${change.label} ${change.value} ${change.unit}</text>
 <line x1="28" x2="708" y1="${top+50}" y2="${top+50}" stroke="#d8e2de"/>
 <text x="28" y="${top+85}">需求量 / kWh</text>
 <rect x="550" y="${top+75}" width="14" height="9" rx="2" fill="${monthColors.left}"/><text x="571" y="${top+85}">参考</text>
 <rect x="636" y="${top+75}" width="14" height="9" rx="2" fill="${monthColors.right}"/><text x="657" y="${top+85}">研究</text>
 ${groups}<line x1="28" x2="708" y1="${top+289}" y2="${top+289}" stroke="#d8e2de"/>
 <g fill="#4e655b"><text x="28" y="${top+313}">参考 · ${monthPeriodText(scope.left_period)} · ${site.left_step_minutes} min</text>
 <text x="28" y="${top+335}">研究 · ${monthPeriodText(scope.right_period)} · ${site.right_step_minutes} min</text>
 <text x="28" y="${top+361}" font-size="13">${monthContext(scope,m.month)}</text></g></svg>`;
}
function monthProfile(site){
 const rows=monthSeries(site).map(r=>`<div class="cm-series"><span class="cm-series-name">${r.name}</span><div>
 ${['left','right'].map(side=>`<div class="cm-reading"><svg class="cm-track" width="100%" height="7" aria-hidden="true"><rect width="${100*r.width(side)}%" height="7" rx="2" fill="${monthColors[side]}"/></svg><span aria-label="${side==='left'?'参考':'研究'} ${format(r[side])} kWh">${format(r[side])}</span></div>`).join('')}
 </div></div>`).join('');
 return `<div class="cm-chart"><div class="cm-chart-head"><strong>需求量 <small>kWh</small></strong><div class="cm-legend"><span><i class="cm-left"></i>参考</span><span><i class="cm-right"></i>研究</span></div></div>${rows}</div>`;
}
function monthTable(m){
 const rows=m.sites.map(s=>{
  const site=`${esc(s.city)}<small>参考 ${s.left_step_minutes??'—'} min · 研究 ${s.right_step_minutes??'—'} min</small>`;
  if(s.reason)return `<tr><th>${site}</th><td colspan="6" class="cm-reason">未纳入 · ${esc(s.reason)}</td></tr>`;
  return commonMonthMetrics.map((k,i)=>`<tr>${i===0?`<th rowspan="3">${site}</th>`:''}<th scope="row">${metricNames[k]}</th><td>${format(s['left_'+k+'_kWh'])}</td><td>${format(s['right_'+k+'_kWh'])}</td><td>${format(s[k+'_saved_kWh'])}</td><td>${format(s[k+'_saved_MJ_m2'])}</td><td>${s[k+'_saved_percent']==null?'—':format(s[k+'_saved_percent'])+'%'}</td></tr>`).join('');
 }).join('');
 return `<div class="table-scroll"><table class="table"><caption>差值按参考减研究计算，正值表示需求降低。</caption><thead><tr><th>地点 / 实际步长</th><th>需求</th><th>参考 / kWh</th><th>研究 / kWh</th><th>降低 / kWh</th><th>降低 / MJ/m²</th><th>降低率</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function commonMonthView(d){
 const scope=d.common_months,{month,valid,site}=commonMonthSelection(d);
 const buttons=scope.months.map(m=>`<button data-common-month="${m.month}" aria-label="比较共同的 ${m.month} 月" aria-pressed="${month?.month===m.month}">${m.month} 月</button>`).join('');
 const header=`<header class="cm-heading"><h3>共同月份负荷对比</h3>${buttons?`<div class="cm-months" role="group" aria-label="选择比较月份">${buttons}</div>`:''}</header>`;
 const periods=`<div class="cm-periods"><span><b>参考</b> ${monthPeriodText(scope.left_period)}${site?` · ${site.left_step_minutes} min`:''}</span><span><b>研究</b> ${monthPeriodText(scope.right_period)}${site?` · ${site.right_step_minutes} min`:''}</span></div>`;
 if(!month)return `<section class="cm-panel">${header}${periods}<p class="cm-note">${buttons?'选择双方完整覆盖的月份，查看负荷差值。':'双方没有共同覆盖的完整自然月。'}</p></section>`;
 const change=site&&monthChange(site,d.metric);
 const picker=valid.length>1?`<select id="common-month-site" aria-label="图表地点">${options(valid.map(s=>[s.site_id,s.city]),site.site_id)}</select>`:esc(site?.city);
 const open=commonMonthChoices.get(d.dataset_sha256)?.details?.[month.month]??month.paired_sites<month.sites.length;
 return `<section class="cm-panel" id="selected-common-month">${header}
 ${site?`<div class="cm-visual"><div class="cm-result">
 <div class="cm-site">${picker}</div><p class="cm-dates">${month.month}月1日—${month.month}月${month.days}日</p>
 <div class="cm-change" data-direction="${change.direction}"><strong>${change.value}<small>${change.unit}</small></strong><span>${change.label}</span></div>
 <p class="cm-amount">${change.note}</p></div>${monthProfile(site)}</div>`:`<p class="cm-note">${month.month}月1日—${month.month}月${month.days}日 · 没有可配对地点</p>`}
 ${site?`<div id="cm-daily">${monthDailyView(monthDailyState(d,month,site))}</div>`:''}
 ${periods}<p class="cm-note">${monthContext(scope,month.month)}</p>
 <div class="cm-foot"><details class="cm-details"${open?' open':''}><summary>地点明细 <small>${month.paired_sites} / ${month.sites.length} 个地点配对</small></summary>${monthTable(month)}</details>
 <div class="cm-downloads"><button data-common-month-export="csv">导出明细 CSV</button>${site?'<button data-common-month-export="svg">下载负荷图 SVG</button>':''}</div></div></section>`;
}
function commonMonthCsv(d,m){
 const {left_period:left,right_period:right}=d.common_months;
 const rows=[['比较月份','月内天数','地点','地点编号','配对状态','排除原因','参考方案','研究方案','参考所选来源','研究所选来源','参考实际结果来源','研究实际结果来源','参考原时段','研究原时段','参考起算','研究起算','参考步长_min','研究步长_min','建筑显热需求','参考_kWh','研究_kWh','参考减研究_kWh','降低_MJ_m2','降低率_%','核验数据标识']];
 const evidence=new Map(d.sites.map(s=>[s.site_id,s]));
 for(const s of m.sites){
  const pin=evidence.get(s.site_id);
  for(const k of (s.reason?[null]:commonMonthMetrics)){
   rows.push([m.month,m.days,s.city,s.site_id,s.reason?'未纳入':'同月同步长配对',s.reason,
    d.records.left.name+' v'+d.records.left.revision,d.records.right.name+' v'+d.records.right.revision,
    d.left.id,d.right.id,pin?.left_evidence?.batch_id||pin?.left_evidence?.job_id||(s.reason?'':d.left.id),
    pin?.right_evidence?.batch_id||pin?.right_evidence?.job_id||(s.reason?'':d.right.id),
    monthPeriodText(left),monthPeriodText(right),monthStartText(left,m.month),monthStartText(right,m.month),
    s.left_step_minutes,s.right_step_minutes,k&&metricNames[k],s['left_'+k+'_kWh'],s['right_'+k+'_kWh'],s[k+'_saved_kWh'],s[k+'_saved_MJ_m2'],s[k+'_saved_percent'],d.dataset_sha256]);
  }
 }
 const field=v=>'"'+String(typeof v==='string'&&/^[\s]*[=+@-]/.test(v)?"'"+v:v??'').replaceAll('"','""')+'"';
 return '\uFEFF'+rows.map(row=>row.map(field).join(',')).join('\r\n');
}
function commonMonthAction(button){
 const d=S.comparisonData;
 if(!d?.common_months)return false;
 if(button.dataset.commonMonth){
  const requested=Number(button.dataset.commonMonth);
  if(d.common_months.months.some(m=>m.month===requested))rememberCommonMonth(d,requested,commonMonthSelection(d).site?.site_id);
  return true;
 }
 const {month,site}=commonMonthSelection(d);
 if(!month)return false;
 const stem=`共同月份-${month.month}月-${d.dataset_sha256.slice(0,12)}`;
 if(button.dataset.commonMonthExport==='csv')rlDownload(stem+'.csv',commonMonthCsv(d,month),'text/csv;charset=utf-8');
 if(button.dataset.commonMonthExport==='svg'&&site)rlDownload(stem+'-'+site.site_id+'.svg',commonMonthChart(d,month,site),'image/svg+xml;charset=utf-8');
 return true;
}
document.addEventListener('change',e=>{
 if(e.target.id!=='common-month-site')return;
 const d=S.comparisonData;
 rememberCommonMonth(d,commonMonthSelection(d).month.month,e.target.value);
 render();
});
document.addEventListener('toggle',e=>{
 if(!e.target.matches?.('.cm-details')||!e.target.isConnected)return;
 const choice=commonMonthChoices.get(S.comparisonData?.dataset_sha256);
 if(choice)choice.details[choice.month]=e.target.open;
},true);
const monthDailyViews = new Map();

function monthDailyState(d,m,site){
 const key=JSON.stringify([d.dataset_sha256,m.month,site.site_id]);
 if(!monthDailyViews.has(key)){
  monthDailyViews.set(key,{open:false,metric:commonMonthMetrics.includes(d.metric)?d.metric:'total',day:1});
  if(monthDailyViews.size>8)monthDailyViews.delete(monthDailyViews.keys().next().value);
 }
 const state=monthDailyViews.get(key);
 monthDailyViews.delete(key);
 monthDailyViews.set(key,state);
 return state;
}

async function monthDailySide(evidence,month,site,side){
 if(evidence?.kind!=='execution')throw Error('这个来源只登记了汇总，无法读取算例逐日记录。');
 const {batch_id:batch,index}=evidence;
 const {summary:inventory}=await rtReadInventory(batch,index);
 if(inventory.identity!==evidence.identity || inventory.summary_sha256!==evidence.result_sha256 ||
    inventory.step_minutes!==site[side+'_step_minutes'] || !['passed','reused'].includes(inventory.registered_status)){
  throw Error('当前登记与本次对比的算例不一致，请重新读取对比结果。');
 }
 const frequencies=inventory.coverage.filter(c=>c.signal==='显热需求').map(c=>c.frequency);
 if(!frequencies.includes('Daily')){
  if(frequencies.length && frequencies.every(f=>f==='Monthly'||f==='Run Period')){
   throw Error('只保存了月度或全期冷热需求汇总，无法还原每天的负荷。');
  }
  throw Error('缺少原生逐日冷热需求记录。'+(frequencies.length?'已登记频率为 '+frequencies.map(f=>rtFreq[f]||f).join('、')+'。':''));
 }
 if(inventory.building_daily_issue)throw Error(inventory.building_daily_issue);
 const date=day=>rtMD(month.month,day);
 const result=await rtReadDetail(batch,index,inventory.view_token,'daily',{
  system:'',scope:'building',start:date(1),end:date(month.days)
 });
 if(result.rows.length!==month.days || result.rows.some((row,i)=>row.date!==date(i+1))){
  throw Error('缺少完整自然月的逐日记录。');
 }
 for(const metric of commonMonthMetrics){
  const actual=result.sums[metric+'_kWh'],expected=site[side+'_'+metric+'_kWh'];
  if(!Number.isFinite(actual)||!Number.isFinite(expected)||Math.abs(actual-expected)>Math.max(1e-7,1e-8*Math.abs(expected))){
   throw Error('逐日负荷之和与本次对比的月度值不符，请重新核对来源。');
  }
 }
 return result.rows;
}

async function loadMonthDaily(d,m,site,state){
 const evidence=d.sites.find(s=>s.site_id===site.site_id);
 state.loading=true;
 state.errors=[];
 try{
  const sides=['left','right'];
  const values=await Promise.allSettled(sides.map(side=>monthDailySide(evidence?.[side+'_evidence'],m,site,side)));
  state.errors=values.flatMap((v,i)=>v.status==='rejected'?[(i?'研究侧':'参考侧')+' · '+v.reason.message]:[]);
  state.rows=state.errors.length?null:values[0].value.map((left,i)=>({date:left.date,left,right:values[1].value[i]}));
  if(!state.rows)state.roomSides=null;
  else if(state.open&&state.roomOpen)void loadMonthRooms(d,m,site,state);
 }finally{
  state.loading=false;
  refreshMonthDaily(state);
 }
}

const monthRoomReads = new RecentViewReader(8);

async function monthRoomSide(evidence,month,state,side){
 const range={start:rtMD(month.month,1),end:rtMD(month.month,month.days)};
 const url=rtCaseUrl('daily-rooms',evidence.batch_id,evidence.index,range);
 const {summary}=await monthRoomReads.read(url,false,async known=>{
  const data=await api(url+(known?'&known='+encodeURIComponent(known):''));
  return {view_token:data.view_token,summary:data.unchanged?undefined:data};
 });
 if(summary.identity!==evidence.identity || summary.summary_sha256!==evidence.result_sha256 ||
    !['passed','reused'].includes(summary.registered_status))throw Error('结果登记发生变化，请重新读取对比。');
 if(summary.rows.length!==month.days)throw Error('缺少完整月份的房间记录。');
 return summary.rows.map((row,i)=>{
  const building=state.rows?.[i]?.[side];
  if(!building||row.date!==building.date)throw Error('房间日期与建筑当天的记录不符。');
  const totals={};
  for(const metric of commonMonthMetrics){
   const field=metric+'_kWh';
   totals[field]=row.rooms.reduce((sum,r)=>sum+r[field],0);
   if(!Number.isFinite(totals[field])||Math.abs(totals[field]-building[field])>Math.max(1e-7,1e-8*Math.abs(building[field]))){
    throw Error('房间合计与 '+row.date+' 的建筑负荷不符。');
   }
  }
  return {rooms:row.rooms,totals};
 });
}

async function loadMonthRooms(d,month,site,state){
 if(state.roomLoading)return;
 state.roomLoading=true;
 state.roomErrors=[];
 try{
  const pin=d.sites.find(s=>s.site_id===site.site_id);
  const reads=await Promise.allSettled(['left','right'].map(side=>monthRoomSide(pin[side+'_evidence'],month,state,side)));
  state.roomErrors=reads.flatMap((r,i)=>r.status==='rejected'?[(i?'研究侧':'参考侧')+' · '+r.reason.message]:[]);
  state.roomSides=state.roomErrors.length?null:reads.map(r=>r.value);
 }finally{
  state.roomLoading=false;
  refreshMonthDaily(state);
 }
}

function monthRoomTable(state){
 if(state.roomErrors?.length)return `<div role="alert">${state.roomErrors.map(s=>`<p>${esc(s)}</p>`).join('')}</div><button data-cm-daily="room-retry">重新读取房间明细</button>`;
 if(!state.roomSides)return '<p role="status">正在读取双方模型的房间连接与逐日负荷…</p>';
 const field=state.metric+'_kWh',index=state.day-1;
 const [left,right]=state.roomSides.map(days=>days[index]);
 const pairs=new Map();
 for(const [side,day] of [['left',left],['right',right]]){
  for(const record of day.rooms){
   const key=record.room.toUpperCase();
   if(!pairs.has(key))pairs.set(key,{name:record.room});
   pairs.get(key)[side]=record[field];
  }
 }
 const all=Array.from(pairs.values(),p=>({...p,delta:p.left==null||p.right==null?null:p.left-p.right}));
 const increases=all.filter(p=>p.delta<0);
 const onlyIncreases=state.roomOrder==='increase';
 const rows=(onlyIncreases?increases:all).sort((a,b)=>
  Number(a.delta==null)-Number(b.delta==null) || (onlyIncreases?a.delta-b.delta:b.delta-a.delta) || a.name.localeCompare(b.name,'zh-CN',{numeric:true}));
 const signed=v=>(v>0?'+':'')+format(v);
 const totalLeft=left.totals[field],totalRight=right.totals[field];
 const unmatched=all.filter(p=>p.delta==null).length;
 return `<div class="cm-room-head"><strong>${state.rows[index].date} · ${metricNames[state.metric]} <small>kWh</small></strong>
 <select id="cm-room-order" aria-label="房间显示顺序"><option value="saving">全部房间 · 降低最多在前</option>
 <option value="increase"${onlyIncreases?' selected':''}>仅看需求增加（${increases.length}）</option></select></div>
 ${unmatched?`<p class="cm-note">${unmatched} 个房间仅一侧有记录，双方均有读数的房间可计算差值。</p>`:''}
 <div class="cm-room-scroll" tabindex="0" aria-label="房间负荷明细"><table class="table"><thead><tr><th scope="col">房间</th><th scope="col">参考</th><th scope="col">研究</th><th scope="col">差值</th></tr></thead><tbody>
 ${rows.map(p=>`<tr><th scope="row">${esc(p.name)}</th><td>${p.left==null?'—':format(p.left)}</td><td>${p.right==null?'—':format(p.right)}</td><td>${p.delta==null?'—':signed(p.delta)}</td></tr>`).join('')||'<tr><td colspan="4">当天没有配对房间的需求增加。</td></tr>'}
 </tbody></table></div><div class="cm-room-total"><strong>全部房间合计</strong> <span>参考 ${format(totalLeft)}</span><span>研究 ${format(totalRight)}</span><span>差值 ${signed(totalLeft-totalRight)} kWh</span><small>已与建筑当日负荷核对</small></div>`;
}

function monthDailyPlot(deltas,day){
 const peak=Math.max(...deltas.map(Math.abs));
 const magnitude=peak?10**Math.floor(Math.log10(peak)):1;
 const cap=Math.ceil(peak/magnitude)*magnitude;
 const width=620,mid=70,slot=width/deltas.length;
 const marks=deltas.map((delta,i)=>{
  const height=cap?Math.abs(delta)/cap*mid:0;
  const x=i*slot,top=delta>0?mid-height:mid;
  const bar=height?`<rect class="${delta>0?'cm-saving':'cm-increase'}" x="${x+slot*.16}" y="${top}" width="${slot*.68}" height="${height}"/>`:
   `<line class="cm-flat" x1="${x+slot*.2}" x2="${x+slot*.8}" y1="${mid}" y2="${mid}"/>`;
  return `<g data-cm-day="${i+1}"><rect x="${x}" width="${slot}" height="140" fill="${i+1===day?'#dce8e3':'transparent'}"/>${bar}</g>`;
 }).join('');
 const tick=cap?cap.toLocaleString('zh-CN',{maximumSignificantDigits:3}):'';
 return `<div class="cm-daily-plot"><div class="cm-daily-axis" aria-hidden="true"><span>${cap?'+'+tick:''}</span><span>0</span><span>${cap?'−'+tick:''}</span></div>
 <svg viewBox="0 0 ${width} 140" preserveAspectRatio="none" role="img" aria-label="每日需求差值，单位千瓦时。可点选柱形或在下方选择日期。">
 <line class="cm-zero" x2="${width}" y1="${mid}" y2="${mid}"/>${marks}</svg>
 <div class="cm-daily-dates" aria-hidden="true"><span>1 日</span><span>${Math.ceil(deltas.length/2)} 日</span><span>${deltas.length} 日</span></div></div>`;
}

function monthDailyView(state){
 const toggle=`<button id="cm-daily-toggle" data-cm-daily="toggle" aria-expanded="${state.open}" aria-controls="cm-daily-content">${state.open?'收起逐日差值':'查看逐日差值'}</button>`;
 if(!state.open)return `${toggle}<div id="cm-daily-content" hidden></div>`;
 let content;
 if(state.errors?.length){
  content=`<div role="alert">${state.errors.map(e=>`<p>${esc(e)}</p>`).join('')}</div><button data-cm-daily="retry">重新读取逐日记录</button>`;
 }else if(!state.rows){
  content='<p role="status">正在核对双方的逐日负荷…</p>';
 }else{
  const {metric,day,rows}=state,field=metric+'_kWh',selected=rows[day-1];
  const deltas=rows.map(r=>r.left[field]-r.right[field]);
  const choices=commonMonthMetrics.map(k=>`<button data-cm-daily="metric" data-metric="${k}" aria-pressed="${k===metric}">${metricNames[k]}</button>`).join('');
  const signed=n=>(n>0?'+':'')+format(n);
  content=`<div class="cm-daily-head"><div><strong>每日需求差值 <small>kWh</small></strong><p class="cm-note">参考减研究，正值表示需求降低。</p></div>
  <div class="cm-months" role="group" aria-label="逐日需求指标">${choices}</div></div>
  ${monthDailyPlot(deltas,day)}
  <div class="cm-daily-values"><label>日期 <select id="cm-daily-day">${rows.map((r,i)=>`<option value="${i+1}"${day===i+1?' selected':''}>${r.date}</option>`).join('')}</select></label>
  <span>参考 <b>${format(selected.left[field])}</b></span><span>研究 <b>${format(selected.right[field])}</b></span>
  <span>差值 <b>${signed(deltas[day-1])} kWh</b></span>
  <button id="cm-room-toggle" data-cm-daily="rooms" aria-expanded="${!!state.roomOpen}" aria-controls="cm-room-detail">${state.roomOpen?'收起房间明细':'按房间展开'}</button></div>
  <section id="cm-room-detail" aria-label="房间负荷明细"${state.roomOpen?'':' hidden'}>${state.roomOpen?monthRoomTable(state):''}</section>`;
 }
 return `${toggle}<section id="cm-daily-content" aria-label="逐日负荷对比">${content}</section>`;
}

function currentMonthDaily(){
 const d=S.comparisonData;
 if(!d?.common_months || !document.getElementById('cm-daily'))return;
 const {month,site}=commonMonthSelection(d);
 if(site)return {d,month,site,state:monthDailyState(d,month,site)};
}
function refreshMonthDaily(state,focus){
 if(currentMonthDaily()?.state!==state)return;
 const target=document.getElementById('cm-daily');
 const active=document.activeElement;
 if(!focus&&target.contains(active)){
  if(active.id)focus='#'+CSS.escape(active.id);
  else if(active.classList.contains('cm-room-scroll'))focus='.cm-room-scroll';
  else if(active.dataset.metric)focus=`[data-metric="${CSS.escape(active.dataset.metric)}"]`;
 }
 target.innerHTML=monthDailyView(state);
 const scroller=target.querySelector('.cm-room-scroll');
 if(scroller)scroller.scrollTop=state.roomScroll||0;
 if(focus)target.querySelector(focus)?.focus({preventScroll:true});
}

document.addEventListener('click',event=>{
 const control=event.target.closest('#cm-daily [data-cm-daily],#cm-daily [data-cm-day]');
 if(!control)return;
 event.stopImmediatePropagation();
 const {d,month,site,state}=currentMonthDaily();
 const action=control.dataset.cmDaily;
 if(action==='toggle')state.open=!state.open;
 if(action==='metric')state.metric=control.dataset.metric;
 if(control.dataset.cmDay)state.day=Number(control.dataset.cmDay);
 if(action==='rooms')state.roomOpen=!state.roomOpen;
 if(state.roomOpen&&(action==='rooms'||action==='room-retry'))void loadMonthRooms(d,month,site,state);
 if(state.open&&(action==='toggle'||action==='retry')&&!state.loading)void loadMonthDaily(d,month,site,state);
 refreshMonthDaily(state,action==='metric'?`[data-metric="${state.metric}"]`:action==='toggle'?'#cm-daily-toggle':action==='rooms'?'#cm-room-toggle':null);
},true);
document.addEventListener('change',event=>{
 if(event.target.id!=='cm-daily-day'&&event.target.id!=='cm-room-order')return;
 const {state}=currentMonthDaily();
 if(event.target.id==='cm-room-order'){
  state.roomOrder=event.target.value;
  state.roomScroll=0;
 }else state.day=Number(event.target.value);
 refreshMonthDaily(state,'#'+event.target.id);
});
document.addEventListener('scroll',event=>{
 if(event.target.matches?.('#cm-room-detail .cm-room-scroll')){
  const current=currentMonthDaily();
  if(current)current.state.roomScroll=event.target.scrollTop;
 }
},true);
