"""业务规则层：SPARQL CONSTRUCT 产出新的三元组。

OWL 负责"分类学与结构逻辑"（见 test_reasoning）；含算术/聚合的业务规则放这里。
规则分两类：分类规则（本文件上半部分）与动作规则（后续任务追加到下半部分）。
"""
from rdflib import Graph

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

# ---------- 动作规则（后续任务追加） ----------
