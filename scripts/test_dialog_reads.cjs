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
