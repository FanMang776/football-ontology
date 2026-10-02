# 足球俱乐部「活的世界」第一期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把电商本体 Demo 重建为足球俱乐部运营世界：对象运行时（perceive/compute/describe）+ 事件流入 + 派生状态传导 + 最小动作治理。

**Architecture:** 沿用五层知识库（declared/retractions/effects/material/rule_out）与 OWL-RL 推理管线，新增 `state` 图层承载对象派生状态；每个本体对象一个 Python 运行时实体，`World.dispatch(event)` 串起感知→计算→规则→建议。对象是壳，事实仍是三元组。

**Tech Stack:** Python 3 + rdflib + owlrl（OWL-RL 物化）+ FastAPI + pytest；前端原生 JS + Cytoscape.js（不变）。

**Spec:** `docs/superpowers/specs/2026-10-02-football-living-world-design.md`

## Global Constraints

- 命名空间统一为 `http://example.org/football#`（`engine/namespaces.py` 的 `EX` 改指向它）。
- 全部内存态、单用户、`KnowledgeBase._lock`（RLock）串行化模式保留。
- 确定性输出：解释文本、建议清单、审计日志不得依赖 dict/SPARQL 返回顺序（排序后处理，沿用现有 `sorted(key=str)` 惯例）；不引入 wall-clock，时间用 `kb.tick` 步进计数器。
- 中文 label、中文注释、中文解释文本的风格延续现有代码。
- `requirements.txt` 不变，不新增依赖。
- Task 2–4 期间的中间提交里，Web/API/scenarios 文案仍指电商属预期，Task 5 起恢复；但每个任务收尾 `python -m pytest -q` 必须全绿。
- fitness 公式（全计划唯一版本，禁止各任务自造）：
  `penalty = Σ round(minutes/6)（每场参与的已结束比赛） + Σ load//10（每节训练课）`；
  `relief = 20 × restGiven 标记数`；
  `fitness = max(0, min(100, 100 − penalty + relief))`。

## Review Focus

1. 非法事件字段（`minutes=0`、`weeks_out>52`、未知 type）→ API 返回 422/400，World 不被构造、无副作用。测试在 Task 5。
2. 同一球员在未恢复时再次 `InjuryEvent` → `weeksOut` 取 max，伤病记录不翻倍。测试在 Task 3。
3. 对健康球员发 `RecoveryEvent` → no-op，不异常、`state_changes` 为空。测试在 Task 3。
4. `fitness` 恰等于 `fitness_floor` → 不触发过度使用建议（严格 `<`）。测试在 Task 2。
5. 治理拒绝（CallUpYouth 超报名上限）后的动作必须写 veto 三元组，刷新后不再反复出现。测试在 Task 4。

---

### Task 1: 留底 + 足球本体重写 + 推理测试

**Files:**
- Create: 无
- Modify: `ontology/schema.ttl`（全量重写）、`ontology/data.ttl`（全量重写）、`engine/namespaces.py`、`tests/test_reasoning.py`（全量重写）
- Delete: `tests/test_rules.py`、`tests/test_actions.py`、`tests/test_scenarios.py`、`tests/test_api.py`（各任务重建）

**Interfaces:**
- Produces: 本体词汇（后续所有任务的 SPARQL/三元组用这些 IRI）：
  类 `FootballEntity`（根）、`Player`、`YouthPlayer ⊑ Player`、`Position ⊑ FootballEntity`、
  位置树 `Goalkeeper / CentreBack / Fullback / DefensiveMidfielder / AttackingMidfielder / Winger / Striker`（均 `⊑ Position`，双层：叶子 ⊑ Position 直接子类即可，不建中层）、
  `Club / Contract / Match / TrainingSession / InjuryRecord`。
  声明属性 `playsFor(Player→Club)`、`hasContract(Player→Contract)`、`contractYears(Contract→int)`、`hasPosition(Player→最细位置)`、`participatesIn(Player→Match)`、`minutesPlayed(Player→int，挂边)`、`matchday(Match→int)`、`injuredWith(Player→InjuryRecord)`、`weeksOut(InjuryRecord→int)`、`trainsIn(Player→TrainingSession)`、`load(TrainingSession→int)`、`squadOf(YouthPlayer→Club)`。
  状态属性（Task 3 写入，schema 声明）：`fitness(Player→int)`、`restGiven(Player→bool)`、`calledUp(Player→bool)`、`treated(Player→bool)`、`vetoed(动作→bool)`。
  动作类：`RestPlayer / CallUpYouth / StartTreatment`。
