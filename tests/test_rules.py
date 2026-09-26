"""业务规则层测试：VIP 分类规则（含边界卡位）。"""
from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_vip_rules

EXPECTED_VIP = {EX.c_zhangwei, EX.c_wanglei, EX.c_zhouyu, EX.c_lina, EX.c_chenjing}


def test_vip_default_thresholds():
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    vips = set(out.subjects(None, EX.VIPCustomer))
    assert vips == EXPECTED_VIP


def test_vip_boundary_exact_5000_excluded():
    """孙丽年消费恰好 5000（默认阈值 >5000）不应是 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_sunli, None, EX.VIPCustomer) not in out


def test_vip_silver_needs_three_orders():
    """赵敏银卡只有 2 单，不满足 ≥3；陈静恰好 3 单满足。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_zhaomin, None, EX.VIPCustomer) not in out
    assert (EX.c_chenjing, None, EX.VIPCustomer) in out


def test_vip_gold_alone_insufficient():
    """罗浩是金卡但年消费低——金卡本身不构成 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_luohei, None, EX.VIPCustomer) not in out


def test_vip_custom_thresholds():
    """阈值降到 1500 后罗浩（1500 不大于 1500）仍不是，孙丽（5000）成为 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g, spend_threshold=1500)
    vips = set(out.subjects(None, EX.VIPCustomer))
    assert EX.c_sunli in vips
    assert EX.c_luohei not in vips
