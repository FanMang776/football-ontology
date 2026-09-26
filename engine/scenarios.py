"""决策场景编排：图谱查询 → 结构化结果 → 每一步传导的自然语言解释。"""
from rdflib import RDF, RDFS

from engine import queries as q
from engine.namespaces import EX

REL_ZH = {"substituteFor": "替代品", "compatibleWith": "兼容配件", "sameSeries": "同系列"}


def _label(g, node) -> str:
    v = g.value(node, RDFS.label)
    return str(v) if v else str(node).split("#")[-1]


def _id(node) -> str:
    return str(node).split("#")[-1]


def _rows(g, query, bindings=None):
    return list(g.query(query, initBindings=bindings or {}))


def risk_chain(kb, supplier) -> dict:
    """延迟供应商的风险视图：每一步传导都标注它依赖的公理/规则。"""
    g = kb.material

    products = [{"id": _id(r.p), "label": str(r.label)}
                for r in _rows(g, q.PRODUCTS_OF_SUPPLIER, {"sup": supplier})]
    product_nodes = [EX[p["id"]] for p in products]

    bundles, seen = [], set()
    for pnode in product_nodes:
        for r in _rows(g, q.BUNDLES_OF_PRODUCT, {"p": pnode}):
            if r.b not in seen:
                seen.add(r.b)
                bundles.append({"id": _id(r.b), "label": str(r.label)})

    promos, seen = [], set()
    for pnode in product_nodes:
        for r in _rows(g, q.PROMOS_TOUCHING_PRODUCT, {"p": pnode}):
            if r.promo not in seen:
                seen.add(r.promo)
                promos.append({"id": _id(r.promo), "label": str(r.label)})

    pending, vip_affected, seen_c = [], [], set()
    vip_now = set(kb.vip_out.subjects(RDF.type, EX.VIPCustomer))
    for r in _rows(g, q.PENDING_ORDERS_WITH_PRODUCT):
        hits = [x.product for x in _rows(g, q.LINES_OF_ORDER, {"o": r.o})
                if x.product in product_nodes]
        if not hits:
            continue
        pending.append({"id": _id(r.o), "customer": _id(r.cust),
                        "customer_label": str(r.custLabel),
                        "products": [_id(h) for h in hits]})
        if r.cust in vip_now and r.cust not in seen_c:
            seen_c.add(r.cust)
            vip_affected.append({"id": _id(r.cust), "label": str(r.custLabel)})

    chain = [
        {"step": 1, "count": len(products),
         "explanation": "suppliedBy 关系直接反查：哪些商品由该供应商供应"},
        {"step": 2, "count": len(bundles),
         "explanation": "isComponentOf 逆属性 + hasPart 传递推理：套装在任意嵌套深度受影响"},
        {"step": 3, "count": len(promos),
         "explanation": "促销覆盖面：直接推广商品、推广其套装、或推广其品类（品类归属来自子类推理）"},
        {"step": 4, "count": len(pending),
         "explanation": "订单→明细→商品路径：包含受影响商品的待发货订单"},
        {"step": 5, "count": len(vip_affected),
         "explanation": "叠加规则层推断的 VIP 客户：需要优先安抚的高价值客户"},
    ]
    return {"products": products, "bundles": bundles, "promotions": promos,
            "pending_orders": pending, "vip_customers": vip_affected,
            "chain": chain}


def vip_report(kb, spend: int, min_orders: int) -> dict:
    g = kb.material
    order_counts = {r.c: int(r.n) for r in g.query(q.ORDER_COUNTS)}
    vips = []
    for c in sorted(set(kb.vip_out.subjects(RDF.type, EX.VIPCustomer)), key=str):
        reasons = []
        s = g.value(c, EX.annualSpend)
        lvl = g.value(c, EX.membershipLevel)
        if s is not None and int(s) > spend:
            reasons.append(f"年消费 {int(s)} > 阈值 {spend}")
        if str(lvl) == "silver" and order_counts.get(c, 0) >= min_orders:
            reasons.append(f"银卡会员且订单数 {order_counts.get(c, 0)} ≥ {min_orders}")
        vips.append({"id": _id(c), "label": _label(g, c),
                     "reason": "；".join(reasons) or "满足规则"})
    return {"vips": vips}


def recommend_report(kb, product) -> dict:
    g = kb.material
    naive = [{"id": _id(r.other), "label": str(r.label)}
             for r in _rows(g, q.NAIVE_SAME_CATEGORY, {"p": product})]
    semantic = [{"id": _id(r.other), "label": str(r.label), "relation": str(r.rel),
                 "relation_label": REL_ZH[str(r.rel)]}
                for r in _rows(g, q.SEMANTIC_RELATIONS, {"p": product})]
    return {"product": {"id": _id(product), "label": _label(g, product)},
            "naive": naive, "semantic": semantic}