- Produces: 数据集（data.ttl 全量声明）：
  俱乐部 `club_star`（label「启明星 FC」）。
  一线队 14 人：GK×2（`p_gk1` 张岩、`p_gk2` 李泉）、CB×2（`p_cb1` 陈盾、`p_cb2` 王垒）、FB×2（`p_fb1` 赵翼、`p_fb2` 钱奔）、DM×1（`p_dm1` 孙闸）、AM×2（`p_am1` 周锐、`p_am2` 吴核）、WG×2（`p_wg1` 郑风、`p_wg2` 冯快）、ST×3（`p_st1` 何锋、`p_st2` 许射、`p_st3` 张凌）。
  青年队 6 人（`squadOf` 指向俱乐部、`YouthPlayer` 类型）：`p_ygk`、`p_ycb`、`p_yfb`、`p_yam1` 楚新、`p_yam2` 卫星、`p_yst`。
  合同：每名一线队球员一条 Contract（`contractYears` 1–5 各异）。
  比赛 3 场（`m_d1..m_d3`，matchday 1–3）与训练 1 节（`t_w1`）。初始伤病：`p_am2 injuredWith inj_am2`，`inj_am2 weeksOut 4`，label「腿筋拉伤」。
  出场史（保证初始 fitness 有梯度）：`p_am1` 三场全踢（90/90/85，fitness=56）、`p_st1` 三场（90/75/0→只报两场 90/75）、其余球员 0–2 场、minutes ≤ 75。

- [ ] **Step 1: 打 tag 留底**

```bash
git tag e-commerce-v1
```

- [ ] **Step 2: 重写 `engine/namespaces.py`**

```python
from rdflib import Namespace

EX = Namespace("http://example.org/football#")
```

- [ ] **Step 3: 重写 `ontology/schema.ttl` 与 `ontology/data.ttl`**

按上方 Interfaces 声明全部类、属性、数据；所有实体带 `rdfs:label` 中文标签。位置子类树是推理教学核心：`YouthPlayer ⊑ Player`、叶子位置 `⊑ Position` 必须能让 OWL-RL 闭包推出 `p_yam1 a ex:AttackingMidfielder` 与 `p_am1 a ex:Position 成员泛化`（即 `p_am1 a AttackingMidfielder` 声明 → 闭包含 `⊑ Position` 全链）。

- [ ] **Step 4: 重写 `tests/test_reasoning.py`（失败测试）**

```python
"""验证 OWL-RL 推理：位置子类泛化、YouthPlayer 归类。"""
from rdflib import RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX


def kb():
    return materialize(load_declared())


def test_position_generalization_inferred():
    """声明最细位置，祖先位置成员关系由推理补全。"""
    g = kb()
    assert (EX.p_am1, RDF.type, EX.AttackingMidfielder) in g   # 声明
    assert (EX.p_am1, RDF.type, EX.Position) in g              # 推断


def test_youth_player_is_player_and_position():
    g = kb()
    assert (EX.p_yam1, RDF.type, EX.Player) in g               # YouthPlayer ⊑ Player
    assert (EX.p_yam1, RDF.type, EX.AttackingMidfielder) in g  # 声明


def test_injury_record_linked():
    g = kb()
    assert (EX.p_am2, EX.injuredWith, EX.inj_am2) in g
    assert (EX.inj_am2, EX.weeksOut, None) in g


def test_declared_scale():
    g = load_declared()
    players = list(g.subjects(RDF.type, EX.Player))
    assert len(players) >= 20   # 14 一线队 + 6 青年队
```

- [ ] **Step 5: 删除旧测试文件**

```bash
git rm tests/test_rules.py tests/test_actions.py tests/test_scenarios.py tests/test_api.py
```

- [ ] **Step 6: 跑测试**

Run: `python -m pytest -q`
Expected: PASS（仅 test_reasoning 四例；`knowledge_base.py` 仍 import 旧 `scenarios`/`apply_vip_rules`，无人调用即可，不报错）

- [ ] **Step 7: Commit**

```bash
git add ontology/ engine/namespaces.py tests/
git commit -m "feat: 足球本体重写——位置树、伤停、阵容数据集；电商版留底 tag e-commerce-v1"
```

---

### Task 2: 足球规则层（过度使用 / 阵容缺口 / 治疗建议）

