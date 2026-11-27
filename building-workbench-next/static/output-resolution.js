'use strict';
const outputResolutionOptions=[['monthly_period_v1','逐月（默认）'],['timeseries_daily_v1','逐天'],['timeseries_hourly_v1','逐时'],['timeseries_timestep_v1','逐步（不超过 31 天）']];
function outputResolutionMarkup(m){
 const period=S.record.factors.scope.period,step=S.record.numerics.step_minutes;
 const day=(mo,d)=>Date.UTC(2025,mo-1,d),days=(day(period[2],period[3])-day(period[0],period[1]))/86400000+1;
 const contract=m.outputContract||m.prepared?.output_contract||'monthly_period_v1';
 const points=contract==='timeseries_daily_v1'?days:contract==='timeseries_hourly_v1'?days*24:contract==='timeseries_timestep_v1'?days*1440/step:period[2]-period[0]+1;
 const opts=outputResolutionOptions.map(([k,label])=>`<option value="${k}"${contract===k?' selected':''}${k==='timeseries_timestep_v1'&&days>31?' disabled':''}>${label}</option>`).join('');
 return `<section class="well"><h3>结果保存的时间尺度</h3><label class="field">保存频率<select id="output-resolution"${m.pending||m.recovering?' disabled':''}>${opts}</select></label><p>每个变量、每个对象约 ${points.toLocaleString()} 个${contract==='monthly_period_v1'?'月度':'明细'}时间点；还会保留月度与整个计算时段汇总。求解步长仍为 ${step} 分钟。</p><p class="muted">文件量随变量、房间／系统／表面数量和算例数增加。全年每项：逐天 365 点，逐时 8,760 点，5 分钟逐步 105,120 点；点数不是文件大小估计。逐步输出用于不超过 31 天的诊断算例。改变频率会建立对应的新计算清单，已有结果和清单保留。</p></section>`;
}
function outputResolutionSummary(p){
 const d=p?.output_detail;if(!d)return '';
 const b=p.observation_followup;
 if(b){
   const period=p.cases[0].period,when=switchStamp(period,b.offset).join(' ');
   const points=(1+(Date.UTC(2025,period[2]-1,period[3])-Date.UTC(2025,period[0]-1,period[1]))/86400000)*1440/b.step;
   return '<div class="well"><strong>测点补录 · '+esc(b.wall)+' · '+esc(b.zone)+'</strong><p>'+b.fields.map(f=>esc(probeLabels[f])).join('、')+'，每 '+b.step+' 分钟保存一次，每项 '+points.toLocaleString()+' 个时间点。</p><p class="muted">原输出频率为'+esc(d.label)+'。打开新批次的墙面测点，可回到 '+when+' 的切换。原批次 '+esc(b.source.batch.slice(-8))+'。</p></div>';
 }
 return `<div class="well"><strong>保存频率：${esc(d.label)}</strong><p>每个输出项 ${d.points_per_series.toLocaleString()} 个时间点；${esc(d.note)}</p><p class="muted">不同输出频率使用各自的历史空间预算；没有同类样本时不沿用月度结果估算。</p></div>`;
}
document.addEventListener('change',e=>{if(e.target.id!=='output-resolution')return;const m=inputFlowWindow?.model;if(!m||m.pending||m.recovering)return;m.outputContract=e.target.value;m.prepared=null;if(m.job?.kind==='prepare')m.job=null;m.message='输出频率已选择。重新准备清单后再提交；旧清单和结果仍保留。';renderInputFlow();});

function outputResolutionLabel(contract){return outputResolutionOptions.find(r=>r[0]===contract)?.[1]||(contract==='daily_sensible_reference_v1'?'逐日参考':'月度');}
