/* Wall selection is local to the open plan. Generated evidence is pinned to a saved revision. */
function wallOpticsGroup(title, fields) {
 const value=n=>typeof n==='number'&&Number.isFinite(n)?String(Number(n.toFixed(8))):n??'未提供';
 return '<div class="wall-optics"><strong>'+esc(title)+'</strong><dl>'+
  fields.map(([label,n])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(String(value(n)))+'</dd></div>').join('')+'</dl></div>';
}

function wallLayerOptics(title, values) {
 if(!values)return '';
 const param=(key,fallback)=>values[key]??('默认 '+fallback);
 return wallOpticsGroup(title,[['太阳吸收率',param('solar_absorptance',0.7)],
  ['长波发射率',param('thermal_absorptance',0.9)],['可见光吸收率',param('visible_absorptance',0.7)]]);
}

function wallMaterialOptics(d,controls,visibleFallback) {
 if(!d)return '';
 const p=d.spectral;
 if(p){
  if(p.variant==='bare')return wallOpticsGroup('裸露发射层',[['太阳反射率',p.emitter_sw_reflectance],['8–13 µm 发射率',p.emitter_window_emissivity]]);
  if(p.variant==='broadband')return wallOpticsGroup('宽带辐射面',[['长波发射率',p.broadband_emissivity]])+
   '<small>太阳吸收率按覆盖系统匹配，可在已生成输入中核对。</small>';
  return wallOpticsGroup('PE 覆盖层 · 太阳波段',[['反射率',p.sw_reflectance],['透射率',p.sw_transmittance],
    ['吸收率',p.sw_reflectance!=null&&p.sw_transmittance!=null?1-p.sw_reflectance-p.sw_transmittance:null]])+
   wallOpticsGroup('PE 覆盖层 · 长波',[['8–13 µm 透射率',p.window_transmittance],['8–13 µm 吸收率',p.window_absorptance],['窗口外发射率',p.outside_window_emissivity]])+
   wallOpticsGroup('下层发射面',[['太阳反射率',p.emitter_sw_reflectance],['8–13 µm 发射率',p.emitter_window_emissivity]]);
 }
 const orientation=controls.find(c=>c.channel==='orientation'),thermal=controls.find(c=>c.channel==='thermal');
 if(!orientation||!thermal)return '<p>这面墙的热学状态或朝外光学组尚未指定。</p>';
 const faces=orientation.mode==='calendar'?['A','B']:[orientation.face_id];
 const states=thermal.mode==='feedback'?d.states.map(s=>s.id):[thermal.state_id];
 const split=d.optics_depend_on_state!==false || d.model==='equivalent_resistance_no_layer_storage';
 return faces.flatMap(face=>(split?states:['R']).map(id=>{
  const o=d.optics?.[face+'_'+id];
  const label=[face+' 面',split&&states.length>1?(d.states.find(s=>s.id===id)?.name||id):'',
    orientation.mode==='calendar'?'按日历切换':''].filter(Boolean).join(' · ');
  if(!o)return '<p>'+esc(label)+' 光学参数缺失。</p>';
  const alpha=o.input_basis==='opaque_reflectance'&&o.reflectance!=null?1-o.reflectance:o.solar_absorptance;
  return wallOpticsGroup(label,[['太阳吸收率',alpha],['长波发射率',o.emissivity],['可见光吸收率',o.visible_absorptance??visibleFallback]]);
 })).join('');
}

