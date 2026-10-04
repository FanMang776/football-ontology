# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## 项目概览

足球本体世界学习 Demo：用小型知识图谱（RDF/OWL + SPARQL）+ 对象运行时演示"现代本体"如何超越知识图谱——语义推理、状态派生、事件感知、治理动作。**这是教学项目**，代码结构的每一处设计（分层、守卫、全量重算）都服务于可讲解性，改动时优先保持教学清晰度而非生产级优化。

`learn/` 五章教程是本项目的主文档，代码引用均来自本仓库源码；改引擎行为时需同步检查对应章节的表述是否仍然成立。

## 常用命令

```bash
pip install -r requirements.txt          # 安装依赖（rdflib/owlrl/fastapi/uvicorn/pytest/httpx/openai）

python -m pytest -q                      # 跑全部 73 个测试
python -m pytest tests/test_reasoning.py -q            # 跑单个文件
python -m pytest tests/test_rules.py::test_name -q     # 跑单个测试

python -m uvicorn api.main:app --reload  # 启动 Web（http://127.0.0.1:8000）

python scripts/explore.py --step N       # 五步命令行学习实验台（1=原始三元组 … 5=治理动作）
```

无 lint/format 配置。前端为原生 JS（web/），浏览器需联网加载 Cytoscape.js CDN。

## 架构

### 数据：本体文件（ontology/）

- `schema.ttl` — TBox：类层级（`subClassOf` 树，根为 `EX.FootballEntity`；位置是类成员建模，球员 `a ex:AttackingMidfielder`，无 hasPosition 属性）、属性公理、动作类
- `data.ttl` — ABox：20 名球员（14 一线队 + 6 青年队）/合同/比赛/训练/伤病的声明事实（312 条；阵容虚构，minutesPlayed 是多值属性，注意 RDF 集合语义下重复值塌缩）

命名空间统一走 `engine/namespaces.py` 的 `EX`，不要在别处硬编码 URI 字符串。

### 引擎：六层知识模型（engine/knowledge_base.py）

理解本项目的关键是六层分层（模块 docstring 有权威描述）：

1. `declared` — schema.ttl + data.ttl，不可变
2. `retractions` — 运行时撤销的声明事实（撤销也是写回，不是叠加新状态）
3. `effects` — 运行时新增的事实（伤病/痊愈、事件分钟数、动作效果、治理 veto）
4. `state` — 对象运行时的派生状态（fitness、squadStrength），每次 dispatch 全量重写，是"算出来的"不是"写进去的"
5. `material` — (declared − retractions + effects + state) 过 OWL-RL 闭包的物化图
6. `rule_out` — 动作建议规则的产出，每次刷新全量重算，是推论不是数据

核心不变量：**声明 vs 推断 vs 派生**。推断和派生都永不落库、随事实即时重算；"建议动作是推论"由此成立——执行动作 = 写回 effects 三元组 + bootstrap 重算 + refresh，已处置的建议自动消失。

fitness 公式唯一实现点在 `engine/objects.py`（docstring 钉死），不要在别处重算或修改语义。

### 关键模块

- `engine/loader.py` — `load_declared()`（TBox+ABox）+ `materialize()`（OWL-RL 闭包，`axiomatic_triples=False` 关掉无关公理，否则推断层混入上千条非业务三元组）
- `engine/events.py` — 四类事件（frozen dataclass，纯数据）+ `build_event()`（统一构造入口，API 与 Agent 工具共用）
- `engine/objects.py` — 对象运行时：`perceive/compute/describe`（五官里的"脑"）
- `engine/world.py` — `World.dispatch`：感知 → 结算（事件写 effects）→ refresh → 全量重算（两段：先球员后俱乐部）→ 传导报告
- `engine/rules.py` — 动作建议规则（轮休/征调/治疗；情况→建议；veto 三元组存在则不再建议）
- `engine/rule_meta.py` — 规则手册：全部规则的声明式展示元数据（render 代入当前参数）；改规则时同步更新，契约测试防漂移
- `engine/actions.py` — 动作治理：前置条件（报名 <16 否决并写 veto）、审批（StartTreatment 两步执行）、审计（kb.audit + tick 计数器）、预览（不落库）
- `engine/agent.py` — LLM Agent：六个本体操作工具（TOOLS + `run_tool`）、手写工具调用循环 `run_turn`（上限 6 轮）、OpenAI 兼容客户端（`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL` 三环境变量；`LLM_MODEL` 未设或 =mock 时走 MockClient 演示模式）。**治理门对 Agent 一视同仁**：execute_action 复用 kb.execute；事件是感知输入故意不上治理门（嘴 vs 手）。工具永不抛异常，失败返回 ok=False
- `api/main.py` — FastAPI 接口 + 静态前端托管；`kb = KnowledgeBase()` 全局单例；审批中间态返回 200 + pending=true（不是 409）；`POST /api/agent/chat` 是 SSE 薄壳（后端无会话状态，历史由前端持有回传）

### 并发与内存模型

- 全部内存态，重启即恢复初始数据；`POST /api/reset` 只重置内存
- FastAPI 把同步端点放进线程池并发调用，而 rdflib 图不支持并发读写：**所有可变入口必须经 `KnowledgeBase._lock`（RLock）串行化**，新增修改状态的端点/方法时必须带锁
- 确定性纪律：解释文本/建议清单/审计全部排序后处理；时间用 `kb.tick` 步进计数器，不引入 wall-clock
- 全量重算管线是刻意为之的教学设计，不要为性能引入增量推理

### 前端（web/）

六 Tab 原生 JS（无构建步骤）：世界总览（Cytoscape.js，声明边实线/推断边虚线）、事件流、球员对象、决策中心（预览/审批/审计/阈值滑杆）、学习路径、智能体（`agent.js` 对话 + 工具卡片，SSE）。`api/main.py` 的 `/api/graph` 端点决定哪些谓词入图（`shown` 集合），改图谱展示需同步改这里。

## 测试

`tests/` 按引擎模块分文件（actions/api/agent/reasoning/rules/world），API 测试经 TestClient 直接调 FastAPI app，不起真实端口；agent 测试用注入的脚本化假模型（FakeClient），不联网。改治理语义（前置条件/审批/veto）时 `test_actions.py` 与 `test_api.py` 都要跑。
