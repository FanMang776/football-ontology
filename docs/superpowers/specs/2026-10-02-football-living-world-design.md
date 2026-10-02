# 设计：足球俱乐部「活的世界」（对象运行时改造）

日期：2026-10-02
状态：待用户评审

## 背景与目标

用户已有一个电商本体学习 Demo（RDF/OWL + SPARQL，四章教程，五 Tab 前端）。结合两篇本体论文章（《本体应用，用通俗易懂的方式解释》《本体论的演进：从形式语义学到知识图谱、决策与 AI Agent》）与 Palantir 本体思想，进行架构级改造。

**改造目的：自己吃透思想。** 成功标准：做完之后，能用今天代码里的事实，讲清「现代本体比知识图谱多了什么、为什么」——即文章的五官隐喻：嘴（数据入口/事件）、鼻子（感知）、眼睛（权限/视野）、脑子（计算/派生）、手（行动）、脚（运行）。

**领域从电商换成足球（俱乐部运营）**。理由：球员是天然活对象——有体能/身价等派生状态，会感知比赛与伤病事件，受转会窗这类时间权限约束，叙事不需解释就能懂。

## 演进路线（三期递进，对应文章五官）

| 期 | 主题 | 器官 | 内容 |
|---|---|---|---|
| 第一期（本设计详述） | 让世界活起来 | 嘴+鼻+脑+基础治理 | 对象运行时、事件流入、状态派生、传导、最小动作治理 |
| 第二期 | 深挖动作治理（Palantir 写路径） | 眼+手 | 转会市场：转会窗时间权限、审批流（队医/董事会）、参数校验、审计日志、执行前影响推演 |
| 第三期 | Agent 闭环 | 脚+新居民 | 自然语言 → 本体定位对象 → 查状态 → 选治理动作 → 改世界 |

每期独立可学习、可验证。本设计只详述第一期，后两期在各期开始前按本设计的评审流程重新设计。

## 第一期设计

### 1. 领域本体（ontology/schema.ttl、data.ttl 全部重写）

**类**：
- `ex:Player`，`ex:YouthPlayer rdfs:subClassOf ex:Player`
- `ex:Position` 子类树：`Goalkeeper / Defender / Midfielder / Forward`（继承原品类树的教学作用）
- `ex:Club`、`ex:Contract`、`ex:Match`、`ex:TrainingSession`、`ex:InjuryRecord`

**声明关系**：`playsFor`、`hasContract`、`hasPosition`（声明最细位置）、`participatesIn`、`injuredWith`、`promotedFrom`（青年队→一线队）。

**声明数据规模**（对齐原 12 商品/10 客户/18 订单的量级）：约 22 名球员（16 一线队 + 6 青年队）、1 俱乐部、22 合同、若干已结束比赛与训练课、初始 1-2 条伤病记录。

**语义传递教学点保留**：球员声明最细位置，「能踢中场」（含所有中场子位置）由 `subClassOf` 推理补全；伤停传导沿位置关系自动覆盖子位置球员。

### 2. 对象运行时（新增 engine/world.py、engine/objects.py、engine/events.py）

核心抽象——每个本体对象是一个会自己说话的运行时实体：

```python
class BaseObject:
    iri: str
    def perceive(self, event): ...    # 嘴+鼻：事件入收件箱
    def compute(self, kb): ...        # 脑：从图谱算自己的派生状态
    def describe(self) -> dict: ...   # 回答「我是谁/现在怎么样/为什么/能做什么」

class World:
    def dispatch(self, event) -> DispatchReport  # 感知→compute→传导→规则→建议
    def describe(self, object_id) -> dict
```

**与 KnowledgeBase 的关系**：对象运行时是壳，事实仍以三元组写入现有五层模型（declared/retractions/effects/material/rule_out）。OWL-RL 推理、VIP 式规则层、动作执行器全部复用。`compute()` 的输入是 material 图，产出的派生状态（体能、可用性、阵容强度）作为带解释的视图返回，不与推理闭包混层。

