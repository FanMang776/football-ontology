# 电商本体论 Demo —— 详细设计

日期：2026-09-26
状态：待确认

## 1. 目标与定位

一个可交互、可运行、可修改的学习项目，回答一个问题：**本体论如何让机器"理解"业务，并促进业务决策。**

- **学习者画像**：熟练开发者，有 Python/JS 基础，第一次系统接触本体论。
- **学习重点**：业务落地——本体驱动的查询、推理、决策支持，而非学术理论。
- **成功标准**：
  1. 打开网页，能直观看到知识图谱、推理过程和决策结论；
  2. 读代码，能看懂本体如何建模（TBox）、业务事实如何表达（ABox）、推理如何发生；
  3. 修改一个事实（如供应商延迟），能看到结论自动传导，理解本体 vs 传统数据库的本质差别；
  4. 技术栈可迁移：Turtle、RDFLib、SPARQL、OWL-RL 是生产级知识图谱项目的真实配置。

## 2. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 本体定义 | Turtle (.ttl)，W3C 标准 | 行业通用格式，可迁移到任何 RDF 工具链 |
| 三元组存储 + 查询 | RDFLib | Python 生态标准库，内置 SPARQL |
| 推理机 | owlrl（OWL-RL 推理） | 真实推理：子类传递、属性传递、对称性、逆属性 |
| 业务规则 | SPARQL CONSTRUCT | OWL 表达不了的算术规则（如 VIP 判定）放规则层，教学中明确区分两种推理 |
| API | FastAPI + uvicorn | 熟悉、轻量 |
| 前端 | 原生 HTML/JS + Cytoscape.js（CDN 引入） | 零构建工具链，图谱可视化效果好 |
| 测试 | pytest | 验证推理结果与场景查询 |

无数据库、无 Docker、无 npm——所有复杂度留给本体本身。

## 3. 项目结构

```
ontology/
├── ontology/
│   ├── schema.ttl          # TBox：类层级、属性、公理（本体的"语法书"）
│   └── data.ttl            # ABox：业务实例（本体的"事实库"）
├── engine/
│   ├── loader.py           # 加载 ttl，运行 OWL-RL 推理，返回显式/推断三元组
│   ├── rules.py            # SPARQL CONSTRUCT 规则（VIP 分类规则 + 动作规则）
│   ├── queries.py          # 场景 SPARQL 查询
│   ├── scenarios.py        # 三个决策场景的编排逻辑 + 解释生成
│   └── actions.py          # 动作执行器：前提校验、效果写回、图谱 diff
├── api/
│   └── main.py             # FastAPI 接口
├── web/
│   ├── index.html          # 单页应用
│   ├── app.js              # 图谱渲染、场景交互
│   └── style.css
├── scripts/
│   └── explore.py          # 命令行逐步学习工具（配套 learn/ 教程）
├── learn/
│   ├── 01-本体是什么.md
│   ├── 02-用本体建模电商业务.md
│   ├── 03-推理如何发生.md
│   └── 04-从查询到决策.md
├── tests/
│   ├── test_reasoning.py
│   ├── test_scenarios.py
│   ├── test_rules.py
│   └── test_actions.py
├── requirements.txt
└── README.md
```

## 4. 本体设计

### 4.1 类层级（TBox 核心）

```
:BusinessObject
├── :Product
│   ├── :PhysicalProduct
│   ├── :DigitalProduct
│   └── :Bundle                    # 捆绑套装，由 hasPart 组合
├── :Category                      # 多层品类树
│   （实例示例：蓝牙耳机 ⊑ 耳机 ⊑ 数码配件 ⊑ 电子产品）
├── :Party
│   ├── :Supplier
│   └── :Customer                  # VIPCustomer 不显式建模——由规则推断
├── :Order
│   └── :OrderLine
├── :Promotion
└── :Action                          # 决策动作——本体不仅描述业务，也描述"可做的事"
    ├── :PausePromotion              # 暂停促销（对象：Promotion）
    ├── :NotifyCustomer              # 通知客户（对象：Customer）
    ├── :CreatePurchaseOrder         # 生成采购单（对象：Product × Supplier）
    ├── :PromoteSubstitute           # 推荐替代品（对象：Product → Product）
    └── :GrantVoucher                # 发放补偿券（对象：Customer）
```

