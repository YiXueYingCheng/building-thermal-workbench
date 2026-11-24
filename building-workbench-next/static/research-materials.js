/* Physical inputs shared by the catalog, portable exports and plan previews. */
const researchModel = d => ['phase_change_layer_v1','spectral_exterior_v1'].includes(d?.model);
const researchVariants = [['covered','PE 覆盖发射层'],['bare','裸露选择性发射层'],['broadband','常规宽带制冷面（匹配太阳吸收）']];
const researchBases = [['effective','材料整体的有效潜热（含纯 PCM）'],['fraction','按 PCM 质量分数估算']];
const researchThermal = [['thickness_mm','厚度 / mm'],['conductivity_W_mK','导热率 / W/(m·K)'],
    ['density_kg_m3','密度 / kg/m³'],['specific_heat_J_kgK','比热 / J/(kg·K)']];
const spectralBand = '大气窗口（8–13 µm）';
function spectralSections(variant) {
    const stateFields=researchThermal.map(([key,label])=>['states.0.'+key,label]);
    const field=(key,label)=>['spectral.'+key,label];
    const peSolar=[field('sw_reflectance','PE 太阳反射率'),field('sw_transmittance','PE 太阳透射率')];
    const emitterSolar=field('emitter_sw_reflectance','发射层太阳反射率');
    const heat=['热物性',stateFields];
    if(variant==='broadband')return [
        ['宽带制冷面与载体',[['热辐射',[field('broadband_emissivity','宽带长波发射率')]],heat]],
        ['短波匹配依据',[['参考覆盖结构的太阳光学参数',[...peSolar,emitterSolar]]],'solar-match']
    ];
    const sections=[];
    if(variant==='covered')sections.push(['外层 · PE 覆盖层',[
        ['传热',[field('pe_resistance','PE 热阻 / m²·K/W')]],
        ['太阳短波',peSolar],
        [spectralBand,[field('window_transmittance','PE 透射率'),field('window_absorptance','PE 吸收率')]],
        ['其余热红外波段',[field('outside_window_emissivity','PE 朝向室外一面的发射率')]]
    ]]);
    sections.push([variant==='covered'?'内层 · 选择性发射层与载体':'裸露的选择性发射层与载体',[
        ['太阳短波',[emitterSolar]],[spectralBand,[field('emitter_window_emissivity','发射层发射率')]],heat
    ]]);
    return sections;
}

function spectralSolarText(p) {
    const {sw_reflectance:r,sw_transmittance:t,emitter_sw_reflectance:b}=p;
    if(![r,t,b].every(v=>Number.isFinite(v)&&v>=0&&v<=1))return '请填写三项 0–1 的短波参数以计算匹配值。';
    if(r+t>1+1e-12)return 'PE 太阳反射率与透射率之和超过 1，请核对。';
    // Same multiple-reflection balance as research_materials.solar_split.
    const through=r*b<1?t/(1-r*b):0;
    const total=(1-r-t)*(1+b*through)+(1-b)*through;
    return '匹配后的宽带面太阳吸收率为 '+total.toFixed(4)+'。';
}

