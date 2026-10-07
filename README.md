# 足球本体世界学习 Demo

用一个小型足球俱乐部知识图谱演示"现代本体"如何超越知识图谱：对象不只**是**什么，还会**感知**世界、**计算**自己的状态、在治理边界内**行动**。

> License: MIT（见 [LICENSE](LICENSE)）

四类能力各有一个可直接操作的场景：

1. **语义推理**——位置以类型成员声明（`p_am1 a ex:AttackingMidfielder`），"德布劳内是场上位置的一员"由 `subClassOf` 闭包自动成立；
2. **状态派生**——体能是算出来的不是存的：出场/训练消耗、轮休恢复，公式固定在 `engine/objects.py`；
3. **事件感知**——比赛、训练、伤病、痊愈四类事件从「嘴」注入，对象感知（perceive）→ 全量重算（compute）→ 规则建议刷新，每一步带中文传导链；
4. **治理动作**——建议动作带边界：征调受报名上限（前置条件）、治疗需队医确认（两步审批）、全程审计，执行前可预览影响。

第五个场景是**智能体**：LLM 通过六个本体操作工具进入这个世界——查状态、问建议、推演动作、执行动作、注入事件。执行走与人类完全相同的治理门；工具调用以卡片实时可见。默认 mock 演示模式（无需任何 key），配上国产模型 key 即接真实模型。

适合谁：有 SQL/ORM 经验、想直观理解"现代本体/Palantir 式写路径到底比知识图谱多了什么"的开发者。不需要任何 RDF 基础，`learn/` 五章教程从零讲起，每章配一段可运行的 `scripts/explore.py`。

## 安装与运行

```bash
pip install -r requirements.txt

# 跑通全部测试
python -m pytest -q

# 启动 Web 界面
python -m uvicorn api.main:app --reload
# 打开 http://127.0.0.1:8000
```

浏览器需要联网加载 Cytoscape.js 核心（CDN）；力导布局脚本（fcose 及其依赖）已本地化在 `web/vendor/`，离线时图谱仍可渲染、自动回退无扩展模式。

命令行学习路径（不需要启动服务）：

```bash
python scripts/explore.py --step 1   # 看原始三元组
python scripts/explore.py --step 2   # 看类层级树（位置树）
python scripts/explore.py --step 3   # 跑 OWL-RL 推理，看声明 vs 推断 diff
python scripts/explore.py --step 4   # 注入事件，看感知→状态→建议传导链
python scripts/explore.py --step 5   # 治理动作：预览→审批两步流→审计
```

## 学习路径

| 教程 | 配套命令 | Web 界面 |
|---|---|---|
| [01 本体是什么](learn/01-本体是什么.md) | `--step 1` | 世界总览 |
| [02 用能力问题建模俱乐部世界](learn/02-用能力问题建模俱乐部世界.md) | `--step 2` | 世界总览（类树） |
| [03 推理如何发生](learn/03-推理如何发生.md) | `--step 3` | 世界总览（实线/虚线边） |
| [04 从状态到行动](learn/04-从状态到行动.md) | `--step 4`、`--step 5` | 事件流 / 球员对象 / 决策中心 |
| [05 智能体面对本体世界](learn/05-智能体面对本体世界.md) | 智能体 Tab | 智能体 |

## 和智能体对话（第五个场景）

「智能体」Tab 里用自然语言查世界、问建议、执行动作。**默认为 mock 演示模式**（脚本化假模型，无需任何 key）；接真实模型只需一步：

```bash
cp config.example.ini config.ini    # 填入 base_url / api_key / model
python -m uvicorn api.main:app --reload
```

- 配置优先级：环境变量（`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`）> `config.ini` > 默认 mock
- `config.ini` 已 gitignore，key 不入库；任何 OpenAI 兼容的国产模型（GLM/DeepSeek/Qwen/Kimi）均可
- 能聊什么：查状态（「哪些球员体能最低？」）、问建议、预览影响（「执行轮休会改哪些三元组？」）、执行动作（「治好 B费」→ 治疗类会停下等你确认）、注入事件（「让亚马尔受伤停 4 周」）
- 治理门对 Agent 一视同仁：veto、两步审批、审计与人类操作同路径——这是本 Tab 的核心教学点

## 项目结构

