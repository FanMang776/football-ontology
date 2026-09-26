"""场景级测试：声科电子延迟的完整传导结果必须与手工核对一致。"""
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

kb = KnowledgeBase()   # 模块级共享一个实例，测试间用 reset 隔离


def setup_function(_):
    kb.reset()


def test_supplier_risk_full_chain():
    result = kb.supplier_risk(EX.sup_shengke, delayed=True)
    assert [p["id"] for p in result["products"]] == ["p_bt01", "p_bt02", "p_hub"]
    assert {b["id"] for b in result["bundles"]} == {"b_music", "b_ultimate"}
    assert {x["id"] for x in result["promotions"]} == {"promo_618", "promo_music"}
    assert {o["id"] for o in result["pending_orders"]} == {"o1", "o3", "o4", "o8", "o14"}
    assert {c["id"] for c in result["vip_customers"]} == {"c_zhangwei", "c_lina", "c_wanglei"}
    # 每一步传导都要有解释
    assert all(step["explanation"] for step in result["chain"])
    assert len(result["chain"]) == 5


def test_supplier_risk_unmark_resolves():
    kb.supplier_risk(EX.sup_shengke, delayed=True)
    result = kb.supplier_risk(EX.sup_shengke, delayed=False)
    assert result["products"] == [] and result["vip_customers"] == []


def test_vip_classification_reasons():
    result = kb.vip_classification(5000, 3)
    ids = {v["id"] for v in result["vips"]}
    assert ids == {"c_zhangwei", "c_wanglei", "c_zhouyu", "c_lina", "c_chenjing"}
    reasons = {v["id"]: v["reason"] for v in result["vips"]}
    assert "5000" in reasons["c_zhangwei"]      # 年消费路径
    assert "3" in reasons["c_chenjing"]         # 银卡订单数路径
    assert "4" in reasons["c_lina"]


def test_recommend_contrast():
    result = kb.recommend(EX.p_bt01)
    naive = {x["id"] for x in result["naive"]}
    semantic = {x["id"] for x in result["semantic"]}
    assert naive == {"p_bt02", "p_x2", "p_buds"}           # 同品类（含推理出的品类成员）
    assert semantic == {"p_x2", "p_bt02", "p_amp", "p_ch65"}
    by_id = {x["id"]: x for x in result["semantic"]}
    assert "替代" in by_id["p_x2"]["relation_label"]
    assert by_id["p_ch65"]["relation"] == "compatibleWith"  # 声明的反向（对称推理）
    assert all(x["relation"] for x in result["semantic"])   # 每条推荐都有语义依据
