# 前端体验重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 spec 给足球本体 demo 前端加剧情模式、把传导报告升级为因果链卡片、简化图谱并统一视觉。

**Architecture:** 后端只动一处——`World.dispatch` 的 `chain` 从字符串列表改为 `{stage, text}` 结构化步骤；其余全部在前端原生 JS/CSS 内完成（新增组件：因果链卡片、剧情坞、图谱预设）。不新增任何 API 端点。

**Tech Stack:** FastAPI + rdflib（现有引擎）、原生 JS + Cytoscape.js fcose（前端，无构建链）、pytest（后端测试）、Playwright（webapp-testing 技能，前端人工验证用）。

**Spec:** `docs/superpowers/specs/2026-10-03-frontend-ux-redesign-design.md`

## Global Constraints

- **前置条件：** 另有两个在途任务（启动治疗效果 / 征召青年队球员的效果）改引擎侧动作语义。开工前先把 main 拉到最新，重新确认 `engine/world.py` 的 `dispatch/_settle` 与 `web/app.js` 现状与本计划引用一致；不一致处停下来说明，不要静默改计划。
- 不引构建链、不换前端框架；图谱保留 Cytoscape + fcose。
- 不做增量推理，不动六层分层、`/api/reset` 语义、两步审批流程、fitness 公式。
- 所有面向用户文案为中文常量（写死在代码里），确定性纪律不变：无 wall-clock，列表渲染前排序。
- 引擎命名空间只走 `engine/namespaces.py` 的 `EX`；前端新增中文映射表放 `app.js` 常量区。
- commit 信息用仓库现有风格（`feat:`/`fix:`/`docs:` + 中文摘要），结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 后端每个任务跑 `python -m pytest -q` 全量 38+ 测试；前端验证用 webapp-testing 技能起 uvicorn + Playwright 断言（不真开端口占用 8000 时先确认）。

## Review Focus

1. **审计 detail 语义**：chain 结构化后，`/api/audit` 的 event 记录 detail 必须仍是人类可读的事件结算文案（settle 步），不能变成 perceive 通用句或对象——Task 1 测试钉住。
2. **Cytoscape 加载失败降级**：CDN 挂掉时（`state.cy` 为 null）剧情模式、图谱预设、边标签全部跳过图谱相关操作但不抛错——Task 3/5 各有一步验证。
3. **空状态变化**：重复注入相同出场分钟（RDF 集合语义塌缩）→ `state_changes` 为空，因果链卡片必须显式呈现「本次无状态变化」而不是留白——Task 2 验证步骤钉住。
4. **剧情模式重走**：reset 后 TOUR 状态（步进、高亮、DOM 类）必须完全清干净，二次走和第一次一致——Task 5 验证步骤钉住。
5. **旧 API 消费者**：`scripts/explore.py` 与 `knowledge_base.py` 审计是 chain 的另外两个消费方，漏改会在运行时才炸（`step["stage"]` 当字符串用）——Task 1 的全量测试 + explore 冒烟钉住。

---

### Task 1: 后端 chain 结构化（{stage, text} 步骤）

**Files:**
- Modify: `engine/world.py:58-147`（`dispatch`、`_settle`）
- Modify: `engine/knowledge_base.py:93-102`（`dispatch` 审计 detail 取法）
- Modify: `scripts/explore.py:85-86`（step4 打印）
- Test: `tests/test_api.py`（新增 1 个测试）

**Interfaces:**
- Produces: `World.dispatch` 返回的 `chain` 变为 `list[dict]`，每项 `{"stage": "perceive"|"settle"|"compute"|"rules", "text": str}`；同事件内 stage 按 perceive → settle → compute → rules 排序，各 stage 至多一条。`KnowledgeBase.dispatch` 与 `/api/events` 原样透传。Task 2 的前端、Task 6 的文档都消费此结构。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 追加：

```python
def test_event_chain_steps_structured(client):
    r = client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert r.status_code == 200
    steps = r.json()["chain"]
    assert steps and all(set(s) == {"stage", "text"} and s["text"] for s in steps)
    stages = [s["stage"] for s in steps]
    assert stages == ["perceive", "settle", "compute", "rules"]
    audit = client.get("/api/audit").json()
    assert audit[0]["detail"]              # 审计 detail 取 settle 步文案，非空且是字符串
    assert isinstance(audit[0]["detail"], str)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api.py::test_event_chain_steps_structured -q`
