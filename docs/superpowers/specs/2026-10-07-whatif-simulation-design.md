# 三期设计：what-if 全量推演（沙盒世界）

日期：2026-10-07
状态：待评审

## 1. 背景与目标

一期建立了六层知识模型与治理动作，二期把 LLM Agent 接入本体世界（六个工具 + 治理门一视同仁）。但 Agent 目前只有"预览"（`preview_action`，只返回将写入/移除的三元组），回答不了执行后世界如何反应。

三期新增**推演**能力：在沙盒世界里把动作真的执行一遍（完整治理 + 全量重算 + 规则刷新），把沙盒世界与真实世界的差异讲给用户听。

核心用例（用户 2026-10-07 选定）：

- **主场景：「试试看再决定」**——用户问"如果征调 16 号会怎样"，Agent 推演后报告因果链，用户再决定是否真执行
- **自然延伸：多步连锁**——一次推演里顺序执行多个动作，每步之间全量重算，看终局世界

范围决定（已与用户确认）：

- 推演引擎独立成模块，Agent 工具是三期唯一入口；**决策中心 UI 按钮留给四期**（加菜，届时只加薄 API + 前端按钮）
- v1 步骤**只支持动作，不支持注入事件**（`build_event` 现成，事件推演同样留作四期加菜）

## 2. 核心定义：推演 vs 预览

| 层次 | 问题 | 现有 preview_action | 三期 simulate_actions |
|---|---|---|---|
| 效果层 | 会写哪些三元组？ | ✅ | ✅（每步 message） |
| 状态层 | fitness / squadStrength 变成多少？ | ❌ | ✅ world_diff.state |
| 建议层 | 哪些建议消失？新冒出什么？ | ❌ | ✅ world_diff.suggestions_* |
| 连锁层 | 第 2、3 步做下去，世界长什么样？ | ❌ | ✅ steps 列表 |

一句话定义：**推演 = 拿一份当前世界的拷贝，在里面真执行（完整 bootstrap 重算 + refresh + 规则刷新），然后 diff 沙盒世界与真实世界。** 执行是假的（不落库），因果链是真的（全真管线跑出来的）。

## 3. 沙盒的建造：方案 A（已确认）

可变的只有 retractions / effects / state / params 四层（外加 pending、audit、tick），declared 不可变。沙盒 = 新建一个真 `KnowledgeBase`，覆盖可变层：

```python
# engine/simulation.py
def open_sandbox(real_kb) -> KnowledgeBase:
    sim = KnowledgeBase()            # declared 重新 parse（312 条，毫秒级）
    with real_kb._lock:
        for t in real_kb.effects:     sim.effects.add(t)
        for t in real_kb.retractions: sim.retractions.add(t)
        sim.params = dict(real_kb.params)
        sim.pending = set(real_kb.pending)
    sim.refresh()
    sim.world.bootstrap()            # 派生状态基于沙盒事实重算
    return sim
```

要点：

- **沙盒就是真实世界**：`execute` / `refresh` / `world.bootstrap` / 审批门零改动复用。不加 Sandbox 子类、不打补丁——"推演 = 在另一个世界里真的做一遍"
- `state` 层不拷贝：它是派生的，`bootstrap()` 会全量重写
- `audit` / `tick` 是沙盒自己新建的，随沙盒丢弃，不污染真实审计
- 快照在 `real_kb._lock` 内取，保证与真实世界一致；`simulate` 整体在 `run_tool` 的 `kb._lock` 内执行（RLock 可重入；沙盒用自己的锁，无死锁）。LLM 调用照旧在锁外

已否决的方案：手写轻量 Sandbox 类（初始化逻辑重复，易与主 KB 漂移）；真实 KB 内事务快照/回滚（污染 audit/tick、并发回滚复杂，违背"推演永不碰真实世界"叙事）。

## 4. 工具形态

对齐二期约定：TOOLS 声明 + `_TOOLS_IMPL` 实现 + 永不抛异常（`run_tool` 已兜底）+ `_summarize` 单行摘要。

```json
{"name": "simulate_actions",
 "description": "在沙盒世界按顺序推演一串建议动作，返回每步结果与沙盒世界和真实世界的差异。不落库",
 "parameters": {"type": "object",
                "properties": {"actions": {"type": "array",
                                 "items": {"type": "string"},
                                 "description": "建议动作 id，按执行顺序"}},
                "required": ["actions"]}}
```

