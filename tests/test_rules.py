"""足球动作规则：过度使用轮休、阵容缺口征调、伤停治疗。"""
from rdflib import Literal, RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_player_rules


def g_with_fitness(fitness_map):
    """物化声明图并注入 (player, fitness, value) 状态三元组。"""
    g = materialize(load_declared())
    for p, v in fitness_map.items():
        g.add((EX[p], EX.fitness, Literal(v)))
    return g


def rules(g, floor=60):
    actions, reasons = apply_player_rules(g, floor=floor)
    return reasons


def test_overuse_suggests_rest():
    """p_am1：三场 90/90/85（fitness=56 < 60）→ 建议 RestPlayer。"""
    r = rules(g_with_fitness({"p_am1": 56}))
    assert any(i["type"] == "RestPlayer" for i in r.values())


def test_fitness_equal_to_floor_not_suggested():
    """fitness 恰等于阈值 60：严格小于才建议。"""
    r = rules(g_with_fitness({"p_am1": 60}))
    assert not any(i["type"] == "RestPlayer" for i in r.values())


def test_low_fitness_without_minutes_not_suggested():
    """低体能但出场不足 3 场 → 不建议轮休。"""
    r = rules(g_with_fitness({"p_gk1": 30}))
    assert not any(i["type"] == "RestPlayer"
                   for i in r.values() if EX.p_gk1 in i["targets"])


def test_squad_gap_suggests_callup():
    """AM 可用仅剩 p_am1（p_am2 伤停）→ 对青年队 AM 建议征调。"""
    r = rules(g_with_fitness({"p_am1": 56}))
    callups = [i for i in r.values() if i["type"] == "CallUpYouth"]
    targets = {str(t).split("#")[-1] for i in callups for t in i["targets"]}
    assert targets == {"p_yam1", "p_yam2"}


def test_treatment_suggested_for_long_injury():
    r = rules(g_with_fitness({}))
    treats = [i for i in r.values() if i["type"] == "StartTreatment"]
    targets = {str(t).split("#")[-1] for i in treats for t in i["targets"]}
    assert targets == {"p_am2"}   # weeksOut 4 ≥ 3


def test_vetoed_action_not_suggested():
    """veto 三元组在图中时，同 ID 动作不再出现。"""
    g = g_with_fitness({"p_am1": 56})
    act = EX.action_RestPlayer_p_am1
    g.add((act, EX.vetoed, Literal(True)))
    r = rules(g)
    assert act not in r
