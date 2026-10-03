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


# ---------- 规则手册(rule_meta)契约 ----------

import os

import pytest

from engine.actions import EFFECTS
from engine.rule_meta import RULES, render

ALL_RULE_IDS = {"rest-player", "callup-youth", "start-treatment",
                "roster-limit", "treatment-approval",
                "veto-suppression", "audit-trail"}


def test_rule_handbook_covers_all_action_types():
    """新增动作类型而漏写手册 → 红。"""
    sug = [r for r in RULES if r["category"] == "suggestion"]
    assert len(sug) == len(EFFECTS)
    assert {r["id"] for r in sug} == {"rest-player", "callup-youth", "start-treatment"}


def test_rule_handbook_covers_governance():
    assert len([r for r in RULES if r["category"] == "governance"]) >= 4
    assert {r["id"] for r in RULES} == ALL_RULE_IDS


def test_rule_handbook_chapter_files_exist():
    for r in RULES:
        for ch in r["chapter"]:
            assert os.path.exists(ch), f"{r['id']} 的章节 {ch} 不存在"


def test_render_formats_current_params():
    out = render({"fitness_floor": 90, "roster_limit": 16})
    assert len(out) == 7
    rest = next(r for r in out if r["id"] == "rest-player")
    assert rest["conditions"][0] == {"text": "体能低于阈值 90", "dynamic": True}
    assert rest["conditions"][1] == {"text": "近期高强度出场(任一场 ≥ 60 分钟)至少 3 场",
                                     "dynamic": False}
    limit = next(r for r in out if r["id"] == "roster-limit")
    assert "16" in limit["conditions"][0]["text"]


def test_render_missing_param_raises():
    with pytest.raises(KeyError):
        render({"fitness_floor": 60})   # 缺 roster_limit
