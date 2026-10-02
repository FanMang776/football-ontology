# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## 项目概览

电商本体学习 Demo：用小型知识图谱（RDF/OWL + SPARQL）演示本体推理如何回答关系数据库难以自然回答的三类问题——语义传递、分类推理、语义决策。**这是教学项目**，代码结构的每一处设计（分层、守卫、全量重算）都服务于可讲解性，改动时优先保持教学清晰度而非生产级优化。

`learn/` 四章教程是本项目的主文档，代码引用均来自本仓库源码；改引擎行为时需同步检查对应章节的表述是否仍然成立。

## 常用命令

```bash
pip install -r requirements.txt          # 安装依赖（rdflib/owlrl/fastapi/uvicorn/pytest/httpx）

python -m pytest -q                      # 跑全部 36 个测试
python -m pytest tests/test_reasoning.py -q            # 跑单个文件
python -m pytest tests/test_rules.py::test_name -q     # 跑单个测试

python -m uvicorn api.main:app --reload  # 启动 Web（http://127.0.0.1:8000）

python scripts/explore.py --step N       # 五步命令行学习实验台（1=原始三元组 … 5=执行建议动作）
```

无 lint/format 配置。前端为原生 JS（web/），浏览器需联网加载 Cytoscape.js CDN。

## 架构

### 数据：本体文件（ontology/）

- `schema.ttl` — TBox：类层级（`subClassOf` 树，根为 `EX.BusinessObject`）、属性公理、动作类
- `data.ttl` — ABox：商品/套装/客户/订单/促销的声明事实（约 390 条）

命名空间统一走 `engine/namespaces.py` 的 `EX`，不要在别处硬编码 URI 字符串。

### 引擎：五层知识模型（engine/knowledge_base.py）

理解本项目的关键是五层分层（模块 docstring 有权威描述）：

1. `declared` — schema.ttl + data.ttl，不可变
2. `retractions` — 运行时撤销的声明事实（撤销也是写回，不是叠加 paused 之类的新状态）
3. `effects` — 运行时新增的事实（供应商延迟、通知标记等）
4. `material` — (declared − retractions + effects) 过 OWL-RL 闭包的物化图
5. `rule_out` — VIP 分类规则 + 动作规则的产出，每次刷新全量重算，是推论不是数据

核心不变量：**声明 vs 推断**。推断三元组永不落库、随事实即时重算；"建议动作是推论"由此成立——执行动作 = 写回 effects 三元组 + refresh，已处置的建议自动消失。

### 关键模块

- `engine/loader.py` — `load_declared()`（TBox+ABox）+ `materialize()`（OWL-RL 闭包，`axiomatic_triples=False` 关掉无关公理，否则推断层混入上千条非业务三元组）
- `engine/rules.py` — VIP 分类（算术/聚合规则放 OWL 之外的规则层，阈值是参数）+ 动作规则（情况→建议）
- `engine/queries.py` — 场景 SPARQL 查询，含朴素推荐的 `subClassOf` 守卫
- `engine/scenarios.py` — 场景编排：查询 → 结构化结果 → 逐步解释
- `engine/actions.py` — 动作执行器：效果即事实，写回后重推
- `api/main.py` — FastAPI 接口 + 静态前端托管；`kb = KnowledgeBase()` 全局单例

### 并发与内存模型

- 全部内存态，重启即恢复初始数据；`POST /api/reset` 只重置内存
- FastAPI 把同步端点放进线程池并发调用，而 rdflib 图不支持并发读写：**所有可变入口必须经 `KnowledgeBase._lock`（RLock）串行化**，新增修改状态的端点/方法时必须带锁
- 全量重算管线是刻意为之的教学设计，不要为性能引入增量推理

### 前端（web/）

五 Tab 原生 JS（无构建步骤）：图谱总览（Cytoscape.js，声明边实线/推断边虚线）、风险传导、客户分类、语义推荐、决策中心。`api/main.py` 的 `/api/graph` 端点决定哪些谓词入图（`shown` 集合），改图谱展示需同步改这里。

## 测试

`tests/` 按引擎模块分文件（actions/api/reasoning/rules/scenarios），API 测试经 httpx 直接调 FastAPI app，不起真实端口。