**Files:**
- Modify: `engine/rules.py`（全量重写）
- Create: `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 1 的本体词汇与数据；`engine/loader.materialize`。
- Produces: `apply_player_rules(g: Graph, floor: int = 60) -> tuple[Graph, dict]`——契约与旧 `apply_action_rules` 相同：返回 (动作三元组图, `{动作URI: {"type", "targets", "reason"}}`)，`g` 必须是含 `fitness` 状态三元组的物化图（Task 3 起由 World 写入；本任务测试里手工注入）。动作 ID 沿用 `_action_id(kind, *parts)` 模式（保留原函数，命名空间已随 EX 变）。
- Produces: 三条规则的语义（钉死）：
  - `RestPlayer(p)`：`p ex:fitness ?f . FILTER(?f < floor)` 且 p 参与 ≥3 场 `minutesPlayed ≥ 60` 的比赛，且 NOT EXISTS 该动作的 veto。
  - `CallUpYouth(y)`：某叶子位置 P 的可用一线队人数 `< 2`（可用 = 无 `weeksOut>0` 的伤病）时，对每个满足 `y a P`（推理可得）且 NOT EXISTS `ex:calledUp true` 且 NOT EXISTS veto 的青年队球员生成一条；`reason` 写明「可用人数、缺哪个位置、依据 YouthPlayer 位置推理」。
  - `StartTreatment(p)`：`p injuredWith ?rec . ?rec weeksOut ?w . FILTER(?w >= 3)` 且 NOT EXISTS `p treated true` 且 NOT EXISTS veto。
  - veto 检查在 Python 侧 `put()` 前判断：`(act, EX.vetoed, Literal(True)) in g` 则跳过。

- [ ] **Step 1: 写失败测试 `tests/test_rules.py`**

```python
"""足球动作规则：过度使用轮休、阵容缺口征调、伤停治疗。"""
from rdflib import Literal, RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_player_rules


def g_with_fitness(fitness_map):
    """物化声明图并注入 (player, fitness, value) 状态三元组。"""
    g = materialize(load_declared())
    for p, v in fitness_map.items():
        g.add((EX[p], EX.fitness, Literal(v)))
    return g


def rules(g, floor=60):
    actions, reasons = apply_player_rules(g, floor=floor)
    return reasons


def test_overuse_suggests_rest():
    """p_am1：三场 90/90/85（fitness=56 < 60）→ 建议 RestPlayer。"""
    r = rules(g_with_fitness({"p_am1": 56}))
    assert any(i["type"] == "RestPlayer" for i in r.values())


def test_fitness_equal_to_floor_not_suggested():
    """fitness 恰等于阈值 60：严格小于才建议（Review Focus 4）。"""
    r = rules(g_with_fitness({"p_am1": 60}))
    assert not any(i["type"] == "RestPlayer" for i in r.values())


def test_low_fitness_without_minutes_not_suggested():
    """低体能但出场不足 3 场 → 不建议轮休。"""
    r = rules(g_with_fitness({"p_gk1": 30}))
    assert not any(i["type"] == "RestPlayer"
                   for i in r.values() if EX.p_gk1 in i["targets"])


def test_squad_gap_suggests_callup():
    """AM 可用仅剩 p_am1（p_am2 伤停）→ 对青年队 AM 建议征调。"""
    r = rules(g_with_fitness({"p_am1": 56}))
    callups = [i for i in r.values() if i["type"] == "CallUpYouth"]
    targets = {str(t).split("#")[-1] for i in callups for t in i["targets"]}
    assert targets == {"p_yam1", "p_yam2"}


def test_treatment_suggested_for_long_injury():
    r = rules(g_with_fitness({}))
    treats = [i for i in r.values() if i["type"] == "StartTreatment"]
    targets = {str(t).split("#")[-1] for i in treats for t in i["targets"]}
    assert targets == {"p_am2"}   # weeksOut 4 ≥ 3


def test_vetoed_action_not_suggested():
    """veto 三元组在图中时，同 ID 动作不再出现（Review Focus 5 前提）。"""
    g = g_with_fitness({"p_am1": 56})
    act = EX.action_RestPlayer_p_am1
    g.add((act, EX.vetoed, Literal(True)))
    r = rules(g)
    assert act not in r
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL（`apply_player_rules` 未定义）

- [ ] **Step 3: 重写 `engine/rules.py`**

