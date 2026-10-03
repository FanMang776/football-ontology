# 规则手册(Rule Handbook)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引擎全部 7 条规则(3 建议 + 4 治理)以声明式注册表暴露为 `GET /api/rules`,学习路径 Tab 渲染"规则手册",阈值随滑杆实时更新。

**Architecture:** 新建 `engine/rule_meta.py`(声明式元数据 + `render(params)` 格式化);`KnowledgeBase.rules_view()` 带锁委托;FastAPI 只读端点;前端纯 JS 渲染。防漂移靠 import 层复用 `engine/actions` 常量 + 契约测试。

**Tech Stack:** rdflib 无关(纯 Python dict)、FastAPI、原生 JS。

**Spec:** `docs/superpowers/specs/2026-10-03-rule-handbook-design.md`

## Global Constraints

- 规则语义权威在 `rules.py`/`actions.py` 实现与测试;`rule_meta.py` 只做展示元数据,docstring 必须写明这一点
- 确定性纪律:输出顺序固定(RULES 列表顺序即展示顺序),不引入 wall-clock
- `rules_view` 必须经 `kb._lock`(AGENTS.md 并发纪律)
- 命名空间不涉及(无新 URI);不动六层知识模型
- 中文文案用本计划钉死的原文,实现者不自行改写

## Review Focus

1. **滑杆调阈值后手册仍显旧值** — 期望:滑杆防抖回调刷新手册。Test:`test_rules_reflect_current_params`(API 层,Task 2)+ Task 3 的 onFloorSlider 调用(人工验证步骤)。
2. **新增动作类型但手册漏写** — 期望:测试红。Test:`test_rule_handbook_covers_all_action_types`(`len(suggestion) == len(EFFECTS)`,Task 1)。
3. **chapter 指向不存在的教程文件** — 期望:测试红。Test:`test_rule_handbook_chapter_files_exist`(Task 1)。
4. **条件文案含 `{}` 误参与 format** — 期望:render 用全参数表跑通全部 RULES。Test:`test_render_formats_current_params` 覆盖每条规则(断言 7 条全渲染成功,Task 1)。
5. **未持锁读参数与物化图** — 期望:`rules_view` 内 `with self._lock`。API 测试并发性测不出,列入代码评审检查项(Task 2 步骤里显式给出)。

---

### Task 1: `engine/rule_meta.py` 规则注册表

**Files:**
- Create: `engine/rule_meta.py`
- Test: `tests/test_rules.py`(文件末尾追加)

**Interfaces:**
- Consumes: `engine.actions.EFFECTS`(dict,3 个动作类型键)、`engine.actions.ROSTER_LIMIT`(int,16)
- Produces: `RULES: list[dict]`(7 条,字段 id/name/category/summary/conditions/code/chapter);`render(params: dict) -> list[dict]`,params 为 `{"fitness_floor": int, "roster_limit": int}`,返回条目中 conditions 变为 `[{"text": str, "dynamic": bool}]`,chapter 为 `list[str]`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_rules.py`;该文件已 import pytest 与 `engine.rules`,按需补 `from engine.actions import EFFECTS` 与 `from engine.rule_meta import RULES, render`)

```python
# ---------- 规则手册(rule_meta)契约 ----------

ALL_RULE_IDS = {"rest-player", "callup-youth", "start-treatment",
                "roster-limit", "treatment-approval",
                "veto-suppression", "audit-trail"}


def test_rule_handbook_covers_all_action_types():
    """新增动作类型而漏写手册 → 红。"""
    sug = [r for r in RULES if r["category"] == "suggestion"]
    assert len(sug) == len(EFFECTS)
    assert {r["id"] for r in sug} == {"rest-player", "callup-youth", "start-treatment"}


def test_rule_handbook_covers_governance():
    assert len([r for r in RULES if r["category"] == "governance"]) >= 4
    assert {r["id"] for r in RULES} == ALL_RULE_IDS


def test_rule_handbook_chapter_files_exist():
    import os
    for r in RULES:
        for ch in r["chapter"]:
            assert os.path.exists(ch), f"{r['id']} 的章节 {ch} 不存在"


def test_render_formats_current_params():
    out = render({"fitness_floor": 90, "roster_limit": 16})
    assert len(out) == 7
    rest = next(r for r in out if r["id"] == "rest-player")
    assert rest["conditions"][0] == {"text": "体能低于阈值 90", "dynamic": True}
    assert rest["conditions"][1] == {"text": "近期高强度出场(任一场 ≥ 60 分钟)至少 3 场",
                                     "dynamic": False}
    limit = next(r for r in out if r["id"] == "roster-limit")
    assert "16" in limit["conditions"][0]["text"]


