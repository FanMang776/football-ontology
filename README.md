# 电商本体学习 Demo

用一个小型电商知识图谱演示本体（RDF/OWL + SPARQL）如何回答关系数据库难以自然回答的三类问题：

1. **语义传递**——促销推广的是"数码配件"品类，BT-01 从未被写进任何促销覆盖表，但"618 大促覆盖 BT-01"这条结论由品类推理自动成立；
2. **分类推理**——VIP 是规则推断出的类别，不落库，改阈值即时生效；
3. **语义决策**——"供应商延迟了该做什么"本身也是一次图谱查询，建议动作是推论，执行后写回事实、推论自动消失。

适合谁：有 SQL/ORM 经验、想直观理解"本体/知识图谱到底解决了什么"的开发者。不需要任何 RDF 基础，`learn/` 四章教程从零讲起，每章配一段可运行的 `scripts/explore.py`。

## 安装与运行

```bash
pip install -r requirements.txt

# 跑通 36 个测试
python -m pytest -q

# 启动 Web 界面
python -m uvicorn api.main:app --reload
# 打开 http://127.0.0.1:8000
```

浏览器需要联网加载 Cytoscape.js CDN（图谱可视化用），离线时其余 Tab 正常、图谱画布空白。

命令行学习路径（不需要启动服务）：

```bash
python scripts/explore.py --step 1   # 看原始三元组
python scripts/explore.py --step 2   # 看类层级树
python scripts/explore.py --step 3   # 跑 OWL-RL 推理，看声明 vs 推断 diff
python scripts/explore.py --step 4   # 跑三个决策场景
python scripts/explore.py --step 5   # 执行一条建议动作，看图谱写回
```

## 学习路径

| 教程 | 配套命令 | Web 界面 |
|---|---|---|
| [01 本体是什么](learn/01-本体是什么.md) | `--step 1` | 图谱总览 |
| [02 用本体建模电商业务](learn/02-用本体建模电商业务.md) | `--step 2` | 图谱总览（类树） |
| [03 推理如何发生](learn/03-推理如何发生.md) | `--step 3` | 图谱总览（实线/虚线边） |
| [04 从查询到决策](learn/04-从查询到决策.md) | `--step 4`、`--step 5` | 风险传导 / 客户分类 / 语义推荐 / 决策中心 |

## 项目结构

```
ontology/
├── ontology/
│   ├── schema.ttl        # TBox：类层级、属性公理、动作类
│   └── data.ttl          # ABox：商品/套装/客户/订单/促销的声明事实
├── engine/
│   ├── namespaces.py     # EX 命名空间
│   ├── loader.py         # 加载 TTL + OWL-RL 物化推理
│   ├── queries.py        # 场景 SPARQL 查询（含朴素推荐的 subClassOf 守卫）
│   ├── rules.py          # VIP 分类规则 + 动作规则（情况→建议）
│   ├── scenarios.py      # 场景编排：查询→结构化结果→逐步解释
│   ├── knowledge_base.py # 五层模型：declared/retractions/effects/material/rule_out
│   └── actions.py        # 动作执行器：效果即事实，写回后重推
├── api/main.py           # FastAPI 接口 + 静态前端托管
├── web/                  # 五 Tab 前端（原生 JS + Cytoscape.js）
├── scripts/explore.py    # 五步命令行学习实验台
├── learn/                # 四章教程（本项目的主文档）
└── tests/                # 36 个测试
```

## Web 界面五个 Tab

| Tab | 一句话 |
|---|---|
| 图谱总览 | 全量知识图谱，声明边实线、推断边虚线；点实体看 declared/inferred 两栏 |
| 风险传导 | 把供应商标记为延迟，五步传导（商品→套装→促销→订单→VIP），每步标注依赖的公理/规则 |
| 客户分类 | 拖动消费额/订单数阈值，VIP 清单实时重算并给出每人的判定理由 |
| 语义推荐 | 任选商品，对比"同品类"朴素推荐与基于替代/兼容/同系列语义边的推荐 |
| 决策中心 | 建议动作清单（每条带解释），逐条或全部执行，已处置的建议自动消失 |

## 关键教学点

- **品类即类**：品类树是 `subClassOf` 树，商品声明最细品类，祖先成员关系由推理补全；
- **声明 vs 推断**：390 条声明事实，OWL-RL 物化后 1169 条——多出的 779 条全部是公理的推论；
- **VIP 不落库**：算术/聚合规则放 OWL 之外的规则层，产出类型三元组并入同一张图，阈值是参数；
- **建议动作是推论**：动作规则每次刷新全量重算，效果写回（含撤销）后已处置建议自动消失；
- **效果即事实**：执行动作 = 写回三元组 + 重新推理，"动作是否生效"问图就知道；
- **撤销也是写回**：暂停促销必须撤销声明的 active 而非只叠加 paused，撤销建模为独立的 retractions 层。

这些点的展开讲解都在 `learn/` 四章里，代码引用均来自本仓库源码。

## 已知限制

- 全部内存态，重启即恢复初始数据（`POST /api/reset` 同样只重置内存）；
- 单用户 demo，KnowledgeBase 全局单例 + 一把锁串行化；
- 图谱可视化依赖 Cytoscape CDN，离线不可用；
- 教学数据（12 商品、10 客户、18 订单）非真实规模，全量重算的推理管线不可直接外推到生产数据量。
