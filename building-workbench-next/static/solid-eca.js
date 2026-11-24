/* Explicit, independently versioned solid-layer research preparation. */
function solidProfile(){return S.record?.numerics.heat_transfer_profile==='five_storey_condfd_1min_v1';}
function solidDefinition(d){return d?.model==='solid_conserved_mass_v1';}
function solidNote(){return '<p class="condition-hint">本组采用官方 EnergyPlus、135 面外墙 CondFD、1 min 求解。反馈每 5 min 判断，至少保持 60 min。与原 5 min 等效热阻方案独立保存。</p>';}
const solidBeforeCapability=capabilityStatus;
capabilityStatus=function(){const html=solidBeforeCapability();return solidProfile()&&html.includes('等待新版 1 min W00')?html.replace('可保存当前配置，计算适配尚未接通','控制接法已接通 · 等待新版逐日参考和日历'):html;};
const solidBeforeThermal=materialViewerThermal;
materialViewerThermal=function(){if(!solidProfile())return solidBeforeThermal();const d=S.record.factors.materials.definitions[0];if(!d)return '<p>W00 保留原构造，外墙采用与实体 ECA 相同的算法及 1 min 步长。</p>';return `<h3>${esc(d.name)}</h3><div class="viewer-table"><table class="table"><thead><tr><th>状态</th><th>真实厚度 / mm</th><th>真实导热率 / W/(m·K)</th><th>密度 / kg/m³</th><th>比热 / J/(kg·K)</th><th>热阻 / m²·K/W</th></tr></thead><tbody>${d.states.map(s=>`<tr><th>${esc(s.name)}</th><td>${format(s.thickness_mm,2)}</td><td>${format(s.conductivity_W_mK,5)}</td><td>${format(s.density_kg_m3,2)}</td><td>${format(s.specific_heat_J_kgK,0)}</td><td>${format(materialViewerR(s),6)}</td></tr>`).join('')}</tbody></table></div><p>同一试件，质量与覆盖面积不变。两态面质量 0.0307 kg/m²，面热容 36.84 J/(m²·K)。压缩密度由守恒推算。</p><details><summary>查看数值接法与校准依据</summary><p>官方实体材料层接口使用固定 2 mm 参考坐标，逐态保持热阻与面热容。内部蓬松态导热率换算为 0.006604 W/(m·K)，并非材料实测导热率。固定两态和冬季、夏季、表面光学切换短段已完成隔离校准；北京同口径四工况全年计算已完成；结果沿用各批次的原复核结论和适用范围。</p></details>${solidNote()}`;};
const solidBeforeOverview=materialViewerOverview;
materialViewerOverview=function(){const html=solidBeforeOverview();return solidProfile()?html.replace('沿用来源模型。','实体材料层，计入材料自身蓄热；物理参数与参考坐标换算分开。')+solidNote():html;};
const solidBeforeCanEdit=materialViewerCanEdit;
materialViewerCanEdit=function(){return solidProfile()?false:solidBeforeCanEdit();};
const solidBeforeLibrary=materialViewerLibraryView;
materialViewerLibraryView=function(){if(!solidProfile())return solidBeforeLibrary();const ref=S.record.factors.materials.definition_reference;return `<h3>独立实体材料版本</h3><p>${ref?esc(ref.name)+' · v'+ref.revision:'W00 没有研究材料层。'}</p><p>本轮使用已确认并完成校准的实体参数；调整试件参数需另建校准版本。原等效热阻材料库版本保持原样。</p>${solidNote()}`;};
const solidBeforeFields=mcFields;
mcFields=function(d){const rows=solidBeforeFields(d);if(solidDefinition(d))for(const s of d.states)rows.push([s.name+' · 密度 / kg/m³',s.density_kg_m3],[s.name+' · 比热 / J/(kg·K)',s.specific_heat_J_kgK],[s.name+' · 面热容 / J/(m²·K)',s.thickness_mm/1000*s.density_kg_m3*s.specific_heat_J_kgK]);return rows;};
const solidBeforeDetails=mcDetails;
mcDetails=function(){const html=solidBeforeDetails();if(mc().tab!=='research'||!solidDefinition(mcRow()?.content))return html;const t=document.createElement('template');t.innerHTML=html;t.content.querySelectorAll('[data-mc="edit"],[data-mc="clone"]').forEach(e=>e.remove());const preview=t.content.querySelector('[data-mc="preview"]');
 if(preview&&S.record&&!solidProfile()){
  preview.disabled=true;
  const reason=document.createElement('p');reason.className='condition-hint';reason.textContent='当前方案为 '+S.record.numerics.step_minutes+' min。这份材料需从五层建筑的 1 min 外墙有限差分（CondFD）方案中选用。';
  preview.parentElement.after(reason);
 }
 return t.innerHTML.replace('等效热阻材料','实体材料 · 质量守恒').replace('忽略材料层自身蓄热；','计入材料层自身蓄热；')+'<p class="muted">本版本保存已完成校准的物理参数。</p>'+(mcForScheme()?'<p>数值接法只适用于独立的 1 min CondFD 对照组。</p>':'');};