教学要点：**品类树用 subClassOf 建模而非属性**——这样"蓝牙耳机是电子产品"不需要存储，是推理出来的，这是本体思维的第一个转折点。

### 4.2 属性与公理

| 属性 | 类型 | 公理 | 推理能力 |
|---|---|---|---|
| `belongsToCategory` | ObjectProperty | — | 配合 subClassOf 实现"商品属于祖先品类" |
| `suppliedBy` | ObjectProperty | — | 供应链追溯 |
| `hasPart` | ObjectProperty | **Transitive**、`isComponentOf` 的逆 | 套装→组件→子组件 链式传导 |
| `substituteFor` | ObjectProperty | **Symmetric** | 声明 A 替代 B，自动得知 B 替代 A |
| `compatibleWith` | ObjectProperty | Symmetric | 配件推荐 |
| `sameSeries` | ObjectProperty | Symmetric | 系列推荐 |
| `placedOrder` / `hasLine` / `lineProduct` | ObjectProperty | 链式结构 | 客户→订单→明细→商品的图路径 |
| `promotes` | ObjectProperty | 活动→商品 | 营销影响范围 |
| `hasTarget` / `hasReason` / `hasPrerequisite` / `actionStatus` | Action 相关 | 动作→业务对象/推理链/前置条件/状态 | 决策动作的自描述 |
| price / stock / annualSpend / membershipLevel / leadTime | DatatypeProperty | — | 规则层数据 |

### 4.3 推理与决策规则层（教学核心设计）

**第一层：OWL-RL 公理推理**（owlrl 自动完成，透明且标准）
- 子类传递：蓝牙耳机 → 电子产品
- 传递属性：套装 hasPart 耳机，耳机 hasPart 单元 → 套装 hasPart 单元
- 对称属性：声明 A substituteFor B → 推断 B substituteFor A

**第二层：业务规则层**（SPARQL CONSTRUCT，显式可读），分两类：

**分类规则**（事实 → 类别推断）：
```sparql
# VIP 规则：年消费 > 5000，或（银卡 且 订单数 ≥ 3）
CONSTRUCT { ?c a :VIPCustomer }
WHERE { ?c a :Customer ; :annualSpend ?s . FILTER(?s > 5000) }
```

**动作规则**（情况 → 建议动作）：
```sparql
# 活动正在推广的套装缺货 → 建议暂停该活动
CONSTRUCT {
  ?act a :PausePromotion ; :hasTarget ?promo ; :hasReason ?why .
}
WHERE {
  ?bundle a :Bundle ; :stock 0 .
  ?promo a :Promotion ; :promotes ?bundle ; :status "active" .
  BIND(:UUID()) AS ?act
  # ?why 通过属性路径绑定到传导原因，供界面解释
}
```

再加三条动作规则覆盖三个场景：
- **延迟供应商 → 生成采购单**：目标供应商沿 `substituteFor` 反查替代品供应商得到（决策本身是一次图谱查询）；
- **风险传导到 VIP 客户的未发货订单 → NotifyCustomer**；
- **缺货商品 → PromoteSubstitute**（推荐位切到替代品）。

教学要点写进 `learn/03`：OWL 负责**分类学与结构逻辑**，含算术/聚合的业务规则放**规则层**——本体提供语义，规则把"情况"映射为"分类"和"动作"，这是生产系统的标准分工，也让学习者理解推理不是魔法。

### 4.4 数据规模（ABox）

刻意保持小而可读：8 个供应商、约 30 个商品（含 3 个套装）、约 12 个品类节点、20 个客户、约 50 个订单、5 个促销活动。所有数据手工可核对，教程可以指着具体三元组讲。

## 5. 三个决策场景