def test_render_missing_param_raises():
    import pytest
    with pytest.raises(KeyError):
        render({"fitness_floor": 60})   # 缺 roster_limit
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rules.py -q -k handbook or render`
Expected: FAIL(ModuleNotFoundError: engine.rule_meta)

- [ ] **Step 3: 实现 `engine/rule_meta.py`**

模块 docstring 第一句:"规则手册:全部规则的声明式展示元数据;权威语义仍在 rules.py / actions.py 的实现与测试里,改规则必须同步改这里(契约测试会抓)。" 常量 `DEFAULT_PARAMS = {"fitness_floor": 60, "roster_limit": ROSTER_LIMIT}`(`ROSTER_LIMIT` 从 `engine.actions` import,不写字面量 16)。

`RULES` 按此顺序与文案钉死(conditions 里 `params` 列出该条件引用的参数键):

1. `rest-player` / 轮休 / suggestion / "过度使用的球员应当轮休恢复。" / conditions: `{"text": "体能低于阈值 {fitness_floor}", "params": ["fitness_floor"]}`、`{"text": "近期高强度出场(任一场 ≥ 60 分钟)至少 3 场", "params": []}` / code: `engine/rules.py:104` / chapter: `["learn/04-从状态到行动.md"]`
2. `callup-youth` / 征调青年队 / suggestion / "位置出现一线队缺口时,从青年队征调补缺。" / conditions: `{"text": "位置可用一线队球员(未伤停)不足 2 人", "params": []}`、`{"text": "存在可征调的该位置青年队球员", "params": []}` / code: `engine/rules.py:111` / chapter: `["learn/03-推理如何发生.md", "learn/04-从状态到行动.md"]`
3. `start-treatment` / 启动治疗 / suggestion / "重伤球员需要队医启动治疗。" / conditions: `{"text": "伤停周数 ≥ 3 周", "params": []}` / code: `engine/rules.py:124` / chapter: `["learn/04-从状态到行动.md"]`
4. `roster-limit` / 报名上限 / governance / "征调有前置条件:报名名单不能超员。" / conditions: `{"text": "报名名单(一线队 + 已征调)< {roster_limit} 人,违反则写 veto 并拒绝执行", "params": ["roster_limit"]}` / code: `engine/actions.py:45` / chapter: `["learn/04-从状态到行动.md"]`
5. `treatment-approval` / 治疗两步审批 / governance / "治疗动作需队医确认,不是一次执行即生效。" / conditions: `{"text": "首次执行返回待审批(pending),对同一动作再次执行即确认", "params": []}` / code: `engine/actions.py:30` / chapter: `["learn/04-从状态到行动.md"]`
6. `veto-suppression` / veto 抑制 / governance / "被否决的动作不再出现在建议清单——建议是推论。" / conditions: `{"text": "动作被否决时写 veto 事实,规则层每次刷新都会跳过它", "params": []}` / code: `engine/rules.py:95` / chapter: `["learn/04-从状态到行动.md"]`
7. `audit-trail` / 审计留痕 / governance / "每一次执行、否决与事件注入都进审计日志。" / conditions: `{"text": "每次执行/否决/事件注入写入审计,step 为确定性步进计数器", "params": []}` / code: `engine/actions.py:60` / chapter: `["learn/04-从状态到行动.md"]`

```python
def render(params: dict) -> list:
    """代入当前参数,返回前端可直接渲染的条目;参数缺失由 str.format 抛 KeyError。"""
    out = []
    for r in RULES:
        conds = [{"text": c["text"].format(**params) if c["params"] else c["text"],
                  "dynamic": bool(c["params"])} for c in r["conditions"]]
        out.append({**r, "conditions": conds})
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rules.py -q`
Expected: 全部 PASS(含原有测试)

- [ ] **Step 5: Commit**

```bash
git add engine/rule_meta.py tests/test_rules.py
git commit -m "feat: 规则手册注册表 engine/rule_meta.py——7 条规则的声明式元数据 + render 格式化,契约测试防漂移"
```

---

### Task 2: `GET /api/rules` 端点

**Files:**
- Modify: `engine/knowledge_base.py`(`audit_view` 之后,约 :114)
- Modify: `api/main.py`(`/api/actions` 端点之后)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 的 `render(params: dict) -> list[dict]`;`kb.params`(dict,含 `fitness_floor`)
- Produces: `KnowledgeBase.rules_view() -> list[dict]`;`GET /api/rules` → `{"rules": [...]}`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_api.py`)

```python
def test_rules_endpoint_lists_all(client):
    rules = client.get("/api/rules").json()["rules"]
    assert len(rules) == 7
    assert {r["id"] for r in rules} == {
        "rest-player", "callup-youth", "start-treatment",
        "roster-limit", "treatment-approval", "veto-suppression", "audit-trail"}


def test_rules_reflect_current_params(client):
    client.post("/api/params", json={"fitness_floor": 90})
    rules = client.get("/api/rules").json()["rules"]
    rest = next(r for r in rules if r["id"] == "rest-player")
    assert "90" in rest["conditions"][0]["text"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api.py -q -k rules`
