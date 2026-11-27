/* Layers run from outdoors to indoors. Source versions are resolved by the server on save. */
const stackModel = 'layer_stack_v1';
const stackLeaves = new Set(['optical_surface_v1','solid_layer_v1','solid_variable_v1','phase_change_layer_v1']);
mtNames.stack = '多层组合材料';

function stackSource(layer) {
    if (layer.version) return JSON.parse(layer.version);
    const ref = layer.reference;
    return mc().data.versions.find(row => row.id === ref.id && row.revision === ref.revision && row.sha256 === ref.sha256);
}
function stackTitle(row) { return row.name + ' · v' + row.revision; }
function stackDraft(name='',source_note='') {
    return {model:stackModel,name,source_note,id:'user_stack',kind:'layer_stack',category:'stack',
        state_identity:'independent',states:[{id:'R',name:'各层固定状态'}],faces:['A'],optics_depend_on_state:false,
        optics:{},layers:[],property_source:{method:'source_reference',note:'各层采用所列材料版本。'}};
}
const stackPreviousConvert = muConvert;
muConvert = function(d,mode,count) {
    if (mode === 'stack') return stackDraft(d.name,d.source_note);
    return stackPreviousConvert(d,mode,count);
};
const stackPreviousModel = mtModel;
mtModel = function(d) {
    return d.model === stackModel ? '由室外向室内排列。各层按保存状态起算，方案可指定一层两态实体参与热阻反馈。' : stackPreviousModel(d);
};
const stackPreviousFields = mcFields;
mcFields = function(d) {
    if (d.model !== stackModel) return stackPreviousFields(d);
    return d.layers.flatMap((layer,i) => {
        const row=stackSource(layer), leaf=row.content, s=leaf.states.find(s=>s.id===layer.state);
        const key='layers.'+i, title='第 '+(i+1)+' 层', o=leaf.optics[layer.face+'_'+(leaf.optics_depend_on_state?s.id:'R')]||{};
        const rows=[[title,stackTitle(row)+' · '+s.name+' · '+layer.face+' 面朝外',key]];
        if (s.thickness_mm!=null) rows.push([title+' · 厚度 / mm',s.thickness_mm,key+'.thickness'],[title+' · 导热率 / W/(m·K)',s.conductivity_W_mK,key+'.conductivity']);
        if (leaf.phase_change) rows.push([title+' · 相变温区 / °C',leaf.phase_change.solidus_C+' – '+leaf.phase_change.liquidus_C,key+'.pcm']);
        if (i===0) rows.push(['组合朝外面的太阳吸收率',o.solar_absorptance,key+'.solar'],['组合朝外面的长波发射率',o.emissivity,key+'.emissivity']);
        return rows;
    });
};
function stackLayerEditor(layer,i,count) {
    const row=stackSource(layer), d=row.content, index=String(i);
    const select=(label,key,items) => '<label class="field">'+label+'<select data-stack-field="'+key+'" data-layer="'+index+'">'+
        options(items,layer[key])+'</select></label>';
    const button=(op,text,disabled=false) => '<button data-mc="stack-'+op+'" data-layer="'+index+'" '+(disabled?'disabled':'')+'>'+text+'</button>';
    return '<fieldset><legend>第 '+(i+1)+' 层 · '+esc(stackTitle(row))+'</legend><div class="grid2">'+
        select('固定热学状态','state',d.states.map(s=>[s.id,s.name]))+
        select('朝外光学面','face',d.faces.map(f=>[f,f+' 面']))+'</div><div class="actions">'+
        button('up','向外移',i===0)+button('down','向内移',i===count-1)+button('remove','移除本层')+'</div></fieldset>';
}
const stackPreviousEditor = mcEditor;
mcEditor = function() {
    const v=mc(),d=v.draft;
    if (d.model !== stackModel) return stackPreviousEditor();
    const rows=v.data.versions.filter(r=>stackLeaves.has(r.content.model));
    const available=rows.map(r=>[r.id+':'+r.revision,stackTitle(r)]);
    return '<h2>'+ (v.parent?'编辑组合材料':'组合多层材料')+'</h2>'+mcInput('组合名称','name',d.name,'text')+
        '<h3>层序 · 从室外到室内</h3>'+
        d.layers.map((l,i)=>stackLayerEditor(l,i,d.layers.length)).join('')+
        (rows.length?'<label class="field">已保存的材料版本<select id="stack-source">'+options(available,available[0][0])+
        '</select></label><button data-mc="stack-add">加入最内侧</button>':'<p>请先在材料库保存实体材料、相变材料或表面涂层，再组合。</p>')+
        '<p>实体层各自传热。纯光学涂层放在第一层，铺设时朝向室外。工况可指定一层可调实体参与热阻反馈，初始状态取本组合的选择。</p>'+
        mcInput('组合说明','source_note',d.source_note,'text')+'<div class="actions"><button class="primary" data-mc="save" '+
        (v.pending||d.layers.length<2?'disabled':'')+'>保存组合版本</button><button data-mc="discard">撤销编辑</button></div>';
};
const stackPreviousAction = mcAction;
mcAction = async function(b) {
    const op=b.dataset.mc, v=mc();
    if (op!=='new-stack'&&!op?.startsWith('stack-')) return stackPreviousAction(b);
    if (v.pending) return;
    try {
        if (op==='new-stack') {
            mcCheckDraft(); v.draft=stackDraft(); v.parent=null; v.exampleOrigin=null;
        } else {
            const layers=v.draft.layers, i=Number(b.dataset.layer);
            if (op==='stack-add') {
                const key=document.querySelector('#stack-source').value;
                const row=v.data.versions.find(r=>r.id+':'+r.revision===key);
                layers.push({reference:{id:row.id,revision:row.revision,sha256:row.sha256},
                    state:row.content.states[0].id,face:row.content.faces[0]});
            } else if (op==='stack-remove') layers.splice(i,1);
            else {
                const dest=i+(op==='stack-up'?-1:1);
                if (dest>=0 && dest<layers.length) [layers[i],layers[dest]]=[layers[dest],layers[i]];
            }
        }
        v.preview=null; v.dirty=op!=='new-stack'; v.error=''; v.message='';
    } catch(e) { v.error=e.message; }
    render();
};

