/* Physical categories keep the original ECA editor available for old snapshots. */

function mtPhysical(d){return ['optical_surface_v1','solid_layer_v1','solid_variable_v1'].includes(d?.model);}

const mtSelections=new Map();

function mtSelection(r){const key=r.id+':'+r.revision;if(!mtSelections.has(key))mtSelections.set(key,{state:'R',face:'A',target:'walls'});return mtSelections.get(key);}

const mtNames={film:'薄膜／涂层',solid:'固定实体材料',variable:'可调实体材料'};

function mtModel(d){return d.model==='optical_surface_v1'?'仅表面光学；忽略薄膜自身热阻与热容量':d.model==='solid_variable_v1'?'可固定使用任一状态，也可在工况中启用统一热阻反馈':'固定实体层；计入热阻与热容量';}

function mtKeys(d){return (d.optics_depend_on_state?d.states:[d.states[0]]).flatMap(s=>d.faces.map(f=>f+'_'+s.id));}

const mtOldFields=mcFields;

mcFields=function(d){if(!mtPhysical(d))return mtOldFields(d);let rows=[];

 if(d.model==='optical_surface_v1')rows.push(['薄膜自身热阻与热容量','忽略；原墙体继续传热']);

 for(const s of d.model==='optical_surface_v1'?[]:d.states){rows.push([s.name+' · 厚度 / mm',s.thickness_mm],[s.name+' · 导热率 / W/(m·K)',s.conductivity_W_mK],[s.name+' · 密度 / kg/m³',s.density_kg_m3],[s.name+' · 比热 / J/(kg·K)',s.specific_heat_J_kgK]);if(d.model!=='optical_surface_v1')rows.push([s.name+' · 热阻 / m²·K/W',materialViewerR(s)],[s.name+' · 面热容 / J/(m²·K)',s.thickness_mm&&s.density_kg_m3&&s.specific_heat_J_kgK?s.thickness_mm/1000*s.density_kg_m3*s.specific_heat_J_kgK:null]);}

 for(const k of mtKeys(d)){const o=d.optics[k];rows.push([k+' · 有效太阳吸收率',o?.solar_absorptance],[k+' · 长波发射率',o?.emissivity]);}return rows;};

const mtOldEditor=mcEditor;

mcEditor=function(){const v=mc(),d=v.draft;if(!mtPhysical(d))return mtOldEditor();const thermal=d.model!=='optical_surface_v1';return `<h2>${v.parent?'编辑材料 · 保存新版本':'新建材料'}</h2><p>参数保存为独立材料版本；未填写项显示为待补，计算前必须补齐所需物性。</p><label class="field">材料类别<select data-mt-category${v.parent?' disabled':''}>${options(Object.entries(mtNames),d.category)}</select></label>${mcInput('材料名称','name',d.name,'text')}${d.category==='film'?`<label class="check"><input type="checkbox" data-mt-thermal${thermal?' checked':''}>计入薄膜自身热阻与热容量</label><p>不勾选时，仅改变覆盖后的有效表面光学参数，原墙体仍正常传热。首批限贴覆不透明墙面／屋面，不处理空气间层和窗膜。</p>`:''}<p class="tag">${esc(mtModel(d))}</p>${thermal?d.states.map((s,i)=>`<fieldset><legend>${esc(s.name)}</legend>${mcInput('状态名称',`states.${i}.name`,s.name,'text')}<div class="grid2">${[['厚度 / mm','thickness_mm'],['导热率 / W/(m·K)','conductivity_W_mK'],['密度 / kg/m³','density_kg_m3'],['比热 / J/(kg·K)','specific_heat_J_kgK']].map(([label,key])=>mcInput(label,`states.${i}.${key}`,s[key])).join('')}</div></fieldset>`).join(''):''}<h3>表面光学</h3><label class="check"><input type="checkbox" data-mt-faces${d.faces.length===2?' checked':''}>分别填写 A、B 两组光学参数</label>${d.states.length>1?`<label class="check"><input type="checkbox" data-mt-state-optics${d.optics_depend_on_state?' checked':''}>光学参数随热学状态变化</label>`:''}${mtKeys(d).map(k=>`<fieldset><legend>${esc(k.replace('_',' 面 · '))}</legend><div class="grid2">${mcInput('有效太阳吸收率 / 0–1',`optics.${k}.solar_absorptance`,d.optics[k]?.solar_absorptance)}${mcInput('长波发射率 / 0–1',`optics.${k}.emissivity`,d.optics[k]?.emissivity)}${mcInput('可见光吸收率（可留空，继承原外表面）',`optics.${k}.visible_absorptance`,d.optics[k]?.visible_absorptance)}</div></fieldset>`).join('')}<p class="muted">填写覆盖后的有效外表面参数。单张膜有透光性时，不能直接用 1 − 膜反射率代替覆盖后吸收率。</p><label class="field">物性来源<select data-mc-field="property_source.method">${options([['user_input','用户输入'],['measured','实测'],['derived','推算'],['source_reference','来源参考'],['demonstration','演示假设']],d.property_source.method)}</select></label>${mcInput('来源／测量条件／推算依据','property_source.note',d.property_source.note,'text')}<label class="field">补充说明<textarea data-mc-field="source_note" rows="3">${esc(d.source_note||'')}</textarea></label><p class="muted">状态间密度不自动补齐；同一试件压缩时需自行明确质量、面积与比热关系。ECA 已校准参数不会自动套用。</p><div class="actions"><button class="primary" data-mc="save"${v.pending?' disabled':''}>${v.parent?'保存新版本':'登记到材料库'}</button><button data-mc="discard">撤销编辑</button></div>`;};