Expected: FAIL（chain 元素是 str，`set(s)` 报 TypeError 或断言失败）

- [ ] **Step 3: 改 `engine/world.py`**

`_settle(event)` 返回值改为 `[{"stage": "settle", "text": <现有各分支文案原样保留>}]`（每个分支把自己的 `chain.append(f"...")` 换成 `chain.append({"stage": "settle", "text": f"..."})`，文案一字不改）。

`dispatch(event)` 组装四段：

1. perceive：`target is not None` 时追加 `{"stage": "perceive", "text": f"「{name}」感知到{EVENT_ZH[type(event).__name__]}，进入收件箱"}`，其中 `EVENT_ZH = {"InjuryEvent": "受伤", "RecoveryEvent": "痊愈", "MatchPlayedEvent": "比赛", "TrainingLoadEvent": "训练"}` 为模块级常量；
2. settle：`_settle` 的返回；
3. compute：`self._compute_all(objs)` 之后追加 `{"stage": "compute", "text": f"派生状态全量重算：{len(changes)} 名对象状态变化"}`（在 `changes` 算出之后组装，顺序注意）；
4. rules：`suggestions` 取到后追加 `{"stage": "rules", "text": f"规则重算：当前全球建议 {len(suggestions)} 条（建议是推论，随事实即时重算）"}`。

模块 docstring 第 7 行「中文传导链」描述同步改为「结构化传导链（stage + 文案）」。

- [ ] **Step 4: 改两个消费方**

- `engine/knowledge_base.py:101`：`"detail": report["chain"][0] ...` 改为取第一个 `stage == "settle"` 的步的 `text`，找不到再回退 `chain[0]["text"]`，空链回退 `""`。
- `scripts/explore.py:85-86`：循环体改为 `print(f"  传导 {i} [{step['stage']}] {step['text']}")`。

- [ ] **Step 5: 全量测试 + explore 冒烟**

Run: `python -m pytest -q` → 全部 PASS（原 38 + 新 1）
Run: `python scripts/explore.py --step 4` → 传导行带 `[perceive]/[settle]/[compute]/[rules]` 徽章，无报错

- [ ] **Step 6: Commit**

```bash
git add engine/world.py engine/knowledge_base.py scripts/explore.py tests/test_api.py
git commit -m "feat: 传导链结构化——chain 改为 {stage, text} 四段步骤（感知/结算/派生/规则）"
```

---

### Task 2: 前端因果链卡片

**Files:**
- Modify: `web/app.js`（`renderEventReport`，约 382-421 行，行号以 Task 1 合并后为准）
- Modify: `web/style.css`（`.chain-*` 区块，约 368-430 行）

**Interfaces:**
- Consumes: Task 1 的 `chain: [{stage, text}]`；现有 `/api/events` 报告的 `state_changes`、`suggestions`、`event.target`。
- Produces: 建议芯片的 DOM 约定 `<span class="sug-chip" data-aid="{动作id}">`——Task 5 剧情模式第 6 步直接引导用户点它。

- [ ] **Step 1: 重写 `renderEventReport`**

常量区新增 `const STAGE_ZH = { perceive: '感知', settle: '结算', compute: '派生', rules: '规则' };`。卡片结构（竖排，stage 徽章 + 文本）：

- 每个链步：`<div class="chain-step lit"><span class="chain-badge b-{stage}">{STAGE_ZH[stage]}</span><div class="chain-expl">{text}</div></div>`（复用现有 `.chain-step` 竖线连接样式，`::before` 连线逻辑保留）。
- `state_changes` 非空：每条渲染 `<div class="state-change">{label} 体能 <b>{old}</b> → <b>{new}</b></div>`（label 用 `state.graph.nodes` 查中文名，查不到用 id——现有 `nodeName` 逻辑推广成 `nodeLabel(id)` 小函数）；为空则显式渲染一行 `<div class="chain-expl muted">本次无状态变化</div>`。
- 建议：沿用现有「本次触发 N 条 / 未触发」的区分逻辑，触发的改为芯片 `<span class="sug-chip" data-aid="...">{ACTION_ZH[type]}：{targets 首个 label}</span>`；未触发保留现有解释文字。
- 图谱脉动（`wave-3` 1.6s）保留。

