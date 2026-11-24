'use strict';
const app=document.getElementById('app');
const nav=document.getElementById('navigation');
const message=document.getElementById('message');
const S={boot:null,view:'editor',factor:'materials',id:'global_fixed',record:null,saved:null,dirty:false,search:'',archived:false,preview:null,generated:null,bundles:[],history:null,left:'global_w00',right:'global_fixed',comparison:null,compareVersions:{},results:null,resultMode:'classes',busy:false};
const copy=x=>JSON.parse(JSON.stringify(x));
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modes={controlled:'温控冷热需求',natural:'自然室温',both:'自然室温与温控',inherited:'继承原输入'};
const factors=[['building','建筑'],['materials','材料'],['condition','工况'],['scope','范围']];
function notice(text=''){message.textContent=text;}
async function api(route,body){
 // These readers merge changes into an explicitly pinned saved version.
 // Do not send unchanged multi-city calendar snapshots back on every view.
 if(['/api/plan-workflow','/api/capabilities','/api/preview','/api/calendar-inspections'].includes(route)&&body?.changes&&body.id===S.saved?.id&&body.revision===S.saved.revision){
  body={...body,changes:Object.fromEntries(Object.entries(body.changes).filter(([k,v])=>JSON.stringify(v)!==JSON.stringify(S.saved[k])))};
 }
 const serialized=body===undefined?undefined:JSON.stringify(body);
 if(serialized!==undefined&&new Blob([serialized]).size>32*1024*1024)throw new Error('本次请求超过 32 MiB，请缩小本次内容；尚未发送。');
 let response;
 try{response=await fetch(route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':S.boot.token},body:serialized});}
 catch(error){throw new Error('未能连接工作区服务。请稍后重试或刷新页面；若刚提交保存或计算，请先查看记录，避免重复提交。');}
 const value=await response.json();if(!response.ok)throw new Error(value.error||'操作未完成。');return value;
}
function readonly(){const item=S.boot.records.find(r=>r.id===S.id);return !S.record||S.record.status!=='draft'||S.record.revision!==item?.revision;}
function disabled(){return readonly()?' disabled':'';}
function options(rows,value){return rows.map(([key,label])=>`<option value="${esc(key)}"${String(key)===String(value)?' selected':''}>${esc(label)}</option>`).join('');}
function select(label,path,rows,value,extra=''){return `<label class="field">${label}<select data-path="${path}"${disabled()} ${extra}>${options(rows,value)}</select></label>`;}
function number(label,path,value,extra=''){return `<label class="field">${label}<input type="number" data-path="${path}" value="${esc(value)}" step="any"${disabled()} ${extra}></label>`;}
function setPath(path,value){const keys=path.split('.');let obj=S.record;for(const key of keys.slice(0,-1))obj=obj[key];obj[keys.at(-1)]=value;S.dirty=true;S.preview=null;S.generated=null;scheduleCapability();}
function updateDirtyStatus(){
 updateActivityDirtyStatus();updateVersionHistoryDirty();
 const generate=app.querySelector('[data-action="generate"]');if(generate)generate.disabled=true;
 const generated=app.querySelector('#generated-inputs');if(generated)generated.remove();
 const save=app.querySelector('[data-action="save"]');if(save)save.disabled=readonly()||!S.dirty;
 let discard=app.querySelector('[data-action="discard"]');
 if(!discard&&S.dirty&&save){discard=document.createElement('button');discard.dataset.action='discard';discard.textContent='撤销未保存修改';save.parentElement.append(discard);}
 if(discard)discard.hidden=!S.dirty;
 const status=app.querySelector('.two-views > .section .row .muted');if(status)status.textContent=(readonly()?'来源或历史版本只读':'新方案可编辑')+' · '+planVersionLabel(S.record)+(S.dirty?' · 有未保存修改':'');
}
function changes(){return Object.fromEntries(['name','factors','numerics','execution'].map(k=>[k,S.record[k]]));}
function format(value,digits=2){return value==null?'无数据':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits,minimumFractionDigits:digits});}
function renderNav(){nav.innerHTML=[['editor','编辑方案'],['compare','对照总览'],['execution','计算队列'],['result-index','结果索引'],['sources','来源与迁移'],['guide','工作区说明']].map(([key,label])=>`<button type="button" data-view="${key}" aria-pressed="${S.view===key||(key==='result-index'&&S.view==='results')}">${label}</button>`).join('');}
function filteredRecords(){return S.boot.records.filter(r=>(S.archived||!r.archived)&&(!S.search||opticalSearch([r.name,r.building],S.search)));}
function sidebar(){return librarySidebar();}
function buildingPanel(){return buildingSummaryMarkup();}
function materialsPanel(){
 const m=S.record.factors.materials;
 if(!m.definitions.length)return `<h2>${m.legacy_construction_overrides?'原构造指定':'保留原建筑构造'}</h2><div class="well">${m.legacy_construction_overrides?'旧构造、层序和参数修改已完整保留，后续逐项转为统一材料应用。':'此方案没有新增研究材料。'}</div>${m.legacy_construction_overrides?`<details open><summary>查看原构造设置</summary><pre>${esc(JSON.stringify(m.legacy_construction_overrides,null,2))}</pre></details>`:''}`;
 return m.definitions.map((d,i)=>`<div><div class="row"><h2>${esc(d.name)}</h2><span class="tag">${d.kind==='single_layer'?'单层材料':'材料组件'}</span></div><p class="muted">状态按独立身份保存。${esc(d.source_note||'')}</p><div class="state-grid">${d.states.map((s,j)=>`<div class="state"><h3>${esc(s.name)} · ${esc(s.id)}</h3>${select('热学输入',`factors.materials.definitions.${i}.states.${j}.thermal_input`,[['resistance','直接热阻'],['conductivity_thickness','厚度与导热系数']],s.thermal_input||'resistance')}${s.thermal_input==='conductivity_thickness'?`${number('厚度 / mm',`factors.materials.definitions.${i}.states.${j}.thickness_mm`,s.thickness_mm,'min="0"')}${number('导热系数 / W/(m·K)',`factors.materials.definitions.${i}.states.${j}.conductivity_W_mK`,s.conductivity_W_mK,'min="0"')}<p class="muted">热阻将在保存与预检时由厚度、导热系数计算。</p>`:number('热阻 / m²·K/W',`factors.materials.definitions.${i}.states.${j}.resistance_m2K_W`,s.resistance_m2K_W,'min="0"')}</div>`).join('')}</div><div class="grid2">${select('两态光学关系',`factors.materials.definitions.${i}.optics_depend_on_state`,[['false','两态相同'],['true','分态设置']],String(d.optics_depend_on_state))}<div class="field">材料层蓄热<div class="line"><span>${d.model==='equivalent_resistance_no_layer_storage'?'沿用忽略该层蓄热的等效模型':'沿用来源模型'}</span></div></div></div><details><summary>查看与编辑表面光学参数参数</summary><div class="grid2">${Object.entries(d.optics||{}).filter(([key])=>d.optics_depend_on_state||key.endsWith('_R')).map(([key,v])=>`<div class="state"><h3>${key.startsWith('A')?'A 组':'B 组'} · ${key.endsWith('C')?'压缩态':d.optics_depend_on_state?'蓬松态':'两态共用'}</h3>${number('太阳反射率',`factors.materials.definitions.${i}.optics.${key}.reflectance`,v.reflectance,'min="0" max="1"')}${number('热发射率',`factors.materials.definitions.${i}.optics.${key}.emissivity`,v.emissivity,'min="0" max="1"')}</div>`).join('')}</div><p class="muted">沿用原不透明材料反射率输入；太阳吸收率由 1 − 反射率得到。未提供的另一组光学参数不自动补零。</p></details></div>`).join('')+m.applications.map((a,i)=>`<div class="control"><h3>应用到建筑 · ${esc(({wall:'墙体',roof:'屋顶',floor:'楼板',window:'窗户'})[a.component]||a.component)}</h3><div class="grid2">${select('安装位置',`factors.materials.applications.${i}.position`,[['exterior','外侧附加'],['interior','内侧附加'],['between','原构造两层之间'],['legacy_construction','沿用旧构造指定']],a.position)}<div class="field">应用范围<div class="line"><span>${a.target_ids.length} 个构件</span></div></div></div>${a.position==='between'?`<label class="field">插入层位（前一层 / 后一层）<input data-between="${i}" value="${esc((a.between_layers||[]).join(' / '))}" placeholder="填写两个实际层名，以 / 分隔"${disabled()}></label>`:''}<details><summary>查看应用构件</summary><p class="muted">${esc(a.target_ids.join('、'))}</p></details></div>`).join('');
}
function stateRoles(){return S.boot.control_roles?.[S.record.provenance.origin_id||S.record.id]||{positive:'R',negative:'C'};}
function conditionPanel(){
 const c=S.record.factors.condition,m=S.record.factors.materials;
 return `<h2>建筑运行与材料使用</h2><div class="grid2">${select('建筑运行','factors.condition.operation.mode',Object.entries(modes),c.operation.mode)}<div class="field">设定点与运行时段<div class="line"><span>${Object.keys(c.operation.overrides||{}).length?Object.keys(c.operation.overrides).length+' 间房有本方案覆盖':'继承建筑默认'}</span></div></div></div>${c.controls.map((control,i)=>{
 const base=`factors.condition.controls.${i}`,a=m.applications.find(a=>a.id===control.application_id),d=m.definitions.find(d=>d.id===a?.material_id);
 return `<div class="control"><h3>${control.channel==='thermal'?'热学状态':'表面光学'} · ${control.target_ids.length} 个构件</h3><div class="grid2">${select('使用方式',base+'.mode',control.channel==='thermal'?[['fixed','固定状态'],['feedback','反馈调节']]:[['fixed','固定光学参数组'],['calendar','按参考日历']],control.mode)}${control.channel==='thermal'?select(control.mode==='fixed'?'固定状态':'初始状态',base+'.state_id',(d?.states||[]).map(s=>[s.id,s.name]),control.state_id):control.mode==='fixed'?select('固定光学参数组',base+'.face_id',[['A','固定 A'],['B','固定 B']],control.face_id||'A'):'<div class="field">日历来源<div class="line"><span>见下方参考计算</span></div></div>'}</div>${control.channel==='thermal'&&control.mode==='feedback'?`<div class="grid2">${select('反馈预设',base+'.rule',[['UNIFIED','统一反馈'],['GROUPED','按朝向分组反馈']],control.rule||'UNIFIED')}${select('控制更新方式',base+'.update.kind',[['solver_step','每个求解步'],['minutes','固定分钟间隔']],control.update?.kind||'solver_step')}</div>${control.update?.kind==='minutes'?number('控制更新间隔 / min',base+'.update.minutes',control.update.minutes,'min="1"'):''}<div class="grid2">${number('低温阈值 / °C',base+'.policy.cold_C',control.policy?.cold_C)}${number('高温阈值 / °C',base+'.policy.hot_C',control.policy?.hot_C)}${number('热流死区 / W/m²',base+'.policy.flux_deadband_W_m2',control.policy?.flux_deadband_W_m2,'min="0"')}${number('最短状态保持 / min',base+'.policy.minimum_hold_minutes',control.policy?.minimum_hold_minutes,'min="0"')}${select('抑制传热时选择',base+'.state_roles.positive',(d?.states||[]).map(s=>[s.id,s.name]),control.state_roles?.positive||stateRoles().positive)}${select('促进传热时选择',base+'.state_roles.negative',(d?.states||[]).map(s=>[s.id,s.name]),control.state_roles?.negative||stateRoles().negative)}</div><p class="muted">依据上一完整步的室温与热流判断，更新状态后应用对应光学参数。求解步长在下方单独设置。</p>`:''}</div>`;
 }).join('')||'<div class="well">本方案没有新增材料控制。</div>'}${c.reference_runs.length?`<details><summary>查看控制规则的参考计算</summary><pre>${esc(JSON.stringify(c.reference_runs.map(referenceDisplay),null,2))}</pre></details>`:''}`;
}
function referenceDisplay(ref){if(ref.kind==='workspace_daily_calendar_v1'){const s=ref.snapshot||{},c=s.content||{};return {id:ref.id,name:s.name,version:s.revision,sha256:s.sha256,rule:c.rule,sites:(c.sites||[]).map(r=>({site_id:r.site_id,city:r.city,calendar_days:r.calendar?.length,calendar_sha256:r.calendar_sha256,switches:r.switches}))};}const {calendar,...rest}=ref;return {...rest,calendar_days:calendar?.length};}
function scopePanel(){
 const scope=S.record.factors.scope,selected=new Set(scope.site_ids);const global=S.record.provenance.adapter==='global_frozen_v011';
 const available=Object.values(S.boot.sites).filter(s=>global?s.source_kind==='reviewed_global':selected.has(s.id));
 return `<h2>地点与时段</h2><div class="grid2"><label class="field">开始（月-日）<input data-period="start" value="${String(scope.period[0]).padStart(2,'0')}-${String(scope.period[1]).padStart(2,'0')}" placeholder="01-01"${disabled()}></label><label class="field">结束（月-日）<input data-period="end" value="${String(scope.period[2]).padStart(2,'0')}-${String(scope.period[3]).padStart(2,'0')}" placeholder="12-31"${disabled()}></label></div><div class="row"><span>已选 ${selected.size} 个地点</span>${global?`<div class="actions"><button data-scope="all"${disabled()}>全部已接受地点</button><button data-scope="sample"${disabled()}>8 个步长研究地点</button></div>`:''}</div><div class="site-picker">${available.map(s=>`<label class="check"><input type="checkbox" data-site="${esc(s.id)}"${selected.has(s.id)?' checked':''}${readonly()||!s.eligible?' disabled':''}><span>${esc(s.name)}${s.climate?' · '+esc(s.climate):''}${!s.eligible?' · 暂缓':''}</span></label>`).join('')}</div><p class="muted">${global?'按气候类型分组、类内代表点等权；未计算地区保留无数据。':'沿用原方案的地点与参考日历。新地点关联将在后续适配中开放。'}</p>`;
}
function previewPanel(){
 if(!S.preview)return '';
 const p=S.preview;
 return `<section class="section"><div class="row"><h2>计算清单预览</h2><span class="tag">不提交任务</span></div><div class="metrics"><span><strong>${p.selected_sites??'—'}</strong>所选地点</span><span><strong>${p.case_count??'待解析'}</strong>算例</span><span><strong>${p.historical_candidates??0}</strong>原结果候选</span></div><p class="muted">${esc(p.execution_status||'请先完善方案')}。候选来源核对时间：${esc(p.source_checked_at||'—')}。</p>${[...(p.errors||[]),...(p.requirements||[]),...(p.notes||[])].map(x=>`<p class="warning">${esc(x)}</p>`).join('')}${caseListView('preview')}<div class="row"><span class="muted">${p.generation?.supported?'生成当前已保存版本的输入；重复生成会核对并复用已有文件。':esc(p.generation?.reasons?.join('；')||'请先完善方案')}</span><button data-action="generate" class="primary"${S.dirty||!p.generation?.supported?' disabled':''}>生成模型输入（不计算）</button></div>${S.dirty?'<p class="warning">请先保存版本，再生成输入。</p>':''}</section>`;
}
function generatedPanel(){
 const p=S.generated;if(!p)return '';
 const base='/api/model-inputs/'+p.id;
 return `<section class="section" id="generated-inputs"><div class="row"><h2>模型输入已保存</h2><button class="primary" data-action="prepare-execution">准备计算清单</button></div><p>${p.case_count} 个输入，${p.exact_matches} 个与原冻结输入逐字段相同；新增模拟 0 次。</p><p class="muted">生成器沿用已核实的建筑，将材料参数、固定或反馈状态、光学参数组、时段与步长写入输入。变更后的结果需要另行计算验证。</p><div class="actions"><a href="${base}/manifest.json" target="_blank" rel="noopener">查看差异与来源清单 ↗</a><a href="${base}/record.json" target="_blank" rel="noopener">查看绑定方案版本 ↗</a></div><button data-inspect-input="${esc(p.id)}">查看完整输入与字段变化</button>${caseListView('generated')}</section>`;
}
function editor(){
 const r=S.record;if(!r)return '<p>正在读取方案…</p>';
 const body={building:buildingPanel,materials:materialsPanel,condition:conditionPanel,scope:scopePanel}[S.factor]();
 return `<div class="workspace">${sidebar()}<div class="two-views"><section class="section"><div class="row"><div><h1>${esc(r.name)}</h1><p class="muted">${readonly()?'来源或历史版本只读':'新方案可编辑'} · ${esc(planVersionLabel(r))}${S.dirty?' · 有未保存修改':''}</p></div><div class="actions">${latestVersionButton()}<button data-action="history">查看版本记录</button><button data-action="preview">计算安排 · ${r.numerics.step_minutes} min</button><button data-action="copy">另存为研究方案</button><button data-action="save" class="primary"${readonly()||!S.dirty?' disabled':''}>保存版本</button>${S.dirty?'<button data-action="discard">撤销未保存修改</button>':''}</div></div><label class="field">方案名称<input data-path="name" value="${esc(r.name)}" maxlength="100"${disabled()}></label>${versionNoteMarkup(S.saved,true)}${versionHistoryPanel()}</section>${planningPanel()}<nav class="factor-nav" aria-label="方案四因素">${factors.map(([k,label],i)=>`<button data-factor="${k}" aria-pressed="${S.factor===k}">${i+1} · ${label}</button>`).join('')}</nav><section class="section">${capabilityPanel()}${body}</section>${inputInspectionView()}${planActivityView()}<details class="footer"><summary>来源与映射说明</summary>${r.provenance.notes.map(n=>`<p class="muted">${esc(n)}</p>`).join('')}<p class="source-path">${esc(r.provenance.source_path||'')}</p></details></div></div>`;
}
function compactFactor(r,key){
 const f=r.factors;if(key==='building')return f.building.name+(f.building.usage_profile?'；'+f.building.usage_profile.name+' · 配置版本 '+f.building.usage_profile.revision:'；原默认作息');
 if(key==='materials')return f.materials.definitions.length?f.materials.definitions.map(d=>d.name).join('、')+'；'+f.materials.applications.map(a=>a.target_ids.length+' 个构件 / '+({exterior:'外侧',interior:'内侧',between:'中间层',legacy_construction:'旧构造'}[a.position])).join('、'):f.materials.legacy_construction_overrides?'沿用旧构造修改':'原建筑构造';
 if(key==='condition')return modes[f.condition.operation.mode]+(Object.keys(f.condition.operation.overrides||{}).length?' · '+Object.keys(f.condition.operation.overrides).length+' 间运行覆盖':' · 继承建筑默认')+'；'+(f.condition.controls.length?f.condition.controls.map(c=>(c.channel==='thermal'?'热学':'表面光学')+' '+({fixed:'固定',feedback:'反馈',calendar:'日历'}[c.mode]||c.mode)+' / '+c.target_ids.length+' 构件').join('；'):'无材料控制');
 if(key==='scope')return f.scope.site_ids.length+' 个地点；'+f.scope.period.slice(0,2).join('-')+' 至 '+f.scope.period.slice(2).join('-');
 return r.numerics.step_minutes+' min';
}
function comparisonView(){
 const c=S.comparison,rows=S.boot.records.map(r=>[r.id,r.name+(r.archived?'（归档）':'')]);
 return `<section class="section"><h1>对照总览</h1><p class="muted">先选择要比较的两份方案配置；保存比较后，到“结果与图表”选择已有计算批次。保存版本是四因素与计算设置的快照，不是一次计算结果。</p>${comparisonCatalogControl()}<div class="grid2 comparison-picks"><label class="field">基准方案<select data-compare="left">${comparisonPlanOptions("left")}</select></label><label class="field">研究方案<select data-compare="right">${comparisonPlanOptions("right")}</select></label></div>${c?`<div class="grid2 plan-version-picks">${planVersionPick("left")}${planVersionPick("right")}</div>${comparisonMatchView()}<div class="grid2">${versionNoteMarkup(c.left)}${versionNoteMarkup(c.right)}</div><div class="table-scroll"><table class="table"><thead><tr><th class="small-col">因素</th><th>${esc(c.left.name)}<small>${esc(planVersionLabel(c.left))}</small></th><th>${esc(c.right.name)}<small>${esc(planVersionLabel(c.right))}</small></th></tr></thead><tbody>${c.comparison.rows.map(row=>`<tr><th>${row.label}</th><td>${esc(compactFactor(c.left,row.key))}</td><td class="${row.equal?'':'changed'}">${esc(compactFactor(c.right,row.key))}${!row.equal?'<small>内容有差异</small>':''}</td></tr>`).join('')}</tbody></table></div>${planDifferencesView()}<p class="${c.comparison.shared_conditions?'muted':'warning'}">${esc(c.comparison.note)}</p><div class="grid2"><label class="field">比较名称<input id="comparison-name" value="${esc(S.planComparisonDraft?.name??(c.right.name+' 对照 '+c.left.name))}" maxlength="100"></label><label class="field">比较指标<select id="comparison-metric">${options([['total','总冷热负荷'],['heating','供暖负荷'],['cooling','制冷负荷'],['temperature','室温表现']],S.planComparisonDraft?.metric??(c.left.factors.condition.operation.mode==='natural'||c.right.factors.condition.operation.mode==='natural'?'temperature':'total'))}</select></label></div><div class="actions"><button data-edit-side="left"${S.boot.records.some(r=>r.id===c.left.id)?'':' disabled title="当前比较保留了方案快照，原方案已移出方案库"'}>编辑基准方案</button><button data-edit-side="right"${S.boot.records.some(r=>r.id===c.right.id)?'':' disabled title="当前比较保留了方案快照，原方案已移出方案库"'}>编辑研究方案</button><button class="primary" data-action="save-comparison">${exactComparisonMatch()?"复用已保存比较":"保存比较关系"}</button></div><p id="comparison-save-note" class="muted">${exactComparisonMatch()?"名称、双方版本和指标完全相同，将打开原比较，不新增记录。":"保存后固定双方版本；改变比较名称、任一版本或指标将另存一条记录。"}</p>`:'<p>正在读取对照…</p>'}</section>${comparisonLibraryView()}`;
}
function resultsView(){
 const d=S.results;if(!d)return '<p>正在读取正式历史结果…</p>';
 const groups=S.resultMode==='classes',rows=groups?d.classes:d.sites;
 return `<section class="section"><div class="row"><h1>${esc(d.label)}</h1><div class="actions"><button data-result-mode="classes" aria-pressed="${groups}">按气候类型</button><button data-result-mode="sites" aria-pressed="${!groups}">按地点</button></div></div><div class="well page-purpose" id="legacy-result-purpose"><h2>这里只展示原平台历史基准</h2><p>原平台正式全球 ${d.minutes} min 对照结果的只读快照，不汇总本工作区后来完成的计算。</p><p>新的 5 min 全球批次、北京全年及其他方案结果，请从计算队列、对应保存版本的“计算与结果”或对照总览查看。</p><div class="actions"><button data-view="execution">查看新工作区计算结果</button><button data-view="compare">打开已有方案对照</button></div></div><p class="muted">${esc(d.note)}</p><p class="muted">单位：MJ/m²，按 ${format(d.conditioned_area_m2,2)} m² 温控面积归一化。此处不是新草案的计算结果。</p><div class="table-scroll" id="legacy-result-table" tabindex="0" aria-label="原平台历史数值"><table class="table"><thead><tr><th>${groups?'气候类型':'地点'}</th><th>样本 / 状态</th><th class="num">供暖降低</th><th class="num">制冷降低</th><th class="num">总需求降低</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${groups?esc(r.climate+' · '+r.name):esc(r.city)+'<small>'+esc(r.climate)+'</small>'}</td><td>${groups?r.validated_sites+' 地点':r.status==='accepted'?'已接受':'暂缓'}</td>${['heating','cooling','total'].map(q=>`<td class="num">${format(r[q+'_saved_MJ_m2'+(groups?'_mean':'')])}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
}
function sourcesView(){
 const v=S.boot.verification;
 return `<section class="section"><div class="row"><h1>来源与迁移核对</h1><button data-action="verify" class="primary">重新核对来源</button></div><div class="well page-purpose" id="source-purpose"><h2>资料来源与迁移核对</h2><p>本页用于核对原平台资料和迁移记录：检查导入方案的映射、历史数值与来源文件，并查看已经生成的输入包。</p><p>当前方案的气象、建筑使用配置和材料版本更新，从编辑方案中的“核对本方案来源”进入；新建筑导入、房间复用与材料应用也在对应方案中操作。</p><p class="muted">重新核对只检查并记录结果，不会迁移磁盘文件、覆盖方案、采用新版本或启动模拟。下方核对时间是该份报告的时间。</p><div class="actions"><button data-view="editor">回到方案与来源更新</button><button data-view="guide">查看能力与维护说明</button></div></div><div class="metrics"><span><strong>${S.boot.records.filter(r=>r.status==='imported').length}</strong>导入方案</span><span><strong>${S.boot.source_summary.accepted_cases}</strong>原全球案例</span><span><strong>${v?.protected_sources??'待核对'}</strong>保护来源</span></div><p class="muted">导入时间：${esc(S.boot.imported_at)}。原平台的程序、输入与结果保持独立。</p>${v?`<div class="well"><h3>${v.passed?'最近一次来源核对通过':'来源核对存在待处理差异'}</h3><p>${v.check_count} 项检查；旧方案往返映射 ${v.legacy_roundtrips} 份；新增模拟 ${v.new_simulations} 次。</p><p class="muted">核对时间：${esc(v.created)}</p>${v.failures.map(x=>`<p class="warning">${esc(x)}</p>`).join('')}</div>`:''}<table class="table"><thead><tr><th>本阶段已接通</th><th>下一阶段</th></tr></thead><tbody><tr><td>四因素记录与来源追溯</td><td>更多建筑与材料适配</td></tr><tr><td>固定、反馈与绑定日历输入生成</td><td>更多类型的实际运行验证</td></tr><tr><td>比较关系与算例预览</td><td>扩展结果比较与作图</td></tr><tr><td>历史年度、月度与气候数值核对</td><td>逐项迁移更多材料与构件模型</td></tr></tbody></table><p class="muted">固定和动态工况已接通输入生成与执行。计算队列使用统一资源预算；历史核对报告中的模拟次数仅指该次核对。</p>${S.boot.model_verification?`<div class="well">固定工况输入核对：${S.boot.model_verification.exact_matches} / ${S.boot.model_verification.cases} 份与原输入逐字段相同；新增模拟 0 次。</div>`:''}${S.boot.dynamic_verification?`<div class="well">动态规则离线验收：${S.boot.dynamic_verification.passed?'通过':'有待检查'}；现有动态方案展开为 ${S.boot.dynamic_verification.legacy_model_inputs} 份输入。建筑模拟 0 次。</div>`:''}<h2 id="source-inputs">已生成的输入包</h2>${S.bundles.map(b=>`<p><a href="/api/model-inputs/${esc(b.id)}/manifest.json" target="_blank" rel="noopener">${esc(b.record_name)} · 版本 ${esc(b.revision)} · ${b.case_count} 个输入</a><small class="muted"> ${esc(b.created)}</small></p>`).join('')||'<p class="muted">尚未生成输入包。</p>'}</section>`;
}
function render(){renderNav();app.innerHTML=resultIndexReturnView()+(S.view==='result-index'?resultIndexView():S.view==='editor'?editor():S.view==='compare'?comparisonWorkspaceView():S.view==='results'?resultsView():S.view==='execution'?executionView():S.view==='guide'?guideView():sourcesView());drawComparisonMap();}
async function bootstrap(){S.boot=await api('/api/bootstrap');}
let recordLoadEpoch=0;
async function loadRecord(id,revision,accept=()=>true){
 if(S.usageDirty)throw usagePendingError('切换方案或版本');
 if(S.dirty)throw new Error('当前修改尚未保存，请保存或撤销后切换方案。');
 const epoch=++recordLoadEpoch,record=await api('/api/records/'+encodeURIComponent(id)+(revision!==undefined?'?revision='+encodeURIComponent(revision):''));
 if(epoch!==recordLoadEpoch||!accept())return false;
 S.id=id;S.record=record;S.saved=copy(record);revealRecordGroup(id);S.preview=null;S.generated=null;S.history=null;S.inputInspection=null;S.inputDetail=null;S.planningOpen=false;resetConfiguration();
 S.planActivity=null;S.planActivityError='';S.workflow=null;S.capability=null;S.capabilityError='';
 // Render the selected record without waiting for its input/history scan.
 // These readers retain their own error and stale-response guards.
 void refreshCapability();void loadPlanActivity({forceWorkflow:false});
 return true;
}
let comparisonEpoch=0;
async function loadComparison(savedId){
 const epoch=++comparisonEpoch;
 const relation=savedId||S.boot?.comparisons?.find(c=>['left','right'].every(k=>c[k].id===S[k]&&c[k].revision===S.compareVersions?.[k+'_revision']))?.id;
 const values=await Promise.allSettled([api('/api/compare',{left:S.left,right:S.right,...S.compareVersions,comparison:relation}),api('/api/history/'+encodeURIComponent(S.left)),api('/api/history/'+encodeURIComponent(S.right))]);
 const failed=values.find(v=>v.status==='rejected');if(failed)throw failed.reason;
 if(epoch===comparisonEpoch){S.comparison=values[0].value;S.planHistories={left:values[1].value,right:values[2].value};S.compareVersions={left_revision:S.comparison.left.revision,right_revision:S.comparison.right.revision};clearUnmatchedResultComparison();}
}
async function action(button){
 if(await versionNoteAction(button)||await copyPlanAction(button)||await comparisonHubAction(button))return;
 if(await resultIndexAction(button)){render();finishResultIndexNavigation();return;}
 if(await sourceOverviewAction(button)){render();return;}
 if(await configurationAction(button)){render();return;}
 if(await exportHistoryAction(button)){render();return;}
 const reviewed=await inputReviewAction(button);if(reviewed){if(reviewed!=='local'){render();if(button.dataset.inspectInput)document.getElementById('input-inspection')?.scrollIntoView({block:'start'});}return;}
 if(await versionHistoryAction(button)){render();if(button.dataset.action==='history')document.getElementById('version-history')?.scrollIntoView({block:'start'});return;}
 if(await comparisonLibraryAction(button)){
  render();
  const target=button.dataset.matchedResults?document.getElementById('comparison-results'):app.querySelector('.comparison-page-tabs');
  target?.scrollIntoView({block:'start'});
  return;
 }
 if(await planActivityAction(button)){render();const target=button.dataset.activityBatch?'execution-results':button.dataset.activityQueue?'batch-'+button.dataset.activityQueue:null;if(target)document.getElementById(target)?.scrollIntoView({block:'start'});return;}
 if(await comparisonResultAction(button)){render();return;}
 if(await executionAction(button)){render();return;}
 if(button.dataset.view){S.view=button.dataset.view;if(S.view==='result-index')await loadResultIndex();if(S.view==='editor')await loadPlanActivity();if(S.view==='compare'){S.comparePage='overview';if(S.left&&S.right)await loadComparison();}if(S.view==='execution')await loadExecution();if(S.view==='results'&&!S.results)S.results=await api('/api/results');if(S.view==='sources')await loadSourceOverview();if(S.view==='guide')S.guide=await api('/api/workspace-guide');}
 else if(button.dataset.exampleRecord){await loadRecord(button.dataset.exampleRecord,Number(button.dataset.exampleRevision));S.view='editor';}
 else if(button.dataset.record){await loadRecord(button.dataset.record);}
 else if(button.dataset.factor){S.factor=button.dataset.factor;if(S.factor==='building')await loadConfiguration();}
 else if(button.dataset.resultMode)S.resultMode=button.dataset.resultMode;
 else if(button.dataset.editSide){await loadRecord(S.comparison[button.dataset.editSide].id,S.comparison[button.dataset.editSide].revision);S.view='editor';}
 else if(button.dataset.revision){await loadRecord(S.id,/^\d+$/.test(button.dataset.revision)?Number(button.dataset.revision):button.dataset.revision);}
 else if(button.dataset.scope){
   const eligible=Object.values(S.boot.sites).filter(s=>s.source_kind==='reviewed_global'&&s.eligible);
   const selected=button.dataset.scope==='all'?eligible:eligible.filter(s=>['Af','BWh','BWk','Cwa','Cwb','Cfc','Dfd','EF'].includes(s.climate)&&['São Gabriel da Cachoeira','Bilma','Kuqa','Dibrugarh','Cochabamba','Río Grande','Namtsy','Summit'].some(name=>s.name.includes(name)));
   if(!selected.length)throw new Error('没有找到对应的已登记地点。');setPath('factors.scope.site_ids',selected.map(s=>s.id));
 }else switch(button.dataset.action){
   case 'copy':openCopyDialog();return;
   case 'save':{const r=await api('/api/drafts/'+S.id,{expected_revision:S.record.revision,changes:changes()});S.dirty=false;await bootstrap();await loadRecord(r.id);notice('已保存新版本；原版本保留。');break;}
   case 'discard':S.record=copy(S.saved);S.dirty=false;S.preview=null;resetConfiguration();await refreshCapability();break;
   case 'refresh-planning':
   case 'preview':S.planningOpen=true;try{S.preview=await api('/api/preview',{id:S.id,revision:S.record.revision,changes:changes()});}catch(error){render();throw error;}break;
   case 'close-planning':S.planningOpen=false;break;
   case 'check-capability':await refreshCapability();break;
   case 'generate':if(S.dirty)throw new Error('请先保存版本，再生成输入。');S.generated=await api('/api/model-inputs',{id:S.id,revision:S.record.revision});await loadPlanActivity();notice(S.generated.reused?'已核对并复用已有输入包。':'模型输入与差异清单已保存，没有启动计算。');break;
   case 'verify':notice('正在只读核对来源和历史数值…');S.boot.verification=await api('/api/verify',{});notice(S.boot.verification.passed?'来源与历史数值核对通过。':'发现差异，请查看核对内容。');break;
   case 'save-comparison':{const c=S.comparison;capturePlanComparisonDraft();const saved=await api('/api/comparisons',{name:S.planComparisonDraft.name,metric:S.planComparisonDraft.metric,left:{id:c.left.id,revision:c.left.revision},right:{id:c.right.id,revision:c.right.revision}});await bootstrap();await openSavedComparison(saved.id);notice(saved.reused_comparison?'已打开原比较，没有新增重复记录。':'已保存比较关系；现在可直接选择双方已有批次查看结果。');break;}
 }
 render();
}
document.addEventListener('click',async event=>{const button=event.target.closest('button');if(!button||button.disabled||S.busy)return;if(button.closest('.map-preview-dialog')||handleMapPreview(button))return;S.busy=true;app.inert=true;nav.inert=true;notice();try{await action(button);}catch(error){notice(error.message);}finally{S.busy=false;app.inert=false;nav.inert=false;}});
document.addEventListener('change',async event=>{
 const t=event.target;try{
   if(t.id==='archived'){S.archived=t.checked;render();return;}
   if(t.dataset.compare||t.dataset.compareVersion){await changePlanSelection(t);return;}
   if(t.dataset.path){let value=t.type==='number'?(t.value===''?null:Number(t.value)):t.value;if(t.dataset.path.endsWith('step_minutes')||t.dataset.path.endsWith('max_parallel'))value=Number(value);if(t.dataset.path.endsWith('optics_depend_on_state'))value=value==='true';
     const keys=t.dataset.path.split('.');if(keys.at(-2)==='state_roles'){const c=S.record.factors.condition.controls[Number(keys[3])];if(!c.state_roles)c.state_roles=copy(stateRoles());}if(keys.at(-1)==='kind'&&keys.at(-2)==='update'){const prefix=keys.slice(0,-2);let obj=S.record;for(const key of prefix)obj=obj[key];if(!obj.update)obj.update={};}
     setPath(t.dataset.path,value);configurationPathChanged(t.dataset.path);
     if(t.dataset.path.endsWith('.mode')&&t.dataset.path.includes('.controls.')){const c=S.record.factors.condition.controls[Number(t.dataset.path.split('.')[3])];if(c.mode==='feedback'){if(!['UNIFIED','GROUPED'].includes(c.rule))c.rule='UNIFIED';c.update=c.update?.kind?c.update:{kind:'solver_step'};c.policy=c.policy||copy(S.boot.control_policy);c.state_roles=c.state_roles||copy(stateRoles());}if(c.mode==='fixed'&&c.channel==='orientation')c.face_id=c.face_id||'A';}
     if(t.tagName==='SELECT')render();else updateDirtyStatus();return;
   }
   if(t.dataset.between!==undefined){setPath(`factors.materials.applications.${t.dataset.between}.between_layers`,t.value.split('/').map(x=>x.trim()).filter(Boolean));updateDirtyStatus();return;}
   if(t.dataset.period){const parts=t.value.split('-').map(Number);const p=copy(S.record.factors.scope.period);p.splice(t.dataset.period==='start'?0:2,2,...(parts.length===2?parts:[null,null]));setPath('factors.scope.period',p);updateDirtyStatus();return;}
   if(t.dataset.site){const ids=new Set(S.record.factors.scope.site_ids),site=t.dataset.site,list=t.closest('.scope-site-list'),listY=list?.scrollTop,mainY=scrollY;t.checked?ids.add(site):ids.delete(site);setPath('factors.scope.site_ids',[...ids]);render();if(listY!==undefined){const current=document.querySelector('.scope-site-list');if(current)current.scrollTop=listY;}document.querySelector(`[data-site="${CSS.escape(site)}"]`)?.focus({preventScroll:true});scrollTo({top:mainY,behavior:'instant'});}
 }catch(error){notice(error.message);}
});
document.addEventListener('input',event=>{const t=event.target;if(t.id==='search'){S.search=t.value;const list=document.querySelector('.record-list');list.innerHTML=libraryList();}else if(t.matches('input[data-path]')&&!readonly()){setPath(t.dataset.path,t.type==='number'?(t.value===''?null:Number(t.value)):t.value);updateDirtyStatus();}});
async function startWorkbench(){
 try{await bootstrap();if(S.boot.records.length){selectInitialRecord();await loadRecord(S.id);}else{S.id=null;S.view='workspace';}render();}
 catch(error){
  notice('工作区未能完整加载，请重新加载后重试。');
  const explanation=document.createElement('p'),retry=document.createElement('button');
  explanation.textContent=error instanceof ReferenceError?'页面功能尚未完整载入，已停止初始化。':error.message;
  retry.textContent='重新加载工作区';retry.dataset.startupRetry='true';
  retry.addEventListener('click',event=>{event.stopPropagation();location.reload();});
  app.replaceChildren(explanation,retry);
 }
}
// The deferred feature scripts below app.js must finish before their functions are used.
if(document.readyState==='complete')startWorkbench();
else document.addEventListener('DOMContentLoaded',startWorkbench,{once:true});
document.addEventListener('input',event=>{
 const t=event.target;if(readonly())return;
 if(t.dataset.between!==undefined){setPath(`factors.materials.applications.${t.dataset.between}.between_layers`,t.value.split('/').map(x=>x.trim()).filter(Boolean));updateDirtyStatus();}
 if(t.dataset.period){const parts=t.value.split('-').map(Number),p=copy(S.record.factors.scope.period);p.splice(t.dataset.period==='start'?0:2,2,...(parts.length===2?parts:[null,null]));setPath('factors.scope.period',p);updateDirtyStatus();}
});
window.addEventListener('beforeunload',event=>{if(S.dirty){event.preventDefault();event.returnValue='';}});
