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


def test_multi_step_chain_and_conditional_failure():
    """多步连锁：第 2 步基于第 1 步后的沙盒状态；中途条件失效续走后续步骤。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))     # AM 缺口 → 征调 y_am1/y_am2
    aids = [a["id"] for a in kb.list_actions()
            if a["type"] == "CallUpYouth" and "p_yam" in a["targets"][0]["id"]]
    assert len(aids) == 2
    aids.append("action_RestPlayer_p_st1")          # 不存在的建议 → 单步失败
    out = simulate(kb, aids)
    assert [s["ok"] for s in out["steps"]] == [True, True, False]
    assert out["steps"][2]["ok"] is False
    assert out["ok"] is True                        # 有 ≥1 步成功即为 true
    called = sorted(t["id"] for a in kb.list_actions()
                    if a["type"] == "CallUpYouth" and "p_yam" in a["targets"][0]["id"]
                    for t in a["targets"])
    assert len(called) == 2                         # 真实世界：两名青年队都没被真征调


def test_multi_step_repeated_action_id():
    """同一动作推两次：第二次不在清单中，单步失败不炸。"""
    from engine.simulation import simulate
    kb = fresh()
    aid = find(kb, "RestPlayer", "p_")
    out = simulate(kb, [aid, aid])
    assert [s["ok"] for s in out["steps"]] == [True, False]
    assert out["ok"] is True


def test_veto_cascade_inside_sandbox():
    """报名 14→16 达上限：沙盒里第三次征调被否决，veto 只写在沙盒。"""
    from engine.simulation import simulate
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))     # AM 缺口 → y_am1/y_am2
    kb.dispatch(InjuryEvent(EX.p_gk1, 4, "伤"))     # GK 缺口 → y_gk1
    aids = [a["id"] for a in kb.list_actions() if a["type"] == "CallUpYouth"]
    assert len(aids) == 3
    before = snapshot(kb)
    out = simulate(kb, aids)
    assert [s["ok"] for s in out["steps"]] == [True, True, False]
    assert "上限" in out["steps"][2]["message"]
    assert snapshot(kb) == before                   # 真实世界无 veto 三元组
