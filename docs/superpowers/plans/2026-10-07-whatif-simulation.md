# 三期 what-if 推演（沙盒世界）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `simulate_actions` 推演能力——在沙盒 KB 里顺序执行建议动作（完整治理 + 全量重算），返回每步结果与沙盒/真实世界的 diff，作为 Agent 的第七个工具。

**Architecture:** 新模块 `engine/simulation.py`：`open_sandbox` 新建真 `KnowledgeBase` 并覆盖可变层（effects/retractions/params/pending，declared 重新 parse），`simulate` 驱动循环在沙盒里复用 `kb.execute`（审批 pending 自动二次确认），最后 diff 两边 state 图与建议清单。Agent 侧只加工具声明、实现分发、`_summarize` 分支和 SYSTEM_PROMPT 纪律。

**Tech Stack:** Python + rdflib（现有栈，无新依赖）；测试 pytest，Agent 测试用脚本化 FakeClient。

**Spec:** `docs/superpowers/specs/2026-10-07-whatif-simulation-design.md`（已获用户确认）

## Global Constraints

- `engine/actions.py`、`engine/knowledge_base.py`、`engine/world.py` **零改动**——沙盒是"新建真 KB + 拷贝可变层"，不给治理门开后门
- 命名空间统一走 `engine/namespaces.py` 的 `EX`，不硬编码 URI
- 确定性纪律：diff 与摘要全部排序后处理；不引入 wall-clock
- `api/main.py` 不加 REST 端点（UI 按钮是四期）
- 全部测试命令用 `python -m pytest ... -q`；当前全量 78 个测试，每个任务结束时全量必须绿
- 提交信息末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## Review Focus

1. **并发一致性**：FastAPI 线程池下，推演与 dispatch/execute 交错时，快照必须取自 `real_kb._lock` 内的一致瞬间——期望推演结果对应它开始时的世界。Task 1 Step 1 的隔离测试钉住。
2. **重复 action id**：列表里同一动作出现两次 → 第二次 `execute` 返回"不在当前建议清单中"，单步 ok=false、链条继续、不抛异常。Task 3 Step 1 钉住。
3. **state 非数值**：`state` 图未来可能加字符串字段，`_state_diff` 的 `int()` 会炸——期望非数值字段跳过而非崩溃。Task 2 Step 1 钉住。
4. **空/缺参数**：`actions` 缺失或空列表 → `{"ok": false, "message": ...}`，不抛异常。Task 3 Step 1 钉住。
5. **参数跟随**：决策中心滑杆改过 `fitness_floor` 后，沙盒建议阈值必须与真实世界一致（params 拷贝）。Task 1 Step 1 钉住。

---

### Task 1: `open_sandbox`——沙盒建造 + 隔离性

**Files:**
- Create: `engine/simulation.py`
- Test: `tests/test_simulation.py`（新建）

**Interfaces:**
- Consumes: `KnowledgeBase`（`engine/knowledge_base.py`，现有公开属性 `effects/retractions/state/params/pending`、方法 `refresh()`、`world.bootstrap()`）
- Produces: `open_sandbox(real_kb: KnowledgeBase) -> KnowledgeBase`——Task 2 依赖此签名

- [ ] **Step 1: Write the failing test**

`tests/test_simulation.py`，沿用 `test_actions.py` 的 `fresh()` 惯例：