const mtOldRead=mcReadField;

mcReadField=function(t){const d=mc().draft;if(!mtPhysical(d))return mtOldRead(t);const keys=t.dataset.mcField.split('.');let o=d;for(const k of keys.slice(0,-1))o=o[k]??={};o[keys.at(-1)]=t.type==='number'?(t.value===''?null:Number(t.value)):t.value;if(keys[0]==='optics')d.optics[keys[1]].input_basis='effective_surface_absorptance';mc().dirty=true;mc().preview=null;};

const mtOldSave=mcSavedContent;

mcSavedContent=function(){if(!mtPhysical(mc().draft))return mtOldSave();const d=copy(mc().draft);for(const k of Object.keys(d.optics))if(!mtKeys(d).includes(k))delete d.optics[k];return d;};

function mtRepairOptics(d){const old=d.optics;d.optics={};for(const k of mtKeys(d))d.optics[k]=copy(old[k]||{input_basis:'effective_surface_absorptance',solar_absorptance:null,emissivity:null});}

document.addEventListener('change',e=>{const t=e.target,d=mc().draft;if(!mtPhysical(d))return;

 if(t.hasAttribute('data-mt-category')||t.hasAttribute('data-mt-thermal')){const next=copy(mc().data.templates[t.hasAttribute('data-mt-category')?t.value:d.category]);next.name=d.name;next.property_source=copy(d.property_source);next.source_note=d.source_note;if(next.category==='film'&&t.hasAttribute('data-mt-thermal')&&t.checked){next.model='solid_layer_v1';next.states[0].thermal_input='conductivity_thickness';}mc().draft=next;mc().dirty=true;render();}

 if(t.hasAttribute('data-mt-faces')){d.faces=t.checked?['A','B']:['A'];mtRepairOptics(d);mc().dirty=true;render();}

 if(t.hasAttribute('data-mt-state-optics')){d.optics_depend_on_state=t.checked;mtRepairOptics(d);mc().dirty=true;render();}

});

const mtOldDetails=mcDetails;

mcDetails=function(){const r=mcRow();if(mc().draft||mc().tab==='sources'||!mtPhysical(r?.content))return mtOldDetails();const d=r.content,choice=mtSelection(r);return `<h2>${esc(r.name)} · v${r.revision}</h2><p>${esc(mtNames[d.category])} · ${esc(mtModel(d))}</p>${mcTable(d)}<p>物性依据：${esc(d.property_source.note||'待补')}</p><p>${esc(d.source_note)}</p><div class="actions"><button data-mc="edit">编辑并保存新版本</button><button data-mc="clone">复制为新材料</button></div><h3>固定计算选用</h3><div class="grid2"><label class="field">固定状态<select id="mt-adopt-state">${options(d.states.map(s=>[s.id,s.name]),choice.state)}</select></label><label class="field">外表面光学参数组<select id="mt-adopt-face">${options(d.faces.map(f=>[f,f+' 组']),choice.face)}</select></label><label class="field">应用表面<select id="mt-adopt-target">${options([['walls','全部不透明外墙'],...(wallScopeSource()?[['conditioned','空调房外墙']]:[]),['roofs','全部屋面'],['both','全部外墙与屋面']],choice.target)}</select></label></div><button class="primary" data-mc="preview"${readonly()?' disabled':''}>预览选入当前方案</button><p>先核对范围和参数，再确认加入草稿。可在方案的材料与工况页继续设置。</p>${mcVersionDiff(r)}`;};

const mtOldList=mcList;

