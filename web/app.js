/* ═══════════════════════════════════════════════════════════
   足球本体世界 · 前端交互
   结构：常量表 → 基础设施(toast/fetch) → 图谱渲染 → 五个 Tab → 初始化
   ═══════════════════════════════════════════════════════════ */
(() => {
'use strict';

/* ---------- 常量表 ---------- */

const CLASS_COLORS = {
  Goalkeeper:          '#0ea5e9',
  CentreBack:          '#3b82c4',
  Fullback:            '#6366f1',
  DefensiveMidfielder: '#14b8a6',
  AttackingMidfielder: '#e8871e',
  Winger:              '#f59e0b',
  Striker:             '#dc4a4a',
  Club:                '#d9a514',
  Contract:            '#64748b',
  Match:               '#22a06b',
  TrainingSession:     '#94a3b8',
  InjuryRecord:        '#ef4444',
  Class:               '#f1f0ea'
};

const CLASS_ZH = {
  Goalkeeper: '门将', CentreBack: '中后卫', Fullback: '边后卫',
  DefensiveMidfielder: '后腰', AttackingMidfielder: '前腰', Winger: '边锋',
  Striker: '中锋', Club: '俱乐部', Contract: '合同',
  Match: '比赛', TrainingSession: '训练课', InjuryRecord: '伤病记录',
  Class: '类（TBox 概念）'
};

const ACTION_ZH = {
  RestPlayer: '轮休', CallUpYouth: '征调青年队', StartTreatment: '启动治疗'
};

const AUDIT_RESULT_ZH = {
  event: '事件', pending: '待审批', executed: '已执行',
  vetoed: '被否决', failed: '已回滚'
};

const RULE_CATEGORY_ZH = { suggestion: '状态建议规则', governance: '治理边界' };

const EDGE_DECLARED = '#cbd5e1';
const EDGE_INFERRED = '#7dd3fc';
const WAVE_MS = 400;

/* 语义推荐子图：与选中商品直接相连、值得展示的谓词（推荐可解释边 + 套装组成） */
const FOCUS_PREDS = ['suppliedBy', 'isComponentOf', 'promotes', 'substituteFor',
  'compatibleWith', 'sameSeries', 'hasPart'];

const state = { graph: null, cy: null, currentTab: 'overview', waveTimer: null,
  filtered: false, graphFilters: null };

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
      label: 'data(label)', 'font-size': 26, 'font-family': 'sans-serif',
      color: '#475569', 'text-valign': 'bottom', 'text-margin-y': 10,
      width: 52, height: 52, shape: 'ellipse',
      'background-color': 'data(color)',
      'border-width': 1, 'border-color': 'rgba(31,41,55,0.18)'
    } },
    { selector: 'node[cls = "Class"]', style: {
      shape: 'round-rectangle', width: 62, height: 46,
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
    { selector: 'node.obj-ring', style: {
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
  // 类别过滤：只有勾选类别的节点入图（边要求两端都可见）
  const nodes = g.nodes.filter(n => state.graphFilters.has(nodeCategory(n.cls)));
  const ids = new Set(nodes.map(n => n.id));
  return nodes.map(n => ({
    group: 'nodes',
    data: { id: n.id, label: n.label, cls: n.cls, color: nodeColor(n.cls) }
  })).concat(g.edges.filter(e => ids.has(e.s) && ids.has(e.o)).map((e, i) => ({
    group: 'edges',
    data: { id: 'e' + i, source: e.s, target: e.o, inferred: !!e.inferred }
  })));
}

/* ---------- 类别过滤开关 ---------- */

function nodeCategory(cls) {
  if (cls === 'Contract' || cls === 'TrainingSession' || cls === 'InjuryRecord' ||
      cls === 'Match' || cls === 'Club' || cls === 'Class') return cls;
  return 'Player';                       // 位置类 / YouthPlayer 等都归入"球员"
}

const FILTER_ZH = {
  Player: '球员', Club: '俱乐部', Class: '类（TBox）', Match: '比赛',
  Contract: '合同', TrainingSession: '训练课', InjuryRecord: '伤病记录'
};

function buildFilters() {
  const box = $('cy-filters');
  // 合同和训练课是纯数量噪声，默认不勾；其余默认显示
  state.graphFilters = new Set(Object.keys(FILTER_ZH)
    .filter(c => c !== 'Contract' && c !== 'TrainingSession'));
  Object.keys(FILTER_ZH).forEach(cat => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = state.graphFilters.has(cat);
    input.addEventListener('change', () => {
      if (input.checked) state.graphFilters.add(cat);
      else state.graphFilters.delete(cat);
      applyGraphFilter();
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(FILTER_ZH[cat]));
    box.appendChild(label);
  });
}

function applyGraphFilter() {
  if (!state.cy || !state.graph) return;
  state.cy.batch(() => {
    state.cy.elements().remove();
    state.cy.add(graphElements(state.graph));
  });
  runLayout(false);
}

function runLayout(animate) {
  const opts = typeof cytoscapeFcose !== 'undefined'
    ? { // fcose：力导布局里间距质量最好
        name: 'fcose', animate: false,   // 动画模式下 layoutstop 时机不可靠，fit 会丢
        animationDuration: 900,
        randomize: true, padding: 60,
        nodeSeparation: 160,      // 节点间距：越大越散
        idealEdgeLength: 110,     // 边理想长度
        nodeRepulsion: 15000,
        edgeElasticity: 0.45,
        numIter: 2500
      }
    : { // 回退：原生 cose
        name: 'cose', animate: false, animationDuration: 900,
        randomize: true, padding: 60,
        nodeOverlap: 60, nodeRepulsion: 16000,
        idealEdgeLength: 110, edgeElasticity: 0.45,
        gravity: 0.4, numIter: 2000, nestingFactor: 1.2
      };
  const layout = state.cy.layout(opts);
  // 布局后不硬 fit 全图：先适配，再把 zoom 收到 0.75 上限——
  // 初始停留在核心区（字号 ~20px 可读），边缘靠拖拽，避免整体缩成蚂蚁
  const settle = () => {
    state.cy.fit(undefined, 60);
    if (state.cy.zoom() > 0.75) { state.cy.zoom(0.75); state.cy.center(); }
  };
  layout.one('layoutstop', settle);
  layout.run();
  settle();   // 无动画布局 layoutstop 同步触发，双保险
}

function updateStats() {
  const g = state.graph;
  $('stat-nodes').textContent = g.nodes.length;
  $('stat-edges').textContent = g.edges.length;
  $('stat-inferred').textContent = g.edges.filter(e => e.inferred).length;
}

function fillDropdowns() {
  const g = state.graph;
  const ev = $('event-player'), ps = $('player-select');
  if (ev.options.length === 0) {
    const POSITIONS = new Set(['Player',
      'Goalkeeper', 'CentreBack', 'Fullback',
      'DefensiveMidfielder', 'AttackingMidfielder', 'Winger', 'Striker']);
    g.nodes
      .filter(n => POSITIONS.has(n.cls))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh'))
      .forEach(n => {
        ev.add(new Option(n.label, n.id));
        ps.add(new Option(n.label, n.id));
      });
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

/* ---------- 点击聚焦邻域 ---------- */

function focusNeighborhood(node) {
  // 只亮目标的一跳邻域（节点 + 与目标直连的边），其余淡化
  state.cy.batch(() => {
    state.cy.elements().addClass('dimmed');
    node.removeClass('dimmed');
    node.connectedEdges().removeClass('dimmed');
    node.connectedEdges().connectedNodes().removeClass('dimmed');
  });
}

function clearFocus() {
  state.cy.elements().removeClass('dimmed');
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
  state.cy.nodes().removeClass('obj-ring');
}

/* ---------- Tab 一：图谱总览 ---------- */

/* 面板为静态内容，统计与图例在 loadGraph / buildLegend 中填充 */

/* ---------- Tab 二：事件流 ---------- */

const EVENT_FIELDS = {
  match:    'field-minutes',
  training: 'field-load',
  injury:   'field-weeks'
};

function onEventTypeChange() {
  const t = $('event-type').value;
  Object.entries(EVENT_FIELDS).forEach(([type, field]) => {
    $(field).style.display = (type === t) ? '' : 'none';
  });
}

async function sendEvent() {
  const type = $('event-type').value;
  const player = $('event-player').value;
  if (!player) { toast('请先选择球员', true); return; }
  const body = { type, player_id: player };
  if (type === 'match') body.minutes = +$('event-minutes').value;
  if (type === 'training') body.load = +$('event-load').value;
  if (type === 'injury') body.weeks_out = +$('event-weeks').value;
  try {
    const r = await post('/api/events', body);
    renderEventReport(r);
    toast('事件已注入世界');
    await Promise.all([loadGraph(), refreshDecisionPanel()]);
  } catch (e) { toast(e.message, true); }
}

function renderEventReport(r) {
  const box = $('event-report');
  let html = '<div class="chain"><p class="chain-title">传导链</p>';
  r.chain.forEach((step, i) => {
    html += '<div class="chain-step lit"><span class="chain-num">' + (i + 1) + '</span>' +
      '<div class="chain-body"><div class="chain-expl">' + esc(step) + '</div></div></div>';
  });
  if (r.state_changes.length) {
    html += '<p class="chain-title">状态变化</p>';
    r.state_changes.forEach(c => {
      html += '<div class="state-change">' + esc(c.id) + ' 体能 ' +
        (c.old === null ? '–' : c.old) + ' → ' + c.new + '</div>';
    });
  }
  // 建议是推论：本次事件的目标球员未必触发条目，把"触发了几条"说清楚，
  // 否则"清单共 N 条"会被读成"本次事件产生了 N 条建议"。
  const nodeName = () => {
    const n = (state.graph && state.graph.nodes.find(x => x.id === r.event.target)) || null;
    return n ? '「' + n.label + '」' : '';
  };
  const mine = r.event.target
    ? r.suggestions.filter(s => (s.targets || []).some(t => t.id === r.event.target))
    : [];
  if (mine.length) {
    html += '<p class="chain-title">' + nodeName() + '触发 ' + mine.length +
      ' 条建议（见决策中心）；全球建议清单共 ' + r.suggestions.length + ' 条</p></div>';
  } else {
    html += '<p class="chain-title">' + nodeName() + '本次未触发任何建议' +
      '（建议是推论，条件未过就不产生）；全球建议清单共 ' + r.suggestions.length +
      ' 条</p></div>';
  }
  box.innerHTML = html;
  if (state.cy && r.event.target) {
    const n = state.cy.getElementById(r.event.target);
    if (n.nonempty()) {
      n.addClass('wave-3');
      setTimeout(() => n.removeClass('wave-3'), 1600);
    }
  }
}

function resetEventPanel() {
  $('event-report').innerHTML = '';
}

/* ---------- Tab 三：球员对象 ---------- */

async function loadPlayerCard() {
  const pid = $('player-select').value;
  if (!pid) return;
  try {
    const r = await api('/api/object/' + encodeURIComponent(pid) + '/describe');
    const list = (arr, cls) => arr.map(x => '<li class="' + (cls || '') + '">' + esc(x) + '</li>').join('');
    const can = r['能做什么'].map(a =>
      '<span class="target" data-id="' + esc(a.id) + '">' + esc(ACTION_ZH[a.type] || a.type) + '</span>').join(' ');
    $('player-card').innerHTML =
      '<div class="obj-card player-card"><span class="obj-name">' + esc(r.label) +
      '</span><span class="obj-tag">' + esc(CLASS_ZH[r.type] || r.type) + '</span>' +
      '<p class="chain-title">现在状态</p><ul class="rec-list">' + list(r['现在状态']) + '</ul>' +
      '<p class="chain-title">为什么</p><ul class="rec-list">' + list(r['为什么']) + '</ul>' +
      '<p class="chain-title">能做什么</p>' + (can || '<span class="rec-empty">当前没有可执行的动作</span>') +
      '</div>';
  } catch (e) { toast(e.message, true); }
}

function onPlayerCardClick(ev) {
  const t = ev.target.closest('.target[data-id]');
  if (t) openDrawer(t.dataset.id);
}

/* ---------- Tab 四：决策中心 ---------- */

async function loadActions() {
  const data = await api('/api/actions');
  $('roster-line').textContent = '报名 ' + data.roster.count + '/' + data.roster.limit;
  const box = $('actions-list');
  const list = data.actions;
  if (!list.length) {
    box.innerHTML = '<div class="empty">没有待处置的建议动作——<br>执行效果已写回图谱，重新推理后建议自动消失。</div>';
    return;
  }
  box.innerHTML = list.map(a =>    '<div class="action-card"><div class="action-head">' +
    '<span class="type-badge">' + esc(ACTION_ZH[a.type] || a.type) + '</span>' +
    '<span class="action-btns">' +
    '<button class="action-preview" data-id="' + esc(a.id) + '">预览影响</button>' +
    '<button class="action-execute" data-id="' + esc(a.id) + '">执行</button></span></div>' +
    '<div class="action-targets">对象：' + a.targets.map(t =>
      '<span class="target" data-id="' + esc(t.id) + '">' + esc(t.label) + '</span>').join('') +
    '</div><div class="why">' + esc(a.reason) + '</div>' +
    '<div class="preview-box" id="pv-' + esc(a.id) + '" style="display:none"></div></div>').join('');
}

async function previewOne(id) {
  const box = $('pv-' + id);
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  try {
    const r = await post('/api/preview-action/' + encodeURIComponent(id));
    box.innerHTML =
      (r.additions.length ? r.additions.map(t =>
        '<div class="state-change add">＋ ' + esc(t) + '</div>').join('') : '') +
      (r.retractions.length ? r.retractions.map(t =>
        '<div class="state-change del">－ ' + esc(t) + '</div>').join('') : '') +
      '<div class="why">执行前推演：绿色三元组执行时写入 effects 层，红色三元组执行时移除（effects 删除或声明层撤销）——效果即事实。</div>';
    box.style.display = '';
  } catch (e) { toast(e.message, true); }
}

async function executeOne(id, btn) {
  try {
    const r = await post('/api/action/' + encodeURIComponent(id) + '/execute');
    toast(r.message || (r.pending ? '已登记待审批' : '已执行'), r.ok === false);
    if (r.pending) { btn.textContent = '确认执行'; }
    await Promise.all([loadActions(), loadAudit(), loadGraph()]);
  } catch (e) { toast(e.message, true); }
}

async function loadAudit() {
  const rows = await api('/api/audit');
  $('audit-list').innerHTML = rows.length
    ? rows.map(e =>
        '<div class="audit-row"><span class="audit-step">step ' + e.step + '</span>' +
        '<span class="audit-result r-' + esc(e.result) + '">' + (AUDIT_RESULT_ZH[e.result] || e.result) + '</span>' +
        '<span class="audit-detail">' + esc((AUDIT_RESULT_ZH[e.result] || e.result) + '：' + e.detail) + '</span></div>').join('')
    : '<p class="rec-empty">暂无操作记录——注入一个事件或执行一条建议。</p>';
}

/* ---------- 规则手册(学习路径 Tab) ---------- */

async function loadRules() {
  const body = await api('/api/rules');
  const groups = {};
  body.rules.forEach(r => (groups[r.category] = groups[r.category] || []).push(r));
  $('rule-handbook').innerHTML = ['suggestion', 'governance'].map(c =>
    '<div class="rule-group"><div class="rule-group-title">' + RULE_CATEGORY_ZH[c] + '</div>' +
    groups[c].map(r =>
      '<div class="rule-card"><div class="rule-name">' + esc(r.name) + '</div>' +
      '<div class="rule-summary">' + esc(r.summary) + '</div>' +
      '<ul class="rule-conditions">' + r.conditions.map(c =>
        '<li' + (c.dynamic ? ' class="rule-dynamic"' : '') + '>' + esc(c.text) + '</li>').join('') +
      '</ul><div class="rule-meta">' + esc(r.code) + ' · ' + esc(r.chapter.join(' · ')) + '</div></div>'
    ).join('') + '</div>').join('');
}

/* 阈值滑杆：改 fitness_floor，规则实时重算（VIP 滑杆的足球等价物） */
let floorTimer = null;

function onFloorSlider() {
  $('fitness-floor-val').textContent = $('fitness-floor').value;
  clearTimeout(floorTimer);
  floorTimer = setTimeout(async () => {
    try {
      await post('/api/params', { fitness_floor: +$('fitness-floor').value });
      await Promise.all([loadActions(), loadRules()]);
    } catch (e) { toast(e.message, true); }
  }, 300);
}

async function refreshDecisionPanel() {
  await Promise.all([loadActions(), loadAudit()]);
}

async function resetDemo() {
  try {
    await post('/api/reset');
    clearHighlights();
    closeDrawer();
    resetEventPanel();
    await Promise.all([loadGraph(), loadActions(), loadAudit(), loadRules()]);
    toast('演示已重置：事件、动作与审计均已清除');
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
  clearHighlights();
  resetEventPanel();
  closeDrawer();
  if (name === 'decisions') refreshDecisionPanel().catch(e => toast(e.message, true));
  if (name === 'player') loadPlayerCard().catch(e => toast(e.message, true));
  if (name === 'learn') loadRules().catch(e => toast(e.message, true));
}

/* ---------- 初始化 ---------- */

function bind() {
  $('tabs').addEventListener('click', ev => {
    const btn = ev.target.closest('.tab');
    if (btn) switchTab(btn.dataset.tab);
  });
  $('drawer-close').addEventListener('click', closeDrawer);
  $('btn-relayout').addEventListener('click', () => runLayout(true));
  $('event-type').addEventListener('change', onEventTypeChange);
  $('btn-send-event').addEventListener('click', sendEvent);
  $('fitness-floor').addEventListener('input', onFloorSlider);
  $('player-select').addEventListener('change', loadPlayerCard);
  $('btn-reset').addEventListener('click', resetDemo);
  $('actions-list').addEventListener('click', ev => {
    const pb = ev.target.closest('.action-preview');
    if (pb) { previewOne(pb.dataset.id); return; }
    const btn = ev.target.closest('.action-execute');
    if (btn) executeOne(btn.dataset.id, btn);
    const t = ev.target.closest('.target');
    if (t) openDrawer(t.dataset.id);
  });
  $('player-card').addEventListener('click', onPlayerCardClick);
}

async function init() {
  buildLegend();
  buildFilters();
  bind();
  if (typeof cytoscape === 'undefined') {
    $('cy-loading').textContent = 'Cytoscape.js 加载失败，请检查网络';
    toast('Cytoscape.js 未能从 CDN 加载，图谱无法渲染', true);
    return;
  }
  if (typeof cytoscapeFcose !== 'undefined') cytoscape.use(cytoscapeFcose);
  state.cy = cytoscape({
    container: $('cy'),
    style: cyStylesheet(),
    wheelSensitivity: 0.2,
    minZoom: 0.2, maxZoom: 2.5
  });
  window.__cy = state.cy;   // 调试句柄（也可用于浏览器端测试）
  state.cy.on('tap', 'node', evt => {
    focusNeighborhood(evt.target);
    openDrawer(evt.target.id());
  });
  state.cy.on('tap', ev => {
    if (ev.target === state.cy) { clearFocus(); closeDrawer(); }
  });
  try {
    await loadGraph({ animate: true });
    $('cy-loading').classList.add('done');
  } catch (e) {
    $('cy-loading').textContent = '图谱加载失败';
    toast(e.message, true);
  }
  loadRules().catch(() => {});
}

document.addEventListener('DOMContentLoaded', init);

})();