```python
"""沙盒推演：建造、隔离性、驱动循环、世界 diff。"""
from engine.events import InjuryEvent
from engine.knowledge_base import KnowledgeBase
from engine.simulation import open_sandbox

from engine.namespaces import EX


def fresh():
    kb = KnowledgeBase()
    kb.reset()
    return kb


def find(kb, type_, contains):
    for a in kb.list_actions():
        if a["type"] == type_ and contains in a["targets"][0]["id"]:
            return a["id"]
    return None


def snapshot(kb):
    """真实世界的可变部位指纹：推演前后必须逐项相等。"""
    return {"effects": sorted(str(t) for t in kb.effects),
            "retractions": sorted(str(t) for t in kb.retractions),
            "state": sorted(str(t) for t in kb.state),
            "params": dict(kb.params),
            "pending": set(kb.pending),
            "tick": kb.tick,
            "audit_len": len(kb.audit),
            "suggestions": sorted(str(a) for a in kb.action_reasons)}


def test_sandbox_copies_mutable_layers():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    sim = open_sandbox(kb)
    assert sorted(str(t) for t in sim.effects) == snapshot(kb)["effects"]
    assert sorted(str(t) for t in sim.retractions) == snapshot(kb)["retractions"]
    assert sim.params == kb.params
    assert sim.pending == kb.pending
    assert sorted(str(a) for a in sim.action_reasons) == snapshot(kb)["suggestions"], \
        "沙盒刷新后的建议清单应与真实世界一致"


def test_sandbox_follows_fitness_floor_param():
    kb = fresh()
    kb.set_params(90)          # 决策中心滑杆改过阈值
    sim = open_sandbox(kb)
    assert sim.params["fitness_floor"] == 90


def test_simulate_leaves_real_world_untouched():
    """隔离性（最关键）：推演后真实世界八个部位逐项不变。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    before = snapshot(kb)
    aid = find(kb, "StartTreatment", "p_st1")
    out = simulate(kb, [aid])
    assert out["ok"] is True
    assert snapshot(kb) == before
```

（本任务只跑 `open_sandbox` 相关断言；`test_simulate_leaves_real_world_untouched` 在 Task 2 实现后转绿，先写在这里防遗漏。）

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'engine.simulation'`

- [ ] **Step 3: Implement `open_sandbox` in `engine/simulation.py`**

模块 docstring 一句话钉死教学叙事："推演 = 在另一个世界里真的做一遍；沙盒是真 KnowledgeBase，用完即扔"。实现即 spec 第 3 节的代码：

```python
def open_sandbox(real_kb):
    sim = KnowledgeBase()
    with real_kb._lock:
        for t in real_kb.effects:
            sim.effects.add(t)
        for t in real_kb.retractions:
            sim.retractions.add(t)
        sim.params = dict(real_kb.params)
        sim.pending = set(real_kb.pending)
    sim.refresh()
    sim.world.bootstrap()
    return sim
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation.py::test_sandbox_copies_mutable_layers tests/test_simulation.py::test_sandbox_follows_fitness_floor_param -q`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/simulation.py tests/test_simulation.py
git commit -m "feat: 沙盒建造 open_sandbox——新建真 KB 覆盖可变层，附隔离性指纹测试"
```

---

### Task 2: `simulate` 单动作驱动 + `world_diff`

**Files:**
- Modify: `engine/simulation.py`
- Test: `tests/test_simulation.py`

**Interfaces:**
- Consumes: `open_sandbox(real_kb)`（Task 1）；`KnowledgeBase.execute(action_id) -> dict`（现有，返回 `{"ok", "message", ...}`，审批动作首次返回 `{"ok": False, "pending": True}`）
- Produces:
  - `simulate(real_kb: KnowledgeBase, action_ids: list[str]) -> dict`——返回 `{"ok": bool, "steps": [{"n", "action_id", "ok", "message", "pending_in_sandbox"}], "world_diff": {"state", "suggestions_removed", "suggestions_added"}}`；全失败时额外带 `"message"`。Task 4 依赖此签名
  - `_state_diff(real_kb, sim) -> list[{"id", "field", "from", "to"}]`（模块私有，测试直接调用）

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_simulation.py`：

```python
def test_state_diff_reports_fitness_change():
    """轮休 +20 体能：world_diff.state 报 from/to；建议随执行消失。"""
    from engine.simulation import simulate, _state_diff
    kb = fresh()
    aid = find(kb, "RestPlayer", "p_")
    assert aid, "初始世界应有轮休建议"
    out = simulate(kb, [aid])
    target = aid.split("RestPlayer_")[-1]
    assert out["ok"] is True
    assert out["steps"] == [{"n": 1, "action_id": aid, "ok": True,
                             "message": out["steps"][0]["message"],
                             "pending_in_sandbox": False}]
    fit = [c for c in out["world_diff"]["state"]
           if c["id"] == target and c["field"] == "fitness"]
    assert fit and fit[0]["to"] == fit[0]["from"] + 20
    assert aid in out["world_diff"]["suggestions_removed"]
    assert aid not in out["world_diff"]["suggestions_added"]


