'use strict';


const stackDays=new DialogReads(8), stackInventories=new RecentViewReader();
let stackView;
function responseDialog(){
 let dialog=document.getElementById('stack-response');
 if(!dialog){
   dialog=document.createElement('dialog');
   dialog.id='stack-response'; dialog.setAttribute('aria-labelledby','stack-response-title');
   dialog.innerHTML='<header class="viewer-head"><h2 id="stack-response-title">材料响应</h2><button data-stack-close>关闭</button></header><div class="focused-body" data-stack-body></div>';
   document.body.append(dialog);
 }
 return dialog;
}
function stackDates(period){
 const [sm,sd,em,ed]=period,days=[];
 for(let t=Date.UTC(2025,sm-1,sd);t<=Date.UTC(2025,em-1,ed);t+=86400000){
   const label=new Date(t).toISOString().slice(5,10);days.push([label,label]);
 }
 return days;
}
async function openStackResponse(batch,index){
 const dialog=responseDialog(),key=JSON.stringify([batch,index]),box=dialog.querySelector('[data-stack-body]');
 if(stackView?.key!==key){
   stackView={key,batch,index,seq:0};
   box.textContent='正在核对结果来源…';
 }
 const v=stackView;
 if(!dialog.open)dialog.showModal();
 try{
   const url='/api/result-timeline/inventory?'+new URLSearchParams({batch,index});
   const receipt=await stackInventories.read(url,false,async known=>{
     const data=await api(url+(known?'&known='+encodeURIComponent(known):''));
     return {view_token:data.view_token,summary:data.unchanged?undefined:data};
   });
   if(v!==stackView)return;
   if(v.inventory?.view_token===receipt.summary.view_token && box.querySelector('[data-stack-date]'))return;
   v.inventory=receipt.summary;
   const items=v.inventory.stack_selections||[];
   if(!items.length){box.textContent='这个结果没有已保存的分层测点。';return;}
   v.slot=0;v.date=stackDates(v.inventory.period)[0][0];v.pos=0;
   box.innerHTML='<div class="actions"><label>墙与层 <select data-stack-point>'+options(items.map((s,i)=>[i,s.wall+' · 第 '+s.layer+' 层 · '+s.name+' v'+s.revision]))+
     '</select></label><button data-stack-result-wall>从平面图选墙</button><label>日期 <select data-stack-date>'+options(stackDates(v.inventory.period),v.date)+'</select></label></div><div data-stack-plot aria-live="polite"></div>';
   await loadStackDay(v);
 }catch(error){if(v===stackView)box.innerHTML='<p role="alert">'+esc(error.message)+'</p><button data-stack-reopen>重试</button>';}
}
async function loadStackDay(v){
 const seq=++v.seq,box=responseDialog().querySelector('[data-stack-plot]'),s=v.inventory.stack_selections[v.slot];
 v.data=null;box.textContent='正在读取所选日期…';
 const req={batch:v.batch,index:v.index,wall:s.wall,layer:s.layer,date:v.date};
 try{
   const data=await stackDays.read(JSON.stringify([v.inventory.view_token,req]),()=>api('/api/material-response',req));
   if(v!==stackView||seq!==v.seq)return;
   if(data.view_token!==v.inventory.view_token)throw Error('结果来源已变化，请重新打开。');
   v.data=data;v.pos=Math.max(0,data.points.findIndex(p=>p[0]===0));
   plotStackDay(v,box);
 }catch(error){if(v===stackView && seq===v.seq)box.innerHTML='<p role="alert">'+esc(error.message)+'</p><button data-stack-retry>重新读取</button>';}
}
function stackTime(m){
 const stamp=m<0?1440+m:m;
 return (m<0?'前日 ':'')+String(Math.floor(stamp/60)).padStart(2,'0')+':'+String(stamp%60).padStart(2,'0');
}
function plotStackDay(v,box){
 const p=v.data.points,s=v.data.selection,length=p.length,first=p[0][0],last=p[length-1][0];
 const x=m=>110+780*(m-first)/(last-first||1);
 const low=Math.floor(Math.min(...p.map(a=>Math.min(a[1],a[2])))),high=Math.max(low+1,Math.ceil(Math.max(...p.map(a=>Math.max(a[1],a[2])))));
 const y=t=>228-88*(t-low)/(high-low);
 const path=(col,row)=>p.map((a,i)=>{
   const xx=x(a[0]).toFixed(2);
   if(!row)return (i?'L':'M')+xx+' '+y(a[col]).toFixed(2);
   const yy=row(a[col]);return i?'H'+xx+'V'+yy:'M'+xx+' '+yy;
 }).join(' ');
 const line=(d,color)=>'<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="2" vector-effect="non-scaling-stroke"/>';
 const label=(xx,yy,t)=>'<text x="'+xx+'" y="'+yy+'">'+esc(String(t))+'</text>';
 let graphic=label(0,21,'外表面光学')+label(75,18,'A')+label(75,44,'B')+label(0,81,'热阻状态');
 if(p.some(a=>a[3]!==null))graphic+=line(path(3,f=>f==='A'?14:40),'#336a84');
 else graphic+=label(110,32,'沿用原构造外表面');
 if(s.feedback)graphic+=label(75,79,'C')+label(75,104,'R')+line(path(4,r=>r==='C'?75:100),'#916438');
 else graphic+=label(110,90,'固定 · '+s.fixed_state);
 graphic+=label(0,151,'温度 / °C')+label(76,145,high)+label(76,232,low)+line(path(1),'#167263')+line(path(2),'#aa532c');
 [0,6,12,18].forEach(h=>{graphic+=label(x(h*60),252,h+':00');});
 graphic+=label(850,252,'24:00');
 box.innerHTML='<p>'+esc(v.data.city)+' · '+esc(s.wall)+' · '+esc(s.name)+' · 每 '+v.data.step_minutes+' 分钟'+
   (s.feedback?' · 热阻反馈作用于第 '+s.control_layer+' 层 '+esc(s.control_name):'')+'</p>'+
   '<div data-switch-host></div><p class="stack-legend"><span>靠室外侧层界面</span><span>靠室内侧层界面</span></p>'+
   '<svg data-stack-chart viewBox="0 0 910 260" role="img" aria-label="光学组、热阻状态和两侧温度的同步时间曲线">'+graphic+
   '<line data-stack-cursor y1="3" y2="236" stroke="#37474c" stroke-dasharray="3 3"/></svg>'+
   '<label>查看时刻 <input type="range" data-stack-slider min="0" max="'+(length-1)+'" step="1"></label><p data-stack-readout></p>'+responseExportBar(v.data.step_minutes,v.exportStep);
 const data=v.data;
 const ref={batch:v.batch,index:v.index,sha256:data.summary_sha256};
 mountWallSwitches(v,box.querySelector('[data-switch-host]'),s.feedback||s.switched?[{ref,token:data.view_token,label:data.city}]:[],s.wall,s.layer,
   ()=>switchOffset(data.period,v.date,v.data?.points[v.pos]?.[0]??0),async offset=>{
     const date=switchStamp(data.period,offset)[0];
     if(v.date!==date){v.date=date;responseDialog().querySelector('[data-stack-date]').value=date;await loadStackDay(v);}
     if(v!==stackView||v.date!==date||!v.data||v.data.selection.wall!==s.wall||v.data.selection.layer!==s.layer)return;
     const i=v.data.points.findIndex(p=>p[0]===offset%1440);if(i>=0)stackCursor(v,i);
   });
 box.querySelector('[data-response-step]').onchange=e=>{v.exportStep=Number(e.target.value);};
 box.querySelectorAll('[data-response-file]').forEach(btn=>btn.onclick=e=>{
   const step=Number(box.querySelector('[data-response-step]').value);
   void verifiedResponseDownload(e.currentTarget,async()=>(await api('/api/result-timeline/inventory?'+new URLSearchParams({batch:v.batch,index:v.index,known:data.view_token}))).unchanged && v.data===data,
     ()=>exportStackDay(data,step,btn.dataset.responseFile));
 });
 const svg=box.querySelector('svg');
 svg.onpointermove=e=>{
   const pt=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
   stackCursor(v,Math.round((pt.x-110)/780*(length-1)));
 };
 stackCursor(v,v.pos);
}
function exportStackDay(data,step,format){
 const native=data.step_minutes,points=data.points.filter(p=>p[0]>=0),count=step/native,s=data.selection;
 if(!responseIntervals(native).includes(step))throw Error('请选择原步长或其整数倍。');
 const rows=[['地点','墙号','层序','层名','月日','区间开始','区间结束','原步长 / min','导出步长 / min','原始点数','靠室外侧温度 / °C','靠室内侧温度 / °C','光学组','热阻状态','A 面占比 / %','C 态占比 / %','批次','结果 SHA-256']];
 for(let i=0;i<points.length;i+=count){
   const group=points.slice(i,i+count),t=group[0][0];
   const values=col=>group.map(p=>p[col]);
   const states=col=>[...new Set(values(col))].filter(v=>v!=null).join(' / ');
   rows.push([data.city,s.wall,s.layer,s.name,data.date,responseClock(t),responseClock(t+step),native,step,group.length,
     responseMean(values(1),0,count),responseMean(values(2),0,count),states(3)||'原构造外表面',states(4),
     group.every(p=>p[3]==='A'||p[3]==='B')?100*group.filter(p=>p[3]==='A').length/count:null,
     group.every(p=>p[4]==='C'||p[4]==='R')?100*group.filter(p=>p[4]==='C').length/count:null,data.batch,data.summary_sha256]);
 }
 const cols=[10,11,12,13,14,15].map(i=>({index:i,label:rows[0][i],
   chart:i<=11?'层两侧温度':i>=14 && rows.slice(1).some(r=>r[i]!=null)?'控制状态占比':null,unit:i<=11?'°C':'%'}));
 return responseFile(format,[data.city,s.wall,'第'+s.layer+'层',data.date,step+'min'].join('_'),rows,cols,[4,5,6],
   [['地点',data.city],['墙面',s.wall],['材料层',s.layer+' · '+s.name],['计算批次',data.batch],['结果 SHA-256',data.summary_sha256],
    ['原始步长 / min',native],['导出步长 / min',step],['状态占比','该导出区间内 A 面或 C 态占用的时间比例']]);
}
function stackCursor(v,i){
 if(!v?.data)return;
 const p=v.data.points,s=v.data.selection;
 v.pos=Math.min(p.length-1,Math.max(0,i));
 const a=p[v.pos],x=110+780*v.pos/Math.max(1,p.length-1),d=responseDialog();
 const line=d.querySelector('[data-stack-cursor]');
 if(!line)return;
 line.setAttribute('x1',x);line.setAttribute('x2',x);
 d.querySelector('[data-stack-slider]').value=v.pos;
 d.querySelector('[data-stack-readout]').textContent=stackTime(a[0])+' · '+(a[3]?'光学 '+a[3]:'原外表面')+
   ' · '+(s.feedback?'反馈 ':'固定 ')+a[4]+' · 靠室外侧 '+a[1].toFixed(3)+' °C · 靠室内侧 '+a[2].toFixed(3)+' °C';
 v.switchNav?.();
}