- [ ] **Step 2: 芯片点击跳转**

`bind()` 里给 `$('event-report')` 加委托点击：命中 `.sug-chip` 时 `switchTab('decisions')`，`await refreshDecisionPanel()`，然后 `document.querySelector('.action-card [data-id="' + aid + '"]')?.closest('.action-card')` 加临时类 `flash`（CSS：金色描边 2s 后移除）并 `scrollIntoView({behavior:'smooth', block:'center'})`。

- [ ] **Step 3: 样式**

`style.css` 补 `.chain-badge`（小圆角徽章，四个 stage 各一色：感知青/结算橙/派生绿/规则金，色值从 Task 4 token 之前先用现有 `--c` 系颜色硬编码，Task 4 收敛）、`.sug-chip`（可点击芯片态：hover 描边 + cursor:pointer）、`.flash`。

- [ ] **Step 4: 浏览器验证**

用 webapp-testing 技能起 `uvicorn api.main:app`（8000 被占则换 `--port 8001`）+ Playwright：

1. 注入 `{"type":"injury","player_id":"p_st1","weeks_out":4}` → 页面出现 4 个徽章且顺序为 感知→结算→派生→规则；
2. 再次注入相同 `match` 事件（同一 minutes）→ 出现「本次无状态变化」；
3. 点建议芯片 → 落在决策中心，对应卡片金色高亮；
4. 浏览器 console 无报错。

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/style.css
git commit -m "feat: 传导报告升级为因果链卡片——四阶段徽章+状态变化高亮+建议芯片跳转决策中心"
```

---

### Task 3: 图谱简化（预设 + 边标签 + 类节点降级）

**Files:**
- Modify: `web/app.js`（`buildFilters`/`graphElements`/`cyStylesheet`/`runLayout`，约 104-226 行）
- Modify: `web/index.html:33-39`（`#cy-filters` 区块加预设按钮）
- Modify: `web/style.css`（过滤区、边标签样式）

**Interfaces:**
- Consumes: `/api/graph` 的 `edges[].p`（谓词短名，后端已有，不改 API）。
- Produces: 无（其余任务不依赖图谱内部结构）。

- [ ] **Step 1: 预设按钮**

常量区新增 `const CORE_CATS = ['Player', 'Club', 'Class'];`。`index.html` 的 `#cy-filters` 顶部加两个按钮 `data-preset="core|full"`；`buildFilters()` 里绑定：`core` → 勾选集 = CORE_CATS，`full` → 全部 7 类，点完调 `applyGraphFilter()`。默认勾选集从现状改为 CORE_CATS（即 Match、InjuryRecord 默认移出，注释同步改）。按钮样式：小 pill，当前命中的预设高亮（勾选集恰好等于对应集合时）。

- [ ] **Step 2: 边谓词标签**

常量区新增 `const PRED_ZH = { playsFor: '效力', squadOf: '所属梯队', hasContract: '有合同', injuredWith: '伤病', participatesIn: '出场', trainsIn: '参训', type: '是（类型）' };`。`graphElements` 把 `p: e.p` 存入 edge data；`cyStylesheet` 边样式加 `label: 'data(p)'` 映射为中文需用 `content: data(p)` 不够——改为在 data 里直接存中文：`pzh: PRED_ZH[e.p] || e.p`，样式 `label: 'data(pzh)'`，`'font-size': 18, color: '#94a3b8', 'text-background-color': '#faf9f5', 'text-background-opacity': 1, 'text-background-padding': 2`。`init()` 里挂 `state.cy.on('zoom', ...)`：`state.cy.zoom() < 0.6` 时给容器加类 `hide-edge-labels`，CSS 里 `.hide-edge-labels .cy-edge-label { display:none }` 不可行（cytoscape 渲染在 canvas）——改用 `state.cy.style()` 切换边 selector 的 `label` 为空串，或在 zoom 回调里批量 `removeClass/addClass` 配合 stylesheet 的 `edge.hide-label` 变体（`{ selector: 'edge.hide-label', style: { label: '' } }`，回调里 `elements.toggleClass('hide-label', zoom<0.6)`）。取后者。

- [ ] **Step 3: 类（TBox）节点视觉降级**

