'use strict';

function probeTransferOptions(m){
 const records=S.boot.records.filter(r=>!r.archived&&r.building_id===m.wallEditor.building);
 const choices=new Map(),key=r=>JSON.stringify([r.id,r.revision]);
 for(const relation of S.boot.comparisons){
   for(const [from,to] of [['left','right'],['right','left']]){
     if(relation[from].id!==m.id||relation[from].revision!==m.revision)continue;
     const ref=relation[to],rec=S.boot.records.find(r=>r.id===ref.id&&!r.archived);
     if(rec&&(ref.id!==m.id||ref.revision!==m.revision)&&(ref.revision!==rec.revision||rec.building_id===m.wallEditor.building))
       choices.set(key(ref),{id:ref.id,revision:ref.revision,name:rec.name,related:true});
   }
 }
 for(const rec of records)if((rec.id!==m.id||rec.revision!==m.revision)&&!choices.has(key(rec)))choices.set(key(rec),rec);
 return [...choices.values()];
}
let probeTransferWindow=null;
function probeTransferWallPreview(row,step){
 const frequency=row.frequency==='Timestep'?'每 '+step+' 分钟':'逐时';
 const quantities=row.fields.map(f=>wallMetrics[f]).join('、');
 const items=[
   ...(quantities?['<li>'+esc(quantities)+' · '+frequency+'</li>']:[]),
   ...row.applied.map(r=>'<li>第 '+r.layer+' 层 · '+esc(r.label)+' 两侧温度 · 每 '+step+' 分钟</li>'),
   ...row.skipped.map(r=>'<li>'+esc(r.label)+' · 跳过（'+esc(r.reason)+'）</li>')
 ];
 return '<section class="transfer-wall-preview"><strong>'+esc(row.wall)+' · '+esc(row.zone)+'</strong><ul>'+items.join('')+'</ul></section>';
}
function openProbeTransfer(m){
 const {config,layers}=probeSettings(),choices=probeTransferOptions(m);
 const walls=configuredWalls().map(wall=>({
   wall,fields:config.points.find(p=>p.wall===wall)?.fields||[],
   layers:layers.filter(p=>p.wall===wall).map(({layer,sha256})=>({layer,sha256}))
 }));
 const request={source:{id:m.id,revision:m.revision},frequency:config.frequency};
 const key=JSON.stringify([m.key,request,walls,choices.map(r=>[r.id,r.revision,r.name,!!r.related])]);
 if(probeTransferWindow?.key===key){
   if(!probeTransferWindow.d.open)probeTransferWindow.d.showModal();
   return;
 }
 probeTransferWindow?.d.remove();
 const d=document.createElement('dialog');
 d.className='probe-transfer';d.setAttribute('aria-labelledby','probe-transfer-name');
 const optionList=related=>choices.flatMap((r,i)=>!!r.related===related?['<option value="'+i+'">'+esc(r.name)+' · '+esc(planVersionLabel(r))+'</option>']:[]).join('');
 const groups=[[true,'此版本的已保存对照'],[false,'同建筑的其他方案']].map(([value,label])=>{
   const items=optionList(value);return items?'<optgroup label="'+label+'">'+items+'</optgroup>':'';
 }).join('');
 const related=choices.filter(r=>r.related);
 const wallOptions=walls.map(({wall,fields,layers},i)=>{
   const installed=probeLayers(wall).layers;
   const labels=[...fields.map(f=>wallMetrics[f]),...layers.map(p=>{
     const row=installed.find(l=>l.index===p.layer&&l.row?.sha256===p.sha256)?.row;
     return (row?.name||'第 '+p.layer+' 层')+' 两侧温度';
   })];
   return '<label><input type="checkbox" data-transfer-wall="'+i+'" checked><span><strong>'+esc(wall)+'</strong> '+esc(labels.join('、'))+'</span></label>';
 }).join('');
 const body='<div class="probe-transfer-body"><label class="field">目标方案<select data-transfer-target><option value="">请选择</option>'+groups+'</select></label>'+
   '<fieldset class="transfer-wall-list"><legend>要一起保存的墙面测点</legend>'+wallOptions+'</fieldset>'+
   '<div data-transfer-status role="status"></div></div>';
 d.innerHTML='<header class="viewer-head"><div><h2 id="probe-transfer-name">将测点用于对照方案</h2><p>'+esc(m.name)+'</p></div><button data-transfer-close>关闭</button></header>'+body;
 document.body.append(d);d.showModal();
 const state=probeTransferWindow={key,d,seq:0},target=d.querySelector('select'),status=d.querySelector('[role=status]');
 const wallList=d.querySelector('fieldset'),boxes=[...wallList.querySelectorAll('input')];
 d.querySelector('[data-transfer-close]').onclick=()=>d.close();
 async function preview(){
   const seq=++state.seq,choice=choices[Number(target.value)];
   const selected=boxes.filter(b=>b.checked).map(b=>walls[Number(b.dataset.transferWall)]);
   if(!selected.length){status.textContent='请勾选要复用测点的墙面。';return;}
   if(target.value===''){status.textContent=choices.length?'选择后核对墙号、房间和材料层。':'当前工作区没有同建筑的其他方案。';return;}
   status.textContent='正在核对两侧的墙、房间和材料版本…';
   const payload={...request,walls:selected,target:{id:choice.id,revision:choice.revision}};
   try{
     const p=await api('/api/probe-transfer',{...payload,action:'preview'});
     if(state.seq!==seq||probeTransferWindow!==state)return;
     const stepSource=S.record.numerics.step_minutes;
     const usable=p.walls.filter(row=>row.fields.length||row.applied.length).length;
     const notes=[...new Set(p.walls.map(row=>row.frequency_note).filter(Boolean))];
     if(p.step!==stepSource&&p.walls.some(row=>row.applied.length||(row.fields.length&&row.frequency==='Timestep')))
       notes.push('两侧求解步长分别为 '+stepSource+' 和 '+p.step+' 分钟。');
     status.innerHTML=p.walls.map(row=>probeTransferWallPreview(row,p.step)).join('')+
       (notes.length?'<p class="probe-hint">'+esc(notes.join(' '))+'</p>':'')+
       (p.changed?'<p>'+usable+' 面墙的可用测点将一起保存。已保存的比较仍指向原版本。</p><button data-transfer-apply class="primary">'+(p.clone?'另存为一份独立对照方案':'保存为一个目标新版本')+'</button>':
       '<p>'+(!usable?'本次没有可带入的测点。':'目标版本已有全部可复用测点。')+'</p>')+
       '<button data-transfer-refresh>重新核对</button>';
     status.querySelector('[data-transfer-refresh]').onclick=preview;
     const apply=status.querySelector('[data-transfer-apply]');
     if(apply)apply.onclick=async()=>{
       apply.disabled=true;target.disabled=true;wallList.disabled=true;status.querySelector('[data-transfer-refresh]').disabled=true;
       let saved=false;
       try{
         const result=await api('/api/probe-transfer',{...payload,action:'apply',signature:p.signature});
         saved=!!result.saved;
         status.textContent=result.saved?'已保存「'+choice.name+(p.clone?' · 测点对照':'')+'」v'+result.saved.revision+'。'+(S.dirty?'当前方案也有未保存修改，可返回编辑页保存。':''):'已核对，无需新增版本。';
         await bootstrap();
         if(result.saved&&!S.dirty){
           const open=document.createElement('button');open.textContent='打开目标版本';status.append(open);
           open.onclick=async()=>{
             if(S.dirty){notice('请先保存当前方案。');return;}
             try{
               d.close();closeInputFlow(false);await loadRecord(result.saved.id,result.saved.revision);S.view='editor';render();openInputFlow(false);
             }catch(e){notice(e.message);}
           };
         }
       }catch(error){status.textContent=error.message;const retry=document.createElement('button');retry.textContent='重新核对';retry.onclick=preview;status.append(retry);}
       finally{target.disabled=saved;wallList.disabled=saved;}
     };
   }catch(error){if(state.seq===seq){status.textContent=error.message;const retry=document.createElement('button');retry.textContent='重试';retry.onclick=preview;status.append(retry);}}
 }
 target.onchange=preview;
 wallList.onchange=preview;
 if(choices.length===1||related.length===1)target.value=String(related.length===1?choices.indexOf(related[0]):0);
 void preview();
}
