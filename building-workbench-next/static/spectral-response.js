'use strict';
const spectralInventories=new RecentViewReader(), spectralReads=new DialogReads(8);
const spectralRoomReads=new DialogReads(6);
const spectralEndpoint='/api/material-response/spectral';
let spectralView;

function spectralRefs(evidence){
 return evidence.map(e=>({batch:e.batch_id,index:e.index,sha256:e.result_sha256}));
}
function spectralOpenButton(evidence,general=false,role=''){
 return '<button '+(general?'data-wall-observe':'data-spectral-open')+'="'+esc(JSON.stringify(spectralRefs(evidence)))+'" data-response-role="'+esc(role)+'">'+(general?'墙面测点':'逐墙材料响应')+(role?'（仅'+esc(role)+'）':'')+'</button>';
}
function spectralDialog(){
 let dialog=document.getElementById('spectral-response');
 if(dialog)return dialog;
 dialog=document.createElement('dialog');dialog.id='spectral-response';dialog.setAttribute('aria-labelledby','spectral-title');
 dialog.innerHTML='<header class="viewer-head"><div><h2 id="spectral-title">材料响应</h2><p data-spectral-context></p></div><button data-spectral-close>关闭</button></header><div class="spectral-body"></div>';
 document.body.append(dialog);
 return dialog;
}
function spectralError(box,error,op){
 box.innerHTML='<p role="alert">'+esc(error.message)+'</p><button data-spectral-retry="'+op+'">重新读取</button>';
}
async function openSpectral(refs,general=false,role=''){
 const dialog=spectralDialog(),body=dialog.querySelector('.spectral-body'),key=JSON.stringify([refs,general,role]);
 if(spectralView?.key!==key){
   spectralView={key,refs,general,role,sequence:0,index:0,fields:Object.keys(wallMetrics)};
   dialog.querySelector('h2').textContent=general?'墙面测点':'材料响应';
   dialog.querySelector('[data-spectral-context]').textContent='';body.textContent='正在核对材料结果…';
 }
 const v=spectralView;
 if(!dialog.open)dialog.showModal();
 try{
   const receipt=await spectralInventories.read(key,false,async known=>{
     const data=await api(spectralEndpoint,{results:refs,known,general});
     return {view_token:data.view_token,summary:data.unchanged?undefined:data};
   });
   if(v!==spectralView || v.token===receipt.view_token && body.querySelector('[data-spectral-wall]'))return;
   const meta=receipt.summary,dates=stackDates(meta.period);
   v.meta=meta;v.token=meta.view_token;v.wall=meta.selected_walls?.[0]||meta.walls[0];v.date=dates.length>1 && dates.length<=7?'all':dates[0][0];v.index=0;
   v.frequency=meta.frequencies?.[0]||'Zone Timestep';
   if(meta.bookmark&&meta.walls.includes(meta.bookmark.wall)){
     v.wall=meta.bookmark.wall;v.date=switchStamp(meta.period,meta.bookmark.offset)[0];
     v.index=Math.floor((meta.bookmark.offset%1440)/(v.frequency==='Hourly'?60:meta.step_minutes));
     v.initialSwitch=meta.bookmark.offset;
   }
   const ranges=dates.length>1 && dates.length<=7?[['all','整个时段（'+dates.length+' 天）'],...dates]:dates;
   dialog.querySelector('[data-spectral-context]').textContent=(role?'仅'+role+'有此类逐墙材料响应 · ':'')+meta.sides.map(s=>s.name+(s.status==='review'?'（待复核）':'')).join('　／　');
   body.innerHTML=(general&&!meta.frequencies.length?'<p>这份结果没有保存墙面或房间的逐时、逐步测点数据。选择墙面可查看各项实际登记的频率。</p>':'')+'<div class="spectral-controls"><label>墙面 <select data-spectral-wall>'+options(meta.walls.map(w=>[w,w]),v.wall)+'</select></label><strong data-spectral-location></strong><button data-spectral-floor>从平面图选墙</button>'+
     '<label>时段 <select data-spectral-date>'+options(ranges,v.date)+'</select></label><span>'+esc(meta.city)+'</span>'+
     (general?(meta.frequencies.length?'<label>已存频率 <select data-observed-frequency>'+options(meta.frequencies.map(f=>[f,f==='Hourly'?'逐时':'每 '+meta.step_minutes+' 分钟']),v.frequency)+'</select></label>':''):'<span>每 '+meta.step_minutes+' 分钟</span>')+'</div><div data-spectral-detail></div>';
   if(meta.bookmark_issue){
     const warning=document.createElement('p');warning.className='warning';warning.textContent=meta.bookmark_issue;body.prepend(warning);
   }
   await loadSpectral(v);
 }catch(error){if(v===spectralView){v.sequence++;spectralError(body,error,'open');}}
}
async function spectralRange(cache,req){
   const key=JSON.stringify(req),full=cache.entries.get(JSON.stringify({...req,date:'all'}));
   if(cache.entries.get(key)?.ready || (req.date!=='all' && full?.ready)){
     if(!(await api(spectralEndpoint,{results:req.results,general:req.general,known:req.view_token})).unchanged)throw Error('结果来源已变化，请重新打开。');
   }
   let data;
   if(req.date!=='all' && full){
     const entire=await full.promise,i=entire.dates.indexOf(req.date),n=1440/entire.step_minutes;
     if(i<0)throw Error('所选日期超出已读时段。');
     data={...entire,dates:[req.date],points:n,sides:entire.sides.map(s=>({...s,values:Object.fromEntries(
       Object.entries(s.values).map(([field,values])=>[field,values.slice(i*n,(i+1)*n)]))}))};
   }else data=await cache.read(key,()=>api(spectralEndpoint,req));
   if(data.view_token!==req.view_token || data.wall!==req.wall)throw Error('结果来源已更新，请重新打开。');
   return data;
}
function roomLabel(room){
 if(!room?.zone)return '房间归属未核实';
 return (room.floor?'第 '+room.floor+' 层':'楼层未核实')+' · '+room.zone;
}
async function loadSpectral(v){
 const seq=++v.sequence,d=spectralDialog(),box=d.querySelector('[data-spectral-detail]');
 const req={results:v.refs,view_token:v.token,wall:v.wall,date:v.date};
 if(v.general)Object.assign(req,{general:true,frequency:v.frequency});
 box.textContent='正在读取所选墙的逐步结果…';d.querySelector('[data-spectral-location]').textContent='';
 v.data=null;v.roomData=null;v.roomPending=null;
 try{
   const data=await spectralRange(spectralReads,req);
   if(v!==spectralView || seq!==v.sequence)return;
   const labels=data.sides.map(side=>roomLabel(side.room));
   d.querySelector('[data-spectral-location]').textContent=new Set(labels).size===1?labels[0]:labels.join(' ／ ');
   v.data=data;drawSpectral(v,box);
 }catch(error){if(v===spectralView && seq===v.sequence)spectralError(box,error,'day');}
}
const spectralPanels=[
 {title:'材料温度',unit:'°C',fields:['cover','surface']},
 {title:'8–13 µm 向天空的净散热',unit:'W/m²',fields:['sky'],sign:'正值向天空散热'},
 {title:'墙体内表面导热',unit:'W/m²',fields:['inward'],sign:'正值向室内，负值向墙内'}
];
function spectralLines(data,panel,v){
 const lines=[];
 const repeated=data.sides.length===2 && data.sides[0].variant===data.sides[1].variant;
 for(const [i,s] of data.sides.entries()){
   const covered=s.variant==='covered', prefix=s.variant==='broadband'?'宽带面':covered?'PE':'裸露发射面';
   const side=repeated?(i?'研究 · ':'基准 · '):'';
   for(const field of panel.fields){
     if(!s.values[field])continue;
     if(v.general){
       if(v.fields.includes(field))lines.push({label:(data.sides.length===1?'':i?'研究 · ':'基准 · ')+wallMetrics[field],style:(i?'pe':'baseline')+({inside:' bare',air:' cover'}[field]||''),values:s.values[field]});
       continue;
     }
     const label=field==='cover'?'PE 覆盖层':field==='surface'&&covered?'下层发射层':field==='sky'&&covered?'发射层透过 PE':prefix;
     const style=(repeated?i===0:s.variant==='broadband')?'baseline':s.variant==='bare'?'bare':'pe';
     lines.push({label:side+label,style:style+(field==='cover'?' cover':''),values:s.values[field]});
   }
 }
 return lines;
}
function spectralGraph(lines,data,panel,scaleLines=lines,states=null){
 let low=Infinity,high=-Infinity;
 for(const line of scaleLines)for(const value of line.values){low=Math.min(low,value);high=Math.max(high,value);}
 if(!scaleLines.length){low=0;high=1;}
 if(panel.sign){low=Math.min(0,low);high=Math.max(0,high);}
 const span=high-low || 1, magnitude=10**Math.floor(Math.log10(span/3));
 const step=[1,2,5,10].map(x=>x*magnitude).find(x=>x>=span/3);
 const bottom=Math.floor(low/step)*step,top=Math.max(bottom+step,Math.ceil(high/step)*step);
 const x=i=>55+745*i/Math.max(1,data.points-1),y=value=>7+68*(top-value)/(top-bottom);
 let svg='';
 if(states){
   let start=0;
   for(let i=1;i<=states.length;i++){
     if(i<states.length && states[i]===states[start])continue;
     const left=x(Math.max(0,start-.5)),right=x(Math.min(states.length-1,i-.5));
     svg+='<rect class="room-band state-'+states[start]+'" x="'+left+'" y="7" width="'+(right-left)+'" height="68"/>';
     start=i;
   }
 }
 for(let i=0;lines.length && i<=Math.round((top-bottom)/step);i++){
   const val=bottom+i*step,yy=y(val);
   svg+='<line class="'+(Math.abs(val)<step/100?'zero':'grid')+'" x1="55" x2="800" y1="'+yy+'" y2="'+yy+'"/><text x="48" y="'+(yy+4)+'" text-anchor="end">'+Number(val.toPrecision(5))+'</text>';
 }
 for(const line of lines){
   const path=line.values.map((v,i)=>(i?'L':'M')+x(i).toFixed(2)+' '+y(v).toFixed(2)).join(' ');
   svg+='<path class="series '+line.style+'" d="'+path+'"/>';
 }
 const perDay=1440/data.step_minutes;
 const ticks=data.dates.length>1?data.dates.map((d,i)=>[i*perDay,d]):[0,6,12,18].map(h=>[h*60/data.step_minutes,h+':00']);
 for(const [i,label] of ticks)svg+='<text x="'+x(i)+'" y="94">'+esc(label)+'</text>';
 svg+='<text x="800" y="94" text-anchor="end">24:00</text><line data-spectral-cursor y1="5" y2="77"/>';
 return '<svg viewBox="0 0 815 99" role="img" aria-label="'+esc(panel.title+'时间曲线')+'">'+svg+'</svg>';
}
const roomModes=['停机','供暖','制冷'];
function updateRoomExport(v,box){
 for(const btn of box.querySelectorAll('[data-response-file]'))btn.disabled=(!!v.showRoom && !v.roomData)||!v.lines.some(lines=>lines.length);
}
async function showRoomControls(v,box){
 const wallData=v.data,details=box.querySelector('[data-spectral-room]'),slot=details.querySelector('[data-room-content]');
 if(v.roomPending===wallData || v.roomData)return;
 v.roomPending=wallData;slot.textContent='正在读取这个房间的逐步温控记录…';
 try{
   const data=await spectralRange(spectralRoomReads,{results:v.refs,view_token:v.token,wall:v.wall,date:v.date,room_controls:true});
   if(spectralView!==v || v.data!==wallData)return;
   if(data.points!==wallData.points || data.step_minutes!==wallData.step_minutes ||
      data.dates.join()!==wallData.dates.join() || data.sides.length!==wallData.sides.length ||
      data.sides.some((s,i)=>s.sha256!==wallData.sides[i].sha256 || s.room.zone!==wallData.sides[i].room.zone)){
     throw Error('房间记录与当前墙面的来源或时段不一致。');
   }
   v.roomData=data;
   const panels=data.sides.map((s,i)=>s.values.air?[{values:s.values.air,style:data.sides.length>1 && !i?'baseline':'pe'}]:[]);
   slot.innerHTML='<div class="room-key">'+roomModes.map((m,i)=>'<span><i class="room-band state-'+i+'"></i>'+m+'</span>').join('')+'</div>'+
     data.sides.map((s,i)=>'<section class="room-side"><h4>'+esc(s.name)+'</h4><div data-room-status="'+i+'"></div>'+
       (s.values.air||s.values.state?spectralGraph(panels[i],data,{title:'房间空气温度与温控状态'},panels.flat(),s.values.state):'')+
       s.notes.map(n=>'<small>'+esc(n)+'</small>').join('')+'</section>').join('');
   bindSpectralPointers(v,slot);updateRoomExport(v,box);moveSpectral(v,v.index);
 }catch(error){
   if(spectralView!==v || v.data!==wallData)return;
   v.roomData=null;slot.innerHTML='<p role="alert">'+esc(error.message)+'</p><button data-room-retry>重新读取房间记录</button>';
   slot.querySelector('button').onclick=()=>showRoomControls(v,box);
 }finally{if(v.roomPending===wallData)v.roomPending=null;}
}
function bindSpectralPointers(v,box){
 function point(event){
   const svg=event.currentTarget,xy=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse());
   moveSpectral(v,Math.round((xy.x-55)/745*(v.data.points-1)));
 }
 box.querySelectorAll('svg').forEach(svg=>{svg.onpointermove=point;svg.onpointerdown=point;});
}
function wallOutputCoverage(v,hasCurves){
 const sides=v.data.sides,step=v.meta.step_minutes;
 const labels={'Zone Timestep':'每 '+step+' 分钟',Hourly:'逐时',Daily:'逐日',Monthly:'逐月','Run Period':'时段汇总'};
 const sideName=i=>sides.length===1?'本批次':i?'研究侧':'基准侧';
 const cells=Object.entries(wallMetrics).map(([field,name])=>{
   const columns=sides.map(s=>{
     const freq=s.saved_frequencies[field];
     if(!freq?.length)return '<td class="coverage-empty">'+(freq===null?'房间待核实':'未记录')+'</td>';
     const ordered=[...Object.keys(labels).filter(f=>freq.includes(f)),...freq.filter(f=>!labels[f])];
     const fine=ordered.find(f=>f===v.frequency)||ordered.find(f=>f==='Zone Timestep'||f==='Hourly');
     const summaryOnly=ordered.every(f=>['Daily','Monthly','Run Period'].includes(f));
     const primary=fine||(summaryOnly?null:ordered[0]);
     const other=ordered.filter(f=>f!==primary).map(f=>labels[f]||f);
     return '<td><span class="coverage-value '+(fine?'coverage-detail':'coverage-aggregate')+'">'+esc(primary?labels[primary]||primary:'仅有汇总')+'</span>'+
       (other.length?'<small>'+esc(other.join(' · '))+'</small>':'')+'</td>';
   });
   return '<tr><th scope="row">'+esc(name)+'</th>'+columns.join('')+'</tr>';
 }).join('');
 const needsStep=sides.some(s=>Object.values(s.saved_frequencies).some(f=>f && !f.includes('Zone Timestep') && !(step===60&&f.includes('Hourly'))));
 return '<details data-observation-coverage'+((v.showCoverage??!hasCurves)?' open':'')+'><summary>测点保存明细<span class="coverage-wall">'+esc(v.wall)+'</span></summary>'+
   '<table aria-label="'+esc(v.wall)+' 的测点保存频率"><thead><tr><th scope="col">观测量</th>'+sides.map((s,i)=>'<th scope="col">'+sideName(i)+'</th>').join('')+'</tr></thead><tbody>'+cells+'</tbody></table>'+
   '<div class="coverage-foot"><p>本次每 '+step+' 分钟求解一次。已保存的逐步数据可直接导出，汇总值无法还原逐步曲线。</p>'+
   (needsStep?'<p><strong>需要补齐曲线？</strong> 在缺项一侧的「计算安排 → 墙面测点」选墙和观测量，按求解步保存并补算。</p>':'')+'</div></details>';
}
function drawSpectral(v,box){
 const data=v.data;
 const panels=v.general?[{title:'墙面与房间温度',unit:'°C',fields:['outside','inside','air']},spectralPanels[2]]:spectralPanels;
 v.lines=panels.map(p=>spectralLines(data,p,v));
 const opts=v.general?'<div class="spectral-controls">'+Object.entries(wallMetrics).map(([f,label])=>{
   const n=data.sides.filter(s=>s.values[f]).length;
   return '<label><input type="checkbox" data-observed-field="'+f+'"'+(n&&v.fields.includes(f)?' checked':'')+(n?'':' disabled')+'> '+label+
     (n===0?'（未保存）':n!==data.sides.length?'（仅'+(data.sides[0].values[f]?'基准':'研究')+'侧）':'')+'</label>';
 }).join('')+'</div>':'';
 const missing=v.general&&data.sides.length===2?data.sides.flatMap((s,i)=>Object.keys(s.values).length?[]:[(i?'研究侧':'基准侧')+'在当前保存频率下缺少这面墙和所属房间的测点记录。']).join(''):'';
 const hasCurves=data.sides.some(s=>Object.keys(s.values).length);
 box.innerHTML=(missing?'<p data-observation-gap>'+esc(missing)+'</p>':'')+(v.general?wallOutputCoverage(v,hasCurves)+'<div data-switch-host></div>':'')+opts+(v.general&&!hasCurves?'':'<div class="spectral-time"><label>查看时刻 <output data-spectral-clock></output><input aria-label="联动时间游标" data-spectral-slider type="range" min="0" max="'+(data.points-1)+'" step="1"></label></div>'+
   panels.map((panel,i)=>!v.lines[i].length?'':'<section class="spectral-panel"><div class="spectral-heading"><h3>'+panel.title+' <small>/ '+panel.unit+'</small></h3>'+
      (panel.sign?'<small>'+panel.sign+'</small>':'')+'</div><div class="spectral-legend">'+v.lines[i].map((line,j)=>
      '<span><i class="'+line.style+'"></i>'+esc(line.label)+' <b data-sp-value="'+i+'-'+j+'"></b></span>').join('')+
      '</div>'+spectralGraph(v.lines[i],data,panel)+'</section>').join('')+
   (!v.lines.some(ls=>ls.length)?'<p>没有可绘制的已选量。可换墙、切换已存频率，或在下次计算前增设测点。</p>':'')+
   (v.general?'':'<details data-spectral-room'+(v.showRoom?' open':'')+'><summary>查看房间温控</summary><div data-room-content></div></details>')+responseExportBar(data.step_minutes,v.exportStep));
 const coverage=box.querySelector('[data-observation-coverage]');
 if(coverage)coverage.ontoggle=()=>{if(coverage.isConnected&&v.data===data)v.showCoverage=coverage.open;};
 if(v.general){
   const targets=v.meta.sides.flatMap((s,i)=>s.switch_walls?.includes(v.wall)?
    [{ref:v.refs[i],token:s.source_token,label:v.refs.length===1?s.name:(i?'研究侧 · ':'基准侧 · ')+s.name}]:[]);
   mountWallSwitches(v,box.querySelector('[data-switch-host]'),targets,v.wall,null,
     ()=>{
       const at=switchOffset(data.period,data.dates[0],v.index*data.step_minutes),selected=v.switchState?.selected;
       if(!hasCurves)return selected??switchOffset(data.period,data.dates[0],0);
       return selected!=null&&at<=selected&&selected<at+data.step_minutes?selected:at;
     },
     async offset=>{
       const day=switchStamp(data.period,offset)[0],dialog=spectralDialog(),wall=v.wall;
       const detailed=v.meta.frequencies.includes('Zone Timestep');
       if(v.date!=='all'&&v.date!==day||detailed&&v.frequency!=='Zone Timestep'){
         if(v.date!=='all'){v.date=day;dialog.querySelector('[data-spectral-date]').value=day;}
         if(detailed){v.frequency='Zone Timestep';dialog.querySelector('[data-observed-frequency]').value=v.frequency;}
         await loadSpectral(v);
       }
       if(spectralView===v&&wall===v.wall&&v.data?.dates.includes(day)&&dialog.querySelector('[data-spectral-slider]'))
         moveSpectral(v,Math.floor((offset-switchOffset(v.data.period,v.data.dates[0],0))/v.data.step_minutes));
     },hasCurves&&v.frequency==='Hourly'&&v.meta.step_minutes!==60);
 }
 if(v.general&&!hasCurves)return;
 const details=box.querySelector('[data-spectral-room]');
 if(details)details.ontoggle=()=>{
   if(v.data!==data || !details.isConnected)return;
   v.showRoom=details.open;updateRoomExport(v,box);
   if(details.open){if(v.roomData)moveSpectral(v,v.index);else void showRoomControls(v,box);}
 };
 updateRoomExport(v,box);
 if(details?.open)void showRoomControls(v,box);
 box.querySelector('[data-response-step]').onchange=e=>{v.exportStep=Number(e.target.value);};
 box.querySelectorAll('[data-response-file]').forEach(btn=>btn.onclick=e=>{
   const step=Number(box.querySelector('[data-response-step]').value);
   const room=details?.open?v.roomData:null;
   if(details?.open && !room)return;
   void verifiedResponseDownload(e.currentTarget,async()=>(await api(spectralEndpoint,{results:v.refs,general:v.general,known:v.token})).unchanged && v.data===data && !!room===!!details?.open,
     ()=>exportSpectral(data,step,room,btn.dataset.responseFile,v.general?v.fields:null));
 });
 bindSpectralPointers(v,box);
 moveSpectral(v,v.index);
}
function exportSpectral(data,step,room=null,format='full',selected=null){
 const native=data.step_minutes,count=step/native;
 if(!responseIntervals(native).includes(step))throw Error('请选择原步长或其整数倍。');
 const fields=selected?Object.fromEntries(selected.map(f=>[f,wallMetrics[f]+(f==='inward'?' / W/m²':' / °C')])):
   {cover:'PE 覆盖层温度 / °C',surface:'发射面温度 / °C',sky:'8–13 µm 向天空净散热 / W/m²',inward:'内表面导热 / W/m²'};
 const series=[],sourceHeaders=[],sourceValues=[],roomHeaders=[];
 const cols=[],sources=[['地点',data.city],['墙号',data.wall],['原始保存步长 / min',native],['导出步长 / min',step],['内表面导热','正值向室内，负值向墙内。'],['聚合','温度、热流密度与功率按区间取平均，温控分钟数按状态累计。']];
 for(const [i,side] of data.sides.entries()){
   const label=data.sides.length===1?side.name:(i?'右侧 · ':'左侧 · ')+side.name;
   const alias=data.sides.length===1?'':i?'研究 · ':'基准 · ';
   sources.push([alias+'方案',side.name],[alias+'批次',side.batch],[alias+'算例索引',side.index],[alias+'结果 SHA-256',side.sha256],[alias+'所属房间',roomLabel(side.room)]);
   for(const [field,name] of Object.entries(fields)){
     if(side.values[field]){
       cols.push({index:8+series.length,label:alias+name,chart:field==='sky'?'向天空净散热':field==='inward'?'内表面导热':'温度',unit:name.endsWith('°C')?'°C':'W/m²'});
       series.push([label+' · '+name,side.values[field]]);
     }
   }
   sourceHeaders.push(label+' · 批次',label+' · 算例索引',label+' · 结果 SHA-256');
   sourceValues.push(side.batch,side.index,side.sha256);
   if(room){
     roomHeaders.push(...['房间','楼层','室温 / °C','供暖显热 / kW','制冷显热 / kW','温控状态','停机 / min','供暖 / min','制冷 / min'].map(name=>label+' · '+name));
   }
 }
 if(room)room.sides.forEach((s,i)=>{
   const alias=data.sides.length===1?'':i?'研究 · ':'基准 · ',offset=8+series.length+9*i;
   for(const [j,name,chart,unit,key] of [[2,'室温 / °C','房间温度','°C','air'],[3,'供暖显热 / kW','房间显热功率','kW','heating'],[4,'制冷显热 / kW','房间显热功率','kW','cooling'],[5,'温控状态',null,null,'state'],[6,'停机 / min','温控时长','min','state'],[7,'供暖 / min','温控时长','min','state'],[8,'制冷 / min','温控时长','min','state']])
     if(s.values[key])cols.push({index:offset+j,label:alias+name,chart,unit});
 });
 const rows=[['地点','墙号','月日','区间开始','区间结束','原步长 / min','导出步长 / min','原始点数',...series.map(s=>s[0]),...roomHeaders,...sourceHeaders]];
 for(let i=0;i<data.points;i+=count){
   const m=i*native%1440;
   const roomCells=[];
   for(const side of room?.sides||[]){
     const a=side.values,modes=a.state?.slice(i,i+count);
     roomCells.push(side.room.zone,side.room.floor,...['air','heating','cooling'].map(k=>a[k]?responseMean(a[k],i,count):null),
       modes?[...new Set(modes)].map(s=>roomModes[s]).join(' / '):null,
       ...roomModes.map((_,s)=>modes?modes.filter(value=>value===s).length*native:null));
   }
   rows.push([data.city,data.wall,data.dates[Math.floor(i*native/1440)],responseClock(m),responseClock(m+step),
     native,step,count,...series.map(s=>responseMean(s[1],i,count)),...roomCells,...sourceValues]);
 }
 return responseFile(format,[data.city,data.wall,data.dates[0],data.dates.at(-1),step+'min',room?'墙面与房间响应':selected?'墙面测点':'逐墙响应'].join('_'),rows,cols,[2,3,4],sources);
}
function moveSpectral(v,index){
 if(!v?.data)return;
 const d=spectralDialog(),data=v.data,i=Math.max(0,Math.min(data.points-1,index));
 v.index=i;
 v.switchNav?.();
 const t=i*data.step_minutes,day=data.dates[Math.floor(t/1440)];
 const hour=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
 d.querySelector('[data-spectral-clock]').textContent=day+'　'+hour(t%1440)+'–'+hour(t%1440+data.step_minutes);
 d.querySelector('[data-spectral-slider]').value=i;
 const x=55+745*i/Math.max(1,data.points-1);
 for(const cursor of d.querySelectorAll('[data-spectral-cursor]')){cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);}
 v.lines.forEach((lines,p)=>lines.forEach((l,j)=>{d.querySelector('[data-sp-value="'+p+'-'+j+'"]').textContent=l.values[i].toFixed(2);}));
 if(v.showRoom && v.roomData)v.roomData.sides.forEach((s,side)=>{
   const a=s.values,slot=d.querySelector('[data-room-status="'+side+'"]');
   if(slot)slot.textContent=[a.state?roomModes[a.state[i]]:null,a.air?'室温 '+a.air[i].toFixed(2)+' °C':null,
     a.heating?'供暖 '+a.heating[i].toFixed(2)+' kW':null,a.cooling?'制冷 '+a.cooling[i].toFixed(2)+' kW':null].filter(Boolean).join('　');
 });
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-spectral-open],[data-wall-observe],[data-spectral-close],[data-spectral-floor],[data-spectral-retry]');
 if(!b)return;
 e.preventDefault();e.stopImmediatePropagation();
 if(b.hasAttribute('data-spectral-close'))return spectralDialog().close();
 if(b.hasAttribute('data-spectral-retry'))return void (b.dataset.spectralRetry==='open'?openSpectral(spectralView.refs,spectralView.general,spectralView.role):loadSpectral(spectralView));
 if(b.hasAttribute('data-spectral-floor')){
   const v=spectralView;
   return resultFloorPlan(v.refs[0],v.token,v.meta.walls,v.wall,wall=>{
     if(v!==spectralView||wall===v.wall)return;
     v.wall=wall;spectralDialog().querySelector('[data-spectral-wall]').value=wall;void loadSpectral(v);
   });
 }
 void openSpectral(JSON.parse(b.dataset.wallObserve||b.dataset.spectralOpen),b.hasAttribute('data-wall-observe'),b.dataset.responseRole||'');
},true);
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-spectral-date],[data-spectral-wall],[data-observed-frequency],[data-observed-field]'))return;
 const v=spectralView;
 if(e.target.hasAttribute('data-observed-field')){
   v.fields=[...spectralDialog().querySelectorAll('[data-observed-field]')].filter(n=>n.checked||n.disabled&&v.fields.includes(n.dataset.observedField)).map(n=>n.dataset.observedField);
   drawSpectral(v,spectralDialog().querySelector('[data-spectral-detail]'));return;
 }
 if(e.target.hasAttribute('data-spectral-wall'))v.wall=e.target.value;
 else if(e.target.hasAttribute('data-observed-frequency')){v.frequency=e.target.value;v.index=0;}
 else{v.date=e.target.value;v.index=0;if(v.switchState)v.switchState.selected=null;}
 void loadSpectral(v);
});
document.addEventListener('input',e=>{if(e.target.matches('[data-spectral-slider]'))moveSpectral(spectralView,Number(e.target.value));});