function stackInitialName(d,n) {
    const l=d.layers[n-1], src=l&&stackSource(l);
    return src?.content.states.find(s=>s.id===l.state)?.name||l?.state||'待核对';
}
function rememberStackFeedback() {
    const v=conditionCurrent(),picker=document.querySelector('#stack-feedback-layer');
    if(v&&picker)v.stackChoice={key:v.stackChoiceKey,layer:picker.value,targets:Array.from(document.querySelectorAll('[data-stack-wall]:checked'),n=>n.value)};
}
document.addEventListener('change',e=>{
    if(e.target.id==='stack-feedback-layer'||e.target.hasAttribute('data-stack-wall'))rememberStackFeedback();
});
function stackFeedbackPanel(d,a,current) {
    const choices=d.layers.flatMap((l,i)=>{
        const row=stackSource(l);
        return row.content.model==='solid_variable_v1'?[[String(i+1),'第 '+(i+1)+' 层 · '+stackTitle(row)+' · 初始 '+stackInitialName(d,i+1)]]:[];
    });
    if (!choices.length) return '<p>此组合各层均按材料版本中的状态计算。</p>';
    const v=conditionCurrent();
    v.stackChoiceKey=JSON.stringify([S.record.factors.materials.definition_reference?.sha256,a.target_ids,current]);
    const choice=v.stackChoice?.key===v.stackChoiceKey?v.stackChoice:null;
    const enabled=current?.mode==='feedback', active=new Set(choice?.targets||(enabled?current.target_ids:a.target_ids));
    return '<section><h3>组合层热阻反馈</h3><p>取上一完整时间步的房间空气温度和整面构件室外侧导热热流，按净面积和热区倍数汇总。1 分钟求解，默认每 5 分钟判断，最短保持 60 分钟。</p>'+
        '<label class="field">受控层<select id="stack-feedback-layer" '+(readonly()?'disabled':'')+'>'+
        options(choices,String(choice?.layer||current?.layer_number||choices[0][0]))+'</select></label>'+
        '<details><summary>选择参与反馈的构件（已铺 '+a.target_ids.length+' 个）</summary>'+
        a.target_ids.map(t=>'<label class="check"><input type="checkbox" data-stack-wall value="'+esc(t)+'" '+(active.has(t)?'checked ':'')+(readonly()?'disabled':'')+'>'+esc(t)+'</label>').join('')+
        '</details><p>其余已铺构件使用各层登记时选定的状态。</p><div class="actions"><button class="primary" data-condition-view="stack-feedback" '+(readonly()?'disabled':'')+'>'+
        (enabled?'更新反馈层与范围':'启用所选层反馈')+'</button>'+(enabled?'<button data-condition-view="stack-fixed" '+(readonly()?'disabled':'')+'>恢复固定组合</button>':'')+'</div></section>';
}
async function applyStackFeedback(v,disable) {
    if(readonly()||v.pending)return;
    const targets=disable?[]:Array.from(document.querySelectorAll('[data-stack-wall]:checked'),n=>n.value);
    if(!disable&&!targets.length)throw Error('请至少选择一个参与反馈的构件。');
    const layer_number=Number(document.querySelector('#stack-feedback-layer').value);
    const stamp=JSON.stringify([S.id,S.saved.revision,changes()]);
    v.pending=true;
    try {
        const result=await api('/api/material-library/stack-feedback',{id:S.id,revision:S.saved.revision,changes:changes(),layer_number,targets});
        if(conditionCurrent()!==v||JSON.stringify([S.id,S.saved.revision,changes()])!==stamp)throw Error('方案已变化，请重新选择。');
        v.stackChoice=null;v.undo=null;v.after=null;
        setPath('factors.condition.controls',result.controls);
        setPath('numerics.step_minutes',result.numerics.step_minutes);
        v.message=disable?'草稿已恢复固定组合。':'草稿已采用第 '+layer_number+' 层反馈，作用于 '+targets.length+' 个构件。';
    } finally {v.pending=false;}
    render();renderConditionViewer();
}

