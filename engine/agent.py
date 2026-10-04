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
