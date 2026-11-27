/* The dialog pins its own group revision for the entire preview/save cycle. */
(() => {
 let current=null;
 const button=(action,text,primary=false)=>`<button data-experiment="${action}" class="${primary?'primary':''}">${text}</button>`;
 function draw(v){
  const {dialog,payload:p}=v;
  const close=button('close','关闭');
  let body='',actions='';
  if(v.error){
   body=`<p class="warning" role="alert">${esc(v.error)}</p>`;
   actions=button('retry','重新核对');
  }else if(!p){
   body='<p role="status">正在核对成员版本和已有结果…</p>';
  }else if(p.saved){
   body=`<p>已保存独立实验方案 v1，并建立与固定蓬松、固定 A 的两两对照。</p><p>${esc(p.comparison.name)}</p>`;
   actions=button('compare','打开两两对照')+button('edit','打开实验方案',true);
  }else{
   const policy=p.policy;
   body=`<table><thead><tr><th>研究输入</th><th>参照 · 固定蓬松、固定 A</th><th>新实验 · 固定 A＋热阻调节</th></tr></thead><tbody>
    <tr><th>材料热阻</th><td>全程蓬松</td><td>以压缩态开始，随后统一反馈</td></tr>
    <tr><th>外表面光学</th><td>固定 A</td><td>固定 A</td></tr>
    </tbody></table><p>热阻调节规则取自本组「表面光学切换＋热阻调节」成员 v${p.donor_revision}。全部 ${p.walls} 面外墙每 ${p.update_minutes} min 判断，切换后至少保持 ${policy.minimum_hold_minutes} min；室温阈值 ${policy.cold_C}／${policy.hot_C} °C，热流死区 ${policy.flux_deadband_W_m2} W/m²。</p>
    <p>建筑、实体材料、气象、温控、计算时段与固定参照 v${p.fixed_revision} 一致，求解步长 ${p.step_minutes} min。两个工况全年固定 A，外表面始终采用同一组太阳吸收率与长波发射率。预览只比较热阻调节。</p>
    <h3>已有结果与新增算例</h3><p>参照可用 ${p.sites.filter(s=>s.reference_available).length}／${p.sites.length} 个地点。新实验拟准备 ${p.sites.length} 个算例。</p>
    <table><thead><tr><th>地点</th><th>本组参照结果</th><th>新实验</th></tr></thead><tbody>${p.sites.map(s=>`<tr><td>${esc(s.name)}</td><td>${s.reference_available?'可复用已核验结果':p.reasons.length?'尚未确认，请查看核对说明':'尚缺已核验结果'}</td><td>待计算</td></tr>`).join('')}</tbody></table>
    ${p.reasons.length?`<details><summary>参照候选核对说明</summary><p>${p.reasons.map(esc).join('<br>')}</p></details>`:''}`;
   actions=v.saving?'<span role="status">正在保存实验与对照…</span>':button('save','保存实验与对照',true);
  }
  dialog.innerHTML=`<header class="viewer-head"><div><h2>固定 A 的热阻调节实验</h2><p>${esc(v.group.name)} · 组 v${v.group.revision}</p></div>${v.saving?'':close}</header>
    <div class="rs-dialog-body">${body}</div><footer class="viewer-foot"><span>保存后可单独安排计算。</span><div class="actions">${actions}</div></footer>`;
 }
 async function request(v,action){
  try{
   const p=await api('/api/research-sets/'+v.group.id+'/experiment/'+action,{
    revision:v.group.revision,set_sha256:v.group.sha256,preview_sha256:v.payload?.preview_sha256});
   if(current===v){v.payload=p;v.error='';}
   if(p.saved && action==='save'){
    try{await bootstrap();}catch(e){notice('实验已保存，方案列表可稍后刷新。','warning');}
   }
  }catch(e){if(current===v)v.error=e.message;}
  finally{if(current===v){v.saving=false;draw(v);}}
 }
 async function click(action,opener){
  if(action==='open'){
   rsGuard();
   if(current)return;
   const dialog=document.createElement('dialog');dialog.className='controlled-experiment';dialog.setAttribute('aria-label','固定 A 的热阻调节实验');document.body.append(dialog);
   const v={group:RS.current,dialog,opener};current=v;
   dialog.addEventListener('cancel',e=>{if(v.saving)e.preventDefault();});
   dialog.addEventListener('close',()=>{if(current===v)current=null;dialog.remove();if(opener.isConnected)opener.focus({preventScroll:true});});
   draw(v);dialog.showModal();await request(v,'preview');return;
  }
  const v=current;if(!v||v.saving)return;
  if(action==='close'){v.dialog.close();return;}
  if(action==='retry'){v.error='';v.payload=null;draw(v);await request(v,'preview');return;}
  if(action==='save'){v.saving=true;draw(v);await request(v,'save');return;}
  rsGuard();v.saving=true;draw(v);
  try{
   await bootstrap();
   if(action==='edit'){await loadRecord(v.payload.target_id,1);RS.context=null;S.view='editor';}
   else if(action==='compare'){await openSavedComparison(v.payload.comparison.id);}
   v.dialog.close();render();scrollTo({top:0,behavior:'instant'});
  }catch(e){v.saving=false;v.error=e.message;draw(v);}
 }
 document.addEventListener('click',e=>{
  const b=e.target.closest('button[data-experiment]');if(!b||b.disabled)return;
  e.preventDefault();e.stopImmediatePropagation();void click(b.dataset.experiment,b).catch(e=>notice(e.message,'error'));
 },true);
})();
