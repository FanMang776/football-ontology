"""足球业务规则层：情况 → 建议动作。

OWL 负责"分类学与结构逻辑"（见 test_reasoning）：位置泛化、青年队归类。
含阈值/计数/聚合的业务规则放这里，分两类：
  状态建议规则（本文件）：过度使用 → 轮休；阵容缺口 → 征调；重伤 → 治疗。
  （动作执行治理在 engine/actions.py：前置条件、审批、否决。）

防重复建议的机制：动作实例的确定性 ID 由（类型, 目标）派生；
治理否决时写 (动作URI, ex:vetoed, true) 进 effects 层，
本层每条规则的匹配里都会检查该动作的 veto 三元组，否决过就不再建议。
即：建议动作和推理结论一样是推论，每次刷新重算，不落库。
"""
from rdflib import Graph, Literal, RDF, RDFS, URIRef
from rdflib.plugins.sparql import prepareQuery

from engine.namespaces import EX

PREFIX = ("PREFIX ex: <http://example.org/football#> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX owl: <http://www.w3.org/2002/07/owl#>")

# ---------- 过度使用 → 轮休 ----------
# 体能低于阈值且最近参与 ≥3 场高负荷（任一分钟数 ≥ 60 即视为该场高负荷，
# minutesPlayed 是球员上的多值属性，见 schema.ttl 的教学简化注释）比赛。
# 注意 FILTER(?f < floor)：恰等于阈值不算过度使用（严格小于）。
Q_OVERUSE = PREFIX + """
SELECT DISTINCT ?p WHERE {
    ?p a ex:Player ; ex:fitness ?f .
    FILTER(?f < %(floor)d)
    { SELECT ?p2 (COUNT(DISTINCT ?m) AS ?n) WHERE {
          ?p2 ex:participatesIn ?m .
          FILTER EXISTS { ?p2 ex:minutesPlayed ?min . FILTER(?min >= 60) }
      } GROUP BY ?p2 HAVING (COUNT(DISTINCT ?m) >= 3) }
    FILTER(?p = ?p2)
}
"""

# ---------- 重伤 → 治疗 ----------
Q_TREATMENT = PREFIX + """
SELECT DISTINCT ?p ?rec ?w WHERE {
    ?p a ex:Player ; ex:injuredWith ?rec .
    ?rec ex:weeksOut ?w .
    FILTER(?w >= 3)
    FILTER NOT EXISTS { ?p ex:treated true }
}
"""

_LEAF_POSITIONS = (EX.Goalkeeper, EX.CentreBack, EX.Fullback,
                   EX.DefensiveMidfielder, EX.AttackingMidfielder,
                   EX.Winger, EX.Striker)

# 每个位置类单独跑一次计数查询：位置是类，成员靠类型闭包，
# 聚合成一条 SPARQL 需嵌套分组，教学 demo 里逐位置直查更可读。
Q_AVAILABLE = PREFIX + """
SELECT (COUNT(DISTINCT ?q) AS ?n) WHERE {
    ?q a %(pos)s ; ex:playsFor ?club .
    FILTER NOT EXISTS { ?q ex:injuredWith ?rec . ?rec ex:weeksOut ?w . FILTER(?w > 0) }
}
"""

Q_YOUTH_OF = PREFIX + """
SELECT DISTINCT ?y WHERE {
    ?y a ex:YouthPlayer, %(pos)s ; ex:squadOf ?club .
    FILTER NOT EXISTS { ?y ex:calledUp true }
}
"""


def _action_id(kind: str, *parts) -> URIRef:
    """由（类型, 目标）派生确定性 URI，如 ex:action_RestPlayer_p_am1。"""
    names = "_".join([kind] + [str(p).split("#")[-1] for p in parts])
    return URIRef(f"http://example.org/football#action_{names}")


def _label_of(g: Graph, n) -> str:
    v = g.value(n, RDFS.label)
    return str(v) if v else str(n).split("#")[-1]


def _vetoed(g: Graph, act: URIRef) -> bool:
    return (act, EX.vetoed, Literal(True)) in g


def apply_player_rules(g: Graph, floor: int = 60):
    """返回 (动作三元组图, {动作URI: {"type", "targets", "reason"}})。

    动作实例和推理结论一样是派生物：每次刷新重算，不落库。
    g 必须是已物化且已写入 fitness 状态三元组的图（位置成员、VIP 式
    泛化都依赖类型闭包）。
    """
    actions = Graph()
    reasons: dict = {}

    def put(act, kind, targets, reason):
        if act in reasons or _vetoed(g, act):
            return
        actions.add((act, RDF.type, kind))
        for t in targets:
            actions.add((act, EX.hasTarget, t))
        actions.add((act, EX.hasReason, Literal(reason, lang="zh")))
        reasons[act] = {"type": str(kind).split("#")[-1],
                        "targets": list(targets), "reason": reason}

    # 过度使用 → 轮休
    for row in sorted(g.query(Q_OVERUSE % {"floor": int(floor)}), key=lambda r: str(r.p)):
        p = row.p
        put(_action_id("RestPlayer", p), EX.RestPlayer, [p],
            f"「{_label_of(g, p)}」体能 {int(g.value(p, EX.fitness))}（低于阈值 {int(floor)}）"
            f"且近期连踢 ≥3 场高强度比赛，建议轮休恢复。")

    # 阵容缺口 → 征调青年队
    for pos in _LEAF_POSITIONS:
        n = int(list(g.query(Q_AVAILABLE % {"pos": pos.n3()}))[0][0])
        if n >= 2:
            continue
        pos_label = _label_of(g, pos)
        for row in sorted(g.query(Q_YOUTH_OF % {"pos": pos.n3()}), key=lambda r: str(r.y)):
            y = row.y
            put(_action_id("CallUpYouth", pos, y), EX.CallUpYouth, [y],
                f"「{pos_label}」位置可用一线队球员仅 {n} 人（< 2），"
                f"建议征调青年队「{_label_of(g, y)}」"
                f"——青年队球员同为该位置类成员（YouthPlayer ⊑ Player 与位置子类推理）。")

    # 重伤 → 治疗
    for row in sorted(g.query(Q_TREATMENT), key=lambda r: str(r.p)):
        p, w = row.p, int(row.w)
        put(_action_id("StartTreatment", p), EX.StartTreatment, [p],
            f"「{_label_of(g, p)}」伤停 {w} 周（≥ 3 周），建议启动治疗。")

    return actions, reasons
