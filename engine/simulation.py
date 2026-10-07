"""沙盒推演：what-if 全量模拟——推演 = 在另一个世界里真的做一遍。

沙盒是真 KnowledgeBase：新建实例覆盖可变层（effects/retractions/params/
pending，declared 从 ttl 重新 parse），execute/审批门/全量重算零改动复用。
推演结束沙盒即弃——执行是假的（不落库），因果链是真的（全真管线跑出来），
真实世界一个字节不动。
"""
from engine.knowledge_base import KnowledgeBase


def open_sandbox(real_kb: KnowledgeBase) -> KnowledgeBase:
    """按当前真实世界快照造一个沙盒：可变层拷贝，declared 重新加载。"""
    sim = KnowledgeBase()
    with real_kb._lock:          # 快照取锁内一致瞬间；RLock 可重入
        for t in real_kb.effects:
            sim.effects.add(t)
        for t in real_kb.retractions:
            sim.retractions.add(t)
        sim.params = dict(real_kb.params)
        sim.pending = set(real_kb.pending)
    sim.refresh()
    sim.world.bootstrap()        # 派生状态基于沙盒事实重算
    return sim


def simulate(real_kb: KnowledgeBase, action_ids: list) -> dict:
    """在沙盒里按顺序真执行动作，返回每步结果 + 沙盒/真实世界 diff。

    驱动循环是唯一特判处：审批动作首次返回 pending 时自动再调一次
    execute 确认（动作列表即用户授权），并在步骤里如实标注——
    execute 本身与治理门零改动。某步失败不影响后续步骤。
    """
    if not action_ids:
        return {"ok": False, "steps": [], "world_diff": None,
                "message": "推演动作列表为空"}
    sim = open_sandbox(real_kb)
    steps = []
    for i, aid in enumerate(action_ids, 1):
        res = sim.execute(str(aid))
        was_pending = bool(res.get("pending"))
        if was_pending:
            res = sim.execute(str(aid))   # 沙盒内自动确认：列表即用户授权
        steps.append({"n": i, "action_id": str(aid),
                      "ok": bool(res.get("ok")),
                      "message": res.get("message", ""),
                      "pending_in_sandbox": was_pending})
    ok = any(s["ok"] for s in steps)
    real_ids = sorted(str(a).split("#")[-1] for a in real_kb.action_reasons)
    sim_ids = sorted(str(a).split("#")[-1] for a in sim.action_reasons)
    out = {"ok": ok, "steps": steps,
           "world_diff": {"state": _state_diff(real_kb, sim),
                          "suggestions_removed": sorted(set(real_ids) - set(sim_ids)),
                          "suggestions_added": sorted(set(sim_ids) - set(real_ids))}}
    if not ok:
        out["message"] = "所有推演步骤均未成功"
    return out


def _state_diff(real_kb: KnowledgeBase, sim: KnowledgeBase) -> list:
    """state 层 diff：按 (主体, 谓词) 归并 from/to；非数值字段跳过。"""
    def index(g):
        out = {}
        for s, p, o in g:
            try:
                out[(str(s), str(p))] = int(o)
            except (TypeError, ValueError):
                pass            # 非数值字段不进 diff
        return out

    before, after = index(real_kb.state), index(sim.state)
    changes = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        if b != a:
            changes.append({"id": key[0].split("#")[-1],
                            "field": key[1].split("#")[-1],
                            "from": b, "to": a})
    return changes
