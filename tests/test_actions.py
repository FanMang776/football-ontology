"""动作治理：报名上限前置条件、治疗审批两步流、审计与预览。"""
from engine.events import InjuryEvent
from engine.knowledge_base import KnowledgeBase
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


def test_treatment_needs_approval_then_executes():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    first = kb.execute(aid)
    assert first["ok"] is False and first.get("pending") is True
    second = kb.execute(aid)
    assert second["ok"] is True


def test_callup_roster_limit_vetoes():
    """一线队 14 + 已征调 2 = 16 达上限，下一次征调被拒并写 veto。"""
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_am1, 4, "伤"))   # AM 缺口 → 建议 y_am1/y_am2
    for _ in range(2):
        aid = find(kb, "CallUpYouth", "p_yam")
        if aid:
            kb.execute(aid)
    # 再制造 GK 缺口：名单已满 16，这次征调必须被 veto
    kb.dispatch(InjuryEvent(EX.p_gk1, 4, "伤"))
    aid = find(kb, "CallUpYouth", "p_ygk")
    assert aid, "GK 缺口应产生征调建议"
    out = kb.execute(aid)
    assert out["ok"] is False
    vetoed = [e for e in kb.audit if e["result"] == "vetoed"]
    assert vetoed


def test_preview_does_not_mutate():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    before = len(kb.effects)
    p = kb.preview(aid)
    assert p["additions"]
    assert len(kb.effects) == before


def test_audit_records_all_results():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    aid = find(kb, "StartTreatment", "p_st1")
    kb.execute(aid)
    kb.execute(aid)
    results = [e["result"] for e in kb.audit]
    assert "event" in results and "pending" in results and "executed" in results


def test_execute_after_condition_gone_fails_gracefully():
    kb = fresh()
    out = kb.execute("nonexistent")
    assert out["ok"] is False


def test_rest_player_executes_and_suggestion_disappears():
    """轮休执行后体能 +20 越过阈值，建议消失——执行路径必须先 refresh 再重算。"""
    kb = fresh()
    kb.set_params(80)
    aid = find(kb, "RestPlayer", "p_dm1")   # 罗德里：三场出场史，初始体能 65
    assert aid, "阈值 80 下罗德里应有轮休建议"
    out = kb.execute(aid)
    assert out["ok"] is True, out
    assert int(kb.state.value(EX.p_dm1, EX.fitness)) == 85   # 65 + 20
    assert not any(a["type"] == "RestPlayer"
                   and any(t["id"] == "p_dm1" for t in a["targets"])
                   for a in kb.list_actions())
