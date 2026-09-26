"""本体加载与 OWL-RL 物化推理。

核心心智模型：图谱有两层——
  声明的三元组 (declared)：schema.ttl + data.ttl 里白纸黑字写的
  推断的三元组 (inferred)：推理机物化出来的，永远不落库、随事实即时重算
"""
from pathlib import Path

from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Graph

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "ontology" / "schema.ttl"
DATA = ROOT / "ontology" / "data.ttl"


def load_declared() -> Graph:
    """加载 TBox + ABox，返回仅含声明三元组的图。TTL 语法错误在此暴露。"""
    g = Graph()
    g.parse(SCHEMA, format="turtle")
    g.parse(DATA, format="turtle")
    return g


def materialize(g: Graph) -> Graph:
    """在副本上运行 OWL-RL 推理闭包，返回物化后的图。

    axiomatic_triples=False / datatype_axioms=False：关掉 OWL 词汇表的公理三元组，
    否则"推断三元组"里会混入上千条和业务无关的公理，无法教学演示。
    """
    m = Graph()
    for t in g:
        m.add(t)
    DeductiveClosure(OWLRL_Semantics, rdfs_closure=True,
                     axiomatic_triples=False, datatype_axioms=False).expand(m)
    return m