document.addEventListener('click',e=>{
 const btn=e.target.closest('[data-stack-open],[data-stack-result-wall],[data-stack-reopen],[data-stack-retry],[data-stack-close]');
 if(!btn)return;
 e.preventDefault();e.stopImmediatePropagation();
 if(btn.disabled)return;
 if(btn.hasAttribute('data-stack-open'))return void openStackResponse(btn.dataset.batch,Number(btn.dataset.index));
 if(btn.hasAttribute('data-stack-result-wall')){
   const v=stackView,items=v.inventory.stack_selections,current=items[v.slot];
   return resultFloorPlan({batch:v.batch,index:v.index,sha256:v.inventory.summary_sha256},v.inventory.view_token,
     items.map(s=>s.wall),current.wall,wall=>{
       if(stackView!==v||wall===current.wall)return;
       const sameLayer=items.findIndex(s=>s.wall===wall && s.layer===current.layer);
       v.slot=sameLayer<0?items.findIndex(s=>s.wall===wall):sameLayer;
       responseDialog().querySelector('[data-stack-point]').value=v.slot;void loadStackDay(v);
     });
 }
 if(btn.hasAttribute('data-stack-reopen'))return void openStackResponse(stackView.batch,stackView.index);
 if(btn.hasAttribute('data-stack-retry'))return void loadStackDay(stackView);
 if(btn.hasAttribute('data-stack-close'))return responseDialog().close();
},true);
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-stack-point],[data-stack-date]'))return;
 const d=responseDialog();stackView.slot=Number(d.querySelector('[data-stack-point]').value);
 if(stackView.switchState)stackView.switchState.selected=null;
 stackView.date=d.querySelector('[data-stack-date]').value;void loadStackDay(stackView);
});
document.addEventListener('input',e=>{if(e.target.matches('[data-stack-slider]'))stackCursor(stackView,Number(e.target.value));});