`cyStylesheet` 的 `node[cls = "Class"]` 变体改小改灰：`width: 44, height: 34, 'font-size': 20, 'border-color': '#d6d1c4', 'background-color': '#eceadf'`（覆盖 data(color)），`'z-index': 1`。图例（`buildLegend`）里 Class 项加「（结构，按需看）」后缀。

- [ ] **Step 4: 浏览器验证**

Playwright：1. 首屏默认无比赛/伤病节点（`window.__cy.nodes().length` 与勾选集一致）；2. 点「完整」后比赛节点出现；3. zoom 放大 > 0.6 后边上有中文谓词标签，缩小后消失；4. console 无报错。另验证 Cytoscape CDN 失败降级：`delete window.cytoscape` 后 reload 模拟不可行——改为代码走查确认 `applyGraphFilter`/zoom 回调均有 `state.cy` 判空。

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/index.html web/style.css
git commit -m "feat: 图谱大简化——核心/完整预设、中文谓词边标签（zoom 门控）、类节点视觉降级"
```

---

### Task 4: 视觉打磨（设计 token 收敛）

**Files:**
- Modify: `web/style.css`（全文，810 行左右）

**Interfaces:**
- Produces: CSS 自定义属性 token 表——后续 Task 5 的剧情坞直接消费。token 名：`--bg/--panel/--ink/--ink-2/--muted/--line/--accent/--ok/--warn/--danger/--radius/--shadow/--space-1..4`。

- [ ] **Step 1: 收敛 token**

`style.css` `:root` 区改为完整 token 表：盘点现有用色（含 `CLASS_COLORS` 之外的 UI 色），归并为上列语义变量；数值参考现有值（如圆角统一为出现频率最高的那个值），不发明新色相。删除散落的魔法数用 `var()` 替换——按钮、卡片、面板标题、徽章、审计行逐区块过。

- [ ] **Step 2: 组件统一**

卡片类（`.action-card`/`.learn-card`/`.obj-card`/`.preview-box`）统一 `--radius` + `--shadow` + 相同内边距刻度；按钮三态（`.btn.primary`/`.btn.ghost`/徽章）统一高度与字号。

- [ ] **Step 3: 浏览器验证**

Playwright 逐 Tab 截图（5 个 Tab + 抽屉打开态 + 因果链卡片），console 无报错；`preview_inspect` 抽查 `.action-card` 的 border-radius/padding 是否等于 token 值。改动纯样式，功能回归靠 Task 2/3 已验证的交互各点一遍（注事件、点芯片）。

- [ ] **Step 4: Commit**

```bash
git add web/style.css
git commit -m "refactor: style.css 收敛设计 token——语义色/间距/圆角/阴影统一，组件视觉归一"
```

---

### Task 5: 剧情模式

**Files:**
- Modify: `web/app.js`（新增 TOUR 常量与剧情坞逻辑，约 120 行）
- Modify: `web/index.html`（topbar 加入口按钮 + `<aside id="tour-dock">`）
- Modify: `web/style.css`（`.tour-*` 样式，用 Task 4 token）

**Interfaces:**
- Consumes: `switchTab`、`sendEvent` 的请求体组装（改为可复用：抽出 `postEvent(type, playerId, extra)` 供表单与 TOUR 共用）、`executeOne`、`refreshDecisionPanel`、`resetDemo`、`/api/audit`。
- Produces: 无。

- [ ] **Step 1: TOUR 常量**

九步剧本（`{tab, text, highlight, action}`；`highlight` 为 DOM 选择器或 `graph:节点id`；`action` 为 async 函数或 null）。旁白每步一句，关键信息钉死：

| # | tab | 旁白要点 | highlight | action |
|---|-----|---------|-----------|--------|
| 1 | overview | 实线=声明事实，虚线=OWL-RL 推论；本体让世界「可推理」 | `.canvas-legend` | – |
| 2 | overview | 点任意节点看抽屉：声明 vs 推断分组 | `graph:p_dm1` | – |
| 3 | player | describe 四问=对象运行时的灵魂 | `#player-card` | – |
| 4 | events | 注入事件=世界唯一的输入通道 | `#btn-send-event` | `postEvent('injury','p_w1',{weeks_out:4})` |
| 5 | events | 因果链卡片：感知→结算→派生→规则 | `#event-report` | – |
| 6 | decisions | 建议是推论：受伤事实触发治疗/征调建议 | `#actions-list` | – |
| 7 | decisions | 治理有边界：两步审批（执行→pending→确认） | `#actions-list` | 找到 StartTreatment 建议执行第一次 |
| 8 | decisions | 审计全程留痕；执行后建议自动消失（写回→重算） | `#audit-list` | – |
| 9 | learn | 每个 Tab 是教程一章的可视化对应物；深入读 learn/ | `.learn-card` 第 1 张 | – |