mcList=function(){let html=mtOldList();if(mc().tab==='sources')return html;const temp=document.createElement('template');temp.innerHTML=html;temp.content.querySelectorAll('[data-mc-select]').forEach(b=>{const r=mcRows().find(r=>r.id+':'+r.revision===b.dataset.mcSelect);if(mtPhysical(r?.content))b.querySelector('span').textContent=(r.builtin?'内置参考':'v'+r.revision)+' · '+mtNames[r.content.category];});return temp.innerHTML;};

const mtOldAction=mcAction;

mcAction=async function(b){const r=mcRow();if(b.dataset.mc!=='preview'||!mtPhysical(r?.content))return mtOldAction(b);const v=mc();if(v.pending)return;v.error='';try{mcCheckDraft();if(readonly())throw Error('请先另存为研究方案。');if(S.usageDirty)throw Error('请先保存或撤销建筑配置编辑。');const state_id=document.getElementById('mt-adopt-state').value,face=document.getElementById('mt-adopt-face').value,kind=document.getElementById('mt-adopt-target').value,stamp=JSON.stringify([S.id,S.saved.revision,changes()]);mtSelections.set(r.id+':'+r.revision,{state:state_id,face,target:kind});v.pending=true;render();const payload={id:S.id,revision:S.saved.revision,changes:changes()};const available=await api('/api/material-library/targets',payload);const targets=kind==='conditioned'?await drawingConditionedTargets(available):available.filter(t=>kind==='both'||t.type===(kind==='walls'?'Wall':'Roof')).map(t=>t.id);const data=await api('/api/material-library/adoption-preview',{...payload,target:{id:r.id,revision:r.revision,sha256:r.sha256},selection:{state_id,face,targets}});if(stamp!==JSON.stringify([S.id,S.saved.revision,changes()]))throw Error('方案已变化，请重新预览。');v.preview={data,stamp};mcShowAdoption();}catch(e){v.error=e.message;}finally{v.pending=false;render();}};

const mtOldCanEdit=materialViewerCanEdit;

materialViewerCanEdit=function(){return S.record.factors.materials.definitions.some(mtPhysical)?false:mtOldCanEdit();};

const mtOldThermal=materialViewerThermal;

materialViewerThermal=function(){const ds=S.record.factors.materials.definitions;if(!ds.some(mtPhysical))return mtOldThermal();return ds.map(d=>'<h3>'+esc(d.name)+'</h3><p>'+esc(mtModel(d))+'</p>'+mcTable(d)).join('')+'<button data-configuration="material-catalog">在材料库编辑独立版本</button>';};

const mtOldOptics=materialViewerOptics;

materialViewerOptics=function(){return S.record.factors.materials.definitions.some(mtPhysical)?materialViewerThermal():mtOldOptics();};

const mtOldControl=conditionCanControl;

conditionCanControl=function(){return S.record.factors.materials.definitions.some(mtPhysical)?false:mtOldControl();};



const mtOldApplication=materialViewerApplication;

materialViewerApplication=function(){const m=S.record.factors.materials;if(!m.definitions.some(mtPhysical))return mtOldApplication();if(drawingScopeEnabled())return drawingApplicationMarkup();return m.applications.map(a=>'<h3>不透明外墙／屋面 · '+a.target_ids.length+' 个表面</h3><p>'+esc(mtModel(m.definitions.find(d=>d.id===a.material_id)))+'</p><details><summary>已采用表面</summary><p>'+a.target_ids.map(esc).join('、')+'</p></details>').join('')+'<p>改变表面范围或固定状态，请在材料库重新预览选用。</p><button data-configuration="material-catalog">打开材料库</button>';};

const mtOldLibraryView=materialViewerLibraryView;

materialViewerLibraryView=function(){if(!S.record.factors.materials.definitions.some(mtPhysical))return mtOldLibraryView();const ref=S.record.factors.materials.definition_reference;return '<h3>'+esc(ref?.name||'独立材料')+' · v'+esc(ref?.revision||'—')+'</h3><p>修改物性先保存材料新版本，再明确预览选入当前方案。</p><button data-configuration="material-catalog">打开材料库</button>';};



const mtOldCatalogView=materialCatalogView;materialCatalogView=function(){return mtOldCatalogView().replace('研究材料与版本</button>','研究材料与版本</button><button data-mt-reference title="前往公用参考库的材料参考">浏览内置材料参考 ↗</button>');};

const mtOldPageAction=action;action=async function(b){if(b.hasAttribute('data-mt-reference')){await rlAction({dataset:{view:'reference-library',rlKind:'materials'}});return;}return mtOldPageAction(b);};

