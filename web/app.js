/* ═══════════════════════════════════════════════════════════
   电商本体论教学演示 · 前端交互
   结构：常量表 → 基础设施(toast/fetch) → 图谱渲染 → 五个场景 → 初始化
   ═══════════════════════════════════════════════════════════ */
(() => {
'use strict';

/* ---------- 常量表 ---------- */

const CLASS_COLORS = {
  PhysicalProduct: '#3b82c4',
  Bundle:          '#8b5cf6',
  Supplier:        '#e8871e',
  Customer:        '#22a06b',
  Order:           '#64748b',
  OrderLine:       '#94a3b8',
  Promotion:       '#dc4a4a',
  Class:           '#f1f0ea'
};

const CLASS_ZH = {
  PhysicalProduct: '商品', Bundle: '套装', Supplier: '供应商',
  Customer: '客户', Order: '订单', OrderLine: '订单明细',
  Promotion: '促销', Class: '类（TBox 概念）'
};

const ACTION_ZH = {
  PausePromotion: '暂停促销', NotifyCustomer: '通知客户',
  CreatePurchaseOrder: '生成采购单', PromoteSubstitute: '推荐替代品'
};

const EDGE_DECLARED = '#cbd5e1';
const EDGE_INFERRED = '#7dd3fc';
const WAVE_MS = 400;

/* 语义推荐子图：与选中商品直接相连、值得展示的谓词（推荐可解释边 + 套装组成） */
const FOCUS_PREDS = ['suppliedBy', 'isComponentOf', 'promotes', 'substituteFor',
  'compatibleWith', 'sameSeries', 'hasPart'];

const state = { graph: null, cy: null, currentTab: 'overview', waveTimer: null,
  filtered: false };

/* ---------- 基础设施 ---------- */

const $ = id => document.getElementById(id);

function esc(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, isError) {
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => el.classList.add('fade'), isError ? 5200 : 3200);
  setTimeout(() => el.remove(), isError ? 5600 : 3600);
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error('无法连接后端，请先启动：uvicorn api.main:app --reload');
  }
  if (!res.ok) {
    let detail = '请求失败（HTTP ' + res.status + '）';
    try {
      const j = await res.json();
      if (j && j.detail) detail = j.detail;
    } catch { /* 非 JSON 响应体，保留默认文案 */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function post(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

/* ---------- 图谱渲染 ---------- */

function nodeColor(cls) { return CLASS_COLORS[cls] || '#f1f0ea'; }

function cyStylesheet() {
  const st = [
    { selector: 'node', style: {
      label: 'data(label)', 'font-size': 10, 'font-family': 'sans-serif',
      color: '#475569', 'text-valign': 'bottom', 'text-margin-y': 4,
      width: 22, height: 22, shape: 'ellipse',
      'background-color': 'data(color)',
      'border-width': 1, 'border-color': 'rgba(31,41,55,0.18)'
    } },
    { selector: 'node[cls = "Class"]', style: {
      shape: 'round-rectangle', width: 26, height: 20,
      'border-color': '#cfcabb'
    } },
    { selector: 'edge', style: {
      width: 1.5, 'curve-style': 'bezier',
      'line-color': EDGE_DECLARED, 'line-style': 'solid'
    } },
    { selector: 'edge[?inferred]', style: {
      'line-style': 'dashed', 'line-color': EDGE_INFERRED
    } },
    { selector: 'node.dimmed', style: { opacity: 0.12 } },
    { selector: 'edge.dimmed', style: { opacity: 0.06 } },
    { selector: 'node.vip-ring', style: {
      'border-width': 4, 'border-color': '#22a06b', 'border-style': 'double'
    } }
  ];
  // 风险传导波次：第 1..5 层，边框与光晕逐层加强
  for (let i = 1; i <= 5; i++) {
    st.push({ selector: 'node.wave-' + i, style: {
      'border-width': 1 + i, 'border-color': '#e8871e',
      'overlay-color': '#e8871e', 'overlay-opacity': 0.06 * i,
      'overlay-padding': 2 * i, 'z-index': 10 + i
    } });
  }
  return st;
}

function graphElements(g) {
  return g.nodes.map(n => ({
    group: 'nodes',
    data: { id: n.id, label: n.label, cls: n.cls, color: nodeColor(n.cls) }
  })).concat(g.edges.map((e, i) => ({
    group: 'edges',
    data: { id: 'e' + i, source: e.s, target: e.o, inferred: !!e.inferred }
  })));
}

function runLayout(animate) {
  state.cy.layout({
    name: 'cose', animate: !!animate, animationDuration: 900,
    randomize: true, padding: 40, nodeOverlap: 12
  }).run();
}

function updateStats() {
  const g = state.graph;
  $('stat-nodes').textContent = g.nodes.length;
  $('stat-edges').textContent = g.edges.length;
  $('stat-inferred').textContent = g.edges.filter(e => e.inferred).length;
}

function fillDropdowns() {
  const g = state.graph;
  const sup = $('supplier-select'), prod = $('product-select');
  if (sup.options.length === 0) {
    g.nodes.filter(n => n.cls === 'Supplier').forEach(n =>
      sup.add(new Option(n.label, n.id)));
    g.nodes.filter(n => n.cls === 'PhysicalProduct' || n.cls === 'Bundle')
      .forEach(n => prod.add(new Option(n.label, n.id)));
    // 首访即有推荐内容：下拉框就绪后立即加载默认商品的推荐
    loadRecommend().catch(() => { /* 切到该 Tab 时会重新加载 */ });
  }
}

async function loadGraph(opts) {
  const animate = !!(opts && opts.animate);
  const g = await api('/api/graph');
  state.graph = g;
  if (!state.cy) return;
  const prev = {};
  state.cy.nodes().forEach(n => { prev[n.id()] = Object.assign({}, n.position()); });
  state.cy.batch(() => {
    state.cy.elements().remove();
    state.cy.add(graphElements(g));
    state.cy.nodes().forEach(n => { if (prev[n.id()]) n.position(prev[n.id()]); });
  });
  if (Object.keys(prev).length === 0) runLayout(animate);
  updateStats();
  fillDropdowns();
}

function buildLegend() {
  const box = $('legend');
  Object.keys(CLASS_COLORS).forEach(cls => {
    const item = document.createElement('span');
    item.className = 'legend-item';
    item.innerHTML = '<i class="dot' + (cls === 'Class' ? ' dot-class' : '') +
      '" style="background:' + CLASS_COLORS[cls] + '"></i>' +
      esc(CLASS_ZH[cls] || cls);
    box.appendChild(item);
  });
}

/* ---------- 语义推荐子图 ---------- */

function focusSubgraph(pid) {
  const g = state.graph;
  const keep = new Set([pid]);
  const edges = g.edges.filter(e => {
    if ((e.s === pid || e.o === pid) && FOCUS_PREDS.indexOf(e.p) < 0) return false;
    if (e.s !== pid && e.o !== pid) return false;
    keep.add(e.s);
    keep.add(e.o);
    return true;
  });
  return { nodes: g.nodes.filter(n => keep.has(n.id)), edges: edges };
}

function renderFocusSubgraph(pid) {
  if (!state.cy) return; // 无图谱（如 CDN 失败）时只展示推荐列表
  state.filtered = true;
  state.cy.batch(() => {
    state.cy.elements().remove();
    state.cy.add(graphElements(focusSubgraph(pid)));
  });
  runLayout(true);
}

function restoreFullGraph() {
  if (!state.filtered) return;
  state.filtered = false;
  if (!state.cy) return;
  state.cy.batch(() => {
    state.cy.elements().remove();
    state.cy.add(graphElements(state.graph));
  });
  updateStats();
}

/* ---------- 高亮管理 ---------- */

function stopWaves() {
  if (state.waveTimer) { clearInterval(state.waveTimer); state.waveTimer = null; }
}

function clearHighlights() {
  stopWaves();
  if (!state.cy) return;
  state.cy.elements().removeClass('dimmed');
  for (let i = 1; i <= 5; i++) state.cy.nodes().removeClass('wave-' + i);
  state.cy.nodes().removeClass('vip-ring');
}

/* ---------- Tab 一：图谱总览 ---------- */

/* 面板为静态内容，统计与图例在 loadGraph / buildLegend 中填充 */

/* ---------- Tab 二：风险传导 ---------- */

const CHAIN_UNITS = ['款商品', '个套装', '场促销', '张待发货订单', '位 VIP 客户'];

async function markRisk(delayed) {
  const sid = $('supplier-select').value;
  if (!sid) { toast('请先选择供应商', true); return; }
  try {
    const r = await post('/api/scenario/supplier-risk',
      { supplier_id: sid, delayed: delayed });
    if (delayed) { renderChain(r); propagateHighlight(r); }
    else { resetRiskPanel(); clearHighlights(); await loadGraph(); }
    toast(delayed ? '已标记延迟，风险沿本体逐层传导' : '已解除该供应商的延迟标记');
  } catch (e) { toast(e.message, true); }
}

function renderChain(r) {
  const box = $('risk-chain');
  $('risk-hint').style.display = 'none';
  let html = '<div class="chain"><p class="chain-title">风险传导链</p>';
  r.chain.forEach((step, i) => {
    html += '<div class="chain-step' + (step.count > 0 ? ' lit' : '') + '">' +
      '<span class="chain-num">' + step.step + '</span>' +
      '<div class="chain-body"><span class="chain-count">' + step.count +
      ' <span class="unit">' + CHAIN_UNITS[i] + '</span></span>' +
      '<div class="chain-expl">' + esc(step.explanation) + '</div></div></div>';
  });
  box.innerHTML = html + '</div>';
}

function resetRiskPanel() {
  $('risk-chain').innerHTML = '';
  $('risk-hint').style.display = '';
}

function propagateHighlight(r) {
  if (!state.cy) return; // 无图谱（如 CDN 失败）时只展示步骤条
  stopWaves();
  clearHighlights();
  const cy = state.cy;
  cy.elements().addClass('dimmed');
  const layers = [
    r.products.map(x => x.id),
    r.bundles.map(x => x.id),
    r.promotions.map(x => x.id),
    r.pending_orders.reduce((a, o) => a.concat([o.id, o.customer]), []),
    r.vip_customers.map(x => x.id)
  ];
  let i = 0;
  state.waveTimer = setInterval(() => {
    if (i >= layers.length) { stopWaves(); return; }
    const ids = layers[i];
    cy.nodes().filter(n => ids.indexOf(n.id()) >= 0).forEach(n => {
      n.removeClass('dimmed');
      n.addClass('wave-' + (i + 1));
      n.connectedEdges().removeClass('dimmed');
    });
    i++;
  }, WAVE_MS);
}

/* 延迟标记是 effects 层事实，传导链与高亮都是它的推论：
   切页/刷新后不靠前端记忆，而是从后端重建。 */
async function loadRisk() {
  try {
    const r = await api('/api/scenario/risk');
    if (r.chain.length) {
      const sup = $('supplier-select');
      if (r.supplier && sup.querySelector('option[value="' + r.supplier + '"]')) {
        sup.value = r.supplier;
      }
      renderChain(r);
      propagateHighlight(r);
    } else {
      resetRiskPanel();
      clearHighlights();
    }
  } catch (e) { toast(e.message, true); }
}

/* ---------- Tab 三：客户分类 ---------- */

let vipTimer = null;

function onVipSlider() {
  $('vip-spend-val').textContent = $('vip-spend').value;
  $('vip-orders-val').textContent = $('vip-orders').value;
  clearTimeout(vipTimer);
  vipTimer = setTimeout(loadVip, 300);
}

async function loadVip() {
  try {
    const r = await post('/api/scenario/vip', {
      spend_threshold: +$('vip-spend').value,
      order_threshold: +$('vip-orders').value
    });
    renderVipCards(r.vips);
    if (!state.cy) return; // 无图谱时仍渲染卡片，跳过圆环
    state.cy.nodes().removeClass('vip-ring');
    r.vips.forEach(v => {
      const n = state.cy.getElementById(v.id);
      if (n.nonempty()) n.addClass('vip-ring');
    });
  } catch (e) { toast(e.message, true); }
}

function renderVipCards(vips) {
  const box = $('vip-cards');
  if (!vips.length) {
    box.innerHTML = '<p class="rec-empty">当前阈值下没有客户满足 VIP 规则。</p>';
    return;
  }
  box.innerHTML = vips.map(v =>
    '<div class="vip-card"><span class="vip-name">' + esc(v.label) +
    '</span><span class="vip-tag">VIP</span>' +
    '<div class="why">' + esc(v.reason) + '</div></div>').join('');
}

/* ---------- Tab 四：语义推荐 ---------- */

async function loadRecommend() {
  const pid = $('product-select').value;
  if (!pid) return;
  try {
    const r = await api('/api/scenario/recommend/' + encodeURIComponent(pid));
    $('rec-product-name').textContent = '为「' + r.product.label + '」推荐：';
    $('rec-naive').innerHTML = r.naive.length
      ? r.naive.map(x => '<li data-id="' + esc(x.id) + '">' + esc(x.label) + '</li>').join('')
      : '<li class="rec-empty">无推荐</li>';
    $('rec-semantic').innerHTML = r.semantic.length
      ? r.semantic.map(x => '<li data-id="' + esc(x.id) + '"><span class="rel-badge">' +
          esc(x.relation_label) + '</span>' + esc(x.label) + '</li>').join('')
      : '<li class="rec-empty">无推荐</li>';
    // 只在推荐页可见时换子图；首访预加载（停在总览页）不动图
    if (state.currentTab === 'recommend') renderFocusSubgraph(pid);
  } catch (e) { toast(e.message, true); }
}

/* 点击推荐结果 → 打开实体抽屉 */
function onRecListClick(ev) {
  const li = ev.target.closest('li[data-id]');
  if (li) openDrawer(li.dataset.id);
}

/* ---------- Tab 五：决策中心 ---------- */

async function loadActions() {
  const list = await api('/api/actions');
  const box = $('actions-list');
  $('btn-execute-all').disabled = !list.length;
  if (!list.length) {
    box.innerHTML = '<div class="empty">没有待处置的建议动作——<br>执行效果已写回图谱，重新推理后建议自动消失。</div>';
    return;
  }
  box.innerHTML = list.map(a =>
    '<div class="action-card"><div class="action-head">' +
    '<span class="type-badge">' + esc(ACTION_ZH[a.type] || a.type) + '</span>' +
    '<button class="action-execute" data-id="' + esc(a.id) + '">执行</button></div>' +
    '<div class="action-targets">对象：' + a.targets.map(t =>
      '<span class="target" data-id="' + esc(t.id) + '">' + esc(t.label) + '</span>').join('') +
    '</div><div class="why">' + esc(a.reason) + '</div></div>').join('');
}

async function executeOne(id) {
  try {
    const r = await post('/api/action/' + encodeURIComponent(id) + '/execute');
    toast(r.message || '已执行');
    await Promise.all([loadActions(), loadGraph()]);
  } catch (e) { toast(e.message, true); }
}

async function executeAll() {
  try {
    const r = await post('/api/actions/execute-all');
    toast('已执行 ' + r.executed + ' 条建议，剩余 ' + r.remaining + ' 条');
    await Promise.all([loadActions(), loadGraph()]);
  } catch (e) { toast(e.message, true); }
}

async function resetDemo() {
  try {
    await post('/api/reset');
    resetRiskPanel();
    clearHighlights();
    closeDrawer();
    await loadGraph();
    if (state.currentTab === 'recommend') await loadRecommend();
    if (state.currentTab === 'decisions') await loadActions();
    toast('演示已重置：延迟标记与执行效果均已清除');
  } catch (e) { toast(e.message, true); }
}

/* ---------- 实体抽屉 ---------- */

async function openDrawer(id) {
  const drawer = $('drawer');
  drawer.classList.add('open');
  $('drawer-title').textContent = '加载中…';
  $('drawer-body').innerHTML = '';
  let e;
  try {
    e = await api('/api/entity/' + encodeURIComponent(id));
  } catch (err) {
    $('drawer-title').textContent = '加载失败';
    $('drawer-body').innerHTML = '<p class="rec-empty">' + esc(err.message) + '</p>';
    toast(err.message, true);
    return;
  }

  $('drawer-title').textContent = e.label;

  const fact = (it, inferred) =>
    '<div class="fact-item"><span class="fact-p">' + esc(it.p) +
    '</span><span class="fact-arrow">→</span>' +
    '<span class="fact-o' + (it.is_literal ? ' lit' : '') + '">' + esc(it.o) + '</span>' +
    (inferred ? '<span class="infer-badge">由推理得出</span>' : '') + '</div>';

  const group = (title, items, inferred) => {
    if (!items.length) return '';
    return '<div class="fact-group"><p class="fact-group-title">' + title +
      '（' + items.length + '）</p>' +
      items.map(it => fact(it, inferred)).join('') + '</div>';
  };

  $('drawer-body').innerHTML =
    group('声明的事实', e.declared, false) +
    group('推断的事实', e.inferred, true);
}

function closeDrawer() { $('drawer').classList.remove('open'); }

/* ---------- Tab 切换 ---------- */

function switchTab(name) {
  const prevTab = state.currentTab;
  state.currentTab = name;
  document.querySelectorAll('#tabs .tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(p =>
    p.classList.toggle('active', p.id === 'panel-' + name));
  closeDrawer();
  if (name === 'recommend') {
    const pid = $('product-select').value;
    if (pid) renderFocusSubgraph(pid);
  } else if (prevTab === 'recommend') {
    restoreFullGraph();
  }
  // 高亮跟随事实而非页面：进风险页重建传导链；从推荐页离开时图元素被重建，
  // 高亮类随之丢失，同样从后端事实重放
  if (name === 'risk' || prevTab === 'recommend') loadRisk();
  if (name === 'decisions') loadActions().catch(e => toast(e.message, true));
  if (name === 'vip') loadVip().catch(e => toast(e.message, true));
}

/* ---------- 初始化 ---------- */

function bind() {
  $('tabs').addEventListener('click', ev => {
    const btn = ev.target.closest('.tab');
    if (btn) switchTab(btn.dataset.tab);
  });
  $('drawer-close').addEventListener('click', closeDrawer);
  $('btn-delay').addEventListener('click', () => markRisk(true));
  $('btn-undelay').addEventListener('click', () => markRisk(false));
  $('btn-reset-risk').addEventListener('click', resetDemo);
  $('vip-spend').addEventListener('input', onVipSlider);
  $('vip-orders').addEventListener('input', onVipSlider);
  $('product-select').addEventListener('change', loadRecommend);
  $('rec-result').addEventListener('click', onRecListClick);
  $('btn-execute-all').addEventListener('click', executeAll);
  $('btn-reset').addEventListener('click', resetDemo);
  $('actions-list').addEventListener('click', ev => {
    const btn = ev.target.closest('.action-execute');
    if (btn) { btn.disabled = true; executeOne(btn.dataset.id); return; }
    const t = ev.target.closest('.target');
    if (t) openDrawer(t.dataset.id);
  });
}

async function init() {
  buildLegend();
  bind();
  if (typeof cytoscape === 'undefined') {
    $('cy-loading').textContent = 'Cytoscape.js 加载失败，请检查网络';
    toast('Cytoscape.js 未能从 CDN 加载，图谱无法渲染', true);
    return;
  }
  state.cy = cytoscape({
    container: $('cy'),
    style: cyStylesheet(),
    wheelSensitivity: 0.2,
    minZoom: 0.2, maxZoom: 2.5
  });
  state.cy.on('tap', 'node', evt => openDrawer(evt.target.id()));
  state.cy.on('tap', ev => { if (ev.target === state.cy) closeDrawer(); });
  try {
    await loadGraph({ animate: true });
    $('cy-loading').classList.add('done');
  } catch (e) {
    $('cy-loading').textContent = '图谱加载失败';
    toast(e.message, true);
  }
  // F5/重开后恢复：若 effects 层仍有延迟标记，重建传导链与高亮
  loadRisk();
}

document.addEventListener('DOMContentLoaded', init);

})();
