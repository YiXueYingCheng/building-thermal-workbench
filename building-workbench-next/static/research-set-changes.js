/* Accepted sensible-demand comparisons within the currently selected set revision. */
const rsChangeMetrics = ['heating_kWh', 'cooling_kWh', 'total_kWh'];
const rsChangeHeadings = '<th scope="col">供暖</th><th scope="col">制冷</th><th scope="col">合计</th>';

function rsChangePair(data, selected, site, role) {
  const order = Object.keys(rsRoles).filter(key => Object.hasOwn(data.members, key));
  const index = order.indexOf(role);
  if (index < 1) return null;
  const reference = RS.changeMode === 'adjacent' ? order[index - 1] : 'baseline';
  function member(key) {
    const batch = selected[key];
    const row = batch?.results.find(item => item.accepted && item.site_id === site && item.mode === 'controlled');
    return {row, batchId:row?.batch_id || batch?.batch_id};
  }
  const left = member(reference), right = member(role);
  const title = rsRoles[reference] + ' → ' + rsRoles[role];
  let reason = '';
  if (!data.audit.consistent || S.boot.sites[site]?.eligible === false) reason = '共同条件或地点待核对';
  else if (!left.row || !right.row) reason = '缺少已选且通过核验的温控结果，请查看结果来源';
  else if (![reference, role].every(key => key === 'baseline' || rsPair(data, selected, key, site, 'controlled'))) {
    reason = '尚未与同条件 W00 完成配对';
  } else if (![left, right].every(side => rsChangeMetrics.every(key => Number.isFinite(side.row.loads?.[key])))) {
    reason = '显热需求数据不完整';
  }
  return {reference, role, title, left, right, reason};
}

function rsChangeNumber(value, unit = '') {
  if (value > 0 && value < 0.005) return '&lt;0.01' + unit;
  return format(value, 2) + unit;
}

function rsChangeCell(before, after, withRate) {
  if (!Number.isFinite(before) || !Number.isFinite(after)) return '<td class="muted">无数据</td>';
  const saving = before - after;
  const direction = saving > 0 ? '减少' : saving < 0 ? '增加' : '持平';
  const tone = saving > 0 ? 'reduction' : saving < 0 ? 'increase' : 'unchanged';
  const rate = before > 0 ? rsChangeNumber(Math.abs(saving) / before * 100, '%') : '参考为零，比例不适用';
  return `<td class="rs-delta ${tone}"><span class="rs-direction">${direction}</span> <strong>${rsChangeNumber(Math.abs(saving))}</strong>${withRate ? `<small>${rate}</small>` : ''}</td>`;
}

