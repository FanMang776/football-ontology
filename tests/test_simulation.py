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


def test_state_diff_reports_fitness_change():
    """轮休 +20 体能：world_diff.state 报 from/to；建议随执行消失。"""
    from engine.simulation import simulate, _state_diff
    kb = fresh()
    aid = find(kb, "RestPlayer", "p_")
    assert aid, "初始世界应有轮休建议"
    out = simulate(kb, [aid])
    target = aid.split("RestPlayer_")[-1]
    assert out["ok"] is True
    assert out["steps"] == [{"n": 1, "action_id": aid, "ok": True,
                             "message": out["steps"][0]["message"],
                             "pending_in_sandbox": False}]
    fit = [c for c in out["world_diff"]["state"]
           if c["id"] == target and c["field"] == "fitness"]
    assert fit and fit[0]["to"] == fit[0]["from"] + 20
    assert aid in out["world_diff"]["suggestions_removed"]
    assert aid not in out["world_diff"]["suggestions_added"]


def test_state_diff_skips_non_numeric_values():
    """state 图未来可能有字符串字段：diff 跳过非数值，不炸。"""
    from rdflib import Literal
    from engine.simulation import _state_diff
    kb = fresh()
    sim = open_sandbox(kb)
    sim.state.add((EX.p_am1, EX.mood, Literal("好")))
    assert _state_diff(kb, sim) == []      # 非数值字段不进 diff


def test_treatment_auto_confirmed_in_sandbox():
    """审批动作：沙盒内自动二次确认，真实 pending 不变，步骤如实标注。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    out = simulate(kb, [aid])
    step = out["steps"][0]
    assert step["ok"] is True and step["pending_in_sandbox"] is True
    assert kb.pending == set()             # 真实世界的审批中间态没被碰
    # 伤病不进 fitness 公式（objects.py：fitness = 100−消耗+轮休恢复），
    # 治疗改变的是俱乐部 squadStrength（伤愈者重新计入阵容强度）
    str_change = [c for c in out["world_diff"]["state"]
                  if c["id"] == "club_star" and c["field"] == "squadStrength"]
    assert str_change, "治疗后 squadStrength 变化应出现在 state diff 里"


def test_simulate_all_failed_reports_message():
    from engine.simulation import simulate
    kb = fresh()
    out = simulate(kb, ["action_Nobody_123"])
    assert out["ok"] is False and out["message"]
    assert out["steps"][0]["ok"] is False


def test_simulate_empty_list():
    from engine.simulation import simulate
    out = simulate(fresh(), [])
    assert out["ok"] is False and out["message"]
