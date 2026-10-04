# LLM Agent 接入（二期）设计 spec

日期：2026-10-04
状态：待用户评审

## 目标与受众

给足球本体世界装上「会说话的入口」：用户在 Web 第六个 Tab「智能体」里用自然语言
查询世界、听取建议、推演并执行动作。Agent 不直接面对 SPARQL 或 REST 端点堆，
而是面对一组**本体操作工具**——「Agent 面对本体世界而不是一堆 API」是二期的核心
教学论点（对应 docs/ 两篇 OntoOS 文章的「行动于世界」层）。

成功标准：

1. 对话 Tab 里能完成六类问答（见「示例问题集」），工具调用过程以卡片可见；
2. Agent 执行动作与人类用户走**同一条治理路**：veto、两步审批、审计一视同仁；
3. 无 API key 也能跑（mock 模式），pytest 全套不联网不花钱；
4. 工具循环上限与拒答纪律写进系统提示词——Agent 不编造世界里不存在的事实；
5. 模型供应商可配置（OpenAI 兼容协议），首测智谱 GLM。

非目标（明确排除）：后端会话持久化、多轮压缩、流式取消、多 Agent 协作、
what-if 全量推演（三期候选）、电商域。会话历史由前端持有，后端无状态。

## 方案（B，已确认）

新增 `engine/agent.py`（工具表 + 手写工具调用循环 + LLM 客户端工厂），API 层薄壳
（一个 SSE 端点），前端加对话 Tab。

否决的备选：
- **内联进 `api/main.py`**——agent 逻辑与 HTTP 层搅在一起，和六层引擎的分层
  讲解风格冲突；
- **Agent 独立服务走 REST**——多进程多部署，对教学 demo 是纯负担；
- **SDK 高层 Tool Runner**——黑盒 helper，违背「每一层可独立讲解」的项目原则，
  循环手写约 30 行，每步（模型要调什么工具 → 执行 → 结果喂回）教程可讲。

## 文件布局

| 文件 | 变更 |
|---|---|
| `engine/agent.py` | 新增：工具表（声明式）、`run_turn()` 生成器、客户端工厂 |
| `api/main.py` | 新增 `POST /api/agent/chat`（SSE），薄壳 |
| `web/` | 第六个 Tab「智能体」：对话界面 + 工具调用卡片 |
| `tests/test_agent.py` | mock LLM 全套测试 |
| `learn/` | 第五章：Agent 与本体世界 |
| `requirements.txt` | 新增 `openai`（OpenAI 兼容客户端，GLM 等国产模型通用） |

## 工具集（6 个）

| 工具 | 实现 | 语义 |
|---|---|---|
| `list_players()` | world 对象表 | 名单 + 体能摘要 |
| `describe_object(object_id)` | `kb.describe` | 四问：是谁/状态/为什么/能做什么 |
| `list_suggestions()` | `kb.list_actions` | 当前建议清单 |
| `preview_action(action_id)` | `kb.preview` | 推演不落库 |
| `execute_action(action_id)` | `kb.execute` | 走完整治理门 |
| `inject_event(type, player_id, ...)` | `kb.dispatch` | 四类事件注入 |

两个教学点钉死：

1. **治理门对 Agent 一视同仁。** `execute_action` 就是 `kb.execute`：
   征调越限 → veto（写 effects，建议消失）；StartTreatment 首次执行 →
   `pending=true`，Agent 必须向用户复述审批要求、等用户确认后再次调用同一工具。
   审计（kb.audit）照记，step 来自 tick 计数器。
2. **事件不上治理门——这是故意的。** 事件是世界的感知输入（嘴），动作才是治理
   对象（手）。`inject_event` 与决策中心的事件注入权限相同。这个不对称本身是
   第五章教材：本体论里「世界发生了什么」和「我们要做什么」是两类写入。

## 并发与一致性

- LLM 流式调用**不持有** `kb._lock`；每个工具执行经 `kb` 方法自行加锁
  （现有代码已保证），与 FastAPI 线程池并发安全兼容。
- 世界可能在 Agent 读与执行之间变化：`actions.execute` 本就以 `action_reasons`
  二次校验、不符即回滚。「建议是推论、执行时重验」纳入第五章叙事。
- 确定性纪律延续：工具结果进对话历史前排序；不引入 wall-clock，
  对话内不出现真实时间戳。

## 对话状态：后端无状态

