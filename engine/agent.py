"""Agent 工具表：Agent 的手 = 六个本体操作，不是 SPARQL，不是 REST 端点堆。

「Agent 面对本体世界而不是一堆 API」在这里落地：每个工具就是本体世界的一个
动作——查对象、问建议、推演、执行、注入事件。治理语义（前置条件/审批/审计）
全部复用 engine/actions.py，Agent 与人类用户走同一扇门。
"""
from engine import events as ev
from engine.namespaces import EX
from engine.objects import ClubObject

SYSTEM_PROMPT = """你是群星 FC 足球本体世界的助理教练。这个世界是一个运行中的
本体：20 名球员（14 一线队 + 6 青年队）是运行时对象，体能是算出来的派生状态，
建议是规则推论——它们会随事实即时变化。

纪律：
1. 回答前先用工具查世界，不要凭空猜测。世界里没有的数据（如下赛季转会计划）
   要明确说「世界没有这个数据」，不要编造。
2. execute_action 返回 pending=true 时，必须停下来向用户复述审批要求，
   得到用户明确确认后才再次调用同一工具执行——治理门对任何人都一样。
3. 用户问「为什么」时，用 describe_object 的「为什么」字段回答，不要自己推理。

示例：
- 用户「帮我把德布劳内轮休」→ 调 execute_action(action_id=action_RestPlayer_p_am1)。
- 用户「伤员都有谁？严重的按流程处理」→ 先 list_players 看伤停，再对伤停最重的
  球员 describe_object 确认，再 execute_action；pending 时停下等确认。
- 用户「下赛季引进谁」→ 回答「世界没有这个数据」。
"""

# 每个工具: OpenAI function-calling 声明 + 同名实现（_TOOLS_IMPL）
TOOLS = [
    {"type": "function", "function": {
        "name": "list_players",
        "description": "列出全部球员及体能摘要（不含俱乐部）",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "describe_object",
        "description": "对象的四问：是谁/现在状态/为什么/能做什么",
        "parameters": {"type": "object",
                       "properties": {"object_id": {"type": "string",
                                       "description": "对象短名，如 p_yam1"}},
                       "required": ["object_id"]},
    }},
    {"type": "function", "function": {
        "name": "list_suggestions",
        "description": "当前动作建议清单（建议是推论，随事实即时重算）",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "preview_action",
        "description": "执行前推演：返回将写入/移除的三元组，不落库",
        "parameters": {"type": "object",
                       "properties": {"action_id": {"type": "string",
                                       "description": "建议动作 id"}},
                       "required": ["action_id"]},
    }},
    {"type": "function", "function": {
        "name": "execute_action",
        "description": "执行一条建议动作（走完整治理门：前置条件/审批/审计）",
        "parameters": {"type": "object",
                       "properties": {"action_id": {"type": "string",
                                       "description": "建议动作 id"}},
                       "required": ["action_id"]},
    }},
    {"type": "function", "function": {
        "name": "inject_event",
        "description": "向世界注入事件（比赛/训练/受伤/痊愈）——事件是感知输入，不上治理门",
        "parameters": {"type": "object",
                       "properties": {
                           "etype": {"type": "string",
                                     "enum": ["match", "training", "injury", "recovery"]},
                           "player_id": {"type": "string"},
                           "minutes": {"type": "integer", "description": "match: 出场分钟 1-120"},
                           "load": {"type": "integer", "description": "training: 负荷 1-100"},
                           "weeks_out": {"type": "integer", "description": "injury: 伤停周数 1-52"},
                           "kind": {"type": "string", "description": "injury: 伤病名称"},
                       },
                       "required": ["etype", "player_id"]},
    }},
]


def _list_players(kb):
    out = []
    for oid, obj in sorted(kb.world._objects().items()):
        if isinstance(obj, ClubObject):
            continue
        recs = list(kb.material.objects(obj.iri, EX.injuredWith))
        weeks = max((int(kb.material.value(r, EX.weeksOut) or 0) for r in recs),
                    default=0)
        out.append({"id": oid,
                    "label": obj.describe()["label"],
                    "type": obj.type.split("#")[-1] if isinstance(obj.type, str)
                    else str(obj.type).split("#")[-1],
                    "fitness": obj.compute(kb)["fitness"],
                    "injured_weeks": weeks})
    return {"players": out}


