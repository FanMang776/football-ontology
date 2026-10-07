"""沙盒推演：建造、隔离性、驱动循环、世界 diff。"""
from engine.events import InjuryEvent
from engine.knowledge_base import KnowledgeBase
from engine.simulation import open_sandbox

from engine.namespaces import EX


def fresh():
    kb = KnowledgeBase()
    kb.reset()
    return kb


def find(kb, type_, contains):
    for a in kb.list_actions():
        if a["type"] == type_ and contains in a["targets"][0]["id"]:
            return a["id"]
    return None


def snapshot(kb):
    """真实世界的可变部位指纹：推演前后必须逐项相等。"""
    return {"effects": sorted(str(t) for t in kb.effects),
            "retractions": sorted(str(t) for t in kb.retractions),
            "state": sorted(str(t) for t in kb.state),
            "params": dict(kb.params),
            "pending": set(kb.pending),
            "tick": kb.tick,
            "audit_len": len(kb.audit),
            "suggestions": sorted(str(a) for a in kb.action_reasons)}


def test_sandbox_copies_mutable_layers():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    sim = open_sandbox(kb)
    assert sorted(str(t) for t in sim.effects) == snapshot(kb)["effects"]
    assert sorted(str(t) for t in sim.retractions) == snapshot(kb)["retractions"]
    assert sim.params == kb.params
    assert sim.pending == kb.pending
    assert sorted(str(a) for a in sim.action_reasons) == snapshot(kb)["suggestions"], \
        "沙盒刷新后的建议清单应与真实世界一致"


def test_sandbox_follows_fitness_floor_param():
    kb = fresh()
    kb.set_params(90)          # 决策中心滑杆改过阈值
    sim = open_sandbox(kb)
    assert sim.params["fitness_floor"] == 90


def test_simulate_leaves_real_world_untouched():
    """隔离性（最关键）：推演后真实世界八个部位逐项不变。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    before = snapshot(kb)
    aid = find(kb, "StartTreatment", "p_st1")
    out = simulate(kb, [aid])
    assert out["ok"] is True
    assert snapshot(kb) == before
