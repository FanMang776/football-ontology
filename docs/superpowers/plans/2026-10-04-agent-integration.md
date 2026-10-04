# LLM Agent 接入（二期）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给足球本体世界接入 LLM Agent：自然语言查询/建议/执行动作，执行走与人类相同的治理门。

**Architecture:** 新增 `engine/agent.py`（声明式工具表 + 手写工具调用循环 + 客户端工厂），`api/main.py` 加一个 SSE 薄壳端点，`web/` 加第六个对话 Tab。后端无会话状态，历史由前端持有回传。

**Tech Stack:** Python 3 + rdflib（现有引擎）、OpenAI 兼容协议（`openai` SDK，首测智谱 GLM）、FastAPI SSE、原生 JS 前端。

**Spec:** `docs/superpowers/specs/2026-10-04-agent-integration-design.md`

## Global Constraints

- 确定性纪律：所有工具结果与摘要排序后输出；不引入 wall-clock（无 datetime.now/时间戳）。
- 并发纪律：LLM 调用不持锁；工具实现只经 `kb` 公有方法（自带 `_lock`），不得绕过。
- URI 一律经 `engine.namespaces.EX`，不硬编码字符串。
- 事件构造统一走 `engine/events.py`（Task 1 下沉），`api/main.py` 不再自己建事件。
- 工具永不抛异常：失败返回 `{"ok": False, "message": str}`。
- 循环上限 6 轮；每轮 `max_tokens=2000`；模型参数：`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`，`LLM_MODEL=mock` 走脚本假模型。
- 无 lint/format 配置；提交信息中文，风格参照 `git log`。

## Review Focus

1. **`inject_event` 的 `player_id` 不存在** → 应返回 `{"ok": False, "message": ...}`，不能 500（Task 1 测试钉住）。
2. **前端回传的历史缺 `role`/`content` 字段或不是列表** → SSE 端点应返回 422，不能让 Pydantic 之外的异常炸流（Task 3 测试钉住）。
3. **循环上限**：模型无限要求调工具时，第 6 轮后必须带已得信息作答并 `done` 收尾，不能死循环（Task 2 测试钉住）。
4. **`execute_action` 审批两步**：Agent 第一次执行 StartTreatment 得 `pending=true` 后，若不向用户复述就自己再调一次，会绕过人工确认——系统提示词必须写明「pending 时停下来等用户确认」（Task 2 的 mock 行为与 Task 5 文档钉住；代码层不强拦，教学叙事点）。
5. **mock 模式未配置 key 也能起服务**：`make_client()` 在 `LLM_MODEL=mock` 时绝不读 `LLM_API_KEY`，否则无 key 演示直接崩（Task 2 测试钉住）。

---

### Task 1: 事件构造下沉 + 工具表（`engine/agent.py` 静态部分）

**Files:**
- Modify: `engine/events.py`（末尾加 `build_event`）
- Modify: `api/main.py:62-80`（`_build_event` 改为委托 `build_event`）
- Create: `engine/agent.py`（本任务只做工具表部分）
- Test: `tests/test_agent.py`（新建）

**Interfaces:**
- Consumes: `KnowledgeBase`（`describe`/`list_actions`/`preview`/`execute`/`dispatch`）、`World._objects()` 经 `kb.world._objects()`。
- Produces（Task 2/3 依赖，签名逐字）:
  - `engine.events.build_event(etype: str, player_id: str, *, minutes: int | None = None, load: int | None = None, weeks_out: int | None = None, kind: str | None = None)` → 事件实例；未知类型/未知球员/缺参数 raise `ValueError`（中文消息）。
  - `engine.agent.TOOLS: list[dict]` —— OpenAI function-calling 格式 `{"type": "function", "function": {"name", "description", "parameters"}}`，6 个工具：`list_players`、`describe_object`、`list_suggestions`、`preview_action`、`execute_action`、`inject_event`。
  - `engine.agent.run_tool(kb, name: str, args: dict) -> dict` —— 按名分发，永不抛异常。
  - `engine.agent.SYSTEM_PROMPT: str` —— 世界设定 + 工具纪律 + 拒答纪律 + 审批复述要求。

- [ ] **Step 1: 写失败测试**（`tests/test_agent.py`）

