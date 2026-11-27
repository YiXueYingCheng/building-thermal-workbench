'use strict';
const switchReads=new DialogReads(12);
const switchChannels={orientation:['光学面','B','A'],thermal:['热阻状态','R','C']};

function switchOffset(period,date,minute){
 const [month,day]=date.split('-').map(Number);
 return (Date.UTC(2025,month-1,day)-Date.UTC(2025,period[0]-1,period[1]))/60000+minute;
}
function switchStamp(period,offset){
 const date=new Date(Date.UTC(2025,period[0]-1,period[1],0,offset));
 return [date.toISOString().slice(5,10),responseClock(offset%1440)];
}
function switchIndex(events,offset){
 let low=0,high=events.length;
 while(low<high){const mid=Math.floor((low+high)/2);if(events[mid][0]<offset)low=mid+1;else high=mid;}
 return low;
}
function switchSummaries(inventory,date){
 return Object.entries(inventory.summaries).map(([channel,summary])=>{
   const label=channel==='thermal'?'C 态':'A 面',key=summary.frequency==='Daily'?date:summary.frequency==='Monthly'?date.slice(0,2):'period';
   const value=summary.values[key];
   if(value==null)return '<p>'+switchChannels[channel][0]+'缺少可定位的逐步记录。</p>';
   const range=summary.frequency==='Daily'?date:summary.frequency==='Monthly'?Number(date.slice(0,2))+' 月（本次运行时段内）':'整个计算时段';
   return '<p>'+esc(range)+' · '+label+'时间占比 '+(100*value).toFixed(2)+'%。此保存频率无法还原切换时刻。</p>';
 }).join('');
}
function switchDetail(data){
 const interval=offset=>{const [d,t]=switchStamp(data.period,offset);return d+' '+t+'–'+responseClock(offset%1440+data.step);};
 const values=Object.entries(data.states).map(([ch,[a,b]])=>{
   const names=switchChannels[ch];return '<tr><th scope="row">'+names[0]+'</th><td>'+names[1+a]+'</td><td>'+names[1+b]+'</td></tr>';
 }).join('')+data.rows.map(r=>'<tr><th scope="row">'+esc(r.label)+(r.values?' <small>/ '+esc(r.unit)+'</small>':'')+'</th>'+
   (r.values?r.values.map(v=>'<td>'+Number(v).toFixed(3)+'</td>').join(''):'<td colspan="2" class="switch-missing">'+esc(r.note)+'</td>')+'</tr>').join('');
 const changes=Object.entries(data.states).filter(([,v])=>v[0]!==v[1]).map(([ch,[a,b]])=>{
   const names=switchChannels[ch];return names[0]+' '+names[1+a]+' → '+names[1+b];
 });
 return '<p><strong>'+switchStamp(data.period,data.offset).join(' ')+' · '+changes.join('、')+'</strong></p><table aria-label="切换前后相邻两个区间的记录"><thead><tr><th scope="col">'+esc(data.wall)+'<small>'+esc(data.zone)+'</small></th><th scope="col">切换前<small>'+interval(data.offset-data.step)+'</small></th><th scope="col">切换后<small>'+interval(data.offset)+'</small></th></tr></thead><tbody>'+values+'</tbody></table>';
}
const probeLabels={inward:'墙内表面导热',air:'所属房间室温',heating:'房间供暖',cooling:'房间制冷'};
let supplementWindow;

