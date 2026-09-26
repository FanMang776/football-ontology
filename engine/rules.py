"""业务规则层：SPARQL CONSTRUCT 产出新的三元组。

OWL 负责"分类学与结构逻辑"（见 test_reasoning）；含算术/聚合的业务规则放这里。
规则分两类：分类规则（本文件上半部分）与动作规则（后续任务追加到下半部分）。
"""
from rdflib import Graph, Literal, RDF, RDFS, URIRef
from rdflib.plugins.sparql import prepareQuery

from engine.namespaces import EX

PREFIX = ("PREFIX ex: <http://example.org/ecom#> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX owl: <http://www.w3.org/2002/07/owl#>")

# ---------- 分类规则 ----------
# 注意：模板用 % 格式化注入阈值，规则 SPARQL 中如出现字面量 % 必须写成 %%，否则格式化时报 ValueError。

VIP_SPEND = PREFIX + """
CONSTRUCT { ?c a ex:VIPCustomer . }
WHERE {
    ?c a ex:Customer ; ex:annualSpend ?s .
    FILTER(?s > %(spend)d)
}
"""

VIP_SILVER = PREFIX + """
CONSTRUCT { ?c a ex:VIPCustomer . }
WHERE {
    { SELECT ?c (COUNT(DISTINCT ?o) AS ?n)
      WHERE { ?o ex:placedBy ?c . } GROUP BY ?c }
    ?c ex:membershipLevel "silver" .
    FILTER(?n >= %(min_orders)d)
}
"""


def apply_vip_rules(g: Graph, spend_threshold: int = 5000,
                    min_orders: int = 3) -> Graph:
    """返回仅包含推断出的 VIPCustomer 类型三元组的图。

    契约：返回值只含新推断的三元组，不包含输入图 g；
    调用方需自行将 g 与返回值合并后再做后续查询。
    """
    spend_threshold = int(spend_threshold)
    min_orders = int(min_orders)
    out = Graph()
    for tmpl in (VIP_SPEND, VIP_SILVER):
        res = g.query(tmpl % {"spend": spend_threshold, "min_orders": min_orders})
        for t in res:
            out.add(t)
    return out

# ---------- 动作规则（情况 → 建议动作）----------
# 每条查询末尾的 FILTER NOT EXISTS 是"建议不重复"的关键：
# 执行器把动作效果写回后（status=paused / notified=true / …），
# 条件不再成立，动作自然从建议清单消失——建议动作也是推论，不落库。
# 动作规则用 SELECT 匹配情况，动作三元组、确定性 ID 与解释文本在 Python 侧组装。

Q_PAUSE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?promo WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?promo a ex:Promotion ; ex:status "active" .
    { ?promo ex:promotes ?p . }
    UNION { ?promo ex:promotes ?b . ?p ex:isComponentOf ?b . }
    UNION { ?promo ex:promotes ?c . ?p a ?c . ?c a owl:Class . }
}
""")

Q_NOTIFY = prepareQuery(PREFIX + """
SELECT DISTINCT ?cust WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?o ex:hasLine ?l . ?l ex:lineProduct ?p .
    ?o ex:orderStatus "pending" ; ex:placedBy ?cust .
    ?cust a ex:VIPCustomer .
    FILTER NOT EXISTS { ?cust ex:notified true }
}
""")

Q_PURCHASE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?p2 ?s2 WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?p2 ex:substituteFor ?p ; ex:suppliedBy ?s2 .
    FILTER NOT EXISTS { ?p ex:restockRequested true }
}
""")

Q_SUBSTITUTE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?p2 WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?p2 ex:substituteFor ?p .
    ?p2 ex:stock ?s . FILTER(?s > 0)
    FILTER NOT EXISTS { ?p2 ex:promoBoosted true }
}
""")


def _action_id(kind: str, *parts) -> URIRef:
    """由（类型, 目标）派生确定性 URI，如 ex:action_NotifyCustomer_c_lina。"""
    names = "_".join([kind] + [str(p).split("#")[-1] for p in parts])
    return URIRef(f"http://example.org/ecom#action_{names}")


def apply_action_rules(g: Graph):
    """返回 (动作三元组图, {动作URI: {"type", "targets", "reason"}})。

    动作实例和推理结论一样是派生物：每次刷新重算，不落库。
    注意：g 必须是已物化且已叠加 VIP 推断的图（Q_NOTIFY 依赖 VIPCustomer 类型）。
    """
    actions = Graph()
    reasons: dict = {}

    def label_of(n) -> str:
        v = g.value(n, RDFS.label)
        return str(v) if v else str(n).split("#")[-1]

    def put(act, kind, targets, reason, extra=()):
        if act in reasons:  # 同一动作命中多行情况（如一个活动覆盖多个延迟商品）时只记一次
            return
        actions.add((act, RDF.type, kind))
        for t in targets:
            actions.add((act, EX.hasTarget, t))
        for p, o in extra:
            actions.add((act, p, o))
        actions.add((act, EX.hasReason, Literal(reason, lang="zh")))
        reasons[act] = {"type": str(kind).split("#")[-1],
                        "targets": list(targets), "reason": reason}

    # 两遍处理：先按活动聚合全部受影响商品，再逐活动生成一条建议。
    # 覆盖同一活动的商品可能有多个（p_bt01/p_bt02/p_hub 都被 promo_618 覆盖），
    # 若按行直接生成，解释文本取决于 SPARQL 返回顺序——跨进程不确定，故必须聚合。
    covered: dict = {}
    for row in g.query(Q_PAUSE):
        covered.setdefault(row.promo, []).append(label_of(row.p))
    # rdflib 的行顺序受 URIRef 哈希随机化影响，跨进程不稳定；
    # 商品名与活动顺序都排序后，解释文本与 reasons 序列化才逐字节确定。
    for promo in sorted(covered, key=str):
        products = sorted(covered[promo])
        put(_action_id("PausePromotion", promo), EX.PausePromotion, [promo],
            f"活动「{label_of(promo)}」覆盖了延迟供应商供应的「{'、'.join(products)}」"
            f"（通过直接推广、推广其所属套装、或推广其所属品类匹配），建议先暂停。")

    for row in sorted(g.query(Q_NOTIFY), key=lambda r: str(r.cust)):
        cust = row.cust
        put(_action_id("NotifyCustomer", cust), EX.NotifyCustomer, [cust],
            f"VIP 客户「{label_of(cust)}」有待发货订单包含延迟供应商的商品，建议主动通知。")

    for row in sorted(g.query(Q_PURCHASE), key=lambda r: str(r.p)):
        p, p2, s2 = row.p, row.p2, row.s2
        put(_action_id("CreatePurchaseOrder", p), EX.CreatePurchaseOrder, [p],
            f"「{label_of(p)}」受供应风险影响，其替代品「{label_of(p2)}」由"
            f"「{label_of(s2)}」供应——采购转向依据 substituteFor 关系。",
            extra=[(EX.hasSupplier, s2)])

    for row in sorted(g.query(Q_SUBSTITUTE), key=lambda r: str(r.p2)):
        p, p2 = row.p, row.p2
        put(_action_id("PromoteSubstitute", p2), EX.PromoteSubstitute, [p2],
            f"「{label_of(p)}」受供应风险影响，推荐位切换到有货的替代品「{label_of(p2)}」。")

    return actions, reasons