function spectralEditor(d) {
    const variant=d.spectral.variant;
    const paths={
        covered:'室外 → PE 覆盖层 → 选择性发射层与载体 → 基墙',
        bare:'室外 → 裸露选择性发射层与载体 → 基墙',
        broadband:'室外 → 常规宽带制冷面与载体 → 基墙'
    };
    const sections=spectralSections(variant).map(([title,groups,role])=>{
        const match=role==='solar-match';
        const content=groups.map(([band,fields])=>'<h4>'+band+'</h4><div class="grid2">'+
            fields.map(([key,label])=>mcInput(label,key,researchValue(d,key))).join('')+'</div>').join('');
        return '<fieldset><legend>'+title+'</legend>'+
            (match?'<p>下列参数来自用于对照的 PE 覆盖结构，用来匹配宽带面的太阳吸收率。</p>':'')+content+
            (match?'<p><output data-spectral-solar>'+spectralSolarText(d.spectral)+'</output></p>':'')+'</fieldset>';
    }).join('');
    return '<label class="field">辐射结构<select data-mc-field="spectral.variant">'+
        options(researchVariants,variant)+'</select></label><p class="muted">'+paths[variant]+'</p>'+sections;
}
function researchFields(d) {
    if(d.spectral)return spectralSections(d.spectral.variant).flatMap(([title,groups])=>
        groups.flatMap(([band,rows])=>rows.map(([k,label])=>[k,title+' · '+band+' · '+label])));
    const fields=researchThermal.map(([k,name])=>['states.0.'+k,name]);
    if(d.phase_change) {
        fields.push(['phase_change.solidus_C','固相线 / °C'],['phase_change.liquidus_C','液相线 / °C'],
            ['phase_change.latent_kJ_kg',d.phase_change.basis==='fraction'?'纯 PCM 潜热 / kJ/kg':'材料有效潜热 / kJ/kg']);
        if(d.phase_change.basis==='fraction')fields.push(['phase_change.mass_fraction','PCM 质量分数 / 0–1']);
        fields.push(['optics.A_R.solar_absorptance','外表面太阳吸收率'],['optics.A_R.emissivity','外表面长波发射率']);
    }
    return fields;
}
function researchValue(d,path){return path.split('.').reduce((value,key)=>value?.[key],d);}
const originalResearchFields=mcFields;
mcFields=function(d){
    if(!researchModel(d))return originalResearchFields(d);
    const x=d.phase_change, choices=x?researchBases:researchVariants;
    return [['计算方式',muProfile(d)?.name],['参数组',choices.find(r=>r[0]===(x?x.basis:d.spectral.variant))?.[1]],
        ...researchFields(d).map(([k,name])=>[name,researchValue(d,k),k]),['物性来源',d.property_source.note]];
};
const originalResearchModel=mtModel;
mtModel=function(d){return researchModel(d)?muProfile(d)?.description:originalResearchModel(d);};
Object.assign(mtNames,{pcm:'相变材料',spectral:'辐射界面解耦与对照'});
const originalResearchEditor=mcEditor;
mcEditor=function(){
    const v=mc(),d=v.draft;
    if(!researchModel(d))return originalResearchEditor();
    const pcm=!!d.phase_change;
    const fields=pcm?researchFields(d):[];
    const inputs=rows=>rows.map(([k,name])=>mcInput(name,k,researchValue(d,k))).join('');
    return '<h2>'+ (v.parent?'编辑材料版本':'登记材料')+'</h2>'+mcInput('材料名称','name',d.name,'text')+
        '<label class="field">计算方式<select data-mu-mode '+(v.parent?'disabled':'')+'>'+
        options(v.data.registration.modes.map(r=>[r.id,r.name]),muMode(d))+'</select></label>'+
        (pcm?'<h3>相变层热物性</h3><div class="grid2">'+inputs(fields.slice(0,4))+'</div>'+
        '<label class="field">潜热依据<select data-mc-field="phase_change.basis">'+options(researchBases,d.phase_change.basis)+'</select></label>'+
        '<div class="grid2">'+inputs(fields.slice(4))+'</div><p class="muted">潜热填 0 可派生等物性显热对照。</p>':spectralEditor(d))+
        '<label class="field">物性来源<select data-mc-field="property_source.method">'+options(Object.entries(miMethodNames),d.property_source.method)+'</select></label>'+
        mcInput('来源与假设','property_source.note',d.property_source.note,'text')+
        mcInput('补充说明','source_note',d.source_note,'text')+
        '<div class="actions"><button class="primary" data-mc="save" '+(v.pending?'disabled':'')+'>保存材料版本</button><button data-mc="discard">撤销编辑</button></div>';
};
const originalResearchConvert=muConvert;
muConvert=function(d,mode,count){
    if(!researchModel(d)&&!['pcm','spectral'].includes(mode))return originalResearchConvert(d,mode,count);
    const t=copy(mode==='resistance'?mc().data.registration.resistance_template:mc().data.templates[
        ['pcm','spectral'].includes(mode)?mode:mode==='optical'?'film':count===2?'variable':'solid']);
    t.name=d.name;t.source_note=d.source_note;
    if(t.property_source&&d.property_source)t.property_source=copy(d.property_source);
    return t;
};
const originalResearchDetails=mcDetails;
mcDetails=function(){
    const r=mcRow();
    if(mc().draft||mc().tab==='sources'||!researchModel(r?.content))return originalResearchDetails();
    if(r.builtin)return '<h2>'+esc(r.name)+'</h2><p>'+esc(r.content.source_note)+'</p>'+mcTable(r.content)+
        '<button class="primary" data-mc="clone">复制为我的材料</button> <button data-material-transfer="export">导出材料 JSON</button> <button data-mi="export">导出材料 CSV</button>';
    const t=document.createElement('template');
    t.innerHTML=originalResearchDetails();
    t.content.querySelectorAll('#mt-adopt-target option').forEach(el=>{if(['both','roofs'].includes(el.value))el.remove();});
    return t.innerHTML;
};
const researchShowAdoption=mcShowAdoption;
mcShowAdoption=function(){
    researchShowAdoption();
    const data=mc().preview?.data,a=data?.audit;
    if(!a?.research_parameters)return;
    const rows=a.surfaces.map(w=>'<tr><td>'+esc(w.surface)+'</td><td>'+format(w.net_m2,2)+'</td><td>'+w.apertures.length+'</td><td>'+w.layers_after.map(esc).join(' → ')+'</td></tr>').join('');
    const text=a.model==='phase_change_layer_v1'?'外置相变层 · 有限差分，计算安排选择 1 或 2 分钟':'载体外表面 · 分波段天空辐射与外层热平衡';
    mcAdoptionDialog().querySelector('.mc-preview-body').insertAdjacentHTML('afterbegin','<p>'+text+' · 净面积 '+format(a.net_m2,2)+' m²</p><details><summary>查看逐墙层序、洞口与面积</summary><table class="table"><tr><th>外墙</th><th>净面积 / m²</th><th>洞口</th><th>从室外到室内</th></tr>'+rows+'</table></details>');
};
document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-research-response]');
    if(!button)return;
    const req={...comparisonRequest(),site_id:document.getElementById('material-response-site').value};
    const dialog=document.createElement('dialog');
    dialog.className='library-adoption';
    dialog.innerHTML='<header class="viewer-head"><h2>材料响应</h2><button>关闭</button></header><div class="mc-preview-body" role="status">正在读取逐步结果…</div>';
    dialog.querySelector('button').onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    document.body.append(dialog);dialog.showModal();
    const box=dialog.querySelector('[role=status]');
    try {
        const data=await api('/api/material-response',req);
        const rows=[];
        const add=(title,getValue)=>rows.push('<tr><td>'+esc(title)+'</td>'+['left','right'].map(s=>'<td>'+format(getValue(data[s]),3)+'</td>').join('')+'</tr>');
        add('覆盖净面积 / m²',r=>r.area_m2);
        for(const [id,label] of [['day','有日照'],['night','无日照']]){
            if(!data.left.segments[id]||!data.right.segments[id])continue;
            add(label+' · 材料层外侧温度 / °C',r=>r.segments[id].emitter_C);
            add(label+' · 向室内净热流 / W/m²',r=>r.segments[id].inward_W_m2);
            if(data.left.model==='spectral_exterior_v1'&&data.right.model===data.left.model)
                add(label+' · 暴露面温度 / °C',r=>r.segments[id].cover_C);
        }
        if(data.left.pcm&&data.right.pcm){
            add('潜热吸收 / kWh',r=>r.pcm.charged_kWh);add('潜热释放 / kWh',r=>r.pcm.released_kWh);
            add('首个时步储存的潜热 / kWh',r=>r.pcm.initial_storage_kWh);add('末个时步储存的潜热 / kWh',r=>r.pcm.final_storage_kWh);
            add('潜热变化时长 / h',r=>r.pcm.active_hours);
            add('相变活动期间制冷需求 / kWh',r=>r.pcm.cooling_during_activity_kWh);
        }
        box.innerHTML='<table class="table"><thead><tr><th>指标</th><th>参考方案</th><th>研究方案</th></tr></thead><tbody>'+rows.join('')+'</tbody></table><p>各墙按净面积加权。以所选墙面平均日照超过 1 W/m² 划分时段。入室净热流正值表示热量传向室内。</p>';
    }catch(e){box.textContent=e.message;}
});
document.addEventListener('input',event=>{
    if(!['spectral.sw_reflectance','spectral.sw_transmittance','spectral.emitter_sw_reflectance'].includes(event.target.dataset.mcField))return;
    const out=event.target.closest('fieldset')?.querySelector('[data-spectral-solar]');
    if(out)out.textContent=spectralSolarText(mc().draft.spectral);
});
