/* Library edits remain independent from the room draft and pinned scheme inputs. */
S.dailyManager=null;
const dailyKey=row=>row.snapshot.id+':'+row.snapshot.revision;
const dailyManagerButton=(target='')=>`<button data-daily-open="${esc(target)}">查找与管理日计划</button>`;
const beforeLibraryControls=scheduleControls;
scheduleControls=function(target,rule,binary=false){return beforeLibraryControls(target,rule,binary)+dailyManagerButton(target);};
function dailyRow(){return S.dailyManager?.rows.find(r=>dailyKey(r)===S.dailyManager.selected);}
function dailyManagerElement(){
 let el=document.getElementById('daily-manager');if(el)return el;
 el=document.createElement('dialog');el.id='daily-manager';el.setAttribute('aria-labelledby','daily-manager-title');
 el.addEventListener('cancel',event=>{event.preventDefault();requestDailyNavigation('close');});
 document.body.appendChild(el);return el;
}
function dailySelect(key){const m=S.dailyManager;m.selected=key;m.draft=null;m.dirty=false;m.pending=null;m.message='';}
function closeDailyManager(){const el=dailyManagerElement();el.close();el.innerHTML='';S.dailyManager=null;}
function requestDailyNavigation(action,key=null){
 const m=S.dailyManager;if(m.dirty){m.pending={action,key};m.message='日计划有未保存编辑，请继续编辑，或明确放弃。';renderDailyManager();return;}
 if(action==='close')closeDailyManager();else{dailySelect(key);renderDailyManager();}
}
function filteredDailyRows(){
 const m=S.dailyManager,q=m.query.trim().toLocaleLowerCase();
 return m.rows.filter(r=>r.is_latest&&(m.showHidden||!r.hidden)&&(m.origin==='all'||(m.origin==='local'?r.editable:!r.editable))
  &&(!m.binaryOnly||r.binary)&&(!q||[r.snapshot.name,r.origin,...r.aliases.map(a=>typeof a==='string'?a:a.name)].join(' ').toLocaleLowerCase().includes(q)));
}
function dailyListMarkup(){
 const rows=filteredDailyRows(),selected=dailyRow();
 return `<p class="muted">${rows.length} 份计划（每份显示最新版本）</p>${rows.map(r=>`<button class="daily-plan-item" data-daily-select="${esc(dailyKey(r))}" aria-pressed="${selected?.snapshot.id===r.snapshot.id}"><strong>${esc(r.snapshot.name)}</strong><small>v${r.snapshot.revision} · ${esc(r.origin)}${r.hidden?' · 已停用':''}${r.binary?' · 0/1':''}</small></button>`).join('')||'<p class="muted">没有符合条件的计划；可调整搜索或勾选已停用。</p>'}`;
}
function dailyPreviewMarkup(values){
 if(values.some(v=>!Number.isFinite(v)||v<0||v>1))return '<p class="warning">请填满 24 个 0–1 比例。</p>';
 const x=h=>34+h*22,y=v=>132-v*102;
 const path=values.map((v,h)=>(h?'L':'M')+x(h)+' '+y(v)+' L'+x(h+1)+' '+y(v)).join(' ');
 return `<svg viewBox="0 0 600 165" class="schedule-chart" role="img" aria-label="日计划比例曲线"><path d="M34 24 V132 H562" fill="none" stroke="#bacac2"/><path d="${path}" fill="none" stroke="#315b4b" stroke-width="2.5"/><text x="12" y="30">1</text><text x="12" y="136">0</text>${[0,4,8,12,16,20,24].map(h=>`<text x="${x(h)}" y="154" text-anchor="middle">${h}</text>`).join('')}</svg>`;
}
function dailyChangesMarkup(){
 const m=S.dailyManager,r=dailyRow(),d=m.draft;if(!d||!r)return '';
 const changes=d.content.values.flatMap((v,h)=>v!==r.snapshot.content.values[h]?[{h,before:r.snapshot.content.values[h],after:v}]:[]);
 return `<p>${changes.length} 个小时的比例改变${d.name!==r.snapshot.name?'；名称改变':''}${d.content.notes!==r.snapshot.content.notes?'；说明改变':''}。保存后不会修改任何房间或已保存方案。</p>${changes.length?`<div class="table-scroll"><table class="table"><thead><tr><th>时段</th><th>原值</th><th>新值</th></tr></thead><tbody>${changes.map(c=>`<tr><td>${c.h}:00–${c.h+1}:00</td><td>${c.before}</td><td>${Number.isFinite(c.after)?c.after:'待填写'}</td></tr>`).join('')}</tbody></table></div>`:''}`;
}
function dailyDetailMarkup(){
 const m=S.dailyManager,r=dailyRow();if(!r)return '<p class="muted">选择一份日计划查看曲线和版本。</p>';
 const s=r.snapshot,d=m.draft,c=d?.content||s.content,versions=m.rows.filter(x=>x.snapshot.id===s.id).sort((a,b)=>b.snapshot.revision-a.snapshot.revision);
 return `<div class="row"><h3>${esc(s.name)}</h3><span class="tag">${r.hidden?'已停用':r.is_latest?'最新版本':'历史版本'}</span></div>
 <p class="muted">${esc(r.origin)} · ${esc(s.created)}。${r.editable?'可追加版本，旧版本保留。':'导入内容只读，可复制后编辑。'}</p>
 <label class="field">查看版本<select data-daily-version>${versions.map(x=>`<option value="${esc(dailyKey(x))}"${dailyKey(x)===m.selected?' selected':''}>版本 ${x.snapshot.revision}${x.is_latest?' · 最新':''} · ${esc(x.snapshot.name)}</option>`).join('')}</select></label>
 ${r.aliases.length?`<p class="muted">来源名称：${r.aliases.map(a=>esc(typeof a==='string'?a:a.name)).join('、')}</p>`:''}
 <div id="daily-manager-chart">${dailyPreviewMarkup(c.values)}</div>
 ${d?`<label class="field">计划名称<input data-daily-name maxlength="100" value="${esc(d.name)}"></label><label class="field">说明<textarea data-daily-notes maxlength="1000">${esc(c.notes)}</textarea></label><div class="daily-edit-fill"><label>起始<select data-daily-start>${Array.from({length:24},(_,h)=>`<option value="${h}">${h}:00</option>`).join('')}</select></label><label>结束<select data-daily-end>${Array.from({length:24},(_,h)=>`<option value="${h+1}"${h===23?' selected':''}>${h+1}:00</option>`).join('')}</select></label><label>比例<input data-daily-fill type="number" min="0" max="1" step="any" value="1"></label><button data-daily-action="fill">填写时段</button></div>`:`<p class="muted">${esc(c.notes||'未填写说明')}</p>`}
 <div class="daily-values">${c.values.map((v,h)=>`<label>${h}:00–${h+1}:00${d?`<input data-daily-hour="${h}" type="number" min="0" max="1" step="any" value="${esc(v??'')}">`:`<strong>${format(v,3)}</strong>`}</label>`).join('')}</div>
 ${d?`<details class="daily-changes" open><summary>保存前核对</summary><div id="daily-manager-changes">${dailyChangesMarkup()}</div></details><div class="actions"><button data-daily-action="save" class="primary">${d.mode==='update'?'保存为此计划的新版本':'保存为本工作区计划'}</button>${d.mode==='update'?'<button data-daily-action="save-copy">将编辑另存为新日计划</button>':''}<button data-daily-action="discard">撤销日计划编辑</button></div>`:`<div class="actions"><button data-daily-action="copy"${disabled()}>复制后编辑</button>${r.editable&&r.is_latest?`<button data-daily-action="edit"${disabled()}>编辑并追加版本</button>`:''}<button data-daily-action="visibility"${disabled()}>${r.hidden?'恢复选用':'停用这份计划'}</button></div><p class="muted">停用仅从本工作区的默认选项中隐藏整份计划；既有引用及历史版本继续有效，原来源文件保持不变。</p>`}
 ${m.target?`<div class="daily-use"><label>用于当前${m.target.startsWith('operation:')?'工况覆盖':'房间计划'}的<select data-daily-use-day><option value="weekday"${m.day==='weekday'?' selected':''}>工作日</option><option value="weekend"${m.day==='weekend'?' selected':''}>周末</option></select></label><button data-daily-action="apply" class="primary"${readonly()||d||r.hidden||(m.binaryOnly&&!r.binary)?' disabled':''}>选用当前预览版本</button>${m.binaryOnly&&!r.binary?'<p class="warning">空调可用只能选择 0/1 计划。</p>':''}${r.hidden?'<p class="muted">如需重新选用，请先恢复。</p>':''}</div>`:''}`;
}
function renderDailyManager(){
 const m=S.dailyManager,el=dailyManagerElement();if(!m)return;
 el.innerHTML=`<div class="daily-manager-head"><div><h2 id="daily-manager-title">日计划库</h2><p class="muted">查找、预览和管理比例计划；保存计划后，仍需明确选入房间配置。</p></div><button data-daily-action="close" aria-label="关闭日计划库">关闭</button></div>
 <div class="daily-manager-message" role="status">${esc(m.message||'')}${m.pending?`<div class="actions"><button data-daily-action="continue">继续编辑</button><button data-daily-action="abandon">放弃编辑并${m.pending.action==='close'?'关闭':'切换'}</button></div>`:''}</div>
 <div class="daily-manager-grid"><aside><label class="field">查找名称或别名<input data-daily-search value="${esc(m.query)}" placeholder="例如：办公室"></label><label class="field">来源<select data-daily-origin><option value="all"${m.origin==='all'?' selected':''}>全部来源</option><option value="imported"${m.origin==='imported'?' selected':''}>导入日计划</option><option value="local"${m.origin==='local'?' selected':''}>本工作区</option></select></label><label class="check"><input type="checkbox" data-daily-hidden${m.showHidden?' checked':''}> 包含已停用</label><div id="daily-manager-list">${dailyListMarkup()}</div><button data-daily-action="refresh">刷新日计划库</button></aside><section id="daily-manager-detail">${dailyDetailMarkup()}</section></div>`;
 if(!el.open)el.showModal();
}
async function refreshDailyCatalog(){
 const rows=await api('/api/daily-library');S.dailyProfiles=rows.filter(r=>r.is_latest&&!r.hidden);if(S.dailyManager)S.dailyManager.rows=rows;
}
async function openDailyManager(button){
 const target=button.dataset.dailyOpen,box=button.closest('.schedule-controls'),rule=target?scheduleTarget(target):null;
 const usable=rule&&(target.startsWith('operation:')||selectedUsage().channel==='available'||rule.kind==='scaled');
 S.dailyManager={rows:[],selected:null,query:'',origin:'all',showHidden:false,draft:null,dirty:false,pending:null,message:'',
  target:usable?target:null,binaryOnly:!!rule&&(target.startsWith('operation:')||selectedUsage().channel==='available'),day:box?.querySelector('[data-profile-day]')?.value||'weekday'};
 try{await refreshDailyCatalog();const ref=rule?.references?.[S.dailyManager.day];S.dailyManager.selected=ref?ref.id+':'+ref.revision:null;
  if(!dailyRow())S.dailyManager.selected=filteredDailyRows()[0]?dailyKey(filteredDailyRows()[0]):null;renderDailyManager();
 }catch(e){S.dailyManager=null;throw e;}
}
const beforeDailyLibraryAction=configurationAction;
configurationAction=async function(button){
 if(button.hasAttribute('data-daily-open')){await openDailyManager(button);return true;}
 if(button.dataset.dailySelect){requestDailyNavigation('select',button.dataset.dailySelect);return true;}
 const action=button.dataset.dailyAction;if(!action)return beforeDailyLibraryAction(button);
 const m=S.dailyManager,r=dailyRow();
 try{
  if(action==='close'){requestDailyNavigation('close');return true;}
  if(action==='continue'){m.pending=null;m.message='';}
  else if(action==='abandon'){const p=m.pending;m.dirty=false;requestDailyNavigation(p.action,p.key);return true;}
  else if(action==='refresh'){await refreshDailyCatalog();m.message='日计划库已刷新；当前房间和日计划编辑保留。';}
  else if(action==='discard'){m.draft=null;m.dirty=false;m.pending=null;m.message='日计划编辑已撤销。';}
  else{
   if(readonly())throw Error('来源或旧方案只读，请从可编辑研究方案管理日计划。');
   if(action==='copy'||action==='edit'){
    if(action==='edit'&&(!r.editable||!r.is_latest))throw Error('请选择本工作区的最新版本；导入内容可复制后编辑。');
    m.draft={mode:action==='edit'?'update':'copy',name:r.snapshot.name+(action==='copy'?' · 副本':''),content:copy(r.snapshot.content),base:copy(r.snapshot)};m.dirty=action==='copy';m.message='';
   }else if(action==='fill'){
    const el=dailyManagerElement(),start=Number(el.querySelector('[data-daily-start]').value),end=Number(el.querySelector('[data-daily-end]').value),raw=el.querySelector('[data-daily-fill]').value,value=raw===''?NaN:Number(raw);
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>24||end<=start||!Number.isFinite(value)||value<0||value>1)throw Error('请填写有效的先后时段和 0–1 比例；跨午夜分两段填写。');
    m.draft.content.values.fill(value,start,end);m.dirty=true;
   }else if(action==='save'||action==='save-copy'){
    const d=m.draft,body={name:d.name,content:d.content};
    if(action==='save-copy'&&d.name===d.base.name)body.name+=' · 副本';
    body[d.mode==='update'&&action!=='save-copy'?'parent':'copied_from']={id:d.base.id,revision:d.base.revision,sha256:d.base.sha256};
    const result=await api('/api/daily-profiles',body);await refreshDailyCatalog();dailySelect(result.profile.id+':'+result.profile.revision);
    m.message=(result.reused?'相同曲线已存在，已复用：':'日计划版本已保存：')+result.profile.name+' · v'+result.profile.revision+'。房间配置与已有方案未改变。'+(result.hidden?'该计划仍为停用状态，可明确恢复。':'');
   }else if(action==='visibility'){
    await api('/api/daily-library/visibility',{id:r.snapshot.id,hidden:!r.hidden,expected_revision:r.state_revision});await refreshDailyCatalog();m.message=r.hidden?'已恢复选用；已有引用保持原版本。':'已停用；已有配置和历史结果仍可使用原快照。';
   }else if(action==='apply'){
    if(m.draft||r.hidden||!m.target||(m.binaryOnly&&!r.binary))throw Error('请先完成编辑并选用符合当前用途的启用计划。');
    const rule=scheduleTarget(m.target);rule[m.day]=copy(r.snapshot.content.values);rule.references={...rule.references,[m.day]:copy(r.snapshot)};
    if(m.target==='usage')S.usageDraft.schema_version=2;scheduleTargetChanged(m.target);const isOperation=m.target.startsWith('operation:');closeDailyManager();notice(isOperation?'已选用到本方案的运行覆盖；请保存方案版本。':'已选用指定日计划版本；请保存建筑配置和方案版本。');return true;
   }
  }
  renderDailyManager();
 }catch(error){m.message=error.message;renderDailyManager();}
 return true;
};
document.addEventListener('input',event=>{
 const t=event.target,m=S.dailyManager;if(!m||!t.closest('#daily-manager'))return;
 if(t.hasAttribute('data-daily-search')){m.query=t.value;document.getElementById('daily-manager-list').innerHTML=dailyListMarkup();return;}
 if(!m.draft||readonly())return;
 if(t.hasAttribute('data-daily-name'))m.draft.name=t.value;
 else if(t.hasAttribute('data-daily-notes'))m.draft.content.notes=t.value;
 else if(t.hasAttribute('data-daily-hour'))m.draft.content.values[Number(t.dataset.dailyHour)]=t.value===''?null:Number(t.value);else return;
 m.dirty=true;document.getElementById('daily-manager-chart').innerHTML=dailyPreviewMarkup(m.draft.content.values);document.getElementById('daily-manager-changes').innerHTML=dailyChangesMarkup();
});
document.addEventListener('change',event=>{
 const t=event.target,m=S.dailyManager;if(!m||!t.closest('#daily-manager'))return;
 if(t.hasAttribute('data-daily-origin'))m.origin=t.value;
 else if(t.hasAttribute('data-daily-hidden'))m.showHidden=t.checked;
 else if(t.hasAttribute('data-daily-version')){requestDailyNavigation('select',t.value);return;}
 else if(t.hasAttribute('data-daily-use-day')){m.day=t.value;return;}else return;
 document.getElementById('daily-manager-list').innerHTML=dailyListMarkup();
});
window.addEventListener('beforeunload',event=>{if(S.dailyManager?.dirty){event.preventDefault();event.returnValue='';}});