function rsChangesView(data, selected) {
  const sites = data.scope.site_ids;
  if (!sites.length) return '';
  if (!sites.includes(RS.changeSite)) RS.changeSite = sites[0];
  const site = RS.changeSite;
  const city = id => S.boot.sites[id]?.name || id;
  const selector = sites.length > 1
    ? `<label class="field">地点<select id="rs-change-site">${options(sites.map(id => [id, city(id)]), site)}</select></label>`
    : `<strong>${esc(city(site))}</strong>`;
  const modes = [['baseline','相对 W00'], ['adjacent','相邻工况']].map(([key,label]) =>
    `<button type="button" data-rs-change-mode="${key}" aria-pressed="${RS.changeMode === key}">${label}</button>`).join('');
  const rows = Object.keys(rsRoles).filter(role => role !== 'baseline' && data.members[role]).map(role => {
    const pair = rsChangePair(data, selected, site, role);
    const values = pair.reason ? `<td colspan="3" class="muted">${esc(pair.reason)}</td>`
      : rsChangeMetrics.map(key => rsChangeCell(pair.left.row.loads[key], pair.right.row.loads[key], true)).join('');
    const action = pair.reason ? '' : `<button type="button" class="rs-month-link" data-rs-month="${role}" aria-label="${esc(pair.title)}，查看月度差异">月度差异</button>`;
    return `<tr><th scope="row">${esc(pair.title)}${action}</th>${values}</tr>`;
  }).join('');
  return `<section class="rs-changes" aria-label="显热需求变化"><div class="rs-changes-head"><h3>显热需求变化</h3><div class="rs-change-modes" role="group" aria-label="比较方式">${modes}</div></div>
    <div class="rs-change-place">${selector}<span>${esc(periodLabel(data.scope.period))} · kWh</span></div>
    <p class="muted">箭头左侧是参考工况，右侧是研究工况。各项降低或增加的百分比以左侧对应需求为基数。</p>
    <div class="rs-delta-scroll"><table class="table rs-delta-table"><thead><tr><th scope="col">比较工况</th>${rsChangeHeadings}</tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function rsMonthsByNumber(data, side) {
  const months = new Map();
  for (const row of data.monthly_by_batch?.[side.batchId]?.[side.row.index] || []) {
    // Ambiguous rows must not turn into savings by silently choosing one.
    months.set(row.month, months.has(row.month) ? null : row);
  }
  return months;
}

function rsShowMonths(trigger) {
  const data = RS.results, site = RS.changeSite;
  if (!data || !site) return;
  const pair = rsChangePair(data, rsSelected(data), site, trigger.dataset.rsMonth);
  if (!pair || pair.reason) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'rs-month-dialog';
  dialog.setAttribute('aria-labelledby','rs-month-title');
  const left = rsMonthsByNumber(data, pair.left), right = rsMonthsByNumber(data, pair.right);
  const [startMonth,,endMonth] = pair.left.row.period;
  let changes = '', raw = '';
  const monthLabel = month => `<th scope="row">${month} 月</th>`;
  for (let m=startMonth; m<=endMonth; m++) {
    const a=left.get(m), b=right.get(m);
    changes += `<tr><th scope="row"><button class="rs-month-inspect" data-rs-inspect-month="${m}" aria-label="查看 ${m} 月控制与时序">${m} 月 ↗</button></th>${rsChangeMetrics.map(key => rsChangeCell(a?.[key], b?.[key], false)).join('')}</tr>`;
    raw += `<tr>${monthLabel(m)}${[a,b].map(row => rsChangeMetrics.map(key =>
      `<td>${Number.isFinite(row?.[key]) ? format(row[key]) : '无数据'}</td>`).join('')).join('')}</tr>`;
  }
  const totals = rsChangeMetrics.map(key => rsChangeCell(pair.left.row.loads[key], pair.right.row.loads[key], false)).join('');
  const city = S.boot.sites[site]?.name || site;
  const missing = !left.size || !right.size;
  dialog.innerHTML = `<header class="viewer-head"><div><p class="muted">${esc(city)} · ${esc(periodLabel(pair.left.row.period))} · kWh</p><h2 id="rs-month-title">月度差异</h2></div><button type="button" data-rs-month-back autofocus>返回对比结果</button></header>
    <div class="rs-month-body"><h3>${esc(pair.title)}</h3><p class="muted">增减均相对左侧工况。点月份查看该月已保存的控制与时序。</p>
    ${missing ? '<p role="status">有工况缺少已保存的月度需求，只展示可核对的数值。</p>' : ''}
    <div class="rs-delta-scroll"><table class="table rs-delta-table"><thead><tr><th scope="col">月份</th>${rsChangeHeadings}</tr></thead><tbody>${changes}</tbody><tfoot><tr><th scope="row">整个时段</th>${totals}</tr></tfoot></table></div>
    <details class="rs-month-raw"><summary>查看两侧月度需求原值 / kWh</summary><div class="rs-delta-scroll"><table class="table"><thead><tr><th rowspan="2">月份</th><th colspan="3" scope="colgroup">${esc(rsRoles[pair.reference])}</th><th colspan="3" scope="colgroup">${esc(rsRoles[pair.role])}</th></tr><tr>${rsChangeHeadings}${rsChangeHeadings}</tr></thead><tbody>${raw}</tbody></table></div></details></div>`;
  dialog.querySelector('[data-rs-month-back]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    const button = event.target.closest('[data-rs-inspect-month]');
    if (!button) return;
    const sides = [[pair.reference,pair.left],[pair.role,pair.right]].map(([role,side]) =>
      ({name:rsRoles[role],batch:side.batchId,index:side.row.index,sha:side.row.evidence.result_sha256}));
    const context = {city, month:Number(button.dataset.rsInspectMonth), sides, side:1};
    rtOpen(sides[1].batch, sides[1].index, context, button);
  });
  dialog.addEventListener('close', () => {
    dialog.remove();
    const button = trigger.isConnected ? trigger : document.querySelector(`#rs-results [data-rs-month="${pair.role}"]`);
    button?.focus({preventScroll:true});
  }, {once:true});
  document.body.append(dialog);
  dialog.showModal();
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-rs-change-mode],[data-rs-month]');
  if (!button) return;
  if (button.dataset.rsMonth) return rsShowMonths(button);
  RS.changeMode = button.dataset.rsChangeMode;
  rsRefreshResults(`[data-rs-change-mode="${RS.changeMode}"]`);
});
document.addEventListener('change', event => {
  if (event.target.id !== 'rs-change-site') return;
  RS.changeSite = event.target.value;
  rsRefreshResults('#rs-change-site');
});