模块结构沿用旧文件：`PREFIX` 换 football 命名空间；`apply_player_rules` 内部三条 SPARQL（SELECT 匹配情况）+ Python 侧组装动作三元组与中文 reason（聚合、`sorted(key=str)` 保证确定性）。`_action_id` 与"建议是推论、不落库"的模块注释保留。AM 可用人数统计注意用物化图的类型闭包（`?q a ex:AttackingMidfielder` 需推理可达，测试图已物化）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rules.py -v`
Expected: 6 例全 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/rules.py tests/test_rules.py
git commit -m "feat: 足球动作规则——轮休/征调/治疗建议，含 veto 与阈值语义"
```

---

### Task 3: 对象运行时（事件 / 对象 / World）+ 知识库状态层接线

**Files:**
- Create: `engine/events.py`、`engine/objects.py`、`engine/world.py`、`tests/test_world.py`
- Modify: `engine/knowledge_base.py`（refresh 加 state 层、params、dispatch 入口）

**Interfaces:**
- Consumes: Task 1 本体、Task 2 `apply_player_rules`。
- Produces（后续任务依赖的精确签名）:

```python
# engine/events.py
@dataclass(frozen=True)
class MatchPlayedEvent:  player: URIRef; minutes: int
@dataclass(frozen=True)
class TrainingLoadEvent: player: URIRef; load: int
@dataclass(frozen=True)
class InjuryEvent:       player: URIRef; weeks_out: int; kind: str = "伤病"
@dataclass(frozen=True)
class RecoveryEvent:     player: URIRef
```

```python
# engine/objects.py
class BaseObject:
    def __init__(self, world, iri: URIRef)
    def perceive(self, event) -> None          # 入 inbox，无副作用
    def compute(self, kb) -> dict              # 返回 {prop短名: 值}
    def describe(self) -> dict
    # describe 返回形如：
    # {"id": str, "label": str, "type": str,
    #  "是谁": str, "现在状态": [str], "为什么": [str], "能做什么": [{"id","type"}]}
class PlayerObject(BaseObject): ...
class ClubObject(BaseObject): ...   # squadStrength = 可用一线队 fitness 之和
# engine/world.py
class World:
    def __init__(self, kb)
    def dispatch(self, event) -> dict
    # 返回 DispatchReport：
    # {"event": {"type": ..., "target": 短名},
    #  "state_changes": [{"id","prop","old","new"}],
    #  "chain": [str],          # 中文传导解释，逐步标注公理/规则依据
    #  "suggestions": [ {"id","type","targets":[短名], "reason"} ]  # 全量建议清单
    # }
    def describe(self, object_id: str) -> dict
```

- Produces（KnowledgeBase 新增/变更）:
  - `self.state: Graph`（第五层半：状态层）；`refresh()` 合并顺序 `declared − retractions + effects + state` 后物化。
  - `self.params = {"fitness_floor": 60}`；`set_params(fitness_floor: int) -> None`（夹取 0–100）。
  - `self.tick: int`（从 0 步进）；`next_step() -> int`。
  - `dispatch(event) -> dict`（加锁透传 World）。
  - `set_state(triples)`：清空 state 后写入（World 每次 compute_all 调用）。
  - `reset()`：同时清 state/audit 后续字段。
- Injury 语义钉死：`InjuryEvent` 写 effects（`(p, injuredWith, inj_N)`、`(inj_N, weeksOut, n)`、`(inj_N, RDF.type, InjuryRecord)`、label）；已有未恢复伤病时取 `max(旧, 新)`（改 weeksOut 三元组，不新增记录）。`RecoveryEvent` 从 effects 删除该球员全部伤病三元组；无伤病时 no-op。
- dispatch 流程钉死：`object.perceive(event)` → 事件效果写 effects（伤/愈）→ `compute_all()`（全部对象的 compute → `kb.set_state` → `kb.refresh()`）→ 与 dispatch 前 fitness 对比生成 `state_changes` → `chain` 由 World 组装（引用公理/规则依据的中文短句）→ `suggestions` 取 `kb.list_actions()`。

- [ ] **Step 1: 写失败测试 `tests/test_world.py`**

