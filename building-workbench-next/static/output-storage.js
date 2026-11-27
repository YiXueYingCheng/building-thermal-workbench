/* A focused dialog: view, register, check, then explicitly choose future storage. */
const OS={data:null,pending:false,error:'',message:'',path:'',label:'',opener:null};
function outputStorageSummary(){
 const d=S.outputStorage,item=d?.items.find(x=>x.id===d.default);
 return `<div class="output-summary" id="output-storage-summary"><div class="row"><div><strong>后续计算结果保存位置</strong><p>${esc(item?.label||'尚未读取')}${item?` · ${item.online?'可用 '+format(item.free_gib,1)+' GiB':'暂不可用'}`:''}</p></div><button data-output-storage="open">管理保存位置</button></div>${item?'<span class="output-path">'+esc(item.path)+'</span>':''}<p class="muted">已提交批次保留各自位置；输入与任务记录仍在工作区。</p></div>`;
}
function outputStorageBudget(s){
 const d=s?.destination,c=s?.capacity;if(!d)return '';
 return `<p><strong>本次结果位置：${esc(d.label)}</strong><span class="output-path">${esc(d.path)}</span></p>${c&&!c.same_volume?`<p class="muted">工作区另有 ${budgetBytes(c.workspace_free_bytes)} 可用；两块磁盘分别保留 ${budgetBytes(c.reserve_bytes)}。输入和任务记录仍占用工作区。</p>`:''}<p class="muted">提交后固定此位置，后续修改默认位置不改变本批次。需要更换时，请先到计算队列的“管理保存位置”，再刷新本次预算。</p>`;
}
function outputDialog(){
 let d=document.getElementById('output-storage-dialog');if(d)return d;
 d=document.createElement('dialog');d.id='output-storage-dialog';d.setAttribute('aria-labelledby','output-storage-title');document.body.append(d);
 d.addEventListener('cancel',e=>{if(OS.pending)e.preventDefault();});
 d.addEventListener('close',()=>{const opener=OS.opener?.isConnected?OS.opener:document.querySelector('[data-output-storage="open"]');opener?.focus();});return d;
}
function outputDraw(){
 const d=outputDialog(),v=OS.data;
 const scrollTop=d.open?d.querySelector('.output-body')?.scrollTop:0;
 d.innerHTML=`<header class="viewer-head"><div><h2 id="output-storage-title">计算结果保存位置</h2><p>选择后用于新提交的批次，已有结果保留原位。</p></div><button data-output-storage="close"${OS.pending?' disabled':''}>关闭</button></header><div class="output-body"><div class="output-feedback" role="status" aria-live="polite">${esc(OS.message||'可先检查连接，再选择用于后续计算。')}</div>${OS.error?'<p class="warning" role="alert">'+esc(OS.error)+'</p>':''}${v?v.items.map(x=>`<article class="output-location ${v.default===x.id?'current':''}"><div class="row"><h3>${esc(x.label)}</h3>${v.default===x.id?'<span class="tag">当前默认</span>':`<button class="primary" data-output-storage="select" data-storage-id="${esc(x.id)}"${OS.pending||!x.online?' disabled':''}>用于后续计算</button>`}</div><p>${x.online?`${esc(x.current_volume.filesystem)} · 可用 ${format(x.free_gib,2)} GiB`:'<span class="warning">'+esc(x.error)+'</span>'}</p><p class="output-path">${esc(x.path)}</p><button data-output-storage="check" data-storage-id="${esc(x.id)}"${OS.pending?' disabled':''}>检查连接与写入</button></article>`).join(''):'<p>正在读取保存位置…</p>'}<details id="output-add"${OS.path||OS.label?' open':''}><summary>添加其他保存位置</summary><p class="muted">请选择独立空文件夹，或填写新文件夹路径。旧平台结果目录和历史归档继续保留。</p><label class="field">位置名称<input id="output-label" maxlength="60" value="${esc(OS.label)}" placeholder="例如：D 盘新版计算结果"${OS.pending?' disabled':''}></label><label class="field">完整文件夹路径<input id="output-path" value="${esc(OS.path)}" placeholder="D:\\EnergyPlus_Workbench_Next\\runs"${OS.pending?' disabled':''}></label><div class="actions"><button data-output-storage="browse"${OS.pending?' disabled':''}>浏览文件夹</button><button data-output-storage="register"${OS.pending?' disabled':''}>登记并检查</button></div><p class="muted">登记后再点击“用于后续计算”，才会更改默认位置。</p></details><p class="muted">结果盘断连时停止新增派发，不自动改存工作区。外置结果不包含在当前本地备份包内。</p><button data-output-storage="refresh"${OS.pending?' disabled':''}>刷新位置状态</button></div>`;
 if(!d.open)d.showModal();
 if(scrollTop)d.querySelector('.output-body').scrollTop=scrollTop;
}
async function outputRead(){OS.data=await api('/api/output-storage');S.outputStorage=OS.data;const el=document.getElementById('output-storage-summary');if(el)el.outerHTML=outputStorageSummary();}
async function outputAction(b){
 if(OS.pending)return;const op=b.dataset.outputStorage;if(op==='close'){outputDialog().close();return;}
 if(op==='open'){OS.opener=b;OS.error='';OS.message='正在读取保存位置…';OS.pending=true;outputDraw();}
 else{OS.label=document.getElementById('output-label')?.value??OS.label;OS.path=document.getElementById('output-path')?.value??OS.path;OS.error='';OS.pending=true;OS.message={browse:'请在文件夹窗口中选择或取消…',register:'正在登记并检查写入…',select:'正在检查并保存后续计算位置…',check:'正在检查连接与写入…',refresh:'正在刷新位置状态…'}[op]||'正在处理…';outputDraw();}
 try{
  if(op==='browse'){const r=await api('/api/output-storage/browse',{path:OS.path});if(r.path)OS.path=r.path;OS.message=r.cancelled?'已取消选择，保存位置未变。':'已选入路径，尚未登记。';}
  else if(op==='register'){await api('/api/output-storage/register',{path:OS.path,label:OS.label});await outputRead();OS.path='';OS.label='';OS.message='登记完成，默认位置未变。可在上方选择用于后续计算。';}
  else if(op==='select'){await api('/api/output-storage/select',{id:b.dataset.storageId});await outputRead();if(S.executionReview){await refreshCalculationBudget();const budget=document.getElementById('calculation-budget');if(budget)budget.outerHTML=calculationBudgetView();}OS.message='后续批次将使用所选位置。已提交批次及已有结果保持原位。';}
  else if(op==='check'){await api('/api/output-storage/check',{id:b.dataset.storageId});await outputRead();OS.message='连接与写入检查通过；临时检查文件已移除。';}
  else{await outputRead();OS.message='保存位置已读取。';}
 }catch(e){OS.error=e.message;OS.message='本次操作未完成，请核对提示后重试。';}
 finally{
  OS.pending=false;outputDraw();
  if(OS.error||op!=='open'){
   const inline=outputDialog().querySelector(OS.error?'[role="alert"]':'.output-feedback');
   noticeIfOutOfView(inline,OS.error||OS.message,OS.error?'error':'status');
  }
 }
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-output-storage]');if(!b||b.disabled)return;e.stopImmediatePropagation();void outputAction(b);},true);
