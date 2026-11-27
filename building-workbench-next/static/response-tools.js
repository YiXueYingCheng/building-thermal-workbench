'use strict';

function downloadResultCsv(filename, rows){
 const cell=value=>{
   let raw=value??'';
   if(typeof raw==='string' && /^[\s]*[=+@-]/.test(raw))raw="'"+raw;
   return '"'+String(raw).replaceAll('"','""')+'"';
 };
 const text=rows.map(row=>row.map(cell).join(',')).join('\r\n');
 const url=URL.createObjectURL(new Blob(['\uFEFF',text],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=filename.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_');
 a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function responseIntervals(native){
 return [native,...[5,10,15,30,60].filter(m=>m>native && m%native===0)];
}
function responseExportBar(native,selected){
 const intervals=responseIntervals(native);
 return '<div class="response-export"><label>导出步长 <select data-response-step>'+
   options(intervals.map(m=>[m,m===native?'原步长 · '+m+' 分钟':m+' 分钟均值']),intervals.includes(selected)?selected:native)+
   '</select></label><button class="primary" data-response-file="xlsx">导出 Excel（可编辑图表）</button>'+
   '<button data-response-csv data-response-file="csv">导出简表 CSV</button>'+
   '<details><summary>更多</summary><button data-response-file="full">完整 CSV（含来源）</button></details><small role="status"></small></div>';
}
function responseClock(minutes){
 return String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');
}
function responseMean(values,offset,count){
 if(count===1)return values[offset];
 let sum=0;
 for(let i=offset;i<offset+count;i++)sum+=values[i];
 return sum/count;
}
async function verifiedResponseDownload(button,check,save){
 const status=button.closest('.response-export').querySelector('[role=status]');
 button.disabled=true;status.textContent='正在核对结果版本…';
 try{
   const valid=await check();
   if(!button.isConnected || !button.closest('dialog')?.open)return;
   if(!valid)throw Error('结果来源已变化，请重新打开数据后导出。');
   await save();status.textContent=button.dataset.responseFile==='xlsx'?'已生成 Excel 工作簿':'已生成 CSV';
 }catch(e){status.textContent=e.message;}
 finally{button.disabled=false;}
}

// The same interval rows drive both file formats and every chart.
async function responseFile(format,file,rows,columns,dates,sources){
 if(format==='full')return downloadResultCsv(file+'.csv',rows);
 const [day,start,end]=dates;
 const headers=['区间开始','区间结束',...columns.map(c=>c.label)];
 const data=rows.slice(1).map(r=>[r[day]+' '+r[start],r[end],...columns.map(c=>r[c.index])]);
 if(format==='csv')return downloadResultCsv(file+'-简表.csv',[headers,...data]);
 const charts=[];
 columns.forEach((c,i)=>{
   if(!c.chart)return;
   let g=charts.find(g=>g.title===c.chart);
   if(!g){g={title:c.chart,unit:c.unit,columns:[]};charts.push(g);}
   g.columns.push(i+2);
 });
 const resp=await fetch('/api/material-response/workbook',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':S.boot.token},
   body:JSON.stringify({headers,rows:data,charts,sources})});
 if(!resp.ok)throw Error((await resp.json()).error||'工作簿导出未完成。');
 const url=URL.createObjectURL(await resp.blob()),a=document.createElement('a');
 a.href=url;a.download=file.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_')+'.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

const responsePlans=new DialogReads(3);
let responsePlanPosition;
function openResponseFloor({key,read,walls,current,select}){
 const allowed=new Set(walls),dialog=document.createElement('dialog');
 dialog.className='response-floor';dialog.setAttribute('aria-label','从平面图选墙');
 dialog.innerHTML='<header class="viewer-head"><h2>从平面图选墙</h2><button data-floor-close>返回</button></header><div class="response-floor-body"></div>';
 const body=dialog.lastElementChild;
 document.body.append(dialog);dialog.showModal();
 let geometry,floor;
 function paint(){
   const mapped=geometry.walls.filter(w=>allowed.has(w.id)),onFloor=mapped.filter(w=>w.floor===floor);
   const levelOptions=geometry.floors.map(f=>[f.id,'第 '+(f.id+1)+' 层 · '+mapped.filter(w=>w.floor===f.id).length+' 面可选墙']);
   body.innerHTML='<div class="response-floor-tools"><label>楼层 <select data-response-floor>'+options(levelOptions,floor)+'</select></label><span>'+esc(geometry.building||'')+
     ' · 当前 '+esc(current)+'</span></div><p class="geometry-legend"><span class="geo-target">可选墙面</span><span class="geo-current">当前墙面</span></p>'+
     (onFloor.length?'':'<p>这层没有可选墙面。</p>')+
     '<div class="geometry-canvas">'+geometrySVG({data:geometry,floor,wall:current,room:null},allowed)+'</div>'+
     (mapped.length<allowed.size?'<p>有 '+(allowed.size-mapped.length)+' 面墙未能投影，可返回按墙号选择。</p>':'');
 }
 async function load(){
   body.textContent='正在读取建筑平面…';
   try{
     geometry=await responsePlans.read(key,read);
     if(!dialog.open)return;
     if(!geometry?.floors?.length)throw Error(geometry?.note||'该建筑没有可显示的楼层。');
     floor=responsePlanPosition?.key===key && responsePlanPosition.current===current?responsePlanPosition.floor:
       (geometry.walls.find(w=>w.id===current)?.floor??0);
     paint();
   }catch(error){
     if(dialog.open)body.innerHTML='<p role="alert">'+esc(error.message)+'</p><button data-floor-retry>重新读取</button>';
   }
 }
 dialog.addEventListener('change',e=>{
   if(e.target.matches('[data-response-floor]')){floor=Number(e.target.value);paint();body.querySelector('select').focus();}
 });
 function choose(node){
   const id=node?.dataset.responseWall;
   if(!allowed.has(id))return;
   dialog.close();select(id);
 }
 dialog.addEventListener('click',e=>{
   if(e.target.closest('[data-floor-close]'))dialog.close();
   else if(e.target.closest('[data-floor-retry]'))void load();
   else choose(e.target.closest('[data-response-wall]'));
 });
 dialog.addEventListener('keydown',e=>{
   const wall=e.target.closest('[data-response-wall]');
   if(wall && ['Enter',' '].includes(e.key)){e.preventDefault();choose(wall);}
 });
 dialog.addEventListener('close',()=>{
   if(Number.isInteger(floor))responsePlanPosition={key,current,floor};
   dialog.remove();
 },{once:true});
 void load();
}
function resultFloorPlan(ref,token,walls,current,select){
 openResponseFloor({key:JSON.stringify([ref,token]),read:()=>api('/api/material-response/floor-plan',ref),walls,current,select});
}

let responseSiteSelection;
function responseActions(d,row){
 if(!row)return '';
 const buttons=[];
 if(d.material_response_available && row.status==='paired' && [row.left_evidence,row.right_evidence].every(e=>e?.kind==='execution'))
   buttons.push('<button data-research-response>日照分段汇总</button>');
 if(row.status==='paired'){
   const refs=[row.left_evidence,row.right_evidence];
   if(refs.every(e=>e?.kind==='execution') && row.left_step_minutes===row.right_step_minutes)
     buttons.push(spectralOpenButton(refs,true));
   const sides=['left','right'].filter(s=>row[s+'_spectral_variant'] && row[s+'_evidence']?.kind==='execution');
   if(sides.length && (sides.length===1 || row.left_step_minutes===row.right_step_minutes))
     buttons.push(spectralOpenButton(sides.map(s=>row[s+'_evidence']),false,sides.length===1?(sides[0]==='left'?'基准侧':'研究侧'):''));
 }
 for(const side of ['left','right']){
   const e=row[side+'_evidence'];
   if(row[side+'_stack_response'] && e?.kind==='execution')buttons.push('<button data-stack-open data-batch="'+esc(e.batch_id)+'" data-index="'+esc(e.index)+'">'+(side==='left'?'基准':'研究')+' · 分层测点</button>');
 }
 return buttons.join('');
}
function spectralSideNote(row){
 const only=['left','right'].filter(s=>row[s+'_spectral_variant'] && row[s+'_evidence']?.kind==='execution');
 if(row.status!=='paired'||only.length!==1)return '';
 const other=only[0]==='left'?'right':'left',label=other==='left'?'基准侧':'研究侧';
 const reason=S.resultComparison?.record_details?.[other]?.original_envelope?
   label+'采用原墙构造，没有 PE 覆盖层和下层发射层，因此没有覆盖层温度或透过 PE 的散热量。':
   label+'没有可读取的逐步辐射材料响应。';
 return '<details><summary>为什么逐墙材料响应只显示一侧？</summary><p>'+reason+' 同一墙面的表面温度、导热和所属房间室温可在「墙面测点」中逐项核对保存频率。</p></details>';
}
function materialResponseControls(d){
 const sites=d.sites.filter(row=>responseActions(d,row));
 if(!sites.length)return '';
 const key=d.dataset_sha256;
 const selected=sites.find(row=>responseSiteSelection?.key===key && responseSiteSelection.site===row.site_id)||sites[0];
 const selector=sites.length===1?'<span class="response-city">'+esc(selected.city)+'</span>':
   '<label>地点 <select data-response-site>'+options(sites.map(row=>[row.site_id,row.city]),selected.site_id)+'</select></label>';
 return '<section class="response-tools" aria-label="材料响应" data-site="'+esc(selected.site_id)+'"><div class="response-tools-title"><h3>材料响应</h3>'+selector+'</div><div class="response-tool-actions">'+responseActions(d,selected)+'</div><div data-response-why>'+spectralSideNote(selected)+'</div></section>';
}
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-response-site]'))return;
 const d=S.comparisonData,row=d.sites.find(r=>r.site_id===e.target.value);
 if(!row)return;
 responseSiteSelection={key:d.dataset_sha256,site:row.site_id};
 const box=e.target.closest('.response-tools');
 box.dataset.site=row.site_id;box.querySelector('.response-tool-actions').innerHTML=responseActions(d,row);
 box.querySelector('[data-response-why]').innerHTML=spectralSideNote(row);
});