function stackLocation(app) {
    return app.position==='between'?'原构造第 '+app.after_layer+' 层之后':app.position==='interior'?'原构造内侧':'原构造外侧';
}
function stackNumber(value) {
    return Number.isFinite(value)?String(Number(value.toPrecision(6))):'待核对';
}
function stackExterior(d,orientation) {
    const layer=d.layers[0], leaf=stackSource(layer).content;
    const face=orientation?.face_basis==='exposed_layer'?orientation.face_id:layer.face;
    const state=leaf.optics_depend_on_state?layer.state:'R';
    return {face,registered:layer.face,faces:leaf.faces,optics:leaf.optics[face+'_'+state]||{}};
}
function stackOpticsLabel(exposed) {
    return esc(exposed.face)+' 组 · 太阳吸收率 '+stackNumber(exposed.optics.solar_absorptance)+' · 长波发射率 '+stackNumber(exposed.optics.emissivity);
}
function stackOpticsSummary(d,orientation) {
    if(orientation?.mode!=='calendar')return stackOpticsLabel(stackExterior(d,orientation));
    return ['A','B'].map((face,i)=>(i?'供暖日 · ':'制冷日 · ')+stackOpticsLabel(stackExterior(d,{face_basis:'exposed_layer',face_id:face}))).join('<br>');
}
function setStackCalendarStep(value) {
    const controls=copy(S.record.factors.condition.controls), optical=controls.find(c=>c.channel==='orientation');
    if(readonly()||optical?.mode!=='fixed')return;
    conditionBegin();
    if(value)optical.calendar_step_minutes=Number(value);
    else delete optical.calendar_step_minutes;
    setPath('factors.condition.controls',controls);
    conditionTrack();render();renderConditionViewer();
}
function stackCalendarReference(record) {
    const {materials,condition}=record.factors, d=materials.definitions[0], app=materials.applications[0];
    if(d?.model!==stackModel||app?.position!=='exterior'||stackExterior(d).faces.length<2)return '';
    const oc=condition.controls.find(c=>c.channel==='orientation'),tc=condition.controls.find(c=>c.mode==='feedback');
    if(!oc)return '';
    const inherited=tc?.reference_step_minutes??record.numerics.step_minutes;
    const steps=[1,2,5,10,15,30,60];
    return '<label class="field">原墙日历参考步长<select id="stack-calendar-step" '+(readonly()||oc.mode==='calendar'?'disabled':'')+'>'+
        '<option value="">沿用方案参考值（'+inherited+' min）</option>'+steps.map(n=>'<option value="'+n+'" '+(oc.calendar_step_minutes===n?'selected':'')+'>'+n+' min</option>').join('')+
        '</select></label><p>材料算例按 '+record.numerics.step_minutes+' min 求解。'+(oc.mode==='calendar'?'如需更换参考步长，先在材料控制中选择固定光学组。':'选择已有原墙结果的步长后，重新核对日历。')+'</p>';
}
function stackOpticsPanel(d,app,control) {
    if(app.position!=='exterior'||!control)return '';
    const exterior=stackExterior(d,control);
    if(exterior.faces.length<2)return '';
    const selected=control.mode==='calendar'?'calendar':control.face_basis==='exposed_layer'?control.face_id:'inherit';
    const choices=[['inherit','沿用组合版本（'+exterior.registered+' 组）'],...exterior.faces.map(f=>[f,'固定 '+f+' 组'])];
    return '<section><h3>最外层光学组</h3><p>'+stackOpticsSummary(d,control)+'</p><div class="actions">'+choices.map(([key,label])=>
        '<button data-condition-view="stack-optics" data-face="'+esc(key)+'" aria-pressed="'+(key===selected)+'"'+
        (key===selected||readonly()?' disabled':'')+'>'+esc(label)+'</button>').join('')+
        '<button data-condition-view="tab" data-condition-tab="calendar">'+(selected==='calendar'?'查看已采用的切换日历':'按日历切换…')+'</button></div></section>';
}
function setStackExterior(face,v) {
    if(readonly()||v.pending)return;
    const {materials,condition}=S.record.factors,app=materials.applications[0], d=materials.definitions[0];
    const controls=copy(condition.controls),oc=controls.find(c=>c.application_id===app.id&&c.channel==='orientation');
    if(d.model!==stackModel||app.position!=='exterior'||!oc||(face!=='inherit'&&!stackExterior(d,oc).faces.includes(face)))return;
    conditionBegin();
    if(oc.mode==='calendar'){
        setPath('factors.condition.reference_runs',condition.reference_runs.filter(ref=>ref.id!==oc.reference_id));
        delete oc.reference_id;oc.mode='fixed';
    }
    if(face==='inherit'){delete oc.face_basis;oc.face_id='A';}
    else {oc.face_basis='exposed_layer';oc.face_id=face;}
    setPath('factors.condition.controls',controls);
    conditionTrack();render();renderConditionViewer();
}
function stackPlanSummary(record) {
    const {materials,condition}=record.factors;
    return (materials.applications||[]).map(app=>{
        const d=materials.definitions.find(material=>material.id===app.material_id);
        if(d?.model!==stackModel)return '';
        const feedback=condition.controls.find(c=>c.application_id===app.id && c.channel==='thermal' && c.mode==='feedback');
        const orientation=condition.controls.find(c=>c.application_id===app.id&&c.channel==='orientation');
        const exterior=app.position==='exterior'?stackOpticsSummary(d,orientation):'';
        const rows=d.layers.map((layer,i)=>{
            const source=stackSource(layer),leaf=source.content,state=leaf.states.find(s=>s.id===layer.state);
            const active=feedback?.layer_number===i+1,pcm=leaf.phase_change;
            let params='';
            if(leaf.model==='optical_surface_v1'){
                params=exterior;
            }else{
                params=(active?leaf.states:[state]).map(s=>esc(s.name)+' '+stackNumber(s.thickness_mm/1000/s.conductivity_W_mK)+' m²·K/W').join('<br>');
                if(i===0&&exterior)params+='<br>'+exterior;
                if(pcm){
                    const latent=pcm.basis==='fraction'?pcm.latent_kJ_kg*pcm.mass_fraction:pcm.latent_kJ_kg;
                    params+='<br>相变温区 '+stackNumber(pcm.solidus_C)+'–'+stackNumber(pcm.liquidus_C)+' °C · 有效潜热 '+stackNumber(latent)+' kJ/kg';
                }
            }
            const mode=active?'初始'+esc(state.name)+' · '+feedback.target_ids.length+'/'+app.target_ids.length+' 个构件反馈':
                pcm?'按焓温关系计算':leaf.model==='optical_surface_v1'?(orientation?.mode==='calendar'?'按日历切换':'固定表面光学'):'固定'+esc(state.name);
            return '<tr><th>'+String(i+1)+' · '+esc(stackTitle(source))+'</th><td>'+mode+'</td><td>'+params+'</td></tr>';
        }).join('');
        return '<details data-stack-plan><summary>组合材料逐层设置 · '+esc(d.name)+'</summary><p>'+
            esc(stackLocation(app))+' · '+app.target_ids.length+' 个构件</p><div class="table-scroll"><table class="table"><thead><tr>'+
            '<th>材料层（室外 → 室内）</th><th>方案设置</th><th>材料版本参数</th></tr></thead><tbody>'+rows+'</tbody></table></div></details>';
    }).join('');
}
function stackInputReadback(stack) {
    if(!stack)return '';
    const calendar=stack.calendar_optics?'<p>最外层按日历切换 · '+['A','B'].map(f=>stackOpticsLabel({face:f,optics:stack.calendar_optics[f]})).join('；')+'。表中列出初始材料输入。</p>':'';
    const rows=stack.layers.flatMap((layer,i)=>layer.groups.map((group,j)=>{
        const coating=layer.model==='optical_surface_v1';
        const inputs=coating?'表面涂层 · 太阳吸收率 '+stackNumber(group.solar_absorptance)+' · 长波发射率 '+stackNumber(group.emissivity):
            stackNumber(group.thickness_mm)+' mm · 初始导热率 '+stackNumber(group.conductivity)+' W/(m·K)'+
            (group.emissivity===undefined?'':'<br>外表面太阳吸收率 '+stackNumber(group.solar_absorptance)+' · 长波发射率 '+stackNumber(group.emissivity));
        const physics=coating?'赋于实体外表面':[
            group.feedback?'导热率反馈':'固定导热率',
            group.enthalpy_points?'焓温曲线 '+group.enthalpy_points+' 点':layer.model==='phase_change_layer_v1'?'未写入焓温曲线':''
        ].filter(Boolean).join(' · ');
        return '<tr><th>'+String(i+1)+' · '+esc(stackTitle(layer))+'</th><td>第 '+group.slot+' 层</td><td>'+inputs+'<br>'+physics+
            '</td><td><details data-stack-group="'+i+'-'+j+'"><summary>'+group.surfaces.length+
            ' 个构件</summary>'+group.surfaces.map(esc).join('、')+'</details></td></tr>';
    })).join('');
    return '<h3>组合材料在模型中的实际层位</h3>'+calendar+'<div class="table-scroll"><table class="table"><thead><tr><th>组合层</th>'+
        '<th>含基墙的层序（从室外起）</th><th>写入模型的参数与控制</th><th>作用构件</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}
function stackWallInfo(d,app,orientation) {
    const parts=d.layers.map(l=>esc(stackTitle(stackSource(l))));
    const description='<p>'+esc(stackLocation(app))+' · '+parts.join(' → ')+'</p>';
    if(app.position!=='exterior')return description+'<p>室外侧沿用原构造外表面的光学参数。</p>';
    if(orientation?.mode==='calendar')return description+'<p>'+stackOpticsSummary(d,orientation)+'</p>';
    const {face,optics}=stackExterior(d,orientation);
    return description+wallOpticsGroup('最外层 · '+face+' 组',[['太阳吸收率',optics.solar_absorptance],
        ['长波发射率',optics.emissivity],['可见光吸收率',optics.visible_absorptance??'沿用原构造室外表面']]);
}
function stackSurfacePreview(audit) {
    if (audit?.model!==stackModel) return '';
    const names=audit.layers.filter(l=>l.model!=='optical_surface_v1').map(l=>l.name+' · v'+l.revision);
    const rows=audit.surfaces.map(s=>{
        const order=s.layers_after.map(key=>{
            const i=s.inserted_layers.indexOf(key);
            return esc(i<0?key:names[i]);
        });
        return '<tr><td>'+esc(s.surface)+'</td><td>'+order.join(' → ')+'</td></tr>';
    });
    return '<details><summary>核对各构件的实际层序（室外 → 室内）</summary>'+
        (audit.layers[0].model==='optical_surface_v1'?'<p>表面涂层的光学参数赋给最外侧实体层。</p>':'')+
        '<div class="viewer-table"><table class="table"><tbody>'+rows.join('')+'</tbody></table></div></details>';
}
function stackPlacement(choice,d) {
    const coated=stackSource(d.layers[0]).content.model==='optical_surface_v1';
    const positions=coated?[['exterior','外侧']]:[['exterior','外侧'],['interior','内侧'],['between','原构造层间']];
    const pos=choice.position||'exterior';
    return '<label class="field">整个组合的安装位置<select id="stack-position">'+options(positions,pos)+'</select></label>'+
        '<label class="field" id="stack-between" '+(pos==='between'?'':'hidden')+'>从室外数，插入原构造第几层之后'+
        '<input id="stack-index" type="number" min="1" step="1" value="'+esc(String(choice.after_layer||1))+'"></label>'+
        (coated?'<p>最外层为纯光学涂层，须暴露在室外。</p>':'');
}
function stackPlacementSelection() {
    const position=document.querySelector('#stack-position').value;
    return position==='between'?{position,after_layer:Number(document.querySelector('#stack-index').value)}:{position};
}
document.addEventListener('change', e=>{
    if (e.target.id==='stack-position') document.querySelector('#stack-between').hidden=e.target.value!=='between';
    if (e.target.dataset.stackField) {
        mc().draft.layers[Number(e.target.dataset.layer)][e.target.dataset.stackField]=e.target.value;
        mc().dirty=true; mc().preview=null;
    }
});
