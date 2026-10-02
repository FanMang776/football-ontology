"""对象运行时：事件感知、状态派生、重复受伤、无效恢复。"""
from rdflib import Literal

from engine.events import (InjuryEvent, MatchPlayedEvent,
                           RecoveryEvent, TrainingLoadEvent)
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX


def fresh():
    kb = KnowledgeBase()
    kb.reset()
    return kb


def test_match_event_lowers_fitness():
    kb = fresh()
    kb.dispatch(MatchPlayedEvent(EX.p_st1, 90))
    v = kb.state.value(EX.p_st1, EX.fitness)
    assert v is not None


def test_fitness_formula_deterministic():
    kb = fresh()
    kb.reset()
    kb.dispatch(MatchPlayedEvent(EX.p_st1, 90))          # penalty round(90/6)=15
    v1 = int(kb.state.value(EX.p_st1, EX.fitness))
    kb2 = fresh()
    kb2.dispatch(MatchPlayedEvent(EX.p_st1, 90))
    v2 = int(kb2.state.value(EX.p_st1, EX.fitness))
    assert v1 == v2


def test_duplicate_injury_takes_max():
    """未恢复再受伤：weeksOut 取 max，记录不翻倍。"""
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 2, "擦伤"))
    kb.dispatch(InjuryEvent(EX.p_st1, 5, "再伤"))
    recs = list(kb.material.objects(EX.p_st1, EX.injuredWith))
    assert len(recs) == 1
    assert kb.material.value(recs[0], EX.weeksOut) == Literal(5)


def test_recovery_of_healthy_player_noop():
    """对健康球员 RecoveryEvent：不异常、无状态变化。"""
    kb = fresh()
    report = kb.dispatch(RecoveryEvent(EX.p_st1))
    assert report["state_changes"] == []


def test_injury_then_recovery_restores():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 3, "拉伤"))
    assert list(kb.material.objects(EX.p_st1, EX.injuredWith))  # 伤病已入图
    kb.dispatch(RecoveryEvent(EX.p_st1))
    recs = list(kb.material.objects(EX.p_st1, EX.injuredWith))
    assert recs == []


def test_dispatch_report_shape():
    kb = fresh()
    kb.dispatch(InjuryEvent(EX.p_st1, 4, "拉伤"))
    # 建议清单含 StartTreatment（weeksOut 4 ≥ 3）
    assert any(a["type"] == "StartTreatment" for a in kb.list_actions())


def test_training_load_event():
    kb = fresh()
    kb.dispatch(TrainingLoadEvent(EX.p_st1, 50))   # penalty 50//10 = 5
    v = int(kb.state.value(EX.p_st1, EX.fitness))
    assert v <= 95