每个场景都围绕同一条主线：**修改/触发一个事实 → 推理自动传导 → 决策结论带解释输出 → 系统给出建议动作 → 执行后效果写回图谱**。

### 场景 1：供应风险传导（关系传递推理）

操作：网页上把供应商「声科电子」标记为延迟。
传导链（每一步都标注依据它的公理）：

```
供应商延迟 (事实)
  → suppliedBy 反查：受影响商品 (SPARQL)
  → isComponentOf 传递：受影响套装 (OWL 传递性)
  → belongsToCategory 推断 + promotes 反查：受影响促销活动
  → placedOrder/hasLine/lineProduct 路径：受影响未发货订单
  → 影响的 VIP 客户（结合场景 2 的推断结果）
```

输出：影响范围清单 + **传导路径可视化**（图谱上高亮传播波纹，区分"声明的边"和"推理出的边"）+ 每个结论的自然语言解释（"套装 A 受影响，因为它 hasPart 蓝牙耳机 X，而 X 由延迟供应商供应"）。

这是 SQL 视角最难复制的场景：关系深度不定（套装嵌套装）、路径依据语义（传递性、逆属性）——用本体是自然表达，用 SQL 是递归 CTE 加一堆特判。

### 场景 2：高价值客户分类（分类推理 + 规则层）

操作：调整 VIP 阈值（滑块），规则重跑。
展示：
- 哪些客户被**新推断**为 VIPCustomer（及原因链：张三年消费 6200 > 5000）；
- 结合场景 1：风险传导到 VIP 客户时自动使用推断结果；
- 对比：传统做法是每张表冗余一个 `is_vip` 字段，阈值一变要刷全表；本体做法是结论永不落库、随事实即时重算。

### 场景 3：语义推荐（语义查询 vs 统计查询）

操作：选一个商品，并排展示两种推荐结果：
- **朴素版**：同品类热门（模拟传统推荐）；
- **语义版**：沿 substituteFor（缺货时推荐替代品）、compatibleWith（买耳机推耳放）、sameSeries（系列复购）推荐，每条推荐附**语义依据**（"因为它与 X 互为替代品"）。

教学要点：推荐可解释，因为每条边都有含义——这是本体驱动机器学习/推荐系统常讲的"可解释性"红利。

### 决策执行闭环（贯穿所有场景）

前三个场景止步于"洞察"，本节补上"执行"——完整闭环：

```
事实变化 → 推理（OWL 公理 + 分类规则）→ 洞察结论
        → 动作规则 → 建议动作（Action 实例，带 hasReason 原因链）
        → 执行校验（SPARQL ASK 检查 hasPrerequisite，如"客户未被通知过"）
        → 模拟执行：动作效果作为新事实写回图谱（活动 status=paused、订单 status=notified）
        → 重新推理 → 图谱 diff：风险清单上的条目被消解 → 可能触发新的推理与动作
```

- **执行器**是 engine 里一个独立的模拟模块：接收动作实例 → 校验前提 → 生成回写事实。教学中明确：生产环境这一步调用业务系统 API（CRM/ERP/营销平台），demo 用内存执行器模拟，**接口形态一致**，替换成 HTTP 调用即是真实系统。
- **教学价值**：决策依据可追溯（每个动作挂推理链）、执行前提可验证（图谱查询即校验）、执行效果可推演（新事实回到图谱再推理）——这三点是"本体驱动决策闭环"区别于硬编码工作流的本质。

### 本体浏览器（贯穿性功能）

- 左侧：类层级树（TBox）；点击类，右侧显示实例及其关系图；
- 每个节点面板列出三元组，用图标区分 **声明（declared）** 与 **推断（inferred）**——对比推理前后图谱，让"机器理解业务"变得可见。

