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
 assert.match(dialog.innerHTML,/采用并启用光学切换/);
 assert.doesNotMatch(dialog.innerHTML,/正在核对日历|undefined|五层表面光学切换/);
 assert.match(dialog.innerHTML,/data-calendar-library-tool="save" disabled/);
});
test('ordinary building still displays supplied optical and wall details',()=>{
 const {context}=environment();
 const html=context.orientationInputMarkup({orientation_input:{status:'input_ready',runtime_verified:true,execution_enabled:true,surfaces:14,net_area_m2:120,resistance_m2K_W:.3,initial_face:'B',faces:{A:{solar_absorptance:.062,emissivity:.988},B:{solar_absorptance:.824,emissivity:.659}}}});
 assert.match(html,/14 面外墙/);assert.match(html,/0.062/);assert.match(html,/B 组光学参数/);
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

test('a separately saved calendar can be adopted with fresh server verification',async()=>{
 const {context,model}=environment();
 const snapshot={id:'calendar',revision:1,created:'now',name:'试用日历'};
 const condition={controls:[],reference_runs:[]};
 context.S.record={factors:{condition}};context.S.saved={revision:3};context.S.id='scheme';
 Object.assign(context,{changes:()=>({}),setPath:()=>{},render:()=>{}});
 Object.assign(model,{result:{...readyResult(),content_sha256:'verified',record_sha256:'scheme'},accept:true,inspectionId:'job',inspectionChoices:null});
 const requests=[];
 context.api=async(_,body)=>{requests.push(body);return {snapshot,reused:body.action==='apply',applied:body.action==='apply',condition};};
 await context.useCalendarLibrary('save',model);
 assert.equal(model.savedOnly,true);assert.equal(model.needsInspection,false);
 await context.useCalendarLibrary('apply',model);
 assert.equal(model.applied,true);assert.equal(requests[0].inspection_id,'job');
 assert.equal('inspection_id' in requests[1],false);
 assert.equal(requests[1].expected_sha256,'verified');
});

test('control summary distinguishes partial, coupled and separate targets',()=>{
 const ctx=vm.createContext({S:{},esc:String,app:{addEventListener(){}},editor(){},loadPlanActivity(){},updateDirtyStatus(){},updateCapabilityStatus(){},action(){}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../building-workbench-next/static/plan-workflow.js'),'utf8'),ctx);
 const thermal={application_id:'material',target_ids:['west','roof'],channel:'thermal',mode:'feedback'};
 const flip={application_id:'material',target_ids:['roof'],channel:'orientation',mode:'calendar'};
 const view=controls=>ctx.materialControlSummary({revision:4,factors:{condition:{controls}}});
 assert.match(view([]),/表面光学切换 · 未启用/);
 assert.match(view([thermal]),/仅热阻调节/);
 assert.match(view([flip]),/仅表面光学切换/);
 assert.match(view([thermal,flip]),/1 个构件同时进行表面光学切换和热阻调节/);
 assert.match(view([thermal,{...flip,target_ids:['east']}]),/分别作用于不同构件/);
 ctx.S.record={factors:{condition:{controls:[flip]}}};ctx.currentCalendarInspection=()=>null;
 const d={nodes:[{id:'prepare',state:'ready'}],calendar_status:[{name:'当地日历',revision:2,active:true,valid:true}]};
 assert.match(ctx.workflowBranchStatus(d),/当地日历 · v2/);
 assert.match(ctx.workflowBranchStatus(d),/可直接生成模型输入/);
 d.calendar_status[0]={...d.calendar_status[0],valid:false,note:'气象已变化'};
 assert.match(ctx.workflowBranchStatus(d),/气象已变化/);
 assert.doesNotMatch(ctx.workflowBranchStatus(d),/可直接生成模型输入/);
 d.calendar_status=[];
 assert.match(ctx.workflowBranchStatus(d),/请先核对/);
 assert.doesNotMatch(ctx.workflowBranchStatus(d),/可直接生成模型输入/);
});

test('opening an adopted calendar reads the chosen version and starts zero inspections',async()=>{
 const {context,dialog}=environment();
 const snap={id:'a',name:'原方案的日历',revision:2,content:{sites:[{site_id:'hrb',city:'哈尔滨',calendar:[0,1],switches:[{date:'01-02',day_of_year:2}],warnings:['原警告'],transition_confirmation:{}}]}};
 const ref={id:'a',kind:'workspace_daily_calendar_v1',snapshot:snap};
 context.S.record={name:'另存方案',factors:{scope:{site_ids:['hrb']},condition:{controls:[{channel:'orientation',mode:'calendar',reference_id:'a'}],reference_runs:[ref]}}};
 context.S.saved={revision:1};context.calendarBindingMarkup=()=>'<p>参考条件一致</p>';
 let requests=0;context.requestCalendarInspection=()=>{requests++;throw Error('unexpected inspection');};
 await context.configurationAction({dataset:{calendarLibrary:'open'}});
 assert.equal(requests,0);assert.match(dialog.innerHTML,/原方案的日历 · v2/);
 assert.match(dialog.innerHTML,/1 月 1 日 B 组/);assert.match(dialog.innerHTML,/01-02 转 A 组/);
 assert.match(dialog.innerHTML,/原警告/);assert.match(dialog.innerHTML,/已保留本地点的季节切换确认/);
});

test('switching schemes during checks with explicit choices resumes the same job and its completed result',async()=>{
 let plan='A',finish;
 const posts=[],choices=[{site_id:'hrb',choice:'keep',binding_sha256:'proof'}];
 const ctx=vm.createContext({S:{record:{},saved:{revision:1}},referenceContext:()=>plan,changes:()=>({}),setTimeout:f=>f(),api:async(route,body)=>{
  if(body){posts.push(body);return {id:plan,state:plan==='A'?'running':'ready'};}
  return new Promise(r=>{finish=r;});
 }});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../building-workbench-next/static/calendar-inspection.js'),'utf8'),ctx);
 ctx.S.id='A';const a=ctx.requestCalendarInspection(false,choices);
 await new Promise(resolve=>setImmediate(resolve));
 plan=ctx.S.id='B';await ctx.requestCalendarInspection();
 assert.equal(ctx.currentCalendarInspection().job.id,'B');
 plan=ctx.S.id='A';assert.equal(ctx.currentCalendarInspection().pending,true);
 assert.equal(ctx.requestCalendarInspection(),a);
 finish({id:'A',state:'ready'});await a;
 plan=ctx.S.id='B';assert.equal(ctx.currentCalendarInspection().job.id,'B');
 plan=ctx.S.id='A';assert.equal((await ctx.requestCalendarInspection()).id,'A');
 assert.deepEqual(posts.map(x=>x.id),['A','B']);assert.deepEqual(ctx.currentCalendarInspection().choices,choices);
});
