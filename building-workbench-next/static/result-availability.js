/* On-demand checks; never turn historical acceptance into a promise of available files. */
const raStates={passed:'通过',reused:'复用完成',review:'待复核',pending:'等待',running:'运行中',failed:'失败',cancelled:'取消',interrupted:'中断'};
const raReads = new RecentViewReader(24);
const raPositions = new Map();
const raLastCase = new Map();
let raCurrent = null;

function raRemember(map,key,value){
 map.delete(key);
 map.set(key,value);
 if(map.size>48)map.delete(map.keys().next().value);
}

function raDialog(){
 let d=document.getElementById('result-availability');
 if(d)return d;
 d=document.createElement('dialog');
 d.id='result-availability';
 d.className='library-adoption';
 d.setAttribute('aria-labelledby','ra-title');
 d.innerHTML='<header class="viewer-head"><h2 id="ra-title">检查结果文件</h2><button data-ra-close>关闭</button></header><div class="mc-preview-body"></div><footer class="actions"><span class="muted" role="status"></span><button data-ra-refresh>重新检查</button><button data-ra-close>关闭并返回</button></footer>';
 document.body.append(d);
 d.addEventListener('cancel',e=>{e.preventDefault();raClose();});
 return d;
}

function raSavePosition(){
 if(!raCurrent?.displayed)return;
 const body=raDialog().querySelector('.mc-preview-body');
 raRemember(raPositions,raCurrent.key,{
  scroll:body.scrollTop,
  open:new Set([...body.querySelectorAll('details[open]')].map(n=>n.dataset.raSection)),
  tables:[...body.querySelectorAll('.viewer-table')].map(n=>[n.scrollLeft,n.scrollTop])
 });
}

function raClose(){
 raSavePosition();
 raCurrent=null;
 raDialog().close();
}

function raContent(view,html,restore=false){
 const body=raDialog().querySelector('.mc-preview-body');
 body.innerHTML=html;
 const pos=restore&&raPositions.get(view.key);
 if(pos){
  for(const section of body.querySelectorAll('details'))section.open=pos.open.has(section.dataset.raSection);
  body.querySelectorAll('.viewer-table').forEach((el,i)=>el.scrollTo(...(pos.tables[i]||[0,0])));
 }
 body.scrollTop=pos?.scroll||0;
}

function raStatus(message,pending){
 const footer=raDialog().querySelector('footer');
 footer.querySelector('[role="status"]').textContent=message;
 footer.querySelector('[data-ra-refresh]').disabled=pending;
}
function raFile(f){const labels={verified:'核对一致',missing:'文件缺失',changed:'校验不一致',unknown:'未知／待核对',removed:'已受控清理'};return `<tr><td>${esc(f.name)}<details data-ra-section="file-${esc(f.path)}"><summary>保存位置</summary><p class="output-path">${esc(f.path)}</p></details></td><td>${esc(labels[f.status]||f.status)}<p>${esc(f.reason||'')}</p></td><td>${smBytes(f.bytes)}</td></tr>`;}
function raReport(r){const s=r.summary,loads=s?.loads;return `${raBack(r.batch)}<h3>算例 ${r.index+1} · ${esc(r.state_label)}</h3><p>任务历史登记：${esc(raStates[r.registered_status]||r.registered_status)}；本次核对：${esc(readableTime(r.checked_at))}。</p><p>${esc(r.note)}</p>${r.issues.length?'<p class="warning" role="alert">'+r.issues.map(esc).join('；')+'</p>':''}<div class="viewer-table"><table class="table"><thead><tr><th>能力</th><th>本次资料条件</th></tr></thead><tbody>${r.capabilities.map(c=>`<tr><td>${esc(c.name)}</td><td><strong>${c.ready===true?'资料条件满足':c.ready===false?'条件未满足':'按具体任务核对'}</strong><p>${esc(c.detail)}</p></td></tr>`).join('')}</tbody></table></div>${s?`<details data-ra-section="summary"><summary>查看已保存汇总（不改写结果结论）</summary><p>${esc(s.city||s.site_id)} · ${esc(periodLabel(s.period||[]))} · ${esc(s.step_minutes)} min</p>${s.status==='review'?'<p class="warning">此结果仍待复核；可读数值不表示已接受。</p>':''}${loads&&typeof loads==='object'?'<p>'+Object.entries(loads).filter(([,v])=>typeof v==='number'&&Number.isFinite(v)).map(([k,v])=>esc(({heating_kWh:'供热显热需求 / kWh',cooling_kWh:'供冷显热需求 / kWh',total_kWh:'总显热需求 / kWh'})[k]||k)+'：'+format(v,3)).join('；')+'</p>':'<p>此模式没有供冷／供热汇总。</p>'}</details>`:''}<details data-ra-section="files"><summary>逐文件核对（${r.files.length} 项原始资料）</summary><div class="viewer-table"><table class="table"><thead><tr><th>文件</th><th>核对结果</th><th>文件体积</th></tr></thead><tbody>${[...(r.summary_file?[r.summary_file]:[]),...r.files].map(raFile).join('')}</tbody></table></div></details><details data-ra-section="retention"><summary>如果只保留汇总、清理计算明细，会怎样？</summary><p class="warning">${esc(r.retention.note)}</p><h4>保留</h4><ul>${r.retention.kept.map(t=>'<li>'+esc(t)+'</li>').join('')}</ul><h4>会失去或影响</h4><ul>${r.retention.lost.map(t=>'<li>'+esc(t)+'</li>').join('')}</ul><p>原登记中涉及的明细文件：${r.retention.files.map(f=>esc(f.name)).join('、')||'暂无可确认条目'}。是否允许清理还需核对比较、日历、复用等关联。</p></details>`;}
function raBack(batch){
 return `<button data-ra-batch="${esc(batch)}" data-ra-list>← 返回本批算例</button>`;
}