- [ ] **Step 2: 剧情坞 DOM 与状态机**

`index.html` topbar 加 `<button class="btn ghost" id="btn-tour">▶ 剧情模式</button>`；`main` 后加：

```html
<aside class="tour-dock" id="tour-dock" hidden>
  <div class="tour-progress" id="tour-progress"></div>
  <p class="tour-text" id="tour-text"></p>
  <div class="tour-btns">
    <button class="btn ghost" id="tour-prev">上一步</button>
    <button class="btn primary" id="tour-next">下一步</button>
    <button class="btn ghost" id="tour-exit">退出</button>
  </div>
</aside>
```

逻辑：`startTour()` → 检查 `/api/audit` 非空则在坞内显示「检测到世界已有变化，建议先重置」+ 内联重置按钮（调 `resetDemo`）；`showStep(i)` → `switchTab(t.tab)`、写旁白、渲染进度点（当前实心）、执行 `action`（仅前进方向首次进入时执行，后退不重放）、按 `highlight` 加 `.tour-spot`（DOM）或 `wave-3`（图谱节点，`state.cy` 判空跳过）；`endTour()` → 清所有高亮类与进度状态。最后一步「下一步」按钮文案变「完成」。`switchTab` 里现有的 `resetEventPanel()` 会清掉第 5 步要看的因果链——`showStep` 在 `switchTab` 之后重渲染：把最近一次 dispatch 报告存 `state.lastReport`，`renderEventReport(state.lastReport)` 恢复。

- [ ] **Step 3: `sendEvent` 重构**

现有 `sendEvent` 拆出 `async function postEvent(type, playerId, extra)`（组体 + POST + `renderEventReport` + `loadGraph`/`refreshDecisionPanel`），表单按钮与 TOUR 的 action 都调它。

- [ ] **Step 4: 浏览器验证**

Playwright 全剧本走查：1. 点入口 → 坞出现、9 个进度点；2. 逐步「下一步」到第 4 步自动注入受伤、第 5 步因果链可见（验证 switchTab 清空后被恢复）、第 7 步 StartTreatment 按钮变「确认执行」；3. 「上一步」不重复注入事件；4. 第 9 步按钮变「完成」，点后坞消失、无残留高亮；5. 走完一遍 → reset → 再走一遍行为一致；6. console 无报错。

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/index.html web/style.css
git commit -m "feat: 剧情模式——九步引导剧本贯穿五 Tab，治没有叙事主线"
```

---

### Task 6: 死代码清理 + 文档同步

**Files:**
- Modify: `web/app.js`（删 `FOCUS_PREDS`、`focusSubgraph`、`renderFocusSubgraph`、`restoreFullGraph`，及 `state.filtered`/`graphElements` 相关联动）
- Modify: `learn/` 第四章（如引用 chain 格式）、`AGENTS.md`（如涉及）

**Interfaces:**
- Consumes: 无。
- Produces: 无。

- [ ] **Step 1: 删电商残留**

删除四个电商函数/常量与 `state.filtered`；`grep -n "filtered\|FOCUS_PREDS\|focusSubgraph" web/app.js` 确认零残留。注意 Task 3 已重写 `graphElements` 附近代码，删前确认无引用。

- [ ] **Step 2: 文档核对**

`grep -rn "chain\|传导" learn/ AGENTS.md README.md`：凡描述 chain 为「字符串列表/逐步文字」的表述改为四段结构化描述（感知/结算/派生/规则），引用 `World.dispatch` 代码导读处同步。learn 章节若给出示例输出，改为新格式样例。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q` → 全绿；Playwright 重走剧情模式一遍（确认清理没碰坏前端）。

- [ ] **Step 4: Commit**

```bash
git add web/app.js learn/ AGENTS.md README.md
git commit -m "chore: 清理电商残留死代码，文档同步 chain 结构化后的表述"
```
