const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const staticDir = path.join(__dirname, '../building-workbench-next/static');
function load(context, name) {
  vm.runInContext(fs.readFileSync(path.join(staticDir, name), 'utf8'), context);
}

test('closing or reopening the timeline during a read keeps one request and restores the selected view', async () => {
  const body = {};
  const dialog = {open:false, querySelector:() => body, close(){this.open=false;}, showModal(){this.open=true;}};
  let finish, calls = 0;
  const receipt = {view_token:'saved', period:[1,1,12,31], monthly_loads:[{}]};
  const context = vm.createContext({
    document:{activeElement:null, addEventListener(){}}, URLSearchParams, resultViewContent(){}, raReport(){},
    async api(url) {
      if (url.includes('known=saved')) return {view_token:'saved', unchanged:true};
      calls++;
      return new Promise(resolve => {finish = () => resolve(receipt);});
    }
  });
  load(context, 'recent-views.js');
  load(context, 'result-timeline.js');
  context.rtDialog = () => dialog;
  context.rtShell = () => {};
  context.rtInventory = () => '';
  context.rtShowTab = tab => {dialog.tab = tab;};
  const first = context.rtOpen('batch', 0);
  await Promise.resolve();
  context.rtClose();
  const second = context.rtOpen('batch', 0);
  context.rtClose();
  finish();
  await Promise.all([first,second]);
  assert.equal(calls, 1);
  assert.equal(dialog.open, false);
  dialog.tab = 'daily';
  await context.rtOpen('batch', 0);
  assert.equal(dialog.tab, 'daily');
  assert.equal(dialog.open, true);
  assert.equal(body.inert, false);
  assert.equal(calls, 1);
});

test('common-month daily reads pin the adopted case, reconcile totals, and identify the side without records', async () => {
  const month = {month:1, days:31};
  const evidence = {kind:'execution', batch_id:'adopted', index:2, identity:'case', result_sha256:'result'};
  const inventory = {view_token:'token', registered_status:'passed', identity:'case', summary_sha256:'result',
    step_minutes:1, coverage:[{signal:'显热需求',frequency:'Daily'}]};
  const rows = Array.from({length:31}, (_,i) => ({date:'01-'+String(i+1).padStart(2,'0'),
    heating_kWh:0, cooling_kWh:2, total_kWh:2}));
  const site = {site_id:'city', left_step_minutes:1, right_step_minutes:1};
  for(const side of ['left','right']){
    Object.assign(site,{[side+'_heating_kWh']:0,[side+'_cooling_kWh']:62,[side+'_total_kWh']:62});
  }
  const context = vm.createContext({document:{addEventListener(){}, getElementById(){return null;}}, S:{}, resultViewContent(){}, raReport(){}, URLSearchParams});
  load(context,'recent-views.js');
  load(context,'result-timeline.js');
  load(context,'comparison-months.js');
  context.rtReadInventory = async(batch,index) => {
    assert.equal(index,2);
    return {summary:batch==='monthly'?{...inventory,coverage:[{signal:'显热需求',frequency:'Monthly'}]}:inventory};
  };
  let reads = 0;
  context.rtReadDetail = async(batch,index,token,kind,range) => {
    assert.equal(batch,'adopted');assert.equal(index,2);assert.equal(token,'token');assert.equal(kind,'daily');
    assert.deepEqual({...range},{system:'',scope:'building',start:'01-01',end:'01-31'});
    reads++;
    return {rows, sums:{heating_kWh:0,cooling_kWh:62,total_kWh:62}};
  };
  const d={sites:[{site_id:'city',left_evidence:evidence,right_evidence:{...evidence,batch_id:'monthly'}}]};
  const state={};
  await context.loadMonthDaily(d,month,site,state);
  assert.equal(reads,1);assert.equal(state.rows,null);assert.match(state.errors[0],/研究侧.*月度/);
  d.sites[0].right_evidence=evidence;
  await context.loadMonthDaily(d,month,site,state);
  assert.equal(state.rows.length,31);
  await assert.rejects(context.monthDailySide({...evidence,identity:'replaced'},month,site,'left'),/当前登记/);
  await assert.rejects(context.monthDailySide(evidence,month,{...site,left_cooling_kWh:61},'left'),/月度值不符/);
  rows[1]={...rows[0]};
  await assert.rejects(context.monthDailySide(evidence,month,site,'left'),/完整自然月/);
});

test('reuse of preview and export reads respects expiry and can retry a failure', async () => {
  const context = vm.createContext({});
  load(context, 'recent-views.js');
  const cache = vm.runInContext('new DialogReads(2)', context);
  let count = 0;
  const fetch = async () => ++count;
  const first = cache.read('version', fetch);
  assert.equal(cache.read('version', fetch), first);
  assert.equal(await first, 1);
  assert.equal(await cache.read('version', fetch), 1);
  assert.equal(await cache.read('version', fetch, () => false), 2);
  await assert.rejects(cache.read('retry', async () => {throw Error('unavailable');}));
  assert.equal(await cache.read('retry', fetch), 3);
});

test('room differences match room names across models and leave one-sided readings unpaired', () => {
  const context=vm.createContext({document:{addEventListener(){}},metricNames:{cooling:'制冷需求'},esc:String,format:v=>v.toFixed(2)});
  load(context,'recent-views.js');
  load(context,'comparison-months.js');
  const day=rooms=>({rooms:rooms.map(([room,cooling_kWh])=>({room,cooling_kWh})),
    totals:{cooling_kWh:rooms.reduce((sum,r)=>sum+r[1],0)}});
  const state={day:1,metric:'cooling',rows:[{date:'01-14'}],roomSides:[
    [day([['West',2],['East',4],['North',3]])],[day([['EAST',2],['west',3]])]]};
  const all=context.monthRoomTable(state);
  assert.match(all,/East<\/th><td>4.00<\/td><td>2.00<\/td><td>\+2.00/);
  assert.match(all,/North<\/th><td>3.00<\/td><td>—<\/td><td>—/);
  state.roomOrder='increase';
  const filtered=context.monthRoomTable(state);
  assert.match(filtered,/West<\/th><td>2.00<\/td><td>3.00<\/td><td>-1.00/);
  assert.doesNotMatch(filtered,/<th scope="row">East/);
  assert.match(filtered,/参考 9.00.+研究 5.00.+差值 \+4.00/);
});