function wallApplicationSummary(w, data) {
 const factors=S.record.factors, materials=factors.materials;
 const apps=materials.applications.filter(a=>a.target_ids.includes(w.id));
 const allWalls=data.walls.filter(x=>x.exterior);
 const conditioned=new Set(data.rooms.filter(r=>r.conditioned).map(r=>r.id));
 const selected=geometryTargets(), covered=allWalls.filter(x=>selected.has(x.id));
 let scope='全楼可定位外墙已选 '+covered.length+' / '+allWalls.length+' 面';
 if(!data.unplotted_walls?.length && covered.length && covered.length<allWalls.length &&
    allWalls.every(x=>selected.has(x.id)===conditioned.has(x.room_id))) scope='已选空调房的全部外墙，共 '+covered.length+' 面';
 const row=S.configuration?.data.envelope?.[w.id]||S.configuration?.data.walls?.find(x=>x.id===w.id);
 const bound=clBound(w.id);
 const envelope=S.configuration?.data.envelope;
 const physical=envelope?.[w.id]?envelopeEffective(envelope,w.id,factors.building.envelope_overrides||{}).layers:row?.layer_details;
 const outer=physical?.[0];
 let layers=(physical||row?.layers||[]).map(l=>typeof l==='string'?l:l.name);
 if(bound){
  layers=bound.reference.content.layers.map(l=>l.material.name);
  if(bound.order==='reversed')layers.reverse();
 }
 const base=layers.length?layers.join(' → '):w.construction;
 const ref=materials.definition_reference;
 const legacy=apps.some(a=>a.placement_basis==='legacy_outer_equivalent_model');
 const applied=apps.map(a=>{
  const d=materials.definitions.find(x=>x.id===a.material_id);
  const version=ref?.content?.id===a.material_id?' · 库版本 v'+ref.revision:' · 随方案保存';
  const pos=({exterior:'外侧',interior:'内侧',between:'层间',legacy_construction:'来源构造'})[a.position]||a.position;
  const controls=factors.condition.controls.filter(c=>c.application_id===a.id && c.target_ids.includes(w.id));
  const describe=c=>{
   if(c.channel==='thermal'){
    const state=d?.states?.find(s=>s.id===c.state_id);
    if(c.mode==='fixed')return '热学固定（'+(state?.name||c.state_id)+'）';
    if(c.mode==='feedback')return '热阻反馈（'+[c.rule,state?'初始 '+state.name:''].filter(Boolean).join('，')+'）';
   }
   if(c.channel==='orientation' && c.mode==='fixed')return '朝外光学组 '+c.face_id;
   if(c.channel==='orientation' && c.mode==='calendar')return '光学组按日历切换';
   return c.mode;
  };
  const hasBase=['Material','Material:NoMass'].includes(outer?.kind)&&outer.values;
  const fallback=['fixed_surface_material_v1','fixed_exterior_movable_v1'].includes(a.placement_basis)?
   (hasBase?(outer.values.visible_absorptance??0.7)+'（沿用外表面）':'沿用基础外表面'):a.surface_model?.visible_absorptance;
  return '<p><strong>'+esc(d?.name||a.material_id)+'</strong>'+esc(version)+'<br>'+esc([pos,...controls.map(describe)].join(' · '))+'</p>'+
   wallMaterialOptics(d,controls,fallback);
 }).join('');
 return '<p><strong>'+(apps.length?'已铺研究材料':'未铺研究材料')+'</strong> · '+esc(scope)+'</p>'+
    (apps.length?applied:'<p>'+(!materials.applications.length?'方案未设置研究材料铺设。':'此墙号未列入方案的材料作用范围。')+'</p>')+
    (legacy?'<p class="muted">此版本采用活动保温层。可展开已生成输入，核对该墙的材料和控制日程。</p>':'')+
    '<p>基础层序（外 → 内）<br>'+esc(base)+'</p>'+
    (['Material','Material:NoMass'].includes(outer?.kind)?wallLayerOptics('基础外表面',outer.values):'');
}