Expected: FAIL(404 Not Found)

- [ ] **Step 3: 实现**

`engine/knowledge_base.py`,`audit_view` 之后新增(锁为评审检查项,必须在内):

```python
    def rules_view(self) -> list:
        """规则手册:阈值代入当前参数。"""
        with self._lock:
            from engine.actions import ROSTER_LIMIT
            from engine.rule_meta import render
            return render(dict(self.params) | {"roster_limit": ROSTER_LIMIT})
```

`api/main.py`,`actions` 端点之后新增:

```python
@app.get("/api/rules")
def rules():
    """规则手册:全部建议规则与治理机制(条件代入当前参数)。"""
    return {"rules": kb.rules_view()}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_api.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/knowledge_base.py api/main.py tests/test_api.py
git commit -m "feat: GET /api/rules——规则手册端点,阈值代入当前参数"
```

---

### Task 3: 前端规则手册(学习路径 Tab)

**Files:**
- Modify: `web/index.html`(learn panel,`<p class="hint muted">每个 Tab 都是…` 之前)
- Modify: `web/app.js`(Tab 四区块之后新增区块;挂载 4 个调用点)
- Modify: `web/style.css`(`.learn-card` 相关样式附近)

**Interfaces:**
- Consumes: Task 2 的 `GET /api/rules` → `{"rules": [{id, name, category, summary, conditions: [{text, dynamic}], code, chapter: [str]}]}`
- Produces: 无(终端 UI)

- [ ] **Step 1: `web/index.html` 加容器**

learn panel 内、四章卡片之后、`<p class="hint muted">每个 Tab…` 之前插入:

```html
      <p class="kicker">规则手册 · 全部规则与触发条件</p>
      <div id="rule-handbook"></div>
```

- [ ] **Step 2: `web/app.js` 加 `loadRules()`**

`loadAudit` 之后新增(esc 已有;`RULE_CATEGORY_ZH` 放文件顶部 `ACTION_ZH` 旁):

```javascript
const RULE_CATEGORY_ZH = { suggestion: '状态建议规则', governance: '治理边界' };

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
```

挂载 4 个调用点:

1. `switchTab` 的 learn 分支(:590 `/* 静态内容 */` 处):改为 `loadRules().catch(e => toast(e.message, true));`
2. `init()` 末尾追加 `loadRules().catch(() => {});`(首屏即有内容)
3. `onFloorSlider` 防抖回调里 `await loadActions();` 改为 `await Promise.all([loadActions(), loadRules()]);`
4. `resetDemo` 的 `Promise.all` 里追加 `loadRules()`

- [ ] **Step 3: `web/style.css` 加样式**

新增类:`.rule-group-title`(小节标题,视觉对齐 `.kicker`)、`.rule-card`(对齐 `.learn-card`)、`.rule-name`(粗体)、`.rule-summary`、`.rule-conditions`(ul,紧凑行距)、`.rule-dynamic`(动态阈值条件加强调色,让"参数是活的"可辨识)、`.rule-meta`(muted 小字,代码位置与章节)。具体数值实现者按 `.learn-card`/`.why` 现有视觉语言定。

- [ ] **Step 4: 浏览器验证**

Run: `python -m uvicorn api.main:app --port 8001` 起服务,浏览器验证:
1. 学习路径 Tab 显示两组共 7 张规则卡,底部队列显示代码位置与章节名;
2. 决策中心把阈值滑杆从 60 拨到 75,回学习路径,轮休卡条件显示"体能低于阈值 75"(切 Tab 会重新拉取);
3. 点"重置演示"后手册仍在。

Expected: 三项全部符合。

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat: 学习路径 Tab 渲染规则手册——两组 7 卡,阈值条件随滑杆实时刷新"
```

---

### Task 4: 收尾——文档同步 + 全量回归

**Files:**
- Modify: `AGENTS.md`(「关键模块」小节)
- Modify: `learn/04-从状态到行动.md`(仅核对,如正文与手册条件表述冲突以实现为准修正)

**Interfaces:**
- Consumes: 前 3 个任务的全部产出
- Produces: 无

- [ ] **Step 1: AGENTS.md 补一行**

「关键模块」列表中 `engine/rules.py` 行后加:

```markdown
- `engine/rule_meta.py` — 规则手册:全部规则的声明式展示元数据(render 代入当前参数);改规则时同步更新,契约测试防漂移
```

- [ ] **Step 2: 核对 learn/04**

通读 `learn/04-从状态到行动.md`,检查正文对轮休/征调/治疗/前置条件/审批/veto 的条件表述与 `RULES` 文案是否一致;不一致处以实现为准修正正文(预计无需改动)。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md learn/04-从状态到行动.md
git commit -m "docs: AGENTS.md 与 learn/04 同步规则手册设计"
```
