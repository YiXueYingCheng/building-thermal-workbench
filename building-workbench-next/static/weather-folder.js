/* Folder import checks one file at a time and records only explicitly reviewed selections. */
const wfLabels={waiting:'等待检查',checking:'正在检查',ready:'可登记',duplicate:'本文件夹内容重复',existing:'气象库已有相同内容',invalid:'需修复',failed:'处理失败',registered:'已登记'};
function wfState(){const m=S.weatherImport;return m.folder??={path:'',storage_mode:'copy',recursive:false,rows:[],notes:[],reviewed:false,stop:false};}
function wfEligible(row){return row.state==='ready';}
function wfProgress(){const f=wfState(),checked=f.rows.filter(r=>r.checked||['failed','invalid'].includes(r.state)).length;return '已检查 '+checked+' / '+f.rows.length+' 份；已勾选 '+f.rows.filter(r=>r.selected&&wfEligible(r)).length+' 份。';}
const beforeFolderRender=renderWeatherImport;

function wfMount(m,el){
 const f=m.folder;
 el.innerHTML=`<div class="room-tool-head"><h2 id="weather-import-title">文件夹批量导入 EPW</h2><button data-weather-action="close">关闭</button></div>
 <div class="actions weather-tabs"><button data-weather-action="open">单个文件导入</button><button data-weather-action="folder">文件夹批量导入</button><button data-weather-action="library">已导入气象</button><button data-weather-action="sources">本方案来源</button></div>
 <p>选择文件夹，逐份检查后勾选登记。相同内容只登记一次，气候类型可在单个文件导入中记录。</p>
 ${weatherStorageChoice(f.storage_mode,'data-wf-field="storage_mode"',false)}
 <label class="field">气象文件夹<input data-wf-field="path"></label><label class="check"><input type="checkbox" data-wf-field="recursive">包含子文件夹（跳过链接和快捷方式）</label>
 <div class="actions"><button data-wf="browse">浏览文件夹…</button><button data-wf="scan" class="primary">扫描并检查 EPW</button><button data-wf="continue">继续检查未完成项</button><button data-wf="stop">完成当前文件后停止</button></div>
 <p class="muted">检查只读取原文件。停止后可继续检查剩余文件。</p><div data-wf-notes></div><p role="status"></p>
 <div data-wf-results><div class="viewer-table"><table class="table"><thead><tr><th><label class="check"><input type="checkbox" data-wf-all>全选可登记项</label></th><th>文件／地点名称</th><th>状态与检查</th></tr></thead><tbody></tbody></table></div>
 <label class="check"><input type="checkbox" data-wf-field="reviewed">已核对勾选地点名称和质量说明；太阳时序及区域代表性另行评估</label><button data-wf="register" class="primary"></button></div>`;
 const view={body:el.querySelector('tbody'),status:el.querySelector('[role=status]'),all:el.querySelector('[data-wf-all]'),register:el.querySelector('[data-wf="register"]'),stop:el.querySelector('[data-wf="stop"]')};
 // The application-wide action stays busy until the batch settles. Stop belongs to this dialog.
 view.stop.onclick=event=>{
  event.stopPropagation();
  if(S.weatherImport!==m||!m.pending)return;
  f.stop=true;
  m.message='正在停止，等待当前文件完成…';
  view.stop.disabled=true;
  wfShowProgress(m);
 };
 view.body.addEventListener('toggle',event=>{
  const detail=event.target;
  if(!detail.matches('details[data-wf-report]'))return;
  const content=detail.lastElementChild;
  if(!detail.open){content.replaceChildren();return;}
  const row=f.rows[Number(detail.dataset.wfReport)];
  if(row?.checked&&!content.hasChildNodes())content.innerHTML=weatherQualityMarkup(row.checked.quality);
 },true);
 return view;
}

function wfShowProgress(m){
 m.folder.view.status.textContent=(m.message||'')+(m.folder.rows.length?' '+wfProgress():'');
}