```python
"""对象运行时：事件感知、状态派生、重复受伤、无效恢复。"""
from rdflib import Literal

from engine.events import (InjuryEvent, MatchPlayedEvent,
                           RecoveryEvent, TrainingLoadEvent)
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX


def fresh():
    kb = KnowledgeBase()
    kb.reset()
    return kb


def test_match_event_lowers_fitness():
    kb = fresh()
    kb.dispatch(MatchPlayedEvent(EX.p_st1, 90))
    v = kb.state.value(EX.p_st1, EX.fitness)
    assert v is not None


def test_fitness_formula_deterministic():
    kb = fresh()
    kb.reset()
    kb.dispatch(MatchPlayedEvent(EX.p_st1, 90))          # penalty round(90/6)=15
    v1 = int(kb.state.value(EX.p_st1, EX.fitness))
    kb2 = fresh()
    kb2.dispatch(MatchPlayedEvent(EX.p_st1, 90))
    v2 = int(kb2.state.value(EX.p_st1, EX.fitness))
    assert v1 == v2


def test_duplicate_injury_takes_max():
    """未恢复再受伤：weeksOut 取 max，记录不翻倍（Review Focus 2）。"""
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 2, "擦伤"))
    kb.dispatch(InjuryEvent(EX.p_st1, 5, "再伤"))
    recs = list(kb.material.objects(EX.p_st1, EX.injuredWith))
    assert len(recs) == 1
    assert kb.material.value(recs[0], EX.weeksOut) == Literal(5)


def test_recovery_of_healthy_player_noop():
    """对健康球员 RecoveryEvent：不异常、无状态变化（Review Focus 3）。"""
    kb = fresh()
    report = kb.dispatch(RecoveryEvent(EX.p_st1))
    assert report["state_changes"] == []


def test_injury_then_recovery_restores():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 3, "拉伤"))
    assert list(kb.material.objects(EX.p_st1, EX.injuredWith))  # 伤病已入图
    kb.dispatch(RecoveryEvent(EX.p_st1))
    recs = list(kb.material.objects(EX.p_st1, EX.injuredWith))
    assert recs == []


def test_dispatch_report_shape():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    # 建议清单含 StartTreatment（weeksOut 4 ≥ 3）
    assert any(a["type"] == "StartTreatment" for a in kb.list_actions())


def test_training_load_event():
    kb = fresh()
    kb.dispatch(TrainingLoadEvent(EX.p_st1, 50))   # penalty 50//10 = 5
    v = int(kb.state.value(EX.p_st1, EX.fitness))
    assert v <= 95
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_world.py -v`
Expected: FAIL（模块未定义）

- [ ] **Step 3: 实现 `engine/events.py`、`engine/objects.py`、`engine/world.py`**

按 Interfaces 的签名与钉死语义。`PlayerObject.compute` 用 Global Constraints 的 fitness 公式，输入取自 kb.material（声明出场史 + effects 事件）；`ClubObject.compute` 出 squadStrength；`describe` 的「能做什么」取当前建议清单中 targets 包含自己的动作。

- [ ] **Step 4: 改造 `engine/knowledge_base.py`**

按 Interfaces 变更。`apply_player_rules(rule_input, floor=self.params["fitness_floor"])` 替换 `apply_vip_rules`；`self.world = World(self)` 延迟初始化（在 `__init__` 末尾，避免构造期递归）；删除对旧 `scenarios.risk_chain/vip_report/recommend_report` 的调用（`risk_view/supplier_risk/vip_classification/recommend` 方法整体移除；`scenarios.py` 的 `_id/_label` 改为从 `engine.world` import 或内联）。

- [ ] **Step 5: 跑全部测试**

Run: `python -m pytest -q`
Expected: PASS（test_reasoning + test_rules + test_world）

- [ ] **Step 6: Commit**

```bash
git add engine/ tests/test_world.py
git commit -m "feat: 对象运行时——事件感知、派生状态、World.dispatch 传导报告"
```

---

### Task 4: 动作治理（前置条件 / 审批 / 审计 / 预览）

**Files:**
- Modify: `engine/actions.py`（全量重写）、`engine/knowledge_base.py`（audit/pending/preview）
- Create: `tests/test_actions.py`

**Interfaces:**
- Consumes: Task 2 动作 ID/类型、Task 3 的 `kb.tick/next_step`。
- Produces（钉死）:
  - `EFFECTS`：`RestPlayer → [(p, restGiven, true)]`；`CallUpYouth → [(y, calledUp, true)]`；`StartTreatment → [(p, treated, true)]`。均无撤销侧。
  - `PRECONDITIONS = {"CallUpYouth": roster_ok}`；`roster_ok(kb) = 一线队人数 + calledUp 青年数 < 16`。拒绝时：写 `(act, EX.vetoed, True)` 进 effects，审计 `result="vetoed"`，返回 `{"ok": False, "message": ...}`。
  - `APPROVAL = {"StartTreatment"}`：第一次 `execute` 返回 `{"ok": False, "pending": True, "message": "需队医确认后再次执行"}` 并记入 `kb.pending`；对同一 action_id 再次 `execute` 即确认并执行（清出 pending）。
  - `preview(kb, action_id) -> dict`：`{"additions": ["s p o", ...], "retractions": [...]}`（短名三元组字符串），用 `EFFECTS[type](targets)` 计算，不落库；未知动作返回 `{"ok": False}`。
  - 审计：`kb.audit: list`，每次 dispatch/execute 追加 `{"step", "action", "type", "target", "result", "detail"}`；`result ∈ {"event", "executed", "vetoed", "pending", "failed"}`（事件 dispatch 也记一条，result="event"）。
  - 执行后二次防护（条件未消除回滚）逻辑保留。