```
ontology/
├── ontology/
│   ├── schema.ttl        # TBox：位置子类树、属性公理、动作类
│   └── data.ttl          # ABox：20 名球员/合同/比赛/训练/伤病的声明事实
├── engine/
│   ├── namespaces.py     # EX 命名空间（football#）
│   ├── loader.py         # 加载 TTL + OWL-RL 物化推理
│   ├── events.py         # 四类事件（纯数据，frozen dataclass）+ 统一构造入口
│   ├── objects.py        # 对象运行时：perceive/compute/describe（五官里的脑）
│   ├── world.py          # World.dispatch：感知→结算→重算→传导报告（脚）
│   ├── rules.py          # 动作建议规则：轮休/征调/治疗（情况→建议）
│   ├── rule_meta.py      # 规则手册：全部规则的声明式展示元数据
│   ├── knowledge_base.py # 六层模型：declared/retractions/effects/state/material/rule_out
│   ├── actions.py        # 动作治理：前置条件/审批/审计/预览（手+眼睛）
│   └── agent.py          # LLM Agent：六个本体操作工具 + 工具调用循环（手：会说话的入口）
├── api/main.py           # FastAPI 接口 + SSE 对话端点 + 静态前端托管
├── web/                  # 六 Tab 前端（原生 JS + Cytoscape.js）
├── scripts/explore.py    # 五步命令行学习实验台
├── learn/                # 五章教程（本项目的主文档）
├── config.example.ini    # 智能体模型配置模板（复制为 config.ini，已 gitignore）
└── tests/                # 78 个测试
```

## Web 界面六个 Tab

| Tab | 一句话 |
|---|---|
| 世界总览 | 全量知识图谱，声明边实线、推断边虚线；点对象看 declared/inferred 两栏 |
| 事件流 | 注入比赛/训练/受伤/痊愈事件，看传导链（感知→状态变化→建议刷新） |
| 球员对象 | 对象卡：describe() 四问——是谁/现在状态/为什么/能做什么 |
| 决策中心 | 建议清单 → 预览影响 → 执行（审批动作两步走）→ 审计日志；体能阈值滑杆实时改规则 |
| 学习路径 | 教程卡片 + 规则手册（全部规则与触发条件） |
| 智能体 | 和本体世界对话：自然语言查/问/推演/执行，工具调用卡片实时可见 |

## 关键教学点

- **位置即类**：位置是 `subClassOf` 树，球员声明最细位置，祖先成员关系由推理补全；
- **声明 vs 推断**：312 条声明事实，OWL-RL 物化后 887 条——多出的 575 条全部是公理的推论；
- **建议动作是推论**：动作规则每次刷新全量重算，治理否决写 `vetoed` 三元组后，该建议不再出现；
- **状态不落库**：`fitness` 在 state 层，每次事件全量重算——它是"算出来的"不是"写进去的"；
- **效果即事实**：执行动作 = 写回三元组 + 重算 + 重新推理，"动作是否生效"问图就知道；
- **治理三要素**：前置条件（报名 < 16 否决并写 veto）、审批（治疗两步执行）、审计（事件与执行全记录）；
- **撤销也是写回**：痊愈从 effects 层移除伤病记录，声明层伤情不可移除——分层模型让"改世界"和"改描述"分得清清楚楚；
- **Agent 面对本体世界**：工具即本体操作，执行与人类同走治理门；事件是感知输入不上治理门（嘴 vs 手），世界里没有的数据 Agent 必须拒答。

这些点的展开讲解都在 `learn/` 五章里，代码引用均来自本仓库源码。

## 已知限制

- **阵容是教学虚构**：球员名来自现实球星，比赛/体能/伤停数据全部为编造；
- fitness 公式（分钟/6、负荷/10、轮休+20）是教学简化，不是任何真实运动科学模型；
- 治疗审批是模拟的两步流（同一动作执行两次），不是真实的审批工作流；
- 全部内存态，重启即恢复初始数据（`POST /api/reset` 同样只重置内存）；
- 单用户 demo，KnowledgeBase 全局单例 + 一把锁串行化；
- 图谱可视化依赖 Cytoscape CDN，离线不可用；
- 教学数据（20 球员、3 场比赛）非真实规模，全量重算的推理管线不可直接外推到生产数据量。