## 6. API 设计

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/graph` | GET | 图谱快照（nodes/edges，含 declared/inferred 标记），支持 `?class=` 过滤 |
| `/api/entity/{id}` | GET | 单实体：声明三元组 + 推断三元组 + 解释 |
| `/api/scenario/supplier-risk` | POST | `{supplier_id, delayed}` → 传导链结果 |
| `/api/scenario/vip` | POST | `{spend_threshold, order_threshold}` → 新分类客户及原因 |
| `/api/scenario/recommend/{product_id}` | GET | 朴素 vs 语义推荐对比 |
| `/api/actions` | GET | 当前建议动作清单（含原因链、前置条件） |
| `/api/action/{id}/execute` | POST | 执行校验 → 写回效果事实 → 返回图谱 diff 与消解清单 |
| `/api/taxonomy` | GET | 类层级（浏览器用） |

推理在每次 POST 后全量重算（数据量小，<100ms），保证"改事实→看结论"的心智模型简单。

## 7. 前端设计

单页应用，五个 Tab：

1. **图谱总览**：Cytoscape.js 力导向图，节点按类着色，可点选实体看声明/推断面板；
2. **风险传导**：供应商列表 + 延迟开关，触发后图谱高亮传导路径（按 hop 顺序动画），侧栏列受影响清单和解释；
3. **客户分类**：阈值滑块 + 实时显示新推断 VIP 及原因，图谱上 VIP 节点高亮；
4. **语义推荐**：商品选择器 + 两种推荐并排对比 + 语义依据；
5. **决策中心**：所有建议动作的清单（动作类型、目标、原因链、前置条件），单条"执行"或全部执行；执行后图谱高亮 diff（新增事实为绿色虚线边），受影响清单条目逐项消解。

教学文案直接嵌在界面里（侧栏"为什么"按钮展开该结论的推理依据），代码与界面通过 learn/ 教程对照。

## 8. 学习教程（learn/）

| 章节 | 内容 | 配套动手 |
|---|---|---|
| 01-本体是什么 | 本体 vs 数据库 vs 面向对象：三种世界观；三元组、TBox/ABox | `python scripts/explore.py --step 1` 查看原始三元组 |
| 02-用本体建模电商业务 | 为什么品类是类不是属性；传递/对称属性的威力；schema.ttl 逐段精读 | 修改 schema.ttl 加一个类，重启看变化 |
| 03-推理如何发生 | OWL-RL 物化原理；声明 vs 推断对比；为什么 VIP 规则不放 OWL 层 | `--step 3` 打印推理前后三元组 diff |
| 04-从查询到决策 | 三个场景的 SPARQL 逐行精读；动作规则（情况→动作）；执行闭环：校验、写回、再推理 | `--step 4` 交互式跑三个场景查询；`--step 5` 触发一条动作并观察图谱回写前后 diff |

`scripts/explore.py` 是教程的实验台：分步加载、打印三元组、跑推理、执行查询，全部带中文注释输出。

## 9. 测试策略

- `test_reasoning.py`：owlrl 物化后断言预期推断三元组存在（子类、传递、对称各一组）；
- `test_rules.py`：VIP 规则在边界数据（5000 整、银卡 2 单 vs 3 单）上的正确性；
- `test_scenarios.py`：给定声科电子延迟，断言受影响商品/套装/活动/客户集合精确匹配手工核对结果；
- `test_actions.py`：动作规则触发条件正确（如只有 active 活动生成暂停建议）；执行器前置校验（重复通知被拦截）；执行后断言风险清单消解、图谱 diff 符合预期。

## 10. 错误处理

- TTL 语法错误：loader 捕获并给出文件名+行号；
- API 未知实体/供应商 ID：404 + 最相近 ID 提示；
- 前端后端不可达：页面显示连接指引（`uvicorn api.main:app`）。

## 11. 实施阶段（供后续实现计划展开）

1. **骨架 + 本体**：schema.ttl（含 Action 类层级）、data.ttl、loader（含测试）；
2. **引擎**：分类规则、动作规则、queries、scenarios、执行器（含测试）——纯 Python 可独立验证；
3. **API**：FastAPI 端点（含动作执行）+ 手工 smoke；
4. **前端**：五 Tab 单页 + 图谱交互 + 决策中心；
5. **教程**：learn/ 四章 + explore.py。

每阶段结束可运行、可演示，依赖顺序严格单向。