```python
import pytest
from engine.knowledge_base import KnowledgeBase
from engine.agent import TOOLS, run_tool, SYSTEM_PROMPT

TOOL_NAMES = {"list_players", "describe_object", "list_suggestions",
              "preview_action", "execute_action", "inject_event"}

@pytest.fixture()
def kb():
    return KnowledgeBase()

def test_tools_schema_complete():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == TOOL_NAMES
    for t in TOOLS:
        assert t["type"] == "function" and t["function"]["description"]
        assert t["function"]["parameters"]["type"] == "object"

def test_list_players_sorted(kb):
    out = run_tool(kb, "list_players", {})
    ids = [p["id"] for p in out["players"]]
    assert ids == sorted(ids) and len(ids) == 20
    assert all("fitness" in p for p in out["players"])

def test_describe_object(kb):
    out = run_tool(kb, "describe_object", {"object_id": "yamal"})
    assert out["id"] == "yamal" and "现在状态" in out

def test_describe_unknown_player_ok_false(kb):
    out = run_tool(kb, "describe_object", {"object_id": "nobody"})
    assert out["ok"] is False

def test_inject_event_and_report(kb):
    out = run_tool(kb, "inject_event",
                   {"etype": "injury", "player_id": "yamal", "weeks_out": 4})
    assert out["ok"] is True and out["chain"]

def test_inject_event_unknown_player_ok_false(kb):
    out = run_tool(kb, "inject_event", {"etype": "injury", "player_id": "x", "weeks_out": 4})
    assert out["ok"] is False and "message" in out

def test_execute_action_walks_governance(kb):
    # 先造一个轮休建议，再走 preview + execute
    run_tool(kb, "inject_event", {"etype": "match", "player_id": "alisson", "minutes": 90})
    sug = run_tool(kb, "list_suggestions", {})
    assert sug["actions"], "事件后应有建议"
    aid = sug["actions"][0]["id"]
    assert run_tool(kb, "preview_action", {"action_id": aid})["ok"] is True
    assert run_tool(kb, "execute_action", {"action_id": aid})["ok"] is True

def test_system_prompt_pins_discipline():
    for word in ("治理", "确认", "没有这个数据"):
        assert word in SYSTEM_PROMPT
```

（注：`yamal`/`alisson` 若与 `data.ttl` 实际短名不符，以 `data.ttl` 为准替换，全文保持一致。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agent.py -q`
Expected: FAIL，`ModuleNotFoundError: engine.agent`

- [ ] **Step 3: 实现**

1. `engine/events.py` 末尾加 `build_event(etype, player_id, *, minutes=None, load=None, weeks_out=None, kind=None)`：把 `api/main.py` `_build_event` 的分支逻辑移进来，球员不存在/参数缺失/未知类型一律 `raise ValueError`，类型注解如 Interfaces 所示。
2. `api/main.py` `_build_event` 改为 try/except 委托 `build_event`，`ValueError` → `HTTPException(400, str(e))`；`/api/events` 行为不变。
3. 新建 `engine/agent.py`：模块 docstring 写明「Agent 的工具表 = 本体操作，不是 SPARQL 不是 REST 端点堆」。实现：
   - `list_players(kb)`：遍历 `kb.world._objects()`，排除 Club；每项 `{"id", "label", "type", "fitness", "injured_weeks"}`（injured_weeks 取 `EX.injuredWith` 记录的 `max(EX.weeksOut)`，无伤为 0），按 `id` 排序。
   - 其余工具一比一委托 `kb.describe` / `kb.list_actions` / `kb.preview` / `kb.execute` / `kb.dispatch(build_event(...))`；`KeyError`/`ValueError` 捕获为 `{"ok": False, "message": ...}`；`kb.describe` 成功结果直接返回（不加 ok 键）。
   - `dispatch` 成功返回 `{"ok": True, "chain": report["chain"], "state_changes": report["state_changes"]}`。
   - `TOOLS` 声明 6 个工具的 JSON Schema（参数名与上面实现一致：`object_id`、`action_id`、`etype`、`player_id`、`minutes`、`load`、`weeks_out`、`kind`）。
   - `SYSTEM_PROMPT`：一段世界设定 + 三条纪律（工具优先于猜测；世界里没有的数据明确说「没有这个数据」；`execute_action` 返回 `pending=true` 时必须停下向用户复述审批要求、得到确认后才再次执行）+ spec「示例问题集」第 4、6、7 类各配一个 few-shot 问答对（演示标准问法与期望行为）。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python -m pytest tests/test_agent.py tests/test_api.py -q`
Expected: 全部 PASS（test_api 回归确认 `_build_event` 委托无破坏）

- [ ] **Step 5: Commit**

```bash
git add engine/events.py engine/agent.py api/main.py tests/test_agent.py
git commit -m "feat: agent 工具表——六个本体操作工具 + 事件构造下沉 events.build_event"
```

---

