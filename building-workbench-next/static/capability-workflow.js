/* Capability feedback never saves records or generates inputs. */
S.capability=null;S.capabilityError='';S.planningOpen=false;S.guide=null;
let capabilityEpoch=0,capabilityTimer;
function capabilityKey(){return JSON.stringify([S.id,S.record?.revision,changes()]);}
function capabilityStatus(){
 const d=S.capability?.key===capabilityKey()?S.capability.data:null;
 if(!d)return `<p class="muted">${S.capabilityError?'支持状态暂未读取：'+esc(S.capabilityError):'正在检查当前设置…'}${S.capabilityError?' <button data-action="check-capability">重试检查</button>':''}</p>`;
 const label={ready:d.model_check_deferred?'控制设置已核对，生成输入时核对实际模型':'当前组合支持生成输入',unsupported:'可保存当前配置，计算适配尚未接通',incomplete:'当前设置需要完善'}[d.status];
 return `<p class="${d.supported?'muted':'warning'}"><strong>${label}</strong>${S.dirty?' · 未保存编辑':''}</p>${d.reasons.map(r=>`<p class="warning">${esc(r)}</p>`).join('')}${d.supported?'<p class="muted">生成时还会核对来源文件；本检查不生成输入或启动计算。</p>':''}`;
}
function updateCapabilityStatus(){const target=document.getElementById('capability-status');if(target)target.innerHTML=capabilityStatus();}
function scheduleCapability(){
 clearTimeout(capabilityTimer);++capabilityEpoch;S.capability=null;S.capabilityError='';updateCapabilityStatus();
 capabilityTimer=setTimeout(()=>refreshCapability(),300);
}
async function refreshCapability(){
 clearTimeout(capabilityTimer);const epoch=++capabilityEpoch,key=capabilityKey();S.capability=null;S.capabilityError='';
 try{const data=await api('/api/capabilities',{id:S.id,revision:S.record.revision,changes:changes()});if(epoch===capabilityEpoch&&key===capabilityKey())S.capability={key,data};}
 catch(error){if(epoch===capabilityEpoch&&key===capabilityKey())S.capabilityError=error.message;}
 if(epoch===capabilityEpoch)updateCapabilityStatus();
}
function capabilityPanel(){
 const g=S.boot.capability_guide.find(x=>x.key===S.factor);
 return `<div class="capability-note"><div id="capability-status" role="status" aria-live="polite">${capabilityStatus()}</div><details><summary>${esc(g.name)}的当前支持范围</summary><p>${esc(g.available)}</p><p class="muted">${esc(g.pending)}</p><button data-view="guide">查看工作区说明与待办</button></details></div>`;
}
function ordinaryTimeBasis(){
 if(S.record?.provenance.adapter!=='ordinary_building_v1')return '';
 const p=S.record.factors.scope.period,days=(Date.UTC(2025,p[2]-1,p[3])-Date.UTC(2025,p[0]-1,p[1]))/86400000+1;
 return `<div class="well" id="ordinary-time-basis"><h3>运行与统计时段</h3><p>正式统计：${p[0]} 月 ${p[1]} 日至 ${p[2]} 月 ${p[3]} 日${Number.isInteger(days)&&days>0?' · '+days+' 天':''}。</p><p>沿用原模型的求解器预热；预热结果不计入统计。当前没有额外的连续天气前置时段。</p><p class="muted">日期在“范围”中调整。时段与初始化说明会随生成输入保存，既有结果继续绑定其原版本。</p></div>`;
}
function planningPanel(){
 if(!S.planningOpen)return '';
 return `<section class="section" id="calculation-arrangement"><div class="row"><h2>计算安排</h2><button data-action="close-planning">收起安排</button></div><div class="grid2">${select('求解步长 / min','numerics.step_minutes',[1,2,5,10,15,30,60].map(x=>[x,String(x)]),S.record.numerics.step_minutes)}<div><p>步长随方案版本保存。控制更新间隔在工况中设置。</p><p class="muted">设备投入在“计算队列”中统一管理。</p></div></div>${S.preview?'':`<p class="muted">${S.dirty?'设置已修改，请重新预览；生成前需保存版本。':'预览地点与算例后，再生成输入。'}</p><button data-action="refresh-planning">更新计算预览</button>`}${ordinaryTimeBasis()}${previewPanel()}${generatedPanel()}</section>`;
}
function guideView(){
 const d=S.guide;if(!d)return '<section class="section">正在读取工作区说明…</section>';
 if(d.kind==='public_preparation')return publicGuideView(d);
 return `<section class="section"><h1>工作区说明与待办</h1><p class="muted">当前版本 ${esc(d.version)}。阶段回执记录当时状态；当前支持范围以本页及编辑时检查为准。</p><h2>常用入口</h2><div class="actions"><button data-view="editor">编辑方案与计算安排</button><button data-view="execution">计算队列与设备投入</button><button data-view="compare">比较与论文导出</button></div><p>在方案标题旁查看版本记录或打开计算安排；保存版本后生成输入、核对清单，再提交队列。</p><h2>四因素支持范围</h2><div class="guide-factors">${d.factors.map(g=>`<article class="well"><h3>${esc(g.name)}</h3><p>${esc(g.available)}</p><p class="muted">${esc(g.pending)}</p></article>`).join('')}</div><h2>本轮功能说明</h2><div class="actions">${(d.documents||[]).map(x=>`<a class="button" href="/api/workspace-docs/${esc(x.id)}" download>${esc(x.name)}</a>`).join('')}</div><h2>已接通</h2><ul>${d.completed.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><h2>下一阶段</h2>${d.next.map(x=>`<p><strong>${esc(x.id)} · ${esc(x.name)}</strong> · ${esc(x.status)}</p>`).join('')}<details><summary>完整待办与维护记录</summary><div class="actions"><a class="button" href="/api/workspace-docs/todos" download>下载完整待办表</a><a class="button" href="/api/workspace-docs/maintenance" download>下载维护与回归说明</a><a class="button" href="/api/workspace-docs/readme" download>下载当前使用说明</a><a class="button" href="/api/workspace-docs/weather" download>下载气象与来源说明</a><a class="button" href="/api/workspace-docs/component-updates" download>下载配置与材料更新说明</a><a class="button" href="/api/workspace-docs/source-recovery" download>下载缺失来源恢复说明</a><a class="button" href="/api/workspace-docs/source-locations" download>下载来源位置登记说明</a><a class="button" href="/api/workspace-docs/building-reuse" download>下载跨建筑复用说明</a><a class="button" href="/api/workspace-docs/ordinary-materials" download>下载五层建筑材料应用说明</a></div><p class="muted">历史证据继续保留；这里的待办不会自动安排新计算。</p></details></section>`;
}