function wfUpdateRow(m,index){
 const f=m.folder,r=f.rows[index],tr=f.view.body.rows[index];
 const [choice,place,inspection]=tr.cells;
 const enabled=wfEligible(r);
 choice.firstChild.checked=r.selected;
 choice.firstChild.disabled=m.pending||!enabled;
 if(tr.dataset.state!==r.state){
  place.lastElementChild.innerHTML=enabled?`<label class="field">地点名称<input data-wf-name="${index}" maxlength="100"></label>`:'<p></p>';
  inspection.firstChild.textContent=wfLabels[r.state]||r.state;
  inspection.children[1].textContent=r.message||'';
  inspection.children[1].hidden=!r.message;
  if(r.checked&&!inspection.querySelector('[data-wf-report]')){
   inspection.insertAdjacentHTML('beforeend',`<details data-wf-report="${index}"><summary>查看地点与完整逐时检查</summary><div></div></details>`);
  }
  tr.dataset.state=r.state;
 }
 const field=place.lastElementChild.firstElementChild;
 if(enabled){
  const input=field.querySelector('input');
  if(input.value!==r.name)input.value=r.name;
  input.disabled=m.pending;
 }else field.textContent=r.name||'';
}

renderWeatherImport=function(){
 const m=S.weatherImport;if(!m||m.mode!=='folder')return beforeFolderRender();
 const f=wfState(),el=weatherDialog();
 if(!f.view||!el.contains(f.view.body))f.view=wfMount(m,el);
 const v=f.view;
 if(v.rows!==f.rows){
  v.rows=f.rows;
  v.body.innerHTML=f.rows.map((r,i)=>`<tr><td><input type="checkbox" data-wf-select="${i}" aria-label="选择 ${esc(r.relative)}"></td><td><div>${esc(r.relative)}</div><div></div></td><td><span></span><p hidden></p></td></tr>`).join('');
  el.querySelector('[data-wf-notes]').innerHTML=f.notes.map(n=>'<p class="warning">'+esc(n)+'</p>').join('');
 }
 f.rows.forEach((_,i)=>wfUpdateRow(m,i));
 const ready=f.rows.filter(wfEligible),chosen=ready.filter(r=>r.selected);
 for(const b of el.querySelectorAll('.weather-tabs button,[data-wf="browse"],[data-wf="scan"],[data-wf-field]'))b.disabled=m.pending;
 el.querySelector('[data-weather-action="sources"]').disabled=m.pending||!S.record;
 el.querySelector('[data-wf-field="storage_mode"]').value=f.storage_mode;
 el.querySelector('[data-wf-field="path"]').value=f.path;
 el.querySelector('[data-wf-field="recursive"]').checked=f.recursive;
 el.querySelector('[data-wf-field="reviewed"]').checked=f.reviewed;
 el.querySelector('[data-wf-results]').hidden=!f.rows.length;
 el.querySelector('[data-wf="continue"]').hidden=m.pending||!f.rows.some(r=>r.state==='waiting');
 v.stop.hidden=!m.pending;v.stop.disabled=f.stop;
 v.all.disabled=m.pending||!ready.length;v.all.checked=!!ready.length&&chosen.length===ready.length;
 v.all.indeterminate=chosen.length>0&&chosen.length<ready.length;
 v.register.disabled=m.pending||!chosen.length;v.register.textContent='登记勾选的 '+chosen.length+' 份气象';
 wfShowProgress(m);
 if(!el.open)el.showModal();
};
async function wfInspect(m){
 const f=m.folder,seen=new Map();
 for(const r of f.rows)if(r.checked&&['ready','registered','existing'].includes(r.state))seen.set(r.checked.sha256,r.relative);
 for(const [index,r] of f.rows.entries()){
  if(f.stop||S.weatherImport!==m)break;if(r.state!=='waiting')continue;
  r.state='checking';m.message='正在逐份检查…';wfUpdateRow(m,index);wfShowProgress(m);
  try{
   const c=await api('/api/weather-import/inspect',{path:r.path});if(S.weatherImport!==m)return;
   r.checked=c;r.name=(c.quality.header?.city||r.name).slice(0,100);r.selected=false;
   if(!c.can_register){r.state='invalid';r.message='存在需修复项，请查看逐时检查。';}
   else if(seen.has(c.sha256)){r.state='duplicate';r.message='与 '+seen.get(c.sha256)+' 内容相同。';}
   else{r.state='ready';r.selected=true;seen.set(c.sha256,r.relative);}
  }catch(e){r.state='failed';r.message=e.message;}
  if(S.weatherImport!==m)return;
  wfUpdateRow(m,index);wfShowProgress(m);
 }
 if(S.weatherImport===m)m.message=f.stop?'检查已停止，可继续未完成项。':'检查结束，请核对地点和质量说明后勾选登记。';
}
const beforeFolderAction=configurationAction;
configurationAction=async function(button){
 const op=button.dataset.wf;if(!op)return beforeFolderAction(button);
 const m=S.weatherImport;if(!m||m.mode!=='folder')return true;const f=wfState();
 if(m.pending)return true;
 m.pending=true;f.stop=false;m.message='正在处理…';renderWeatherImport();
 try{
  if(op==='browse'){const r=await api('/api/weather-import/folder-browse',{path:f.path});if(S.weatherImport!==m)return true;if(r.path&&f.path!==r.path){f.path=r.path;f.rows=[];f.notes=[];f.reviewed=false;}m.message=r.cancelled?'已取消选择，原路径保留。':'';}
  if(op==='scan'){
   f.rows=[];f.notes=[];f.reviewed=false;
   const scan=await api('/api/weather-import/folder-scan',{path:f.path,recursive:f.recursive});if(S.weatherImport!==m)return true;
   f.path=scan.path;f.notes=scan.notes;f.rows=scan.files.map(r=>({...r,state:'waiting',selected:false}));
   renderWeatherImport();
   if(f.rows.length&&!f.stop)await wfInspect(m);else m.message=f.stop?'已停止，可继续检查。':'所选范围没有找到 EPW 文件。';
  }
  if(op==='continue'){f.reviewed=false;await wfInspect(m);}
  if(op==='register'){
   if(!f.reviewed)throw Error('请先核对勾选地点名称与质量说明，并勾选确认。');
   const selected=f.rows.filter(r=>r.selected&&wfEligible(r));
   if(!selected.length)throw Error('请勾选可登记项。');
   if(selected.some(r=>!r.name.trim()))throw Error('请填写每个勾选地点的名称。');
   let added=0,reused=0,failed=0;
   for(const r of selected){
    if(f.stop||S.weatherImport!==m)break;
    m.message='正在登记：'+r.name;wfShowProgress(m);
    try{
     const result=await api('/api/weather-import/folder-register',{path:r.checked.path,expected_sha256:r.checked.sha256,metadata:{storage_mode:f.storage_mode,name:r.name,reviewed:true}});
     r.state=result.reused?'existing':'registered';r.selected=false;r.message=result.reused?'已复用相同登记。':f.storage_mode==='reference'?'已登记原文件引用。':'已保存工作区副本。';result.reused?reused++:added++;
    }catch(e){r.state='failed';r.selected=false;r.message=e.message;failed++;}
    if(S.weatherImport===m){wfUpdateRow(m,f.rows.indexOf(r));wfShowProgress(m);}
   }
   // Refresh only the library so an existing, unsaved research draft remains intact.
   const boot=await api('/api/bootstrap');S.boot.sites=boot.sites;S.boot.workspace=boot.workspace;
   m.message=(f.stop?'已停止。':'登记结束。')+'新增 '+added+' 项，复用已有 '+reused+' 项，失败 '+failed+' 项。失败项可重新扫描核对；任何方案均未自动改变。';f.reviewed=false;
  }
 }catch(e){if(S.weatherImport===m)m.message=e.message;}
 finally{if(S.weatherImport===m){m.pending=false;renderWeatherImport();}}
 return true;
};
document.addEventListener('input',e=>{
 const m=S.weatherImport,t=e.target;if(!m||m.mode!=='folder'||m.pending)return;const f=wfState(),k=t.dataset.wfField;
 if(k){f[k]=t.type==='checkbox'?t.checked:t.value;if(k==='path'||k==='recursive'){f.rows=[];f.notes=[];f.reviewed=false;}if(k==='recursive')renderWeatherImport();}
 if(t.hasAttribute('data-wf-name')){f.rows[Number(t.dataset.wfName)].name=t.value;f.reviewed=false;}
});
document.addEventListener('change',e=>{
 const m=S.weatherImport,t=e.target;if(!m||m.mode!=='folder'||m.pending)return;const f=wfState();
 if(t.hasAttribute('data-wf-all')){for(const r of f.rows)if(wfEligible(r))r.selected=t.checked;f.reviewed=false;renderWeatherImport();}
 if(t.hasAttribute('data-wf-select')){const r=f.rows[Number(t.dataset.wfSelect)];if(wfEligible(r))r.selected=t.checked;f.reviewed=false;renderWeatherImport();}
 // Do not rerender text fields during IME composition. Sync confirmation after editing a name/path.
 if(t.hasAttribute('data-wf-name')||t.dataset.wfField==='path')renderWeatherImport();
});
