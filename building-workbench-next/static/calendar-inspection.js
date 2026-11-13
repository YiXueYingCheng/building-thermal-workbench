/* Shared read-only inspection; opening/closing a view never locks the workspace. */
S.calendarInspection=null;
const calendarFlights=new Map();
function calendarInspectionKey(){return S.record&&S.saved?JSON.stringify([S.id,S.saved.revision,changes()]):null;}
function currentCalendarInspection(){return S.calendarInspection?.key===calendarInspectionKey()?S.calendarInspection:null;}
function calendarInspectionMessage(state=currentCalendarInspection()){
 if(!state)return '核对分三步：① 同条件 W00 逐日参考；② 日历与地点特例；③ 材料范围和实际控制输入。尚未开始核对。';
 if(state.error)return state.error;
 const job=state.job;
 if(job?.state==='ready')return `核对完成 · 来源复查于 ${job.validated_at.replace('T',' ')}${job.reused?' · 已复用相同来源的预览':''}`;
 const p=job?.progress;
 return p?`${p.stage}${p.total?' · '+p.completed+' / '+p.total+' 地点':''}${p.city?' · '+p.city:''}。可收起或关闭后继续其他操作。`:'正在准备核对…可收起或关闭后继续其他操作。';
}
function notifyCalendarInspection(state){
 if(S.calendarInspection!==state||state.key!==calendarInspectionKey())return;
 if(typeof updateWorkflowDOM==='function')updateWorkflowDOM();
 const m=S.calendarLibrary;
 if(m?.key===state.key&&m.pending&&!m.result){m.message=calendarInspectionMessage(state);const el=document.querySelector('#calendar-library-dialog .calendar-preview-body>[role="status"]');if(el)el.textContent=m.message;}
}
function requestCalendarInspection(force=false){
 const key=calendarInspectionKey();
 if(calendarFlights.has(key)){S.calendarInspection=calendarFlights.get(key);notifyCalendarInspection(S.calendarInspection);return S.calendarInspection.promise;}
 const state={key,pending:true,job:null,error:''},body={id:S.id,revision:S.saved.revision,changes:changes(),force};
 S.calendarInspection=state;calendarFlights.set(key,state);notifyCalendarInspection(state);
 state.promise=(async()=>{
  try{
   let job=await api('/api/calendar-inspections',body);
   while(true){state.job=job;notifyCalendarInspection(state);if(!['queued','running'].includes(job.state))break;await new Promise(resolve=>setTimeout(resolve,600));job=await api('/api/calendar-inspections/'+job.id);}
   if(job.state!=='ready')throw Error(job.error||'核对未完成，请重新核对。');
   return job;
  }catch(error){state.error=error.message;return null;}
  finally{state.pending=false;if(calendarFlights.get(key)===state)calendarFlights.delete(key);notifyCalendarInspection(state);}
 })();return state.promise;
}
