"""动作执行器：效果即事实——写回后重新推理，已处置建议自动消失。

生产环境中 execute 是对 CRM/ERP/营销平台 API 的调用；
demo 里把动作效果作为新三元组写回 effects 层（撤销写回 retractions 层），
接口形态一致。每条效果返回 (新增三元组列表, 撤销三元组列表)。
"""
from rdflib import Literal

from engine.namespaces import EX

# PausePromotion 必须撤销声明层的 "active"（data.ttl 里已有），
# 只叠加 "paused" 的话声明层 "active" 仍在物化图里，Q_PAUSE 会永远命中——
# 所以这里用 (新增, 撤销) 二元组：新增走 effects 层，撤销走 retractions 层。
EFFECTS = {
    "PausePromotion": lambda targets: (
        [(targets[0], EX.status, Literal("paused"))],
        [(targets[0], EX.status, Literal("active"))]),
    "NotifyCustomer": lambda targets: (
        [(targets[0], EX.notified, Literal(True))], []),
    "CreatePurchaseOrder": lambda targets: (
        [(targets[0], EX.restockRequested, Literal(True))], []),
    "PromoteSubstitute": lambda targets: (
        [(targets[0], EX.promoBoosted, Literal(True))], []),
}


def execute(kb, action_id: str) -> dict:
    """执行一条建议动作，返回 {ok, message}。"""
    act = EX[action_id]
    if act not in kb.action_reasons:
        return {"ok": False,
                "message": f"动作 {action_id} 不在当前建议清单中（可能已执行或条件已变化）"}
    info = kb.action_reasons[act]
    factory = EFFECTS.get(info["type"])
    if factory is None:
        return {"ok": False, "message": f"未知动作类型 {info['type']}"}
    additions, retractions = factory(info["targets"])
    for t in additions:
        kb.effects.add(t)
    for t in retractions:
        kb.retractions.add(t)
    kb.refresh()
    if act in kb.action_reasons:
        # 二次防护：执行后条件应已消除；未消除则回滚本次效果
        for s, p, o in additions:
            kb.effects.remove((s, p, o))
        for s, p, o in retractions:
            kb.retractions.remove((s, p, o))
        kb.refresh()
        return {"ok": False, "message": "动作执行后条件未消除，已回滚"}
    return {"ok": True, "message": info["reason"]}
