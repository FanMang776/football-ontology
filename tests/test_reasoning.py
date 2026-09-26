"""验证 OWL-RL 推理：子类传递、属性传递、对称性、逆属性。"""
from rdflib import RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX


def kb():
    return materialize(load_declared())


def test_subclass_chain_inferred():
    """蓝牙耳机 BT-01 挂在 cat_headphone 上，应推断出属于全部祖先品类。"""
    g = kb()
    for cat in (EX.cat_headphone, EX.cat_digital_acc, EX.cat_electronics, EX.Product):
        assert (EX.p_bt01, RDF.type, cat) in g


def test_transitive_has_part():
    """b_ultimate hasPart b_music，b_music hasPart p_bt01 → 推断 b_ultimate hasPart p_bt01。"""
    g = kb()
    assert (EX.b_ultimate, EX.hasPart, EX.p_bt01) in g
    assert (EX.b_ultimate, EX.hasPart, EX.p_amp) in g


def test_inverse_is_component_of():
    """hasPart 的逆属性 isComponentOf 应双向物化。"""
    g = kb()
    assert (EX.p_bt01, EX.isComponentOf, EX.b_music) in g
    assert (EX.p_bt01, EX.isComponentOf, EX.b_ultimate) in g


def test_symmetric_substitute():
    """只声明 p_bt01 substituteFor p_x2，应推断出反向。"""
    g = kb()
    assert (EX.p_bt01, EX.substituteFor, EX.p_x2) in g          # 声明的
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) in g          # 推断的


def test_declared_vs_inferred_split():
    """p_x2 substituteFor p_bt01 在原始图中不存在，在物化图中存在。"""
    declared = load_declared()
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) not in declared
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) in kb()
