"""执行器测试：建议动作 → 校验 → 写回 → 再推理 → 清单消解。"""
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

kb = KnowledgeBase()


def setup_function(_):
    kb.reset()
    kb.supplier_risk(EX.sup_shengke, delayed=True)


def test_actions_listed_with_reasons():
    actions = kb.list_actions()
    assert len(actions) == 9
    assert all(a["reason"] for a in actions)
    types = {a["type"] for a in actions}
    assert types == {"PausePromotion", "NotifyCustomer",
                     "CreatePurchaseOrder", "PromoteSubstitute"}


def test_execute_notify_then_list_shrinks():
    act = next(a for a in kb.list_actions() if a["type"] == "NotifyCustomer")
    result = kb.execute(act["id"])
    assert result["ok"]
    # 该客户已通知 → 规则里 FILTER NOT EXISTS 生效，建议清单少一条
    assert len(kb.list_actions()) == 8


def test_execute_pause_promotion_removes_it():
    act = next(a for a in kb.list_actions() if a["id"] == "action_PausePromotion_promo_618")
    result = kb.execute(act["id"])
    assert result["ok"]
    ids = {a["id"] for a in kb.list_actions()}
    assert act["id"] not in ids
    # 效果已写回：活动状态变为 paused（声明层的 active 已被撤销）
    from rdflib import Literal
    assert (EX.promo_618, EX.status, Literal("paused")) in kb.material
    assert (EX.promo_618, EX.status, Literal("active")) not in kb.material


def test_execute_all_clears_everything():
    result = kb.execute_all()
    assert result["executed"] == 9
    assert result["remaining"] == 0
    assert kb.list_actions() == []
    # 风险仍在（供应商仍延迟），但建议动作已全部处置
    snap = kb.risk_view()
    assert len(snap["vip_customers"]) == 3


def test_execute_unknown_action_rejected():
    result = kb.execute("action_Nope_nope")
    assert not result["ok"]


def test_reset_restores():
    kb.execute_all()
    kb.reset()
    assert kb.list_actions() == []