### Task 2: mock 客户端 + `run_turn` 工具循环

**Files:**
- Modify: `engine/agent.py`（追加循环与客户端部分）
- Modify: `requirements.txt`（加 `openai>=1.0`）
- Test: `tests/test_agent.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `TOOLS`/`run_tool`/`SYSTEM_PROMPT`。
- Produces（Task 3 依赖，签名逐字）:
  - `class BaseClient`：`stream_chat(model: str, messages: list[dict], tools: list[dict]) -> Iterator[dict]`，产出 `{"type": "text-delta", "text": str}` 零或多个，最后产出恰好一个 `{"type": "tool_calls", "calls": [{"id": str, "name": str, "arguments": dict}]}`（可为空列表）。
  - `engine.agent.MockClient(BaseClient)`：按最后一条 user 消息的关键词返回预设脚本（用于无 key 演示；测试用 FakeClient 注入，不依赖关键词表）。
  - `engine.agent.make_client() -> BaseClient`：`os.environ["LLM_MODEL"] == "mock"` → `MockClient()`（**不读 LLM_API_KEY**）；否则 `openai.OpenAI(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"])` 的适配子类。
  - `engine.agent.run_turn(kb, client, model: str, messages: list[dict]) -> Iterator[dict]`：产出四类事件字典（SSE 载荷，逐字）：
    - `{"type": "delta", "text": str}`
    - `{"type": "tool_call", "name": str, "args": dict}`
    - `{"type": "tool_result", "name": str, "summary": str}`
    - `{"type": "done", "rounds_used": int}`（终止事件，每轮恰好一个）
  - `engine.agent.MAX_ROUNDS = 6`，`engine.agent.MAX_TOKENS = 2000`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_agent.py`）

```python
from engine.agent import run_turn, MAX_ROUNDS

class FakeClient:
    """脚本化假模型：pop 序列，脚本耗尽后固定作答。"""
    def __init__(self, script):
        self.script = list(script)   # 每项: (text_delta_or_None, calls_or_None)
    def stream_chat(self, model, messages, tools):
        item = self.script.pop(0) if self.script else (f"回答 {len(messages)}", [])
        text, calls = item
        if text:
            yield {"type": "text-delta", "text": text}
        yield {"type": "tool_calls",
               "calls": [{"id": f"c{i}", "name": n, "arguments": a}
                         for i, (n, a) in enumerate(calls or [])]}

def collect(kb, client, msgs):
    return list(run_turn(kb, client, "m", msgs))

def test_run_turn_plain_answer(kb):
    evts = collect(kb, FakeClient([(None, [])]), [{"role": "user", "content": "hi"}])
    assert [e["type"] for e in evts] == ["delta", "done"] and evts[-1]["rounds_used"] == 1

def test_run_turn_tool_loop(kb):
    script = [(None, [("list_suggestions", {})]),
              ("共 %d 条建议", [])]
    evts = collect(kb, FakeClient(script), [{"role": "user", "content": "有什么建议"}])
    types = [e["type"] for e in evts]
    assert types == ["tool_call", "tool_result", "delta", "done"]
    assert evts[1]["summary"]        # tool_result 有紧凑摘要

def test_run_turn_round_cap(kb):
    evts = collect(kb, FakeClient([(None, [("list_players", {})])] * 99),
                   [{"role": "user", "content": "名单"}])
    assert evts[-1]["type"] == "done" and evts[-1]["rounds_used"] == MAX_ROUNDS
    assert evts[-2]["type"] == "delta" and "上限" in evts[-2]["text"]

def test_run_turn_pending_approval_recorded(kb):
    run_tool(kb, "inject_event", {"etype": "injury", "player_id": "alisson", "weeks_out": 4})
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "StartTreatment")
    msgs = [{"role": "user", "content": "处理重伤员"}]
    evts = list(run_turn(kb, FakeClient([(None, [("execute_action", {"action_id": aid})])]), "m", msgs))
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert "pending" in tr["summary"]
    # assistant 收到 pending 结果，供下一轮用户确认后再次执行
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert tool_msgs and "pending" in tool_msgs[-1]["content"]

