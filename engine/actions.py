"""动作治理：Palantir 写路径的三要素——前置条件、审批、审计。

执行即写回：动作效果作为新事实进 effects 层（撤销走 retractions 层），
写回后重算状态并刷新推理——已处置的建议自动消失。
生产环境中 execute 是对业务系统 API 的调用；demo 里接口形态一致。

治理语义（计划钉死）：
  CallUpYouth 的前置条件：报名名单 < 16 人（一线队 + 已征调青年队）。
  违反 → 写 (动作, vetoed, true) 进 effects（规则层不再建议该动作），
  审计记 vetoed，返回 ok=False。
  StartTreatment 是审批动作：第一次 execute 返回 pending=True，
  对同一动作再次 execute 即确认执行。
  每次 dispatch/execute 写审计（kb.audit），step 来自确定性步进计数器。
"""
from rdflib import Literal

from engine.namespaces import EX

ROSTER_LIMIT = 16

EFFECTS = {
    "RestPlayer": lambda targets: (
        [(targets[0], EX.restGiven, Literal(True))], []),
    "CallUpYouth": lambda targets: (
        [(targets[0], EX.calledUp, Literal(True))], []),
    "StartTreatment": lambda targets: (
        [(targets[0], EX.treated, Literal(True))], []),
}

APPROVAL = {"StartTreatment"}
APPROVAL_MESSAGE = "治疗动作需队医确认：对同一动作再次执行即确认"


def _roster_count(kb) -> int:
    seniors = set(kb.material.subjects(EX.playsFor, None))
    called = {s for s in kb.material.subjects(EX.calledUp, None)
              if bool(kb.material.value(s, EX.calledUp))}
    return len(seniors) + len(called)


def _roster_ok(kb, targets) -> bool:
    return _roster_count(kb) < ROSTER_LIMIT


PRECONDITIONS = {"CallUpYouth": _roster_ok}
PRECONDITION_MESSAGES = {
    "CallUpYouth": f"报名名单已达上限 {ROSTER_LIMIT} 人（一线队 + 已征调），征调被否决",
}


def _short(t) -> str:
    from engine.objects import _id
    from rdflib import Literal as L
    if isinstance(t, L):
        return str(t)
    return _id(t)


def _record(kb, action_id, info, result, detail):
    kb.audit.append({"step": kb.next_step(),
                     "action": action_id,
                     "type": info["type"],
                     "target": _short(info["targets"][0]) if info["targets"] else "",
                     "result": result,
                     "detail": detail})


def execute(kb, action_id: str) -> dict:
    """执行一条建议动作。第一次调用审批动作只登记待审批；治理否决写 veto。"""
    act = EX[action_id]
    info = kb.action_reasons.get(act)
    if info is None:
        return {"ok": False,
                "message": f"动作 {action_id} 不在当前建议清单中（可能已执行或条件已变化）"}
    kind = info["type"]
    factory = EFFECTS.get(kind)
    if factory is None:
        return {"ok": False, "message": f"未知动作类型 {kind}"}
    targets = info["targets"]

    # 审批门：第一次只登记，第二次放行
    if kind in APPROVAL and action_id not in kb.pending:
        kb.pending.add(action_id)
        _record(kb, action_id, info, "pending", APPROVAL_MESSAGE)
        return {"ok": False, "pending": True, "message": APPROVAL_MESSAGE}
    kb.pending.discard(action_id)

    # 前置条件：违反即否决，写 veto 让规则层闭嘴
    pre = PRECONDITIONS.get(kind)
    if pre is not None and not pre(kb, targets):
        kb.effects.add((act, EX.vetoed, Literal(True)))
        kb.refresh()
        msg = PRECONDITION_MESSAGES[kind]
        _record(kb, action_id, info, "vetoed", msg)
        return {"ok": False, "message": msg}

    additions, retractions = factory(targets)
    for t in additions:
        kb.effects.add(t)
    for t in retractions:
        kb.retractions.add(t)
    # 效果即事实：写回后重算派生状态（如轮休 +20 体能）再刷新推理，
    # 已处置建议的条件随之消除
    kb.world.bootstrap()
    if act in kb.action_reasons:
        # 二次防护：执行后条件应已消除；未消除则回滚本次效果
        for t in additions:
            kb.effects.remove(t)
        for t in retractions:
            kb.retractions.remove(t)
        kb.world.bootstrap()
        _record(kb, action_id, info, "failed", "动作执行后条件未消除，已回滚")
        return {"ok": False, "message": "动作执行后条件未消除，已回滚"}
    _record(kb, action_id, info, "executed", "已执行：" + info["reason"])
    return {"ok": True, "message": "已执行：" + info["reason"]}


def preview(kb, action_id: str) -> dict:
    """执行前推演：返回将新增/撤销的三元组（短名），不落库。"""
    act = EX[action_id]
    info = kb.action_reasons.get(act)
    if info is None:
        return {"ok": False, "additions": [], "retractions": [],
                "message": f"动作 {action_id} 不在当前建议清单中"}
    factory = EFFECTS.get(info["type"])
    if factory is None:
        return {"ok": False, "additions": [], "retractions": [],
                "message": f"未知动作类型 {info['type']}"}
    additions, retractions = factory(info["targets"])
    fmt = lambda t: " ".join(_short(x) for x in t)
    return {"ok": True,
            "additions": [fmt(t) for t in additions],
            "retractions": [fmt(t) for t in retractions]}