- `KnowledgeBase` 新增：`pending: set`、`audit: list`、`preview(action_id)`（加锁透传）、`audit_view()` 返回按 step 排序列表；`reset()` 清空两者。

- [ ] **Step 1: 写失败测试 `tests/test_actions.py`**

```python
"""动作治理：报名上限前置条件、治疗审批两步流、审计与预览。"""
from engine.events import InjuryEvent
from engine.knowledge_base import KnowledgeBase
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


def test_treatment_needs_approval_then_executes():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    first = kb.execute(aid)
    assert first["ok"] is False and first.get("pending") is True
    second = kb.execute(aid)
    assert second["ok"] is True


def test_callup_roster_limit_vetoes():
    """一线队 14 + 已征调 2 = 16 达上限，第三次征调被拒并写 veto。"""
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))   # AM 缺口 → 建议 y_am1/y_am2
    for _ in range(2):
        aid = find(kb, "CallUpYouth", "p_yam")
        if aid:
            kb.execute(aid)
    # 再制造另一位置缺口继续征调，直到 roster 达 16 后被 veto
    assert len(kb.audit) > 0
    vetoed = [e for e in kb.audit if e["result"] == "vetoed"]
    assert vetoed  # 上限场景在两次成功征调 + 补充事件后必然出现


def test_preview_does_not_mutate():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    before = len(kb.effects)
    p = kb.preview(aid)
    assert p["additions"]
    assert len(kb.effects) == before


def test_audit_records_all_results():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    kb.execute(aid)
    kb.execute(aid)
    results = [e["result"] for e in kb.audit]
    assert "event" in results and "pending" in results and "executed" in results


def test_execute_after_condition_gone_fails_gracefully():
    kb = fresh()
    out = kb.execute("nonexistent")
    assert out["ok"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_actions.py -v`
Expected: FAIL（pending/audit/preview 未实现）

- [ ] **Step 3: 重写 `engine/actions.py` + 改造 `engine/knowledge_base.py`**

按 Interfaces。注意 `test_callup_roster_limit_vetoes` 的造数路径：一线队 14 人，两次成功征调后 `roster_ok` 为 False，若仍有 CallUpYouth 建议在清单（如再伤一名制造第二处缺口），execute 走 veto 分支写 veto 三元组并记审计。若规则在该数据下凑不满 veto 场景，允许在测试里直接 `kb.effects.add((EX.action_CallUpYouth_p_ygk, EX.vetoed 的前置动作))` 之外再 dispatch 一次 InjuryEvent（FB 或 CB 位置）来逼出第三条征调建议——实施者按实际清单选可达路径，断言不变。

- [ ] **Step 4: 跑全部测试**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/ tests/test_actions.py
git commit -m "feat: 动作治理——报名上限前置条件、治疗审批两步流、审计日志、执行预览"
```

---

### Task 5: API 足球化

**Files:**
- Modify: `api/main.py`（场景端点替换）
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 3/4 的 `kb.dispatch/describe/preview/audit_view/set_params/list_actions/execute`。
- Produces（HTTP 契约钉死）:
  - `POST /api/events`，body `{"type": "match"|"training"|"injury"|"recovery", "player_id": str, "minutes": int|None, "load": int|None, "weeks_out": int|None, "kind": str|None}`；pydantic 约束 `minutes: ge=1, le=120`、`load: ge=1, le=100`、`weeks_out: ge=1, le=52`（非法 → FastAPI 自动 422）；未知 `type` 或未知 `player_id` → 400；成功返回 DispatchReport。
  - `GET /api/object/{oid}/describe` → describe dict；未知 → 404。
  - `POST /api/preview-action/{aid}` → preview dict；`GET /api/audit` → 审计列表。
  - `POST /api/params`，body `{"fitness_floor": int}`（夹取 0–100）→ `{"ok": True, "params": {...}}`（VIP 阈值滑杆的足球等价物）。
  - `POST /api/action/{aid}/execute`、`POST /api/actions/execute-all`、`POST /api/reset`、`GET /api/graph`、`GET /api/taxonomy`（根改 `ex:FootballEntity`）、`GET /api/entity/{eid}` 保留，`graph()` 的 `shown` 白名单换足球关系（playsFor/hasContract/hasPosition/injuredWith/participatesIn/trainsIn/squadOf/RDF.type）。
  - 删除：`/api/scenario/supplier-risk`、`/api/scenario/vip`、`/api/scenario/recommend/{pid}`、`RiskBody/VipBody`。
  - `app.title` 改「足球本体世界 Demo」。

- [ ] **Step 1: 写失败测试 `tests/test_api.py`**

用 `fastapi.testclient.TestClient` + module 级 fixture（`kb.reset()` 后用）。用例钉死：

```python
def test_event_invalid_minutes_422(client):
    r = client.post("/api/events", json={"type": "match", "player_id": "p_st1", "minutes": 0})
    assert r.status_code == 422


