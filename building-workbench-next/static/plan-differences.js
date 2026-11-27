/* Read-only comparison of saved records. No plan normalization or dispatch. */
S.planHistories={left:[],right:[]}; S.planDiffOnly=true;
S.planComparisonDraft=null;
const planLabels={
 density_kg_m3:'密度 / kg/m³',specific_heat_J_kgK:'比热 / J/(kg·K)',visible_absorptance:'可见光吸收率',solar_input:'太阳输入依据',quantity:'所填物理量',value:'输入值',state_relationship:'状态关系',source_state:'基准状态',target_state:'目标状态',specific_heat:'比热关系',inputs:'推算时依据',property_source:'物性来源',method:'来源类型',note:'依据说明',id:'编号',name:'名称',building:'建筑',materials:'材料',condition:'工况',scope:'范围',numerics:'计算设置',
 definition_status:'建筑定义',zones:'热区数量',north_axis:'建筑朝向 / °',conditioned_area_m2:'温控面积 / m²',total_area_m2:'总面积 / m²',wall_ids:'外墙构件',
 definitions:'材料定义',applications:'材料应用',kind:'类型',model:'材料模型',state_identity:'状态区分方式',states:'状态',
 thermal_input:'热学输入方式',resistance_m2K_W:'热阻 / m²·K/W',thickness_mm:'厚度 / mm',conductivity_W_mK:'导热系数 / W/(m·K)',
 optics:'光学参数',reflectance:'太阳反射率',solar_absorptance:'太阳吸收率',emissivity:'热发射率',input_basis:'输入依据',
 optics_depend_on_state:'按状态区分光学参数',source_note:'材料来源说明',material_id:'材料编号',component:'应用构件类型',position:'安装位置',
 target_ids:'作用构件',orientation:'光学参数组含义',placement_basis:'安装依据',between_layers:'插入层位',layers:'材料层序',
 operation:'建筑运行',mode:'使用方式',settings:'运行设置',load_basis:'负荷口径',controls:'材料控制',application_id:'材料应用编号',
 channel:'控制对象',state_id:'固定或初始状态',face_id:'外表面光学参数组',rule:'反馈规则',update:'控制更新',minutes:'更新间隔 / min',
 policy:'反馈判据',cold_C:'低温阈值 / °C',hot_C:'高温阈值 / °C',flux_deadband_W_m2:'热流死区 / W/m²',minimum_hold_minutes:'最短保持时间 / min',
 state_roles:'反馈选择状态',positive:'抑制传热时选择',negative:'促进传热时选择',reference_runs:'控制参考计算',calendar:'参考日历',
 site_ids:'地点清单',site_id:'地点',period:'计算时段',aggregation:'汇总方式',weighting:'权重',missing:'缺失值处理',class_count:'气候类别数',
 step_minutes:'求解步长 / min',engine:'计算引擎',engine_files:'引擎文件核对信息',legacy_construction_overrides:'原构造修改',
 A_R:'A 组 · R 状态',A_C:'A 组 · C 状态',B_R:'B 组 · R 状态',B_C:'B 组 · C 状态',A:'A 组',B:'B 组'
};
const planEnums={
 controlled:'温控冷热需求',natural:'自然室温',both:'自然室温与温控',inherited:'继承原输入',fixed:'固定',feedback:'反馈调节',calendar:'按参考日历',
 thermal:'热学状态',orientation:'表面光学',R:'R 状态',C:'C 状态',A:'A 组',B:'B 组',UNIFIED:'统一反馈',GROUPED:'按朝向分组反馈',
 solver_step:'每个求解步',minutes:'固定分钟间隔',single_layer:'单层材料',independent:'独立状态',
 equivalent_resistance_no_layer_storage:'等效热阻，忽略该层蓄热',resistance:'直接输入热阻',conductivity_thickness:'厚度与导热系数',
 exterior:'外侧附加',interior:'内侧附加',between:'原构造两层之间',legacy_construction:'原构造指定',wall:'墙体',roof:'屋顶',floor:'楼板',window:'窗户',
 cooling_face:'A 组',other_face:'B 组',opaque_reflectance:'不透明材料反射率',inherit_frozen_building:'继承原建筑运行',
 zone_sensible_demand:'热区显热需求',climate:'气候类型',equal_sites:'代表地点等权',null:'保留无数据',
 frozen_model_family:'已冻结模型',legacy_outer_equivalent_model:'沿用原外侧等效模型'
};
function planEqual(a,b){
 if(a===b)return true;
 if(a===null||b===null||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
 const ak=Object.keys(a),bk=Object.keys(b);
 return ak.length===bk.length&&ak.every(k=>Object.hasOwn(b,k)&&planEqual(a[k],b[k]));
}
function planFields(a,b,path=[],out=[]){
 const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
 const key=path.at(-1);
 // Large evidence and calendars remain exact, expandable values rather than thousands of rows.
 if(['engine_files','calendar','legacy_construction_overrides'].includes(key)){
  out.push({path,a,b,equal:planEqual(a,b)});return out;
 }
 if((obj(a)||a===undefined)&&(obj(b)||b===undefined)&&(obj(a)||obj(b))){
  const keys=[...new Set([...Object.keys(a||{}),...Object.keys(b||{})])];
  if(keys.length){for(const k of keys)planFields(a?.[k],b?.[k],[...path,k],out);return out;}
 }
 const ar=Array.isArray(a)?a:[],br=Array.isArray(b)?b:[];
 if((Array.isArray(a)||a===undefined)&&(Array.isArray(b)||b===undefined)&&[...ar,...br].some(obj)){
  // Preserve recorded order, including layer order. Never merge states by numeric value.
  for(let i=0;i<Math.max(ar.length,br.length);i++)planFields(ar[i],br[i],[...path,i],out);
  return out;
 }
 out.push({path,a,b,equal:planEqual(a,b)});return out;
}
function planFieldName(path,group){
 let a=group==='numerics'?S.comparison?.left.numerics:S.comparison?.left.factors[group],b=group==='numerics'?S.comparison?.right.numerics:S.comparison?.right.factors[group];
 let opticsA,opticsB;
 return path.map(k=>{
  if(k==='optics'){opticsA=a;opticsB=b;}
  a=a?.[k];b=b?.[k];
  if(typeof k==='string'&&/^[AB]_[RC]$/.test(k)&&typeof miOpticsName==='function'&&(opticsA||opticsB)){const x=opticsA?miOpticsName(opticsA,k):null,y=opticsB?miOpticsName(opticsB,k):null;return x&&y&&x!==y?x+' → '+y:x||y;}
  if(typeof k!=='number')return planLabels[k]||k;
  const title=x=>x?.name?(x.id&&x.id!==x.name?`${x.name} (${x.id})`:x.name):x?.id||null;
  const at=title(a),bt=title(b);
  return at&&bt&&at!==bt?at+' → '+bt:at||bt||(planEnums[(b||a)?.channel]?'第 '+(k+1)+' 项 · '+planEnums[(b||a).channel]:'第 '+(k+1)+' 项');
 }).join(' › ');
}
function planValueText(value,key){
 if(value===undefined)return '未设置';
 if(value===null)return '未填写';
 if(value===true)return '是';if(value===false)return '否';
 if(typeof value==='number')return String(value); // Preserve precision: small changes remain visible.
 if(Array.isArray(value)){
  if(!value.length)return '空列表';
  if(key==='period'&&value.length===4)return `${value[0]}月${value[1]}日 至 ${value[2]}月${value[3]}日`;
  if(key==='site_ids')return value.map(id=>`${S.boot.sites[id]?.name||id}${S.boot.sites[id]?.climate?' · '+S.boot.sites[id].climate:''} [${id}]`).join('\n');
  if(value.every(x=>x===null||typeof x!=='object'))return value.map(String).join('、');
  return JSON.stringify(value,null,2);
 }
 if(typeof value==='object')return JSON.stringify(value,null,2);
 if(key==='site_id')return S.boot.sites[value]?.name||String(value);
 // Names and free text are never translated as enum values.
 return ['mode','channel','state_id','face_id','rule','kind','model','state_identity','thermal_input','position','component','A','B','input_basis','settings','load_basis','weighting','missing','definition_status','placement_basis','positive','negative'].includes(key)?planEnums[value]||String(value):String(value);
}
function planValue(value,key){
 const text=planValueText(value,key);
 if(text.length>240||text.split('\n').length>5){
  const hint=Array.isArray(value)?`${value.length} 项`:typeof value==='object'&&value?`${Object.keys(value).length} 项`:'长文本';
  return `<details class="plan-value"><summary>${hint} · 展开完整内容</summary><pre>${esc(text)}</pre></details>`;
 }
 return `<span class="plan-value-text">${esc(text)}</span>`;
}
function planPairCell(row,side){
 const key=row.path.at(-1),value=row[side];let note='';
 if(!row.equal&&['site_ids','target_ids','wall_ids'].includes(key)&&Array.isArray(row.a)&&Array.isArray(row.b)){
  const other=row[side==='a'?'b':'a'],unique=value.filter(x=>!other.includes(x));
  note=unique.length?`<div class="plan-membership"><small>仅${side==='a'?'参考':'研究'}包含 · ${unique.length} 项</small>${planValue(unique,key)}</div>`:
   `<small class="plan-membership">${row.a.length===row.b.length&&row.a.every(x=>row.b.includes(x))?'成员相同，数量或记录顺序不同':'没有仅此侧包含的项'}</small>`;
 }
 return planValue(value,key)+note;
}
function planDifferenceGroups(c){return [...factors,['numerics','计算设置']].map(([key,label])=>{
 const a=key==='numerics'?c.left.numerics:c.left.factors[key],b=key==='numerics'?c.right.numerics:c.right.factors[key];
 return {key,label,rows:planFields(a,b),equal:planEqual(a,b)};
});}
function planDifferenceBody(){
 if(!S.comparison)return '';
 const groups=planDifferenceGroups(S.comparison),changed=groups.filter(g=>!g.equal).length;
 return `<p class="muted">${changed?'有 '+changed+' 组记录不同':'四因素与计算设置的记录相同'}。逐项显示保存值，包含参数与来源说明；结果配对仍按建筑、运行、气象和数值设置核验。</p>`+groups.map(g=>{
  const rows=g.rows.filter(r=>!S.planDiffOnly||!r.equal),count=g.rows.filter(r=>!r.equal).length;
  return `<details class="plan-diff-group" data-plan-group="${g.key}"${count&&count<=12?' open':''}><summary>${g.label} · ${count?count+' 项不同':'相同'}</summary>${rows.length?`<p class="scroll-hint muted">窄屏可横向滑动，查看参考与研究双方。</p><div class="table-scroll"><table class="table plan-diff-table"><thead><tr><th>项目</th><th>基准方案</th><th>研究方案</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.equal?'':'plan-field-changed'}"><th scope="row">${esc(planFieldName(r.path,g.key))}${!r.equal?'<small>不同</small>':''}</th><td>${planPairCell(r,'a')}</td><td>${planPairCell(r,'b')}</td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">本组没有不同项，可取消“仅看不同项”查看。</p>'}</details>`;
 }).join('');
}
function planDifferencesView(){return `<section class="plan-differences"><div class="row"><h2>逐项对照</h2><label class="check"><input type="checkbox" id="plan-diff-only"${S.planDiffOnly?' checked':''}>仅看不同项</label></div><div id="plan-diff-body">${planDifferenceBody()}</div><p class="muted">设备投入在计算队列统一设置，不计入四因素差异。</p></section>`;}
function planVersionLabel(r){return typeof r.revision==='number'?'版本 '+r.revision:'原来源版本';}
function planVersionPick(side){
 const rows=S.planHistories[side]||[],current=S.comparison?.[side];
 if(!rows.length&&current)return `<label class="field">${side==='left'?'基准方案':'研究方案'}的保存版本<select disabled><option>${esc(planVersionLabel(current))} · 比较保存的快照</option></select></label>`;
 return `<label class="field">${side==='left'?'基准方案':'研究方案'}的保存版本<select data-compare-version="${side}">${rows.map((r,i)=>`<option value="${esc(r.revision)}"${String(current?.revision)===String(r.revision)?' selected':''}>${esc(planVersionLabel(r)+(i===0?' · 最新保存':'')+' · '+versionNoteLabel({id:current?.id,revision:r.revision})+' · '+readableTime(r.saved_at))}</option>`).join('')}</select></label>`;
}
function capturePlanComparisonDraft(){
 const name=document.getElementById('comparison-name'),metric=document.getElementById('comparison-metric');
 if(name&&metric)S.planComparisonDraft={name:name.value,metric:metric.value};
}
async function changePlanSelection(t){
 if(S.busy)return;
 const old={left:S.left,right:S.right,versions:{...S.compareVersions},comparison:S.comparison,histories:S.planHistories,draft:S.planComparisonDraft};
 S.busy=true;app.inert=true;nav.inert=true;notice('正在读取已保存版本…');capturePlanComparisonDraft();
 try{
  if(t.dataset.compare){const side=t.dataset.compare;S[side]=t.value;delete S.compareVersions[side+'_revision'];}
  else{const side=t.dataset.compareVersion,row=S.planHistories[side].find(r=>String(r.revision)===t.value);if(!row)throw Error('没有找到该版本，请重新读取方案。');S.compareVersions[side+'_revision']=row.revision;}
  await loadComparison();notice();
 }catch(error){S.left=old.left;S.right=old.right;S.compareVersions=old.versions;S.comparison=old.comparison;S.planHistories=old.histories;notice(error.message,'error');}
 finally{render();S.busy=false;app.inert=false;nav.inert=false;}
}
document.addEventListener('change',event=>{
 const t=event.target;
 if(t.id==='plan-diff-only'){S.planDiffOnly=t.checked;document.getElementById('plan-diff-body').innerHTML=planDifferenceBody();}
});
document.addEventListener('input',event=>{if(['comparison-name','comparison-metric'].includes(event.target.id))capturePlanComparisonDraft();});