def _describe(kb, args):
    try:
        return kb.describe(args["object_id"])
    except KeyError:
        return {"ok": False, "message": f"未知对象: {args.get('object_id')}"}


def _suggestions(kb):
    return {"actions": kb.list_actions()}


def _preview(kb, args):
    return kb.preview(args["action_id"])


def _execute(kb, args):
    return kb.execute(args["action_id"])


def _inject(kb, args):
    try:
        report = kb.dispatch(ev.build_event(
            kb, args["etype"], args["player_id"],
            minutes=args.get("minutes"), load=args.get("load"),
            weeks_out=args.get("weeks_out"), kind=args.get("kind")))
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "chain": report["chain"],
            "state_changes": report["state_changes"]}


_TOOLS_IMPL = {
    "list_players": lambda kb, args: _list_players(kb),
    "describe_object": _describe,
    "list_suggestions": lambda kb, args: _suggestions(kb),
    "preview_action": _preview,
    "execute_action": _execute,
    "inject_event": _inject,
}


def run_tool(kb, name: str, args: dict) -> dict:
    """按名分发工具调用。工具永不抛异常：失败返回 {"ok": False, "message"}。"""
    impl = _TOOLS_IMPL.get(name)
    if impl is None:
        return {"ok": False, "message": f"未知工具: {name}"}
    try:
        return impl(kb, args or {})
    except Exception as e:      # noqa: BLE001——工具边界，一切失败都转成 ok=False
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}


# ---------- 工具调用循环：Agent 的脑 ----------

import json as _json
import os as _os

MAX_ROUNDS = 6
MAX_TOKENS = 2000

CAP_MESSAGE = "工具轮数已达上限，以下基于已获信息回答。"


def _summarize(name: str, result: dict) -> str:
    """确定性紧凑摘要：前端只展示这句，完整结果仅本轮内喂回模型。"""
    if not result.get("ok", True):
        prefix = "[pending] " if result.get("pending") else ""
        return prefix + result.get("message", "工具调用失败")
    if name == "list_players":
        ps = result["players"]
        low = min(ps, key=lambda p: (p["fitness"], p["id"]))
        return f"共 {len(ps)} 名球员，体能最低的是 {low['label']}({low['fitness']})"
    if name == "list_suggestions":
        acts = result["actions"]
        return f"共 {len(acts)} 条建议：" + "、".join(a["id"] for a in acts)
    if name == "preview_action":
        add = "、".join("+" + a for a in sorted(result["additions"]))
        ret = "、".join("−" + a for a in sorted(result["retractions"]))
        return f"将写入：{add or '无'}；将移除：{ret or '无'}"
    if name == "execute_action":
        prefix = "[pending] " if result.get("pending") else ""
        return prefix + result.get("message", "已执行")
    if name == "inject_event":
        settle = next((s["text"] for s in result["chain"]
                       if s["stage"] == "settle"), "")
        return settle or "事件已注入"
    if name == "describe_object":
        return "；".join(result.get("现在状态", []))
    return result.get("message", "完成")


def _assistant_msg(text, calls):
    tc = [{"id": c["id"], "type": "function",
           "function": {"name": c["name"],
                        "arguments": _json.dumps(c["arguments"], ensure_ascii=False)}}
          for c in calls]
    msg = {"role": "assistant", "content": text or ""}
    if tc:
        msg["tool_calls"] = tc
    return msg