function openSwitchSupplement(context,detail){
 const key=JSON.stringify(context);
 if(supplementWindow?.key===key){
   const dialog=supplementWindow.dialog;
   if(!dialog.open)dialog.showModal();
   if(supplementWindow.recheck)supplementWindow.refresh();
   return;
 }
 supplementWindow?.dialog.remove();
 const dialog=document.createElement('dialog');
 dialog.className='probe-supplement';dialog.setAttribute('aria-labelledby','probe-supplement-title');
 const fields=detail.rows.filter(r=>r.field),[m,d,endM,endD]=detail.period;
 const missing=fields.filter(r=>r.requestable&&!r.values);
 dialog.innerHTML='<header class="viewer-head"><div><h2 id="probe-supplement-title">补录切换测点</h2><p>'+esc(detail.wall)+' · '+esc(detail.zone)+' · '+switchStamp(detail.period,detail.offset).join(' ')+'</p></div><button data-close>关闭</button></header>'+
   '<div class="probe-body"><p>沿用原方案、气象和预热设置，从 '+m+' 月 '+d+' 日连续算到 '+endM+' 月 '+endD+' 日。每 '+detail.step+' 分钟保存所选测点。</p>'+
   '<fieldset><legend>需要的逐步读数</legend>'+fields.map(r=>'<label><input type="checkbox" value="'+esc(r.field)+'"'+(r.requestable&&!r.values?' checked':' disabled')+'> '+esc(r.label)+'<small>'+esc(r.values?'原结果已有':r.note)+'</small></label>').join('')+'</fieldset>'+
   '<div data-probe-status role="status"></div><div class="actions"><button data-prepare class="primary">准备补录清单</button><button data-check>重新核对已有结果</button></div></div>';
 document.body.append(dialog);dialog.showModal();
 const state={key,dialog,seq:0},status=dialog.querySelector('[data-probe-status]'),button=dialog.querySelector('[data-prepare]'),check=dialog.querySelector('[data-check]');
 supplementWindow=state;dialog.querySelector('[data-close]').onclick=()=>dialog.close();
 const selected=()=>[...dialog.querySelectorAll('input:checked')].map(el=>el.value);
 async function inspect(prepare=false){
   const seq=++state.seq,fields=selected();
   state.recheck=false;
   button.hidden=false;button.disabled=true;check.disabled=true;
   status.textContent=fields.length?(prepare?'正在核对原输入、气象和测点，准备清单…':'正在核对已有结果的逐步记录…'):'请选择至少一项。';
   if(!fields.length){check.disabled=false;return;}
   try{
     const result=await api('/api/material-response/supplement',{...context,fields,action:prepare?'prepare':'check'});
     if(supplementWindow!==state||seq!==state.seq)return;
     const reused=Object.entries(result.reused).map(([f,r])=>esc(probeLabels[f])+' · '+esc(r.batch.slice(-8)));
     const sources=reused.length?'<details><summary>查看复用来源</summary><p>'+reused.join('<br>')+'</p></details>':'';
     if(result.detail){
       button.hidden=true;status.innerHTML='<p>已有结果覆盖所选测点，每项 '+result.points.toLocaleString()+' 个时间点。</p>'+sources+'<details class="switch-panel" open><summary>原切换时刻的补录读数</summary>'+switchDetail(result.detail)+'</details>';
     }else{
       status.innerHTML='<p>'+esc(result.city)+' · 需补录'+result.missing.map(f=>esc(probeLabels[f])).join('、')+'，每项 '+result.points.toLocaleString()+' 个时间点。</p><p>所选 '+fields.length+' 项中可复用 '+reused.length+' 项，需补算 1 个算例。</p>'+sources;
       if(result.issues.length)status.innerHTML+='<details><summary>候选结果核对说明</summary>'+result.issues.map(x=>'<p>'+esc(x.reason)+'</p>').join('')+'</details>';
       if(result.review){
         button.hidden=true;
         const next=document.createElement('button');next.className='primary';next.textContent=result.review.existing_batch?'查看已提交清单':'查看预算与提交';status.append(next);
         next.onclick=async()=>{
           next.disabled=true;
           try{
             const p=result.review,[execution,budget]=await Promise.all([api('/api/execution'),api('/api/calculation-budget',{review_id:p.id,plan_sha256:p.plan_sha256})]);
             if(!dialog.open||supplementWindow!==state||seq!==state.seq)return;
             if(S.dirty)throw Error('请先保存正在编辑的方案，再进入计算队列。');
             state.recheck=true;
             const open=[...document.querySelectorAll('dialog[open]')];
             for(const el of open.reverse())el.close();
             S.execution=execution;if(!S.resourcesDirty)S.resourceDraft=copy(execution.resources);
             S.executionReview=p;S.calculationBudget=budget;S.budgetError='';S.executionResults=null;resetBatchResults();S.view='execution';render();
             requestAnimationFrame(()=>document.getElementById('execution-review')?.scrollIntoView({block:'start'}));
           }catch(e){if(seq===state.seq)notice(e.message);}finally{next.disabled=false;}
         };
       }else button.disabled=false;
     }
   }catch(e){if(seq===state.seq){status.textContent=e.message;button.disabled=true;}}
   finally{if(seq===state.seq)check.disabled=false;}
 }
 button.onclick=()=>inspect(true);check.onclick=()=>inspect();
 state.refresh=()=>inspect();
 dialog.querySelector('fieldset').onchange=()=>inspect();
 if(missing.length)void inspect();
}
function mountWallSwitches(v,host,targets,wall,layer,position,jump,hourly=false){
 if(!targets.length){v.switchNav=null;v.switchState=null;return;}
 const key=JSON.stringify([targets,wall,layer]);
 if(v.switchState?.key!==key){
   v.switchState={key,side:0,open:v.initialSwitch!=null||v.switchState?.open||false,selected:v.initialSwitch??null};
   v.initialSwitch=null;
 }
 const state=v.switchState,el=document.createElement('details');
 el.className='switch-panel';el.open=state.open;
 el.innerHTML='<summary>定位材料切换</summary><div data-switch-body></div>';
 host.append(el);
 const body=el.lastElementChild;
 function current(){return el.isConnected&&v.switchState===state;}
 function request(extra){
   const target=targets[state.side],req={result:target.ref,source_token:target.token,wall,layer,...extra};
   return switchReads.read(JSON.stringify(req),async()=>{
     const d=await api('/api/material-response/switches',req);
     if(d.source_token!==target.token||d.wall!==wall)throw Error('结果来源已更新，请重新打开。');
     return d;
   });
 }
 let inventory,summaryDate;
 function anchor(){const minute=position();return minute??state.selected??0;}
 function nav(){
   if(!current()||!el.open||!inventory)return;
   const at=anchor();
   if(Object.keys(inventory.summaries).length){
     const date=switchStamp(inventory.period,Math.max(0,at))[0];
     if(date!==summaryDate){body.querySelector('[data-switch-summaries]').innerHTML=switchSummaries(inventory,date);summaryDate=date;}
   }
   if(!inventory.events.length)return;
   const events=inventory.events,i=switchIndex(events,at),here=events[i]?.[0]===at;
   body.querySelector('[data-switch-detail]').hidden=state.selected!==at;
   body.querySelector('[data-switch-prev]').disabled=i===0;
   body.querySelector('[data-switch-next]').disabled=(here?i+1:i)>=events.length;
   body.querySelector('[data-switch-here]').hidden=!here||state.selected===at;
 }
 v.switchNav=nav;
 async function detail(){
   const target=state.side,offset=state.selected,slot=body.querySelector('[data-switch-detail]');
   if(!slot||offset===null)return;
   slot.textContent='正在读取切换前后的记录…';
   try{
     const d=await request({offset});
     if(current()&&slot.isConnected&&state.selected===offset&&state.side===target){
       slot.innerHTML=switchDetail(d);
       if(d.rows.some(r=>r.requestable&&!r.values)){
         const button=document.createElement('button');button.textContent='补录这些测点';button.dataset.switchSupplement='';
         button.onclick=()=>openSwitchSupplement({result:targets[target].ref,source_token:targets[target].token,wall,layer,offset},d);
         slot.append(button);
       }
     }
   }catch(e){if(current()&&slot.isConnected&&state.selected===offset&&state.side===target){slot.innerHTML='<p role="alert">'+esc(e.message)+'</p><button>重新读取</button>';slot.querySelector('button').onclick=detail;}}
 }
 async function choose(offset){
   if(offset==null)return;
   state.selected=offset;
   try{await jump(offset);}catch(e){if(current())body.textContent=e.message;return;}
   if(current()){nav();void detail();}
 }
 async function show(){
   const side=state.side;
   body.textContent='正在核对所选墙的控制记录…';
   try{
     const d=await request({});
     if(!current()||state.side!==side)return;
     inventory=d;
     summaryDate=null;
     body.innerHTML=(targets.length>1?'<label>查看方案 <select data-switch-side>'+options(targets.map((t,i)=>[i,t.label]),side)+'</select></label>':v.refs?.length===2?'<p>'+esc(targets[0].label)+'</p>':'')+
       (d.events.length?'<div class="switch-nav"><button data-switch-prev>上一次切换</button><button data-switch-next>下一次切换</button><button data-switch-here>查看此刻切换</button><span>计算时段内共 '+d.events.length+' 个切换时刻</span></div>':
       d.exact.length?'<p>已记录的逐步状态在本时段内没有变化。</p>':'')+
       (d.events.length&&hourly?'<p class="muted">逐时曲线的游标指向切换所在的小时，前后读数按表中标明的区间显示。</p>':'')+
       '<div data-switch-summaries></div><div data-switch-detail></div>';
     const sel=body.querySelector('[data-switch-side]');
     if(sel)sel.onchange=()=>{state.side=Number(sel.value);state.selected=null;inventory=null;void show();};
     if(d.events.length){
       for(const direction of ['prev','next','here']){
         body.querySelector('[data-switch-'+direction+']').onclick=()=>{
           const at=anchor(),i=switchIndex(d.events,at),j=direction==='prev'?i-1:direction==='next'&&d.events[i]?.[0]===at?i+1:i;
           void choose(d.events[j]?.[0]);
         };
       }
       void detail();
     }
     nav();
   }catch(e){if(current()&&state.side===side){body.innerHTML='<p role="alert">'+esc(e.message)+'</p><button>重试</button>';body.querySelector('button').onclick=show;}}
 }
 el.ontoggle=()=>{if(current()){state.open=el.open;if(el.open&&!inventory)void show();else nav();}};
 if(el.open)void show();
}