def test_event_unknown_type_400(client):
    r = client.post("/api/events", json={"type": "party", "player_id": "p_st1"})
    assert r.status_code == 400


def test_event_unknown_player_400(client):
    r = client.post("/api/events", json={"type": "match", "player_id": "p_nope", "minutes": 90})
    assert r.status_code == 400


def test_injury_event_returns_report(client):
    r = client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert r.status_code == 200
    body = r.json()
    assert "chain" in body and "suggestions" in body


def test_describe_object(client):
    r = client.get("/api/object/p_am1/describe")
    assert r.status_code == 200
    assert set(("是谁", "现在状态", "为什么", "能做什么")) <= set(r.json())


def test_describe_unknown_404(client):
    assert client.get("/api/object/p_nope/describe").status_code == 404


def test_audit_and_params(client):
    client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert client.get("/api/audit").status_code == 200
    r = client.post("/api/params", json={"fitness_floor": 70})
    assert r.status_code == 200 and r.json()["params"]["fitness_floor"] == 70


def test_taxonomy_root(client):
    assert client.get("/api/taxonomy").status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL（端点不存在/422 缺失）

- [ ] **Step 3: 改造 `api/main.py`**

按 Interfaces。`describe` 端点用 `kb.world.describe`；事件映射到 `engine.events` 的 dataclass；`kb.reset()` 同时清 world 状态（Task 3 已做）。

- [ ] **Step 4: 跑全部测试**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: 手动冒烟**

Run: `python -m uvicorn api.main:app --reload`，浏览器开 http://127.0.0.1:8000/docs 依次试 `/api/events`、`/api/object/p_am1/describe`。确认无 500 后停掉。