function wallInputMarkup(v,w) {
 if(S.dirty||S.usageDirty)return '<p class="muted">当前显示草稿。保存方案并生成对应输入后，可核对实际构造。</p>';
 const state=v.wallInput;
 if(!state)return '<button data-viewer="wall-input">核对已生成输入</button>';
 const bundle=state.bundles?.find(b=>b.id===state.bundle);
 const choices=(state.bundles?.length>1?'<label class="field">保存的输入包<select id="wall-input-bundle">'+options(state.bundles.map(b=>[b.id,b.created+' · '+b.case_count+' 个算例 · '+b.id.slice(-6)]),state.bundle)+'</select></label>':'')+
    (state.cases?.length?'<label class="field">核对算例<select id="wall-input-case">'+options(state.cases.map((c,i)=>[i,[c.city||c.site_id,modes[c.mode]||c.mode,c.period?periodLabel(c.period):'',c.step_minutes?c.step_minutes+' min':''].filter(Boolean).join(' · ')]),state.index)+'</select></label>':'');
 let body='';
 if(state.error)body='<p class="warning">'+esc(state.error)+'</p><button data-viewer="wall-input">重新读取</button>';
 else if(state.loading)body='<p role="status">正在读取保存的计算输入…</p>';
 else if(!bundle)body='<p>此保存版本尚无可核对的输入包。</p>';
 else if(!state.model)body='<p>此输入包没有算例。</p>';
 else {
  const m=state.model, construction=m.walls[w.id], layers=m.stacks[construction];
  body=construction?'<p>模型构造 · '+esc(construction)+'</p><p>实际层序（外 → 内）</p>'+
   (layers?'<ol>'+layers.map(layer=>'<li>'+esc(layer)+'</li>').join('')+'</ol>':'<p>此构造类型未提供常规分层。</p>')+
   wallLayerOptics('输入文件 · 构造最外层',m.layer_optics?.[layers?.[0]])+
   (construction && S.record.factors.condition.controls.some(c=>c.mode!=='fixed'&&c.target_ids.includes(w.id))?
    '<p>这里列出输入文件中的材料值。运行时的状态或朝外面由此墙的控制设置决定。</p>':'')+
   (m.exterior_heat_sources[w.id]?'<p>外表面另有换热日程 · '+esc(m.exterior_heat_sources[w.id])+'。分波段辐射通过该日程耦合，材料字段中的长波值只代表引擎原生项。</p>':'')+
   (m.insulation[w.id]||[]).map(x=>'<p>活动保温层 · '+esc(x.material_name)+' · '+esc(x.schedule_name)+'</p>'+
      wallLayerOptics('输入文件 · 活动保温层',m.layer_optics?.[x.material_name])).join(''):
   '<p class="warning">该算例没有找到此墙号。</p>';
  body+='<a target="_blank" rel="noopener" href="/api/model-inputs/'+encodeURIComponent(bundle.id)+'/'+encodeURIComponent(m.file)+'">查看算例模型 ↗</a>';
 }
 return '<h4>已生成输入 · 方案 v'+esc(S.saved.revision)+'</h4>'+choices+body;
}

async function loadWallInput(v, bundleId, index) {
 const previous=v.wallInput;
 const state={loading:true,bundles:bundleId?previous?.bundles:null,bundle:bundleId,
              cases:bundleId && bundleId===previous?.bundle?previous.cases:null,index:index??0};
 v.wallInput=state;
 function update() {
  if(buildingViewerCurrent()!==v || v.wallInput!==state)return;
  const w=geometryState().data?.walls.find(x=>x.id===geometryState().wall);
  const slot=buildingViewerDialog().querySelector('[data-wall-input-slot]');
  if(w && slot)slot.innerHTML=wallInputMarkup(v,w);
 }
 update();
 const query=new URLSearchParams({record:S.saved.id,revision:S.saved.revision});
 try {
  if(!state.bundles){
   const activity=await api('/api/plan-activity/'+encodeURIComponent(S.saved.id)+'?revision='+encodeURIComponent(S.saved.revision));
   if(!activity.inputs.length && activity.issues.length)throw Error(activity.issues.join('；'));
   state.bundles=activity.inputs;state.bundle=activity.inputs[0]?.id;
  }
  if(!state.bundle || v.wallInput!==state || buildingViewerCurrent()!==v)return;
  const route='/api/input-inspection/'+encodeURIComponent(state.bundle)+'/wall-model';
  if(!state.cases)state.cases=(await api(route+'?'+query)).cases;
  if(state.cases.length && v.wallInput===state && buildingViewerCurrent()===v)
   state.model=await api(route+'/'+state.index+'?'+query);
 }catch(e){state.error=e.message;}
 finally{state.loading=false;update();}
}
