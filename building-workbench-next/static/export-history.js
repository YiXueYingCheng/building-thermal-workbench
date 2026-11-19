/* Archived packages stay separate from live result data and plotting state. */
S.exportHistories={};
function exportOwner(kind){return kind==='comparison'?S.resultComparison?.comparison.id:S.executionResults?.id;}
async function refreshExportHistory(kind,id){
 const key=kind+':'+id,old=S.exportHistories[key];
 try{const data=await api('/api/export-history/'+kind+'/'+encodeURIComponent(id));S.exportHistories[key]={data,error:'',open:true};}
 catch(error){S.exportHistories[key]={data:old?.data,error:error.message,open:true};}
}
function archivedSource(id){return id==='historical'?'原正式历史结果':'批次 '+id;}
function exportHistoryView(kind,id){
 const key=kind+':'+id,state=S.exportHistories[key],data=state?.data;
 const current=kind==='comparison'?S.comparisonData:S.executionResults;
 const hash=current?.dataset_sha256;
 const seriesLabels={loads:'冷热需求',temperatures:'房间温度',thermal:'热阻状态',optical:'光学状态',schedules:'作息数值'};
 const labels={'comparison.zip':'完整图表与数据包','batch.zip':'完整批次数据包','figure.svg':'SVG','figure.pdf':'PDF','figure.png':'PNG','编辑说明.txt':'Origin 编辑说明','阅读说明.txt':'阅读说明','dataset.json':'数据与来源','climates.csv':'气候汇总 CSV','sites.csv':'地点 CSV','monthly.csv':'月度 CSV','period-loads.csv':'时段负荷 CSV','rooms.csv':'房间 CSV','room_temperatures.csv':'室温 CSV'};
 return `<div class="export-history" data-export-history-panel="${kind}"><div class="row"><button data-export-history="${kind}">${state?.open?'收起已导出数据包':'查看已导出数据包'}</button>${state?.open?`<button data-refresh-export-history="${kind}">刷新导出记录</button>`:''}</div>${state?.open?`
 <p class="muted">以下为导出时保存的快照，分别保留当时的版本与结果范围。下载原包不改变当前结果。</p>
 ${state.error?`<p class="warning">导出记录读取失败：${esc(state.error)}。${data?'下方保留上次读取的列表。':''}</p>`:''}
 ${data?`<p class="muted">读取于 ${esc(readableTime(data.checked_at))} · ${data.exports.length} 个通过文件核对的数据包。</p>${data.issues.length?`<details class="warning"><summary>${data.issues.length} 个导出包未能核对</summary><p>无法识别归属的包可能属于其他${kind==='comparison'?'比较':'批次'}；原文件保留。</p>${data.issues.map(x=>`<p>${esc(x.id)}：${esc(x.message)}</p>`).join('')}</details>`:''}
 <div class="export-history-list">${data.exports.map(r=>`<article class="export-history-card" data-archived-export="${esc(r.id)}"><div class="row"><h3>${esc(r.name)}</h3><span class="tag">${hash?(r.dataset_sha256===hash?'与当前读取结果一致':'与当前读取结果不同'):'尚未与当前结果比对'}</span></div><p class="muted">导出于 ${esc(readableTime(r.created))} · ${esc(periodLabel(r.period))} · ${esc(r.step_label)} · 包 ${esc(r.id.slice(-8))}</p>
 ${kind==='comparison'?`<div class="grid2">${['left','right'].map(s=>`<div><span class="source-role">${s==='left'?'基准':'研究'}</span><p>${esc(r.records[s].name)} · ${esc(planVersionLabel(r.records[s]))}</p><small class="muted">${esc(archivedSource(r.sources[s]))}</small></div>`).join('')}</div><p>${esc(modes[r.mode]||r.mode)} · 有效配对 ${r.paired_sites} / ${r.selected_sites} 地点 · ${esc(r.unit)}</p>`:`<p>${esc(planVersionLabel(r.record))} · 已接受 ${r.counts.accepted} / ${r.counts.total} 项 · 待复核 ${r.counts.pending_review} · 未完成 ${r.counts.unfinished}</p><p class="muted">${esc(r.modes.map(x=>modes[x]||x).join('、'))}；单批次负荷为 kWh，房间温度为 °C。</p>`}
 ${kind==='batch'?`<p>${r.selection?.length?'所选时序 · '+esc(r.selection.map(([g,f])=>seriesLabels[g]+' / '+(rtFreq[f]||f)).join('、')):'基础汇总'}</p>`:''}
 <div class="actions">${Object.entries(labels).filter(([file])=>r.files.includes(file)).map(([file,label])=>`<a class="button" data-export-file="${esc(file)}" download="${esc(file)}" href="/api/${kind}-exports/${esc(r.id)}/${encodeURIComponent(file)}">${label}</a>`).join('')}</div><details><summary>查看完整数据标识</summary><p class="source-path">${esc(r.dataset_sha256)}</p></details></article>`).join('')||`<p class="muted">${data.issues.length?'当前可核对记录中没有此项导出。':'此项尚无已保存导出，可在读取结果后使用原导出按钮。'}</p>`}</div>`:''}`:''}</div>`;
}
async function exportHistoryAction(button){
 const kind=button.dataset.exportHistory||button.dataset.refreshExportHistory;if(!kind)return false;
 const id=exportOwner(kind);if(!id)throw Error('请先打开对应比较或批次结果。');
 const key=kind+':'+id;
 if(button.dataset.exportHistory&&S.exportHistories[key]?.open)S.exportHistories[key].open=false;
 else await refreshExportHistory(kind,id);
 return true;
}
async function refreshOpenExportHistory(kind,id){if(S.exportHistories[kind+':'+id]?.open)await refreshExportHistory(kind,id);}