function publicGuideView(d){
 return `<section class="section"><h1>${esc(d.title)}</h1><p>${esc(d.introduction)}</p><p class="muted">版本 ${esc(d.version)}</p><h2>从示例开始</h2><div class="guide-factors">${d.examples.map(x=>`<article class="well"><h3>${esc(x.name)}</h3><p><strong>${esc(x.period)}</strong></p><p>${esc(x.description)}</p><div class="actions">${x.records.map(r=>`<button data-example-record="${esc(r.id)}" data-example-revision="${esc(r.revision)}">${esc(r.label)}</button>`).join('')||'<span class="muted">按下方复现说明登记后即可打开。</span>'}</div></article>`).join('')}</div><h2>使用流程</h2><ol>${d.steps.map(t=>`<li>${esc(t)}</li>`).join('')}</ol><div class="actions"><button data-view="editor">编辑方案</button><button data-view="execution">计算队列</button><button data-view="compare">对照总览</button><button data-view="result-index">结果索引</button></div><h2>当前支持范围</h2>${miSupportMarkup(d.material_support)}<div class="guide-factors">${d.factors.map(g=>`<article class="well"><h3>${esc(g.name)}</h3><p>${esc(g.available)}</p><p class="muted">${esc(g.pending)}</p></article>`).join('')}</div><h2>理解结果</h2>${d.notes.map(t=>`<p>${esc(t)}</p>`).join('')}<h2>安装与复现资料</h2><div class="actions">${d.documents.map(x=>`<a class="button" href="/api/workspace-docs/${esc(x.id)}" download>${esc(x.name)}</a>`).join('')}</div></section>`;
}