历史消息由**前端持有**、每轮全量上送（工具调用与其 `tool_result` 紧凑摘要作为
结构化消息一起回传，见 SSE 节）；后端不存会话。与 LLM API 本身的无状态语义一致，也符合项目「重启即恢复初始数据」约定；
`POST /api/reset` 无需新逻辑（前端收到 reset 后清空对话历史）。

## LLM 接入与配置

- OpenAI 兼容协议（`openai` SDK），三个环境变量：
  `LLM_BASE_URL`（智谱：`https://open.bigmodel.cn/api/paas/v4`，以官方文档为准）、
  `LLM_API_KEY`、`LLM_MODEL`（首测 `glm-4.6`，实现时核对当前型号）。
- `LLM_MODEL=mock` → 脚本化假模型（按关键词返回预设工具调用序列），用于
  测试与无 key 演示；真实/假模型经同一客户端接口切换，一行配置。
- 工具循环上限 **6 轮**，超限即带着已得信息作答并在回复中说明——防失控也防
  意外账单。`max_tokens` 每轮 ~2000（教学回答不需要长文）。
- 系统提示词内容：世界设定一句话 + 工具使用纪律 + 拒答纪律（见示例问题集第 7 类）
  + 审批复述要求。系统提示词放 `engine/agent.py` 顶部，与工具表同处可讲。

## SSE 协议

`POST /api/agent/chat`，请求体 `{messages: [...]}`（前端持有的完整历史，
含结构化工具消息），响应 `text/event-stream`：

| 事件 | 载荷 | 前端行为 |
|---|---|---|
| `delta` | `{text}` | 追加文字气泡 |
| `tool_call` | `{name, args}` | 渲染工具卡片（调用了什么） |
| `tool_result` | `{name, summary}` | 卡片补全（带回了什么，紧凑摘要） |
| `done` | `{rounds_used}` | 结束输入态 |

`tool_result` 只传紧凑摘要（排序后的短句），前端历史里持有并回传的也是这份摘要；
完整结构化结果仅在后端本轮内拼进 LLM 请求（喂给下一轮工具循环），不落前端——
控制对话历史体积，代价是后续轮次模型看到的是摘要而非全量工具结果，教学场景够用。

## 前端 Tab（第六个 Tab「智能体」）

- 原生 JS，无构建步骤，与现有五 Tab 同风格（视觉 token 复用）。
- 消息列表 + 输入框；`tool_call`/`tool_result` 渲染为卡片，样式语言复用
  决策中心的因果链卡片。
- 待审批复述以高亮卡片呈现；用户回复「确认」即由 Agent 再次 `execute_action`。
- 无 key/mock 模式在 Tab 顶部显示提示条，不隐藏功能。

## 示例问题集（一鱼三吃：系统提示词 few-shot / 第五章演示脚本 / 测试场景）

1. 查名单/状态：现在哪些球员体能最低？亚马尔现在什么状态，为什么？
2. 问建议：教练组现在有什么建议？为什么建议轮休他？
3. 推演动作：执行轮休会改动世界里的哪些三元组？
4. 执行动作：帮我把阿利松轮休；执行全部建议；「确认那个治疗」（pending 二次确认）。
5. 注入事件：让亚马尔受伤停 4 周；他刚打满 90 分钟；他伤愈复出了。
6. 多步组合：伤员都有谁？严重的按流程处理（describe → suggestions → execute）。
7. **拒答类**：下赛季引进谁？——本体世界里没有的事实，Agent 必须说明
   「世界没有这个数据」而不是编造。

## 测试策略（tests/test_agent.py，全部走 mock）

- 工具表 schema 完整性（名称/参数/实现一一对应）；
- 只读工具返回结构与排序确定性；
- `execute_action`：veto 路径（报名满 16 再征调）与 pending 两步路径；
- 循环上限：mock 模型无限要求调工具，第 6 轮后强制作答；
- SSE 端点：httpx 收流，断言事件序列与 `done` 收尾；
- 回归：`test_actions.py`、`test_api.py` 照跑（治理语义未动，但同路径）。

## 三期预留

工具表是 `engine/agent.py` 内的声明式列表，新增工具即扩展能力——三期的
what-if 推演（全量因果链模拟）预期以新工具（如 `simulate_season`）挂进同一循环，
不改循环本体。规划上三期仍基于足球世界（用户已定），候选主题：推演/多 Agent 视野。

## 工作量估计

引擎 + API 约 1 天；前端 Tab 半天到 1 天；测试 + 教程 1 天。合计 2–3 天。