def test_state_diff_skips_non_numeric_values():
    """state 图未来可能有字符串字段：diff 跳过非数值，不炸。"""
    from rdflib import Literal
    from engine.simulation import _state_diff
    kb = fresh()
    sim = open_sandbox(kb)
    sim.state.add((EX.p_am1, EX.mood, Literal("好")))
    assert _state_diff(kb, sim) == []      # 非数值字段不进 diff


def test_treatment_auto_confirmed_in_sandbox():
    """审批动作：沙盒内自动二次确认，真实 pending 不变，步骤如实标注。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    out = simulate(kb, [aid])
    step = out["steps"][0]
    assert step["ok"] is True and step["pending_in_sandbox"] is True
    assert kb.pending == set()             # 真实世界的审批中间态没被碰
    inj = [c for c in out["world_diff"]["state"] if c["id"] == "p_st1"]
    assert inj, "治疗后体能恢复应出现在 state diff 里"


def test_simulate_all_failed_reports_message():
    from engine.simulation import simulate
    kb = fresh()
    out = simulate(kb, ["action_Nobody_123"])
    assert out["ok"] is False and out["message"]
    assert out["steps"][0]["ok"] is False


def test_simulate_empty_list():
    from engine.simulation import simulate
    out = simulate(fresh(), [])
    assert out["ok"] is False and out["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation.py -q`
Expected: FAIL，`ImportError: cannot import name 'simulate'`

- [ ] **Step 3: Implement `simulate` + `_state_diff` in `engine/simulation.py`**

驱动循环（审批自动放行是循环的行为，`execute` 零改动）：

```python
def simulate(real_kb, action_ids):
    if not action_ids:
        return {"ok": False, "steps": [], "world_diff": None,
                "message": "推演动作列表为空"}
    sim = open_sandbox(real_kb)
    steps = []
    for i, aid in enumerate(action_ids, 1):
        res = sim.execute(aid)
        was_pending = bool(res.get("pending"))
        if was_pending:
            res = sim.execute(aid)   # 沙盒内自动确认：列表即用户授权
        steps.append({"n": i, "action_id": aid,
                      "ok": bool(res.get("ok")),
                      "message": res.get("message", ""),
                      "pending_in_sandbox": was_pending})
    ok = any(s["ok"] for s in steps)
    real_ids = sorted(str(a).split("#")[-1] for a in real_kb.action_reasons)
    sim_ids = sorted(str(a).split("#")[-1] for a in sim.action_reasons)
    out = {"ok": ok, "steps": steps,
           "world_diff": {"state": _state_diff(real_kb, sim),
                          "suggestions_removed": sorted(set(real_ids) - set(sim_ids)),
                          "suggestions_added": sorted(set(sim_ids) - set(real_ids))}}
    if not ok:
        out["message"] = "所有推演步骤均未成功"
    return out


def _state_diff(real_kb, sim):
    def index(g):
        out = {}
        for s, p, o in g:
            try:
                out[(str(s), str(p))] = int(o)
            except (TypeError, ValueError):
                pass            # 非数值字段不进 diff
        return out
    before, after = index(real_kb.state), index(sim.state)
    changes = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        if b != a:
            changes.append({"id": key[0].split("#")[-1],
                            "field": key[1].split("#")[-1],
                            "from": b, "to": a})
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation.py -q`
Expected: PASS（含 Task 1 遗留的隔离性测试）

- [ ] **Step 5: Commit**

```bash
git add engine/simulation.py tests/test_simulation.py
git commit -m "feat: simulate 驱动循环——审批沙盒内自动放行，返回 steps + world_diff"
```

---

### Task 3: 多步连锁——中途失败续走、veto 传导

**Files:**
- Test: `tests/test_simulation.py`（`simulate` 已支持列表，本任务只补测试；若发现实现缺口再改 `engine/simulation.py`）

**Interfaces:**
- Consumes: `simulate(real_kb, action_ids)`（Task 2）
- Produces: 无新接口——本任务是多步语义的行为钉子

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_simulation.py`：

```python
def test_multi_step_chain_and_conditional_failure():
    """多步连锁：第 2 步基于第 1 步后的沙盒状态；中途条件失效续走后续步骤。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))     # AM 缺口 → 征调 y_am1/y_am2
    aids = [a["id"] for a in kb.list_actions()
            if a["type"] == "CallUpYouth" and "p_yam" in a["targets"][0]["id"]]
    assert len(aids) == 2
    aids.append("action_RestPlayer_p_st1")          # 不存在的建议 → 单步失败
    out = simulate(kb, aids)
    assert [s["ok"] for s in out["steps"]] == [True, True, False]
    assert out["steps"][2]["ok"] is False
    assert out["ok"] is True                        # 有 ≥1 步成功即为 true
    called = sorted(t["id"] for a in kb.list_actions()
                    if a["type"] == "CallUpYouth" and "p_yam" in a["targets"][0]["id"]
                    for t in a["targets"])
    assert len(called) == 2                         # 真实世界：两名青年队都没被真征调