def test_make_client_mock_needs_no_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    from engine.agent import make_client, MockClient
    assert isinstance(make_client(), MockClient)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agent.py -q -k "turn or client"`
Expected: FAIL，`ImportError: cannot import name 'run_turn'`

- [ ] **Step 3: 实现**

1. `requirements.txt` 加 `openai>=1.0` 并 `pip install -r requirements.txt`。
2. `run_turn(kb, client, model, messages)`（生成器）：
   - 外层 `for round in range(1, MAX_ROUNDS + 1)`：调 `client.stream_chat(model, messages, TOOLS)`，转发 `text-delta` 为 `{"type": "delta", ...}` 并把文字攒进 assistant 消息；拿到 `tool_calls` 后：空列表 → yield `{"type": "done", "rounds_used": round}` 结束。
   - 非空：yield 每个调用为 `tool_call` 事件；按序 `run_tool(kb, name, args)`，yield `tool_result` 事件（`summary = _summarize(name, result)`）；把 assistant 的 tool_calls 消息（`arguments` json-dumps）与 `role:"tool"` 消息（content 为完整结果 json-dumps）append 进 `messages`。
   - 循环走满 MAX_ROUNDS 仍未结束：yield 一条 `delta`（文案固定含「工具轮数已达上限」），再 yield `done`。
   - `_summarize(name, result) -> str`：确定性紧凑摘要——`list_players` → 「共 N 名球员，体能最低的是 X(值)」；`list_suggestions` → 「共 N 条建议：id1、id2…」；`preview_action` → 「+a、+b；−c」；`execute_action` → `result["message"]`（pending 时天然含审批文案）；`inject_event` → settle 文案；失败 → message。全部排序后拼接。
3. `MockClient.stream_chat`：关键词脚本（建议/谁/执行/受伤 等映射到工具调用序列，最后一轮固定中文回答）；脚本表放模块顶部 dict，注释「仅供无 key 演示，测试用注入 FakeClient」。
4. `OpenAIClient(BaseClient)`：内部持 `openai.OpenAI` 客户端；`stream_chat` 调 `chat.completions.create(model, messages, tools, stream=True, max_tokens=MAX_TOKENS)`，增量 `delta.content` → `text-delta`，`delta.tool_calls` 聚合（按 index 拼 `arguments` 字符串，结束时 `json.loads`）为终止 `tool_calls` 事件。（以 openai SDK 当前流式签名为准，实现时核对。）
5. `make_client()`：读三个环境变量，按 Interfaces 的 mock 短路规则返回。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agent.py -q`
Expected: PASS（含 Task 1 的测试）

- [ ] **Step 5: Commit**

```bash
git add engine/agent.py requirements.txt tests/test_agent.py
git commit -m "feat: run_turn 工具循环 + mock/OpenAI 兼容客户端"
```

---

### Task 3: SSE 端点 `POST /api/agent/chat`

**Files:**
- Modify: `api/main.py`（`/api/reset` 之前插入端点）
- Test: `tests/test_api.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `run_turn`/`make_client`。
- Produces: `POST /api/agent/chat`，请求体 `{"messages": [{"role": str, "content": str, ...}]}`（Pydantic 宽松校验：messages 必为非空列表、每项必须有 `role` 与 `content`，多余键放行）；响应 `text/event-stream`，每行 `data: {json}\n\n`，事件即 `run_turn` 的四类字典，`done` 收尾。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_api.py`）

```python
import json
import httpx

class LocalFakeClient:
    """与 tests/test_agent.py 的 FakeClient 同构，本地复制避免跨文件 import。"""
    def __init__(self, script):
        self.script = list(script)
    def stream_chat(self, model, messages, tools):
        item = self.script.pop(0) if self.script else ("回答", [])
        text, calls = item
        if text:
            yield {"type": "text-delta", "text": text}
        yield {"type": "tool_calls",
               "calls": [{"id": f"c{i}", "name": n, "arguments": a}
                         for i, (n, a) in enumerate(calls or [])]}

def test_agent_chat_sse(monkeypatch):
    import api.main as m
    monkeypatch.setattr(m, "AGENT_CLIENT", LocalFakeClient([("你好，世界", [])]))
    with httpx.Client(transport=httpx.ASGITransport(app=m.app), base_url="http://t") as c:
        with c.stream("POST", "/api/agent/chat",
                      json={"messages": [{"role": "user", "content": "在吗"}]}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = [json.loads(line[len("data: "):])
                      for line in r.iter_lines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["delta", "done"]

def test_agent_chat_rejects_bad_history():
    import api.main as m
    with httpx.Client(transport=httpx.ASGITransport(app=m.app), base_url="http://t") as c:
        r = c.post("/api/agent/chat", json={"messages": [{"role": "user"}]})
        assert r.status_code == 422
        r = c.post("/api/agent/chat", json={"messages": "hi"})
        assert r.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api.py -q -k agent`
Expected: FAIL，404 Not Found

- [ ] **Step 3: 实现**

