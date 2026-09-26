"""场景 SPARQL 查询：每个决策问题就是一条图谱查询。

绑定变量 ?sup / ?p / ?o 通过 initBindings 传入。
"""
PREFIX = ("PREFIX ex: <http://example.org/ecom#> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX owl: <http://www.w3.org/2002/07/owl#>")

PRODUCTS_OF_SUPPLIER = PREFIX + """
SELECT ?p ?label WHERE {
    ?p ex:suppliedBy ?sup ; rdfs:label ?label .
} ORDER BY ?p
"""

# ?p 的所有祖先套装——isComponentOf 的传递 + 逆属性物化结果，一条查询直达任意深度
BUNDLES_OF_PRODUCT = PREFIX + """
SELECT ?b ?label WHERE {
    ?p ex:isComponentOf ?b ; rdfs:label ?label .
} ORDER BY ?b
"""

PROMOS_TOUCHING_PRODUCT = PREFIX + """
SELECT DISTINCT ?promo ?label WHERE {
    ?promo rdfs:label ?label ; ex:status "active" .
    { ?promo ex:promotes ?p . }                                    # 直接推广该商品
    UNION { ?promo ex:promotes ?b . ?p ex:isComponentOf ?b . }     # 推广其所属套装
    UNION { ?promo ex:promotes ?c . ?p a ?c . ?c a owl:Class . }   # 推广其所属品类
}
"""

PENDING_ORDERS_WITH_PRODUCT = PREFIX + """
SELECT DISTINCT ?o ?cust ?custLabel WHERE {
    ?o ex:orderStatus "pending" ; ex:placedBy ?cust .
    ?cust rdfs:label ?custLabel .
}
"""

LINES_OF_ORDER = PREFIX + """
SELECT ?product WHERE { ?o ex:hasLine ?line . ?line ex:lineProduct ?product . }
"""

ORDER_COUNTS = PREFIX + """
SELECT ?c (COUNT(DISTINCT ?o) AS ?n) WHERE { ?o ex:placedBy ?c . } GROUP BY ?c
"""

# 朴素推荐：同品类其他商品。品类成员关系（?other a ?cat）本身是子类推理的结果；
# 用 cat_ 前缀限定排除 Product/Bundle 这类结构性父类。
# 关键一步：物化后 ?p 会同时带上全部祖先品类（cat_headphone → cat_digital_acc →
# cat_electronics），若不限定"最具体品类"，"同品类"会泄漏成整棵子类树。
# NOT EXISTS 要求该品类下没有 ?p 也属于的更细子类，从而只命中叶子品类；
# 注意排除 ?sub = ?cat——OWL-RL 会物化自反的 subClassOf 边，不排除则全查询落空。
NAIVE_SAME_CATEGORY = PREFIX + """
SELECT DISTINCT ?other ?label WHERE {
    ?p a ?cat . ?other a ?cat ; rdfs:label ?label .
    ?cat a owl:Class .
    FILTER(STRSTARTS(STR(?cat), "http://example.org/ecom#cat_"))
    FILTER(?other != ?p)
    FILTER NOT EXISTS {
        ?sub rdfs:subClassOf ?cat . ?p a ?sub .
        FILTER(?sub != ?cat)
    }
} ORDER BY ?other
"""

# 语义推荐：三条语义边，双向匹配（对称属性的反向是推理出来的，一样有效）
SEMANTIC_RELATIONS = PREFIX + """
SELECT DISTINCT ?other ?rel ?label WHERE {
    { ?p ex:substituteFor ?other . BIND("substituteFor" AS ?rel) }
    UNION { ?other ex:substituteFor ?p . BIND("substituteFor" AS ?rel) }
    UNION { ?p ex:compatibleWith ?other . BIND("compatibleWith" AS ?rel) }
    UNION { ?other ex:compatibleWith ?p . BIND("compatibleWith" AS ?rel) }
    UNION { ?p ex:sameSeries ?other . BIND("sameSeries" AS ?rel) }
    UNION { ?other ex:sameSeries ?p . BIND("sameSeries" AS ?rel) }
    ?other rdfs:label ?label .
    FILTER(?other != ?p)
} ORDER BY ?other
"""
