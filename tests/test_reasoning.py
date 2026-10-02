"""验证 OWL-RL 推理：位置子类泛化、YouthPlayer 归类。"""
from rdflib import RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX


def kb():
    return materialize(load_declared())


def test_position_generalization_inferred():
    """声明最细位置，祖先位置成员关系由推理补全。"""
    g = kb()
    assert (EX.p_am1, RDF.type, EX.AttackingMidfielder) in g   # 声明
    assert (EX.p_am1, RDF.type, EX.Position) in g              # 推断


def test_youth_player_is_player_and_position():
    g = kb()
    assert (EX.p_yam1, RDF.type, EX.Player) in g               # YouthPlayer ⊑ Player
    assert (EX.p_yam1, RDF.type, EX.AttackingMidfielder) in g  # 声明


def test_injury_record_linked():
    g = kb()
    assert (EX.p_am2, EX.injuredWith, EX.inj_am2) in g
    assert (EX.inj_am2, EX.weeksOut, None) in g


def test_declared_scale():
    """青年队只有 YouthPlayer 类型，Player 计数须在物化图上（闭包补全后）。"""
    g = kb()
    players = list(g.subjects(RDF.type, EX.Player))
    assert len(players) >= 20   # 14 一线队 + 6 青年队
