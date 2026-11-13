/* Run with node --test scripts/test_calendar_ui.cjs. No browser dependencies. */
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../building-workbench-next/static/calendar-library.js'),'utf8');
function environment(){
 const dialog={innerHTML:'',open:true,querySelector:()=>({}),querySelectorAll:()=>[],showModal(){this.open=true;}};
 const context=vm.createContext({S:{calendarLibrary:null},conditionPanel:()=>'',updateCapabilityStatus:()=>{},configurationAction:()=>{},window:{addEventListener(){}},document:{querySelector:()=>dialog},copy:x=>JSON.parse(JSON.stringify(x)),esc:x=>String(x??''),format:x=>String(x??'无数据'),readonly:()=>false,referenceContext:()=> 'same',calendarInspectionMessage:()=> '核对完成',currentCalendarInspection:()=>null});
 vm.runInContext(source,context);
 context.selectLibraryDay=()=>{};
 const model={key:'same',label:'本地验证',dirty:false,result:null,site:0,day:0,pending:true,accept:false,transitionChoices:null};
 context.S.calendarLibrary=model;
 return {context,dialog,model};
}
function readyResult(){return {phase:'inspected',source_kind:'accepted_queue_daily_v1',issues:[],scope_sites:[{city:'长沙'}],rows:[{site_id:'cs',city:'长沙',ready:true,issues:[],orientation_input:{status:'input_ready',note:'Drawing26 日历、来源与输入核对通过。'}}],can_save:true,can_apply:true,versions:[],history:[],parent_options:[],application_issues:[],content:{sites:[]}};}
test('Drawing26 compact inspection renders complete preview and save/apply controls',async()=>{
 const {context,dialog,model}=environment();
 context.requestCalendarInspection=async()=>({id:'inspection',state:'ready',result:readyResult()});
 await context.loadCalendarInspection(model);
 assert.equal(model.pending,false);
 assert.match(dialog.innerHTML,/Drawing26 日历、来源与输入核对通过/);
 assert.match(dialog.innerHTML,/保存日历版本/);
 assert.match(dialog.innerHTML,/采用并启用翻面/);
 assert.doesNotMatch(dialog.innerHTML,/正在核对日历|undefined|五层材料翻面/);
 assert.match(dialog.innerHTML,/data-calendar-library-tool="save" disabled/);
});
test('ordinary building still displays supplied optical and wall details',()=>{
 const {context}=environment();
 const html=context.orientationInputMarkup({orientation_input:{status:'input_ready',runtime_verified:true,execution_enabled:true,surfaces:14,net_area_m2:120,resistance_m2K_W:.3,initial_face:'B',faces:{A:{solar_absorptance:.062,emissivity:.988},B:{solar_absorptance:.824,emissivity:.659}}}});
 assert.match(html,/14 面外墙/);assert.match(html,/0.062/);assert.match(html,/B 面朝外/);
});
test('blocked inputs remain blocked and show their reason',()=>{
 const {context}=environment();const html=context.orientationInputMarkup({orientation_input:{status:'blocked',note:'缺少匹配参考'}});
 assert.match(html,/缺少匹配参考/);assert.match(html,/请先处理/);
});
test('unexpected rendering error clears stale target and leaves retry controls',async()=>{
 const {context,dialog,model}=environment();
 context.requestCalendarInspection=async()=>({id:'inspection',state:'ready',result:readyResult()});
 context.orientationInputMarkup=()=>{throw Error('fixture render failure');};
 await context.loadCalendarInspection(model);
 assert.equal(model.pending,false);assert.equal(model.result,null);assert.equal(model.inspectionId,null);
 assert.match(dialog.innerHTML,/日历预览未能显示/);assert.match(dialog.innerHTML,/重新核对/);
 assert.doesNotMatch(dialog.innerHTML,/正在核对日历|保存日历版本/);
});
test('closing the dialog while checking does not reopen or adopt a result',async()=>{
 const {context,dialog,model}=environment();let finish;
 context.requestCalendarInspection=()=>new Promise(resolve=>finish=resolve);
 const pending=context.loadCalendarInspection(model);context.S.calendarLibrary=null;
 const closedMarkup=dialog.innerHTML;finish({id:'old',state:'ready',result:readyResult()});await pending;
 assert.equal(dialog.innerHTML,closedMarkup);assert.equal(model.result,null);
});