- 单动作推演 = 列表放一个元素，"试试看"零特判
- 多步连锁 = 一次调用传多个 id，引擎里顺序 execute、每步之间重算。一次工具调用完成，不占 `MAX_ROUNDS=6` 额度
- 中途某步条件已变（不在沙盒建议清单里）→ 该步 `ok=false`，**后续步骤继续尝试**——与真实 `execute` 的二次防护语义一致
- 未知 action id 同理：单步 `ok=false`，不炸整次推演
- 空列表 / 缺参数 → `{"ok": false, "message": ...}`

### 审批门：沙盒内自动放行（修正自早期方案）

`execute` 零改动。审批动作第一次调用返回 pending 时，`simulate` 的**驱动循环**自动再调一次 `execute` 确认，并在该步标注 `pending_in_sandbox: true`。

理由：不改 `execute`、不给治理门开后门——推演的动作列表是用户（经 Agent）发起的，视为已确认；报告如实告知"这步在真实世界需要审批"。审批动作第二次仍失败（如条件同时被否决）则按普通失败步骤记录，链条继续。

## 5. 报告格式

```json
{"ok": true,
 "steps": [
   {"n": 1, "action_id": "action_RestPlayer_p_am1", "ok": true,
    "message": "已执行：体能低于阈值", "pending_in_sandbox": false},
   {"n": 2, "action_id": "action_RestPlayer_p_fw2", "ok": false,
    "message": "动作 action_RestPlayer_p_fw2 不在当前建议清单中（可能已执行或条件已变化）",
    "pending_in_sandbox": false}],
 "world_diff": {
   "state": [
     {"id": "p_am1", "field": "fitness", "from": 62, "to": 82},
     {"id": "c_main", "field": "squadStrength", "from": 87, "to": 83}],
   "suggestions_removed": ["action_RestPlayer_p_am1"],
   "suggestions_added": ["action_Callup_p_yam3"]}}
```

- `steps`：驱动循环逐条收集 `execute` 的返回（含 pending 放行后的最终结果）
- `world_diff.state`：diff 真实与沙盒的 `state` 图（新增/消失三元组），按 (主体, 谓词) 归并为 from/to 字段；数值型谓词取值，实现细节（谓词 → 展示名映射）放 `simulation.py` 内
- `world_diff.suggestions_*`：两边 `list_actions()` 的 id 集合差
- `ok`：整次推演只要有 ≥1 步成功即为 true；全部失败时 `ok=false` + 汇总 message
- `_summarize` 单行版（前端工具卡片只显示这句）："推演 2 步（1 成功）；体能 62→82；新增建议 1 条"——具体拼装以实现为准，保持确定性排序
- SYSTEM_PROMPT 追加纪律："simulate_actions 的结果只在沙盒成立，真正执行必须走 execute_action"

## 6. 模拟模式与文档同步

- `MockClient.RULES` 增加"推演"关键词脚本（list_suggestions → simulate_actions → 收尾），保证无 key 也能演示三期功能
- `learn/` 教程：新增一章（或第五章后续节）讲反事实推演——预览只答三元组、推演答整条因果链、沙盒与六层模型的关系；代码引用来自实装
- `README` / `AGENTS.md` 同步：关键模块表加 `engine/simulation.py`，测试计数更新

## 7. 测试（TDD）

新建 `tests/test_simulation.py`：

1. **隔离性（最关键）**：推演后真实 kb 的 effects / retractions / state / params / pending / audit / tick / action_reasons 全部不变
2. 单动作：world_diff.state 的 fitness from/to 正确；建议消失/新增正确
3. 多步连锁：第 2 步基于第 1 步之后的沙盒状态（建议清单随第 1 步变化）
4. 中途条件失效：某步 ok=false，后续步骤仍执行
5. 审批动作：自动放行 + `pending_in_sandbox: true`；真实 kb 的 pending 集合不变
6. 未知 action id / 空列表：单步或整体 ok=false，不抛异常
7. veto 传导：沙盒里触发前置条件否决时，建议按真实语义闭嘴

`tests/test_agent.py`（FakeClient 注入，不联网）：

8. simulate_actions 工具声明与分发正确；失败转 `{"ok": false}`
9. `_summarize` 单行摘要格式
10. SYSTEM_PROMPT 含新纪律

改治理语义相关的既有测试（`test_actions.py`、`test_api.py`）全量回归——本设计不改 `actions.py`，若有失败即为回归信号。

## 8. 明确不做（YAGNI）

- 不加 REST 端点（UI 按钮四期再加薄 API）
- 不支持沙盒注入事件
- 不做沙盒会话缓存（无状态，多步靠动作列表）
- 不做方案对比（A/B 两条链并列展示）
- 不做增量推理、不引入 wall-clock——全量重算与 tick 纪律照旧
