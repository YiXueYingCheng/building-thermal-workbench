/* Imports change the weather library; adoption only changes the current draft. */
S.weatherImport=null;
const beforeWeatherSidebar=sidebar;
sidebar=function(){return beforeWeatherSidebar().replace(/(<button\b[^>]*data-import-action="open"[^>]*>[\s\S]*?<\/button>)/,'$1<button data-weather-action="open">气象导入与来源更新</button>');};
scopeSites=function(){const own=S.boot.ordinary_weather_sites?.[S.record.factors.building.id];return Object.values(S.boot.sites).filter(s=>['reviewed_global','imported_epw_v1'].includes(s.source_kind)||(S.record.provenance.adapter==='ordinary_building_v1'&&s.id===own));};
const beforeWeatherScope=scopePanel;
scopePanel=function(){let html=beforeWeatherScope();
 return html.replace('<h2>地点与时段</h2>','<div class="row"><h2>地点与时段</h2><div class="actions"><button data-weather-action="open">导入 EPW 气象</button><button data-weather-action="sources">核对本方案来源</button></div></div>').replaceAll('· null','· 未分类').replace('沿用气候类型分组、类内代表点等权。可用气象与区域代表性分别记录。','导入地点可暂不分类；未分类地点保留地点结果，不进入气候分组。指定类型需记录依据，不自动代表整个气候区。');
};
function weatherContext(){if(!S.record)return 'empty-workspace';return JSON.stringify({id:S.id,revision:S.record.revision,changes:changes()});}
function weatherDialog(){let el=document.getElementById('weather-import-dialog');if(el)return el;el=document.createElement('dialog');el.id='weather-import-dialog';el.setAttribute('aria-labelledby','weather-import-title');document.body.append(el);el.addEventListener('cancel',e=>{e.preventDefault();closeWeatherImport();});el.addEventListener('click',e=>{if(e.target.closest('[data-weather-action="close"]')){e.stopPropagation();closeWeatherImport();}});return el;}
function closeWeatherImport(){weatherDialog().close();weatherDialog().innerHTML='';S.weatherImport=null;}
function weatherOptions(sites,selected,empty){return (empty?`<option value="">${esc(empty)}</option>`:'')+sites.map(s=>`<option value="${esc(s.id)}"${s.id===selected?' selected':''}>${esc(s.name)} · ${esc(s.climate||'未分类')}${s.source_kind==='imported_epw_v1'?' · 导入':''}</option>`).join('');}
function renderWeatherImport(){const m=S.weatherImport;if(!m)return;const el=weatherDialog(),sites=Object.values(S.boot.sites),current=(S.record?.factors.scope.site_ids||[]).map(i=>S.boot.sites[i]);let html='';
 if(m.mode==='import'){
  const c=m.checked,h=c?.quality.header;
  html=`<p>选择本机 EPW，检查后登记独立副本。也可将它登记为某个已有来源的更新，再在方案中显式选用。</p><label class="field">EPW 完整路径<input data-weather-field="path" value="${esc(m.path)}" placeholder="C:/气象/站点.epw"${m.pending?' disabled':''}></label><div class="actions"><button data-weather-action="browse"${m.pending?' disabled':''}>浏览文件…</button><button data-weather-action="inspect" class="primary"${m.pending?' disabled':''}>检查气象</button><button data-weather-action="clear"${m.pending?' disabled':''}>撤销本次检查</button></div>`;
  if(c){html+=`<section class="well"><h3>${esc(h?.city||'未识别地点')} · ${c.can_register?'检查完成':'需先修复'}</h3><p>${esc(h?.country||'')} · 站号 ${esc(h?.station||'')} · 纬度 ${esc(h?.latitude||'')} / 经度 ${esc(h?.longitude||'')} · UTC ${esc(h?.timezone||'')}</p><p>数据来源：${esc(h?.source||'')}；文件 ${(c.bytes/1024/1024).toFixed(2)} MiB。</p><details><summary>查看完整逐时检查</summary>${weatherQualityMarkup(c.quality)}</details></section>`;
   if(c.can_register){html+=`<label class="field">地点显示名称<input data-weather-field="name" maxlength="100" value="${esc(m.name)}"></label><label class="field">登记用途<select data-weather-field="supersedes">${weatherOptions(sites.filter(s=>s.weather),m.supersedes,'新增地点（保留已有来源）')}</select></label><div class="grid2"><label class="field">气候类型<select data-weather-field="climate"><option value="">暂不分类</option>${(S.boot.climate_classes||[]).map(c=>`<option value="${c.climate}"${c.climate===m.climate?' selected':''}>${c.climate} · ${esc(c.name)}</option>`).join('')}</select></label><label class="field">分类依据（选类型时必填）<input data-weather-field="climate_basis" maxlength="500" value="${esc(m.climate_basis)}" placeholder="数据集、版本或人工核对依据"></label></div><label class="field">来源与使用说明<textarea data-weather-field="note" maxlength="1000" rows="2">${esc(m.note)}</textarea></label><label class="check"><input type="checkbox" data-weather-field="reviewed"${m.reviewed?' checked':''}>已核对地点和数据说明；太阳时序及区域代表性另行评估</label><div class="actions"><button data-weather-action="register" class="primary"${m.pending?' disabled':''}>登记独立副本</button></div><p class="muted">登记后加入范围选择；尚不改变任何方案。气候归类是明确记录的人工判断，检查通过不表示已验收模拟结果。</p>`;}
  }
 }else{
  const choices=sites.filter(s=>s.supersedes===m.old);
  html=`<p>当前方案：${esc(S.record.name)} · v${S.record.revision}${S.dirty?'（包含当前未保存编辑）':''}</p><button data-weather-action="audit"${m.pending?' disabled':''}>核对引用文件与可用更新</button>`;
  if(m.audit){const a=m.audit,bad=a.files.filter(f=>f.status!=='matches');html+=`<section class="well source-audit"><h3>${a.passed?'引用文件身份一致':'有来源需要处理'}</h3><p>核对 ${a.files.length} 个文件；${bad.length} 个异常；${a.updates.length} 个已登记的气象更新。</p><p>${esc(a.note)}</p><button data-weather-action="audit-download">下载本次核对记录</button>${(a.external_files||[]).filter(f=>f.status!=='matches').map(f=>`<p>导入时原文件：${weatherStatuses[f.status]} · ${esc(f.name)}。计算仍使用独立副本。<small class="source-path">${esc(f.path)}</small></p>`).join('')}${bad.map(f=>`<p class="warning">${esc(f.roles.join('、'))} · ${weatherStatuses[f.status]}<small class="source-path">${esc(f.path)}</small>${f.status==='missing'&&!f.relocation&&!f.roles.includes('计算引擎')?`<button data-source-recovery="choose" data-recovery-path="${esc(f.path)}">查找原文件副本…</button>`:''}${typeof sourceLocationButton==='function'?sourceLocationButton(f):''}</p>`).join('')}<details><summary>逐文件身份记录</summary>${a.files.map(f=>`<p>${esc(f.roles.join('、'))} · ${weatherStatuses[f.status]}<small class="source-path">${esc(f.path)}</small><small class="source-path">${esc(f.expected_sha256)} → ${esc(f.actual_sha256||'未取得')}</small>${f.actual_path?`<small class="source-path">当前读取：${esc(f.actual_path)}</small>`:''}${typeof sourceLocationButton==='function'?sourceLocationButton(f):''}</p>`).join('')}</details></section>`;}
  if(typeof sourceLocationsMarkup==='function')html+=sourceLocationsMarkup(m);
  if(typeof sourceRecoveryMarkup==='function')html+=sourceRecoveryMarkup(m);
  if(typeof componentUpdatesMarkup==='function')html+=componentUpdatesMarkup(m);
  html+=`<section class="source-update-section" aria-label="气象来源更新"><h3>显式采用气象更新</h3><div class="grid2"><label class="field">原地点<select data-weather-field="old">${weatherOptions(current,m.old)}</select></label><label class="field">已登记的更新<select data-weather-field="next">${weatherOptions(choices,m.next,'请选择更新')}</select></label></div><div class="actions"><button data-weather-action="preview"${!choices.length||m.pending?' disabled':''}>预览替换影响</button><button data-weather-action="import-update">为所选地点导入更新</button></div>`;
  if(!choices.length)html+='<p class="muted">尚无此来源的更新登记。导入 EPW 时选择对应原地点，原文件和历史版本会保留。</p>';
  html+='</section>';
  if(m.preview){const p=m.preview;html+=`<section class="well"><h3>来源变化</h3><div class="grid2">${[['原来源',p.before],['新来源',p.after]].map(([label,s])=>`<div><strong>${label} · ${esc(s.name)}</strong><p>${esc(s.climate||'未分类')} · ${esc(s.latitude)}, ${esc(s.longitude)}</p>${s.timezone!=null?`<p>UTC ${esc(s.timezone)} · 海拔 ${esc(s.elevation)} m</p>`:''}<small class="source-path">${esc(s.weather.sha256)}</small></div>`).join('')}</div><p>同时更新气象与模型地点；沿用本建筑 Kiva 基础、土壤及方案作息。气象身份改变，原结果不作为新结果复用。</p><p>${esc(p.note)}</p><button data-weather-action="apply" class="primary"${readonly()?' disabled':''}>应用到当前编辑</button>${readonly()?'<p class="muted">来源与历史版本只读，请先另存为研究方案。</p>':''}</section>`;}
 }
 el.innerHTML=`<div class="room-tool-head"><h2 id="weather-import-title">${m.mode==='import'?'导入 EPW 气象':'本方案来源与显式更新'}</h2><button data-weather-action="close">关闭</button></div><div class="actions weather-tabs"><button data-weather-action="open"${m.pending?' disabled':''}>单个文件导入</button><button data-weather-action="folder"${m.pending?' disabled':''}>文件夹批量导入</button><button data-weather-action="sources"${m.pending||!S.record?' disabled':''}>本方案来源</button></div>${html}<p role="status" class="weather-message">${esc(m.message||'')}</p>`;if(m.pending)el.querySelectorAll('input,select,textarea,button:not([data-weather-action="close"])').forEach(e=>e.disabled=true);if(!el.open)el.showModal();
}
function openWeatherImport(mode='import',supersedes=''){const old=S.record?.factors.scope.site_ids[0]||'';S.weatherImport={mode,path:'',checked:null,name:'',climate:'',climate_basis:'',note:'',reviewed:false,supersedes,old,next:'',pending:false,message:'',context:weatherContext()};renderWeatherImport();}
const beforeWeatherAction=configurationAction;
configurationAction=async function(button){const action=button.dataset.weatherAction;if(!action)return beforeWeatherAction(button);
 if(action==='close'){closeWeatherImport();return true;}
 if(action==='open'||action==='sources'||action==='folder'){openWeatherImport(action==='open'?'import':action);return true;}
 const m=S.weatherImport;if(!m||m.pending)return true;
 if(action==='import-update'){openWeatherImport('import',m.old);return true;}
 if(action==='audit-download'&&m.audit){const url=URL.createObjectURL(new Blob([JSON.stringify(m.audit,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='source-audit-'+S.id+'-v'+S.record.revision+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return true;}
 if(action==='clear'){m.checked=null;m.reviewed=false;m.message='本次检查已撤销，没有写入气象库。';renderWeatherImport();return true;}
 m.pending=true;m.message='正在处理…';renderWeatherImport();
 try{
  if(action==='browse'){const r=await api('/api/weather-import/browse',{path:m.path});if(S.weatherImport!==m)return true;if(r.path&&r.path!==m.path){m.path=r.path;m.checked=null;m.reviewed=false;}m.message=r.cancelled?'已取消选文件，原路径保留。':'';}
  if(action==='inspect'){m.checked=null;m.reviewed=false;const r=await api('/api/weather-import/inspect',{path:m.path});if(S.weatherImport!==m)return true;m.checked=r;m.name=r.quality.header?.city||'';m.message=r.can_register?'检查完成，请核对并登记。':'存在需修复项，暂不能登记。';}
  if(action==='register'){
   if(!m.checked||!m.reviewed)throw Error('请先检查气象，并确认地点与数据说明。');
   const r=await api('/api/weather-import/register',{path:m.checked.path,expected_sha256:m.checked.sha256,metadata:{name:m.name,climate:m.climate,climate_basis:m.climate_basis,note:m.note,supersedes:m.supersedes,reviewed:m.reviewed}});
   await bootstrap();if(S.weatherImport!==m)return true;m.checked=null;m.reviewed=false;m.message=(r.reused?'已找到相同登记，复用原副本。':'已登记独立副本。')+(S.record?' 当前方案未改变；可关闭后在范围中选择，或进入本方案来源预览更新。':' 可关闭后继续导入建筑，并选择此气象。');
  }
  if(action==='audit'){m.audit=null;const r=await api('/api/source-updates/audit',{id:S.id,revision:S.record.revision,changes:changes()});if(S.weatherImport!==m)return true;m.audit=r;m.message='核对完成，没有修改文件或方案。';}
  if(action==='preview'){m.preview=null;m.context=weatherContext();const key=JSON.stringify([m.old,m.next]);const r=await api('/api/source-updates/preview',{id:S.id,revision:S.record.revision,changes:changes(),old_id:m.old,new_id:m.next});if(S.weatherImport!==m||m.context!==weatherContext()||key!==JSON.stringify([m.old,m.next]))return true;m.preview=r;m.message='预览完成，尚未替换。';}
  if(action==='apply'){
   if(readonly()||!m.preview||m.context!==weatherContext())throw Error('当前方案或预览已变化，请重新核对可编辑方案。');
   setPath('factors.scope.site_ids',copy(m.preview.scope.site_ids));closeWeatherImport();notice('气象更新已应用到当前编辑；请保存新版本。原结果与已排队任务保持。');return true;
  }
 }catch(e){if(S.weatherImport===m)m.message=e.message;}
 finally{if(S.weatherImport===m){m.pending=false;renderWeatherImport();}}
 return true;
};
document.addEventListener('input',e=>{const t=e.target,m=S.weatherImport,k=t.dataset.weatherField;if(!m||!k)return;m[k]=t.type==='checkbox'?t.checked:t.value;if(k==='path'){m.checked=null;m.reviewed=false;}if(k==='old'||k==='next'){m.preview=null;if(k==='old')m.next='';renderWeatherImport();}});