function raListing(r){
 const rows=r.cases.map(c=>`<tr><td>${c.index+1}</td><td>${esc(raStates[c.status]||c.status)}</td><td><button data-ra-batch="${esc(r.batch)}" data-ra-index="${c.index}">检查此算例文件</button>${c.has_summary?'':'<small>尚未登记完成汇总</small>'}</td></tr>`);
 return `<p>${esc(r.note)}</p><div class="viewer-table"><table class="table"><thead><tr><th>算例</th><th>历史登记</th><th>现在的资料</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

function raShow(view,report){
 raContent(view,view.index==null?raListing(report):raReport(report),true);
 view.displayed=true;
}

async function raOpen(batch,index,force=false){
 raSavePosition();
 const key=JSON.stringify([batch,index??null]);
 const view=raCurrent={batch,index,key,displayed:false};
 raRemember(raLastCase,batch,index??null);
 const dialog=raDialog();
 if(!dialog.open)dialog.showModal();
 const previous=raReads.entries.get(key);
 if(previous)raShow(view,previous.summary);
 else raContent(view,'<p role="status">正在检查，可以先关闭窗口。</p>');
 raStatus(previous?'上次检查于 '+readableTime(previous.summary.checked_at)+(force?' · 正在重新检查':' · 正在核对来源是否有变化'):'正在读取…',true);
 try{
  const read=await raReads.read(key,force,known=>{
   const q=new URLSearchParams({batch,view:force?'refresh':'recent'});
   if(index!=null)q.set('index',index);
   if(known)q.set('known',known);
   return api('/api/result-availability?'+q);
  });
  if(raCurrent!==view)return;
  if(!view.displayed||!read.reused||read.view_token!==previous?.view_token){
   raSavePosition();
   raShow(view,read.summary);
  }
  raStatus((index==null?'列表读取于 ':'文件检查于 ')+readableTime(read.summary.checked_at)+(read.reused?' · 已核对来源无变化':''),false);
 }catch(error){
  if(raCurrent!==view)return;
  raSavePosition();
  view.displayed=false;
  raContent(view,(index==null?'':raBack(batch))+'<p class="warning" role="alert">'+esc(error.message)+'</p>');
  raStatus('读取失败，可重新检查。',false);
 }
}

document.addEventListener('click',e=>{
 const b=e.target.closest('[data-ra-batch],[data-ra-close],[data-ra-refresh]');
 if(!b)return;
 e.preventDefault();
 e.stopImmediatePropagation();
 if(b.hasAttribute('data-ra-close'))return raClose();
 if(b.hasAttribute('data-ra-refresh')){
  if(raCurrent&&!b.disabled)raOpen(raCurrent.batch,raCurrent.index,true);
  return;
 }
 const batch=b.dataset.raBatch;
 const index=b.hasAttribute('data-ra-index')?Number(b.dataset.raIndex):b.hasAttribute('data-ra-list')?null:raLastCase.get(batch);
 raOpen(batch,index);
},true);
const raPreviousDependencies=smDependencies;
smDependencies=function(info){return raPreviousDependencies(info)+(info.owners||[]).map(o=>`<button data-ra-batch="${esc(o.batch)}" data-ra-index="${o.index}">核对算例 ${o.index+1} 的资料与能力</button>`).join('');};