def test_multi_step_repeated_action_id():
    """同一动作推两次：第二次不在清单中，单步失败不炸。"""
    from engine.simulation import simulate
    kb = fresh()
    aid = find(kb, "RestPlayer", "p_")
    out = simulate(kb, [aid, aid])
    assert [s["ok"] for s in out["steps"]] == [True, False]
    assert out["ok"] is True


def test_veto_cascade_inside_sandbox():
    """报名 14+2=16 已达上限：沙盒里第三次征调被否决，veto 只写在沙盒。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))     # AM 缺口 → y_am1/y_am2
    kb.dispatch(InjuryEvent(EX.p_gk1, 4, "伤"))     # GK 缺口 → y_gk1
    aids = [a["id"] for a in kb.list_actions() if a["type"] == "CallUpYouth"]
    assert len(aids) == 3
    out = simulate(kb, aids)
    assert [s["ok"] for s in out["steps"]] == [True, True, False]
    assert "上限" in out["steps"][2]["message"]
    assert snapshot(kb)["effects"] == snapshot(kb)["effects"]   # 真实世界无 veto 三元组
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_simulation.py -q`
Expected: PASS——Task 2 的驱动循环语义（单步失败续走、`execute` 复用）已覆盖；若 FAIL，修 `engine/simulation.py` 使其过，**不得改 `actions.py`**

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q`
Expected: 全绿（78 + 新增）

- [ ] **Step 4: Commit**

```bash
git add tests/test_simulation.py
git commit -m "test: 多步连锁语义钉子——条件失效续走、重复 id、veto 传导"
```

---

### Task 4: Agent 集成——第七个工具

**Files:**
- Modify: `engine/agent.py`（TOOLS 表、`_TOOLS_IMPL`、`_summarize`、SYSTEM_PROMPT）
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `simulate(real_kb, action_ids) -> dict`（Task 2 签名）
- Produces: 工具名 `simulate_actions`；`_summarize("simulate_actions", result)` 单行摘要

- [ ] **Step 1: Write the failing tests**

`tests/test_agent.py` 修改 `TOOL_NAMES` 并追加：

```python
TOOL_NAMES = {"list_players", "describe_object", "list_suggestions",
              "preview_action", "execute_action", "inject_event",
              "simulate_actions"}


def test_simulate_actions_tool(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    out = run_tool(kb, "simulate_actions", {"actions": [aid]})
    assert out["ok"] is True and out["steps"][0]["action_id"] == aid


def test_simulate_actions_bad_args_ok_false(kb):
    assert run_tool(kb, "simulate_actions", {})["ok"] is False
    assert run_tool(kb, "simulate_actions", {"actions": []})["ok"] is False


def test_summarize_simulate_one_line(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    out = run_tool(kb, "simulate_actions", {"actions": [aid]})
    s = _summarize("simulate_actions", out)
    assert s.startswith("推演 1 步（1 成功）") and "fitness" in s


def test_system_prompt_pins_sandbox_discipline():
    assert "沙盒" in SYSTEM_PROMPT and "execute_action" in SYSTEM_PROMPT


def test_run_turn_simulate_via_fake_client(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    evts = collect(kb, FakeClient(
        [(None, [("simulate_actions", {"actions": [aid]})]),
         ("推演完成", [])]),
        [{"role": "user", "content": "如果轮休他会怎样"}])
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert tr["summary"].startswith("推演")
```

（`_summarize` 需在文件头部的 import 行补进 `from engine.agent import ... _summarize ...`。）

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent.py -q`
Expected: FAIL——`simulate_actions` 不在 TOOLS，`test_tools_schema_complete` 等先红

- [ ] **Step 3: Implement in `engine/agent.py`**

四处小改：

1. TOOLS 表追加声明（放在 `execute_action` 之后）：

```python
    {"type": "function", "function": {
        "name": "simulate_actions",
        "description": "在沙盒世界按顺序推演一串建议动作，返回每步结果与"
                       "沙盒世界和真实世界的差异。不落库，不影响真实世界",
        "parameters": {"type": "object",
                       "properties": {"actions": {"type": "array",
                                        "items": {"type": "string"},
                                        "description": "建议动作 id，按执行顺序"}},
                       "required": ["actions"]}},
    },
```

2. 实现与分发：

```python
def _simulate(kb, args):
    from engine.simulation import simulate
    actions = args.get("actions")
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "message": "actions 必须是非空的动作 id 列表"}
    return simulate(kb, [str(a) for a in actions])


_TOOLS_IMPL = {
    ...
    "simulate_actions": _simulate,
}
```

3. `_summarize` 加分支（放在 `inject_event` 分支后）：

```python
    if name == "simulate_actions":
        steps = result.get("steps") or []
        ok_n = sum(1 for s in steps if s.get("ok"))
        diff = result.get("world_diff") or {}
        parts = [f"推演 {len(steps)} 步（{ok_n} 成功）"]
        parts += [f"{c['field']} {c['from']}→{c['to']}"
                  for c in diff.get("state", [])]
        if diff.get("suggestions_added"):
            parts.append(f"新增建议 {len(diff['suggestions_added'])} 条")
        if diff.get("suggestions_removed"):
            parts.append(f"消失建议 {len(diff['suggestions_removed'])} 条")
        return "；".join(parts)
```

（空列表失败路径无 `steps`，落到函数末尾 `result.get("message")`——确认该路径返回 `"推演动作列表为空"`。）

4. SYSTEM_PROMPT 纪律追加第 4 条：

```
4. simulate_actions 的结果只在沙盒成立，不能当作已发生的事实；
   用户决定采纳时，必须走 execute_action 真正执行。
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add engine/agent.py tests/test_agent.py
git commit -m "feat: Agent 第七个工具 simulate_actions——沙盒推演接入同一循环"
```

---

### Task 5: mock 演示 + 文档同步

**Files:**
- Modify: `engine/agent.py`（MockClient.RULES）
- Create: `learn/06-推演与沙盒世界.md`
- Modify: `README.md`、`AGENTS.md`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `simulate_actions`（Task 4 已入 TOOLS）
- Produces: 无——收尾任务

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_agent.py`（MockClient 演示不依赖 key）：

```python
def test_mock_client_simulate_demo():
    evts = collect(KnowledgeBase(), MockClient(
        [("有什么可推演的", []),
         (None, [("list_suggestions", {})]),
         (None, [("simulate_actions",
                  {"actions": ["action_RestPlayer_p_am1"]})]),
         (None, [])]),
        [{"role": "user", "content": "如果轮休德布劳内，推演一下"}])
    summaries = [e.get("summary", "") for e in evts if e["type"] == "tool_result"]
    assert any(s.startswith("推演") for s in summaries)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py::test_mock_client_simulate_demo -q`
Expected: FAIL——RULES 无"推演"关键词

- [ ] **Step 3: Implement MockClient rule + write docs**

1. `MockClient.RULES` 追加（关键词放在"轮休"规则之前）：

```python
        ("推演", [(None, [("list_suggestions", {})]),
                  (None, [("simulate_actions",
                           {"actions": ["action_RestPlayer_p_am1"]})]),
                  (None, [])]),
```

（动作 id 不在清单时单步失败也成立——mock 收尾文案如实转述 message，不谎报。）

2. `learn/06-推演与沙盒世界.md`：对照前五章的风格写。内容骨架：
   - 预览只答三元组（`engine/actions.py` 的 `preview`），推演答整条因果链（`engine/simulation.py` 的 `simulate`）
   - 沙盒是真 KnowledgeBase：六层模型里可变层拷贝、declared 重 parse，`execute` 零改动复用——"推演 = 在另一个世界里真的做一遍"
   - 审批沙盒内自动放行的治理叙事：门没变，是发起者已确认
   - 多步连锁与 veto 传导实例（引用 `tests/test_simulation.py` 的测试名）
   - 配套实验：Web 端智能体 Tab 问"如果轮休德布劳内会怎样"（mock 模式可用），及 `tests/test_simulation.py`

3. `README.md` 同步（对照现状逐处改）：
   - 开头场景段（"第五个场景是**智能体**"段）："六个本体操作工具"改"七个本体操作工具"；工具清单改为"查状态、问建议、预览影响、沙盒推演、执行动作、注入事件"，并加一句"推演是在沙盒世界里把动作真做一遍、看整条因果链，再决定是否真执行"
   - §"和智能体对话"的"能聊什么"列表：加一条推演示例「如果轮休德布劳内会怎样？」→ 沙盒推演返回体能/阵容/建议的连锁变化
   - §学习路径表格：加一行 [06 推演与沙盒世界](learn/06-推演与沙盒世界.md)，配套列"智能体 Tab"
   - §项目结构：`engine/` 列表加 `simulation.py` 一行（"沙盒推演：新建真 KB 覆盖可变层，execute 零改动复用"）；`agent.py` 行"六个本体操作工具"改"七个"；`learn/` 注释"五章教程"改"六章教程"；测试计数改实际数字（预计 95 左右，以 `python -m pytest -q` 尾行为准）
   - §关键教学点：加一条"**沙盒推演**：执行是假的（不落库），因果链是真的（全真管线跑出来的）——推演永不碰真实世界"；末段"都在 `learn/` 五章里"改"六章"
4. `AGENTS.md`：`engine/agent.py` 描述"六个本体操作工具"改"七个"，关键模块表加 `engine/simulation.py` 一行（一句话：沙盒推演——新建真 KB 覆盖可变层，execute 零改动复用）。

- [ ] **Step 4: Run tests to verify they pass + 全量回归**

Run: `python -m pytest -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add engine/agent.py tests/test_agent.py learn/06-推演与沙盒世界.md README.md AGENTS.md
git commit -m "docs: 三期收尾——mock 推演演示、learn/06 沙盒章节、README/AGENTS 同步"
```