**事件类型**（第一期）：
- `MatchPlayedEvent(player, minutes)` — 体能随出场消耗
- `TrainingLoadEvent(player, load)` — 训练负荷
- `InjuryEvent(player, weeks_out)` — 写入伤停状态
- `RecoveryEvent(player)` — 解除伤停

**派生状态（compute 产出）**：
- 球员：`fitness`（0-100，出场/训练消耗、时间恢复）、`availability`（可出场/伤停 N 周）、`overuseRisk`（体能低 + 连续首发）
- 阵容：`squadStrength`（可出场主力汇总）、`positionGap`（某位置无人可用）

**传导链**（对应原「风险传导」场景）：`InjuryEvent → 中场无人可用 → positionGap → squadStrength 下降 → 触发动作建议`。每一步标注依赖的公理/规则（沿用现有逐步解释机制）。

**动作与最小治理**（动作执行器模式复用，效果即事实）：
- `RestPlayer`（轮休，恢复体能）
- `CallUpYouth(player)` — **前置条件**：一线队报名 < 25 人；违反则拒绝执行
- `StartTreatment(player)` — **审批门**：第一期模拟为需「确认」两步执行
- 每次执行写入审计日志（who/when/action/why），新增 `GET /api/audit` 可查

**执行前预览**：`POST /api/preview-action` 返回将新增/撤销的三元组（effects 预演，不落库），对应「行动之前先推演」。

### 3. 前端（web/ 内容全部换，五 Tab 结构保留）

| Tab | 内容 |
|---|---|
| 世界总览 | 足球知识图谱（Cytoscape），声明实线/推断虚线，点球员看状态摘要 |
| 事件流 | 注入事件的按钮面板（比赛结束/训练/受伤/恢复），展示事件→感知→状态变化的实时反馈 |
| 球员对象 | 对象卡：`describe()` 四问（是谁/现在状态/为什么/能做什么）——对象运行时的灵魂展示 |
| 决策中心 | 建议清单（带传导解释）→ 预览影响 → 执行（含治理拦截演示）→ 审计日志 |
| 学习路径 | 四章教程入口 + 每章对应的世界操作 |

### 4. 教程（learn/ 四章重写，足球版）

1. **本体是什么** — 足球图谱与三元组；从「张三的爸爸是谁」式表查询到对象直连关系
2. **建模俱乐部世界** — **能力问题驱动**（文章第七层）：先问「谁受伤会影响下场比赛？哪些球员过度使用？」，再反推需要哪些类/关系/状态，然后动手改 schema
3. **推理如何发生** — 位置子类树、声明 vs 推断、伤停语义传导
4. **从状态到行动** — 五官映射：事件→感知→派生→规则→建议→治理→写回；对象运行时代码导读

每章配套 `scripts/explore.py` 步骤重写（`--step 1`..`--step 5` 对应新世界）。

### 5. API 变更

保留：图谱/推理/决策相关端点形态。新增：`POST /api/events`（事件注入）、`GET /api/object/{id}/describe`、`POST /api/preview-action`、`GET /api/audit`。移除：电商场景专属端点（风险传导/客户分类/语义推荐以足球等价物替代）。

### 6. 测试策略

沿用 pytest。核心新增用例：事件 dispatch 后状态正确变化；传导链逐步解释完整；治理前置条件拒绝（25 人上限）；审批两步流；预览与实际执行的三元组一致；审计日志完整。目标覆盖现有 36 个测试的等价物 + 运行时新增约 10-15 个。

### 7. 迁移与工程量

- 动手前给当前 main 打 tag（`e-commerce-v1`），电商版本永久留在历史里
- 引擎保留 loader/knowledge_base/actions 的分层模式，新增三个模块；场景层重写
- 预估：引擎+本体约 2-3 个工作时段，前端 1-2，教程 1-2；合计约一周业余投入

## 明确不做（第一期）

- 转会窗时间权限、多级审批、影响推演沙盘（第二期）
- 自然语言入口、LLM 集成（第三期）
- 持久化存储、多用户、真实规模数据（延续现有已知限制）
