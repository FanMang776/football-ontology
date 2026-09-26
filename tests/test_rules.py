"""业务规则层测试：VIP 分类规则（含边界卡位）。"""
from rdflib import RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_vip_rules

EXPECTED_VIP = {EX.c_zhangwei, EX.c_wanglei, EX.c_zhouyu, EX.c_lina, EX.c_chenjing}


def test_vip_default_thresholds():
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    vips = set(out.subjects(RDF.type, EX.VIPCustomer))
    assert vips == EXPECTED_VIP


def test_vip_boundary_exact_5000_excluded():
    """孙丽年消费恰好 5000（默认阈值 >5000）不应是 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_sunli, RDF.type, EX.VIPCustomer) not in out


def test_vip_silver_needs_three_orders():
    """赵敏银卡只有 2 单，不满足 ≥3；陈静恰好 3 单满足。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_zhaomin, RDF.type, EX.VIPCustomer) not in out
    assert (EX.c_chenjing, RDF.type, EX.VIPCustomer) in out


def test_vip_gold_alone_insufficient():
    """罗浩是金卡但年消费低——金卡本身不构成 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_luohei, RDF.type, EX.VIPCustomer) not in out


def test_vip_custom_thresholds():
    """阈值降到 1500 后罗浩（1500 不大于 1500）仍不是，孙丽（5000）成为 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g, spend_threshold=1500)
    vips = set(out.subjects(RDF.type, EX.VIPCustomer))
    assert EX.c_sunli in vips
    assert EX.c_luohei not in vips


def kb_with_delay() -> "Graph":
    """动作规则的完整输入：物化图 + VIP 推断 + 声科电子延迟。"""
    from rdflib import Graph, Literal

    from engine.rules import apply_vip_rules

    g = materialize(load_declared())
    for t in apply_vip_rules(g):
        g.add(t)
    g.add((EX.sup_shengke, EX.status, Literal("delayed")))
    return g


def test_action_rules_expected_nine():
    """声科延迟 → 2 暂停 + 3 通知 + 2 采购 + 2 推荐 = 9 条建议动作。"""
    from engine.rules import apply_action_rules

    actions, reasons = apply_action_rules(kb_with_delay())
    assert len(reasons) == 9  # actions 是三元组图（29 条），动作实例数以 reasons 计
    assert all(v["reason"] for v in reasons.values())


def test_pause_rule_only_active_promos():
    """promo_ultimate 已是 paused、promo_travel 不含声科商品——都不生成暂停建议。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    targets = set(actions.objects(None, EX.hasTarget))
    assert {EX.promo_618, EX.promo_music} <= targets
    assert EX.promo_travel not in targets and EX.promo_ultimate not in targets


def test_notify_only_vip_customers():
    """赵敏有待发货订单 o8 含 p_bt02，但她不是 VIP——通知规则必须排除她。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    notified = set()
    for act in actions.subjects(RDF.type, EX.NotifyCustomer):
        notified |= set(actions.objects(act, EX.hasTarget))
    assert notified == {EX.c_zhangwei, EX.c_lina, EX.c_wanglei}


def test_purchase_order_needs_substitute():
    """p_hub 无替代品 → 无采购动作；p_bt01/p_bt02 各一条。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    subs = set(actions.subjects(RDF.type, EX.CreatePurchaseOrder))
    assert subs == {EX.action_CreatePurchaseOrder_p_bt01, EX.action_CreatePurchaseOrder_p_bt02}


def test_actions_deterministic_ids():
    """动作 URI 由（类型, 目标）派生，重复刷新必须稳定（可执行、可测试）。"""
    from engine.rules import apply_action_rules

    a1, _ = apply_action_rules(kb_with_delay())
    a2, _ = apply_action_rules(kb_with_delay())
    assert set(a1.subjects()) == set(a2.subjects())

