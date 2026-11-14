/* Building choice creates an ordinary scheme through the existing version flow. */
const beforeBuildingSidebar=sidebar;
sidebar=function(){const sources=S.boot.records.filter(r=>r.id==='global_w00'||(r.adapter==='ordinary_building_v1'&&r.status==='imported'));const choice=`<section class="well"><label class="field">从建筑开始<select id="building-template">${sources.map(r=>`<option value="${r.id}"${S.record?.factors.building.name===r.building?' selected':''}>${esc(r.building)}</option>`).join('')}</select></label><button data-building-template>查看建筑原配置</button><p class="muted">查看后“另存为研究方案”，再编辑本次研究。</p></section>`;return beforeBuildingSidebar().replace('<aside class="sidebar">','<aside class="sidebar">'+choice);};
const beforeOrdinaryMaterials=materialsPanel;
materialsPanel=function(){if(S.record.provenance.adapter!=='ordinary_building_v1')return beforeOrdinaryMaterials();return '<h2>保留普通建筑构造</h2><p>基础墙体、楼板、门窗在“建筑”中查看与编辑。本方案尚未添加研究材料。</p><p class="muted">此建筑的动态材料、作用墙分组与参考日历仍需单独适配。</p>';};
const envelopeLabels={thickness:'厚度 / m',conductivity:'导热系数 / W/(m·K)',density:'密度 / kg/m³',specific_heat:'比热 / J/(kg·K)',thermal_absorptance:'热发射率',solar_absorptance:'太阳吸收率',visible_absorptance:'可见光吸收率',u_factor:'U / W/(m²·K)',solar_heat_gain_coefficient:'SHGC',visible_transmittance:'可见光透射率'};
const surfaceTypes={Wall:'墙',Roof:'屋顶',Floor:'楼板',Ceiling:'顶板',Door:'门',Window:'窗'};
const beforeOrdinaryBuilding=buildingPanel;
buildingPanel=function(){let html=beforeOrdinaryBuilding();if(S.record.provenance.adapter!=='ordinary_building_v1')return html;
 const d=S.configuration?.data;html+=`<div class="configuration-toolbar"><button data-ordinary-envelope>${S.envelopeOpen?'收起':'查看'}普通构造</button></div>`;
 if(!d)return html;
 if(!S.envelopeOpen)return html;
 html+=envelopeEditor(d.envelope);
 return html;
};
const beforeOrdinaryAction=configurationAction;
configurationAction=async function(button){
 if(button.hasAttribute('data-building-template')){await loadRecord(document.getElementById('building-template').value);S.factor='building';await loadConfiguration();return true;}
 if(button.hasAttribute('data-ordinary-envelope')){await loadConfiguration();S.envelopeOpen=!S.envelopeOpen;return true;}
 if(button.hasAttribute('data-envelope-clear')){const x=copy(S.record.factors.building.envelope_overrides||{});delete x[S.envelopeTarget];if(Object.keys(x).length)setPath('factors.building.envelope_overrides',x);else{delete S.record.factors.building.envelope_overrides;S.dirty=true;S.preview=null;S.generated=null;scheduleCapability();}return true;}
 return beforeOrdinaryAction(button);
};
document.addEventListener('change',event=>{if(event.target.id==='envelope-target'){S.envelopeTarget=event.target.value;render();}});
document.addEventListener('input',event=>{const t=event.target;if(!t.dataset.envelopeField||readonly())return;
 const all=S.configuration.data.envelope,row=all[S.envelopeTarget],x=copy(S.record.factors.building.envelope_overrides||{});
 if(x[row.pair]||(S.record.factors.building.library_constructions||[]).some(e=>e.target_ids.includes(row.id)))return;
 x[row.id]??={layers:row.layers.map(l=>({kind:l.kind,values:copy(l.values)}))};x[row.id].layers[Number(t.dataset.envelopeLayer)].values[t.dataset.envelopeField]=t.value===''?null:Number(t.value);
 setPath('factors.building.envelope_overrides',x);updateDirtyStatus();
});