def run_turn(kb, client, model: str, messages: list):
    """一轮对话：循环 流式回答 ↔ 工具执行，产出 SSE 事件字典（生成器）。

    LLM 调用不持 kb._lock；工具执行经 kb 方法自行加锁。世界可能在
    Agent 读与执行之间变化——execute 自带二次校验（建议是推论，执行时重验）。
    """
    for rnd in range(1, MAX_ROUNDS + 1):
        text_parts = []
        calls = None
        for chunk in client.stream_chat(model, messages, TOOLS):
            if chunk["type"] == "text-delta":
                text_parts.append(chunk["text"])
                yield {"type": "delta", "text": chunk["text"]}
            elif chunk["type"] == "tool_calls":
                calls = chunk["calls"]
        if not calls:
            messages.append({"role": "assistant",
                             "content": "".join(text_parts)})
            yield {"type": "done", "rounds_used": rnd}
            return
        messages.append(_assistant_msg("".join(text_parts), calls))
        for c in calls:
            yield {"type": "tool_call", "name": c["name"], "args": c["arguments"]}
            result = run_tool(kb, c["name"], c["arguments"])
            yield {"type": "tool_result", "name": c["name"],
                   "summary": _summarize(c["name"], result)}
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": _json.dumps(result, ensure_ascii=False,
                                                    sort_keys=True)})
    yield {"type": "delta", "text": CAP_MESSAGE}
    yield {"type": "done", "rounds_used": MAX_ROUNDS}


# ---------- LLM 客户端：OpenAI 兼容协议（GLM 等国产模型通用） ----------

class BaseClient:
    def stream_chat(self, model, messages, tools):
        raise NotImplementedError


class MockClient(BaseClient):
    """关键词脚本假模型：仅供无 key 演示。测试请注入 FakeClient，别依赖此表。"""

    RULES = [   # (关键词, [(text, [(tool, args)])])，按序取第一个命中的规则
        ("建议", [(None, [("list_suggestions", {})]),
                  (None, [])]),
        ("名单", [(None, [("list_players", {})]),
                  (None, [])]),
        ("伤", [(None, [("list_players", {})]),
                (None, [])]),
        ("轮休", [(None, [("list_suggestions", {})]),
                  (None, [("execute_action", {"action_id": "action_RestPlayer_p_am1"})]),
                  (None, [])]),
    ]

    def stream_chat(self, model, messages, tools):
        last = next((m["content"] for m in reversed(messages)
                     if m.get("role") == "user" and m.get("content")), "")
        for keyword, script in self.RULES:
            if keyword in last:
                idx = sum(1 for m in messages
                          if m.get("role") == "assistant" and m.get("tool_calls"))
                if idx < len(script):
                    text, calls = script[idx]
                    if text:
                        yield {"type": "text-delta", "text": text}
                    yield {"type": "tool_calls",
                           "calls": [{"id": f"m{i}", "name": n, "arguments": a}
                                     for i, (n, a) in enumerate(calls or [])]}
                    return
        yield {"type": "text-delta", "text": "（演示模式）我基于本体世界回答：请试试问「有什么建议」「球队名单」或「帮德布劳内轮休」。"}
        yield {"type": "tool_calls", "calls": []}


class OpenAIClient(BaseClient):
    """OpenAI 兼容流式客户端：文本增量直通，tool_calls 增量按 index 聚合。"""

    def __init__(self, base_url, api_key):
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def stream_chat(self, model, messages, tools):
        stream = self._client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            stream=True, max_tokens=MAX_TOKENS)
        text_parts = []
        calls = {}          # index -> {"id", "name", "arguments": [parts]}
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue
            if delta.content:
                text_parts.append(delta.content)
                yield {"type": "text-delta", "text": delta.content}
            for tc in (delta.tool_calls or []):
                slot = calls.setdefault(tc.index, {"id": tc.id, "name": "",
                                                   "arguments": []})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"].append(tc.function.arguments)
        out = [{"id": slot["id"], "name": slot["name"],
                "arguments": _json.loads("".join(slot["arguments"]) or "{}")}
               for _, slot in sorted(calls.items())]
        yield {"type": "tool_calls", "calls": out}


def make_client() -> BaseClient:
    """LLM_MODEL 未设或 =mock → MockClient（绝不读 LLM_API_KEY，无 key 可演示，
    api.main 无环境变量也能 import）；设为其他值 → OpenAI 兼容客户端，
    需 LLM_BASE_URL / LLM_API_KEY 两个环境变量，缺了就让它 KeyError 显式报错。"""
    model = _os.environ.get("LLM_MODEL") or "mock"
    if model == "mock":
        return MockClient()
    base_url = _os.environ["LLM_BASE_URL"]
    api_key = _os.environ["LLM_API_KEY"]
    return OpenAIClient(base_url, api_key)