`api/main.py`：
- 模块级 `AGENT_CLIENT = agent.make_client()`（import 时即定，测试 monkeypatch 此名字）。
- `class ChatBody(BaseModel)`：`messages: list[dict[str, Any]] = Field(min_length=1)`。
- 端点为**同步生成器**（`def chat(body: ChatBody) -> Iterator[str]`——不持 `kb._lock`，工具执行在 `run_turn` 内经 kb 方法自行加锁）：`yield` 每个事件为 `f"data: {json.dumps(e, ensure_ascii=False)}\n\n"`，以 `StreamingResponse(media_type="text/event-stream")` 返回。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python -m pytest tests/test_api.py tests/test_agent.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: POST /api/agent/chat SSE 端点"
```

---

### Task 4: 前端第六个 Tab「智能体」

**Files:**
- Modify: `web/index.html`（tabs 加按钮 + `panel-agent` 区块 + `</body>` 前加 `<script src="/agent.js">`）
- Modify: `web/style.css`（对话样式，视觉 token 复用现有变量）
- Create: `web/agent.js`（独立文件，不放 `app.js`——对话逻辑自成单元）

**Interfaces:**
- Consumes: `POST /api/agent/chat`（SSE）。
- Produces: 无后端依赖；Tab 切换走现有 `data-tab` → `panel-{id}` 通用机制（实现前先在 `app.js` 确认切换逻辑是通用的，若按 tab 名硬编码则补 `agent` 分支）。

- [ ] **Step 1: `index.html` 加 Tab 按钮与面板**

按钮加在「学习路径」后：`<button class="tab" data-tab="agent"><i class="tab-dot" style="--c:#9d5bd2"></i>智能体</button>`。`panel-agent` 区块含：提示条（`LLM_MODEL=mock` 或未配 key 时显示「当前为演示模式」）、消息列表 `#agent-messages`、输入框 + 发送按钮。

- [ ] **Step 2: `web/agent.js` 实现对话**

- `history` 数组存于页面内存（后端无状态）；发送时带上完整历史，本轮新产生的 `tool_call`（`{name, args}`）与 `delta` 拼成的 assistant 文本按 OpenAI 消息格式追加进 `history`；`tool_result` 的 `summary` 以 `role:"tool"` 消息（含对应 `name`）存入。
- `fetch("/api/agent/chat", {method:"POST", body})` 后用 `response.body.getReader()` 逐行解析 `data: {...}`：`delta` 追加打字气泡；`tool_call`/`tool_result` 渲染工具卡片（复用决策中心因果链卡片的 class）；`done` 解锁输入框。
- 待审批（`tool_result.summary` 含「pending」或「确认」）时在卡片上高亮并提示用户可直接回复「确认」。

- [ ] **Step 3: `style.css` 加对话样式**

消息气泡、工具卡片、输入区；颜色/圆角/间距用 `style.css` 顶部现有 CSS 变量，不新起一套。

- [ ] **Step 4: 浏览器验证**

启动 `python -m uvicorn api.main:app --reload`（`LLM_MODEL=mock`），验证：Tab 切换、发消息收流、mock 关键词触发工具卡片、`POST /api/reset` 后前端历史清空。截图留证。

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/agent.js web/style.css
git commit -m "feat: 智能体对话 Tab——SSE 流式对话 + 工具调用卡片"
```

---

### Task 5: 教程第五章 + AGENTS.md 同步 + 全量回归

**Files:**
- Create: `learn/05-智能体面对本体世界.md`
- Modify: `AGENTS.md`（关键模块清单加 `engine/agent.py` 一行；「38 个测试」改为实际数）

- [ ] **Step 1: 写 `learn/05-智能体面对本体世界.md`**（40–70 行，对齐前四章体量与口吻）

必讲五点：① Agent 工具 = 本体操作，不是 API 堆；② 治理门对 Agent 一视同仁（veto/两步审批/审计）；③ 事件不上治理门的不对称（嘴 vs 手）；④ 建议是推论、执行时重验（Agent 读与执行之间世界可变）；⑤ 拒答纪律——世界里没有的数据就说没有。演示脚本用 spec 的七类示例问题。

- [ ] **Step 2: 同步 AGENTS.md**——`### 关键模块` 加 `engine/agent.py`（一句话：工具表=本体操作、循环上限、mock 切换）；测试总数改实际值。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q`
Expected: 全部 PASS，无 skip

- [ ] **Step 4: Commit**

```bash
git add learn/05-智能体面对本体世界.md AGENTS.md
git commit -m "docs: learn/ 第五章——智能体面对本体世界；AGENTS.md 同步"
```
