/* Independent sampled disk evidence, separate from solver results and dispatch. */
S.diskObservations=null;S.diskObservationError='';
function diskObservationView(){
 const d=S.diskObservations;
 if(!d)return `<div class="well"><h3>运行目录磁盘采样</h3><p class="warning">${esc(S.diskObservationError||'采样状态尚未读取')}</p></div>`;
 const o=d.observer;
 return `<div class="well" id="disk-observations"><h3>运行目录磁盘采样</h3><p>${o.running?'观测已就绪，每 5 秒采样正在运行的算例。':o.enabled?'观测当前未运行，请核对提示。':'当前服务没有开启自动观测。'}${o.error?' '+esc(o.error):''}</p>
 <p class="muted">核对于 ${esc(d.created)}。采样最大值可能漏过两次采样之间的短暂峰值，不作为磁盘容量保证。</p>
 ${!d.observations.length?'<p>尚无采样记录。下一次实际计算时自动记录；已有历史结果不补造峰值。</p>':`<div class="table-wrap"><table class="table"><thead><tr><th>地点 / 模式</th><th>采样最大占用</th><th>有效样本</th><th>覆盖情况</th><th>执行状态</th></tr></thead><tbody>${d.observations.map(r=>`<tr><td>${esc(r.city)}<small>${esc(modes[r.mode]||r.mode)} · ${r.step_minutes} min</small></td><td>${budgetBytes(r.peak_bytes)}</td><td>${r.sample_count}<small>运行中 ${r.active_sample_count}</small></td><td>${esc(r.coverage)}</td><td>${esc(jobLabels[r.status]||r.status)}${r.finalized?' · 已结束':' · 观测中'}</td></tr>`).join('')}</tbody></table></div>`}
 ${d.issues.length?`<p class="warning">${d.issues.length} 份记录未通过读取核对。</p>`:''}
 <details><summary>采样范围与限制</summary>${d.notes.map(x=>`<p class="muted">${esc(x)}</p>`).join('')}<a href="/api/disk-observations" target="_blank" rel="noopener">完整采样记录 JSON ↗</a></details></div>`;
}
const performanceHistoryBeforeDisk=performanceHistoryView;
performanceHistoryView=function(){const html=performanceHistoryBeforeDisk();if(!html)return '';const index=html.lastIndexOf('</section>');return html.slice(0,index)+diskObservationView()+html.slice(index);};
const executionViewBeforeDisk=executionView;
executionView=function(){return executionViewBeforeDisk().replace('查看已有运行实测','查看运行实测与磁盘采样');};
const executionActionBeforeDisk=executionAction;
executionAction=async function(button){
 const done=await executionActionBeforeDisk(button);
 if(done&&button.dataset.action==='open-performance'){
  S.diskObservations=null;S.diskObservationError='';
  try{S.diskObservations=await api('/api/disk-observations');}catch(e){S.diskObservationError=e.message;}
 }
 if(done&&button.dataset.action==='close-performance'){S.diskObservations=null;S.diskObservationError='';}
 return done;
};
