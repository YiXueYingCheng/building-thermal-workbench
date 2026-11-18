/* Folder import checks one file at a time and records only explicitly reviewed selections. */
const wfLabels={waiting:'等待检查',checking:'正在检查',ready:'可登记',duplicate:'本文件夹内容重复',existing:'气象库已有相同内容',invalid:'需修复',failed:'处理失败',registered:'已登记'};
function wfState(){const m=S.weatherImport;return m.folder??={path:'',recursive:false,rows:[],notes:[],reviewed:false,stop:false};}
function wfEligible(row){return row.state==='ready';}
function wfProgress(){const f=wfState(),checked=f.rows.filter(r=>r.checked||['failed','invalid'].includes(r.state)).length;return '已检查 '+checked+' / '+f.rows.length+' 份；已勾选 '+f.rows.filter(r=>r.selected&&wfEligible(r)).length+' 份。';}
const beforeFolderRender=renderWeatherImport;
renderWeatherImport=function(){
 const m=S.weatherImport;if(!m||m.mode!=='folder')return beforeFolderRender();
 const f=wfState(),el=weatherDialog(),busy=m.pending,ready=f.rows.filter(wfEligible),chosen=ready.filter(r=>r.selected);
 el.innerHTML=`<div class="room-tool-head"><h2 id="weather-import-title">文件夹批量导入 EPW</h2><button data-weather-action="close">关闭</button></div><div class="actions weather-tabs"><button data-weather-action="open"${busy?' disabled':''}>单个文件导入</button><button data-weather-action="folder"${busy?' disabled':''}>文件夹批量导入</button><button data-weather-action="sources"${busy||!S.record?' disabled':''}>本方案来源</button></div><p>选择文件夹，逐份检查后勾选登记。相同内容只登记一次，已有来源和方案保持；气候类型暂不分类，可在单个文件导入中记录分类依据。</p><label class="field">气象文件夹<input data-wf-field="path" value="${esc(f.path)}"${busy?' disabled':''}></label><label class="check"><input type="checkbox" data-wf-field="recursive"${f.recursive?' checked':''}${busy?' disabled':''}>包含子文件夹（跳过链接和快捷方式）</label><div class="actions"><button data-wf="browse"${busy?' disabled':''}>浏览文件夹…</button><button data-wf="scan" class="primary"${busy?' disabled':''}>扫描并检查 EPW</button>${f.rows.some(r=>r.state==='waiting')&&!busy?'<button data-wf="continue">继续检查未完成项</button>':''}${busy?'<button data-wf="stop">完成当前文件后停止</button>':''}</div><p class="muted">检查只读取原文件。登记会保存独立副本；关闭窗口停止后续文件，当前已提交的一份会处理完成，已登记项保留。</p>${f.notes.map(n=>'<p class="warning">'+esc(n)+'</p>').join('')}<p role="status">${esc(m.message||'')}${f.rows.length?' '+wfProgress():''}</p>${f.rows.length?`<div class="viewer-table"><table class="table"><thead><tr><th><label class="check"><input type="checkbox" data-wf-all${ready.length&&chosen.length===ready.length?' checked':''}${busy||!ready.length?' disabled':''}>全选可登记项</label></th><th>文件／地点名称</th><th>状态与检查</th></tr></thead><tbody>${f.rows.map((r,i)=>`<tr><td><input type="checkbox" data-wf-select="${i}" aria-label="选择 ${esc(r.relative)}"${r.selected?' checked':''}${busy||!wfEligible(r)?' disabled':''}></td><td><div>${esc(r.relative)}</div>${wfEligible(r)?`<label class="field">地点名称<input data-wf-name="${i}" maxlength="100" value="${esc(r.name)}"${busy?' disabled':''}></label>`:`<p>${esc(r.name||'')}</p>`}</td><td>${esc(wfLabels[r.state]||r.state)}${r.message?'<p>'+esc(r.message)+'</p>':''}${r.checked?`<details><summary>查看地点与完整逐时检查</summary>${weatherQualityMarkup(r.checked.quality)}</details>`:''}</td></tr>`).join('')}</tbody></table></div><label class="check"><input type="checkbox" data-wf-field="reviewed"${f.reviewed?' checked':''}${busy?' disabled':''}>已核对勾选地点名称和质量说明；太阳时序及区域代表性另行评估</label><button data-wf="register" class="primary"${busy||!chosen.length?' disabled':''}>登记勾选的 ${chosen.length} 份气象</button>`:''}`;
 const all=el.querySelector('[data-wf-all]');if(all)all.indeterminate=chosen.length>0&&chosen.length<ready.length;
 if(!el.open)el.showModal();
};
async function wfInspect(m){
 const f=m.folder,seen=new Map();
 for(const r of f.rows)if(r.checked&&['ready','registered','existing'].includes(r.state))seen.set(r.checked.sha256,r.relative);
 for(const r of f.rows){
  if(f.stop||S.weatherImport!==m)break;if(r.state!=='waiting')continue;
  r.state='checking';m.message='正在逐份检查…';renderWeatherImport();
  try{
   const c=await api('/api/weather-import/inspect',{path:r.path});if(S.weatherImport!==m)return;
   r.checked=c;r.name=(c.quality.header?.city||r.name).slice(0,100);r.selected=false;
   if(!c.can_register){r.state='invalid';r.message='存在需修复项，请查看逐时检查。';}
   else if(seen.has(c.sha256)){r.state='duplicate';r.message='与 '+seen.get(c.sha256)+' 内容相同。';}
   else{r.state='ready';r.selected=true;seen.set(c.sha256,r.relative);}
  }catch(e){r.state='failed';r.message=e.message;}
  if(S.weatherImport===m)renderWeatherImport();
 }
 if(S.weatherImport===m)m.message=f.stop?'检查已停止，可继续未完成项。':'检查结束，请核对地点和质量说明后勾选登记。';
}
const beforeFolderAction=configurationAction;
configurationAction=async function(button){
 const op=button.dataset.wf;if(!op)return beforeFolderAction(button);
 const m=S.weatherImport;if(!m||m.mode!=='folder')return true;const f=wfState();
 if(op==='stop'){f.stop=true;m.message='完成当前文件后停止；已完成项保留。';renderWeatherImport();return true;}
 if(m.pending)return true;
 m.pending=true;f.stop=false;m.message='正在处理…';renderWeatherImport();
 try{
  if(op==='browse'){const r=await api('/api/weather-import/folder-browse',{path:f.path});if(S.weatherImport!==m)return true;if(r.path&&f.path!==r.path){f.path=r.path;f.rows=[];f.notes=[];f.reviewed=false;}m.message=r.cancelled?'已取消选择，原路径保留。':'';}
  if(op==='scan'){
   f.rows=[];f.notes=[];f.reviewed=false;
   const scan=await api('/api/weather-import/folder-scan',{path:f.path,recursive:f.recursive});if(S.weatherImport!==m)return true;
   f.path=scan.path;f.notes=scan.notes;f.rows=scan.files.map(r=>({...r,state:'waiting',selected:false}));
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
    m.message='正在登记：'+r.name;renderWeatherImport();
    try{
     const result=await api('/api/weather-import/folder-register',{path:r.checked.path,expected_sha256:r.checked.sha256,metadata:{name:r.name,reviewed:true}});
     r.state=result.reused?'existing':'registered';r.selected=false;r.message=result.reused?'复用已有相同内容，未新增副本。':'已保存工作区独立副本。';result.reused?reused++:added++;
    }catch(e){r.state='failed';r.selected=false;r.message=e.message;failed++;}
   }
   // Refresh only the library so an existing, unsaved research draft remains intact.
   const boot=await api('/api/bootstrap');S.boot.sites=boot.sites;
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