- [ ] **Step 6: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: API 足球化——事件注入、对象 describe、动作预览/审批、审计、参数"
```

---

### Task 6: 命令行实验台重写

**Files:**
- Modify: `scripts/explore.py`（五步全换）

**Interfaces:**
- Consumes: Task 3/4 的 dispatch/execute/audit。保留现有 argparse 骨架与 `--step 1..5` 形态。

- [ ] **Step 1: 实现五步**

1. `--step 1`：原始三元组抽样（声明图，按主语分组打印，中文注释「白纸黑字写的事实」）
2. `--step 2`：位置子类树打印（复用 `/api/taxonomy` 的递归逻辑或直接读 declared）
3. `--step 3`：OWL-RL 推理 diff——`declared` vs `material` 的三元组差集，重点展示 `p_yam1 a Player`、`p_am1 a Position` 等位置泛化
4. `--step 4`：连续 dispatch 三个事件（`InjuryEvent(p_am1, 4)` → 演示 state_changes + chain 逐条打印）
5. `--step 5`：列出建议 → preview 一条 → execute 一条 StartTreatment（两次：pending → executed）→ 打印 audit

- [ ] **Step 2: 手动验证**

Run: `python scripts/explore.py --step 1` 至 `--step 5`
Expected: 每步输出中文、无 traceback；step 5 能看到 pending → executed 两段输出。

- [ ] **Step 3: Commit**

```bash
git add scripts/explore.py
git commit -m "feat: explore.py 五步实验台换足球世界"
```

---

### Task 7: Web 前端五 Tab 足球化

**Files:**
- Modify: `web/index.html`、`web/app.js`、`web/style.css`

**Interfaces:**
- Consumes: Task 5 全部 HTTP 契约。五 Tab 结构保留，标题与内容换：

| Tab | 内容 |
|---|---|
| 世界总览 | Cytoscape 图谱（/api/graph 契约未变，仅改图例文案）；点球员侧栏显示 /api/entity 的 declared/inferred |
| 事件流 | 四种事件注入表单（比赛/训练/受伤/恢复，含数值输入）；每次提交渲染 DispatchReport：state_changes 表 + chain 步骤列表 |
| 球员对象 | 球员下拉 → /api/object/{id}/describe 渲染对象卡（是谁/现在状态/为什么/能做什么 四栏） |
| 决策中心 | 建议清单 → 每条「预览影响」（/api/preview-action，红绿标 additions/retractions）→「执行」（StartTreatment 展示两步审批 UI）；底部审计日志表（/api/audit）；体能阈值滑杆（/api/params） |
| 学习路径 | 四章教程卡片 + 对应 explore.py 命令 |

- [ ] **Step 1: 改 `web/index.html`**——五 Tab 标题与容器结构。
- [ ] **Step 2: 改 `web/app.js`**——每个 Tab 一个渲染函数，保留现有 fetch/Cytoscape 初始化模式；事件表单提交后把 report.chain 渲染为有序步骤（复用现有风险传导的五步样式）。
- [ ] **Step 3: 浏览器验证**

用预览工具启动 uvicorn（launch.json 配置 `python -m uvicorn api.main:app --port 8000`），逐 Tab 检查：图谱有节点有边；注入一个 InjuryEvent 后决策中心出现 StartTreatment、预览显示将写 `treated true`、执行两次完成审批、审计出现三行；滑杆拖到 70 后建议清单变化。

- [ ] **Step 4: Commit**

```bash
git add web/
git commit -m "feat: Web 五 Tab 足球化——事件流、对象卡、治理决策中心"
```

---

### Task 8: 教程四章 + README + 全量验证

**Files:**
- Delete: `learn/02-用本体建模电商业务.md`、`learn/04-从查询到决策.md`
- Create: `learn/02-用能力问题建模俱乐部世界.md`、`learn/04-从状态到行动.md`
- Modify: `learn/01-本体是什么.md`、`learn/03-推理如何发生.md`（内容换足球）、`README.md`（全量重写）

**Interfaces:**
- Consumes: 全部前序成果。四章标题与 explore 步骤对齐 README 表格。

- [ ] **Step 1: 重写四章**

1. `01-本体是什么.md`：三元组与对象——用「张岩 playsFor 启明星 FC」对照关系表的 JOIN；结尾指向 `--step 1`
2. `02-用能力问题建模俱乐部世界.md`：能力问题驱动（文章第七层）——先问「谁受伤会影响下场比赛？哪些球员过度使用？」，反推出需要位置树/伤停/出场史，再展示 schema.ttl 对应片段；练习：读者自己加一个位置子类
3. `03-推理如何发生.md`：声明 vs 推断——位置泛化、YouthPlayer 归类；指向 `--step 3`
4. `04-从状态到行动.md`：五官映射（嘴=事件接口、鼻=perceive、脑=compute 派生、手=治理动作、脚=World 运行时）；传导链逐步解释；治理三要素（前置条件/审批/审计）与 Palantir 写路径对照；指向 `--step 4`、`--step 5` 与决策中心 Tab

- [ ] **Step 2: 重写 `README.md`**

结构沿用现版：安装运行、学习路径表（四章 × explore 步骤 × Web Tab）、项目结构树（加 events/objects/world）、Web 五 Tab 表、关键教学点（改写为：位置即类、声明 vs 推断、状态不落库（state 层每次重算）、建议动作是推论、效果即事实、治理=前置条件+审批+审计、审计也是写回）、已知限制（追加：fitness 公式是教学简化、治疗审批是模拟两步流）。代码引用全部指向新源码。

- [ ] **Step 3: 全量验证**

Run: `python -m pytest -q`
Expected: 全绿（预期 35+ 例）

Run: `python scripts/explore.py --step 5`
Expected: 无 traceback

- [ ] **Step 4: Commit**

```bash
git add learn/ README.md
git commit -m "docs: 四章足球教程与 README——能力问题驱动、五官映射、治理三要素"
```

---

## 收尾

- 全部任务完成后：`git log --oneline` 核对 8 个功能提交；对照 spec 的「第一期设计」逐节勾验（本体词汇、对象运行时、事件四类、派生状态、传导链、三个动作治理、五 Tab、四章、API 契约）。
- 第二期（转会窗治理）开工前按 spec 流程重新 brainstorm + design + plan。
