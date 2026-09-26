"""知识库引擎：声明层 + 撤销层 + 效果层 + 推理 + 规则，全部内存态。

分层（自底向上）：
  declared    schema.ttl + data.ttl（不可变）
  retractions 运行时撤销的声明事实（如把活动状态从 active 撤下）——撤销也是写回
  effects     运行时新增的事实（供应商延迟、通知标记、补货标记……）
  material    (declared − retractions + effects) 过 OWL-RL 闭包
  rule_out    VIP 分类规则 + 动作规则的产出（每次刷新重算，是推论不是数据）
"""
import threading

from rdflib import Graph, Literal

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_action_rules, apply_vip_rules
from engine.scenarios import _id, _label, risk_chain, vip_report, recommend_report


class KnowledgeBase:
    def __init__(self):
        self.declared = load_declared()
        self.effects = Graph()
        self.retractions = Graph()
        self.vip_params = {"spend": 5000, "min_orders": 3}
        # FastAPI 会把同步端点放进线程池并发调用，而 rdflib 图不支持并发读写；
        # 全部可变入口（含 refresh）经此锁串行化。用 RLock：execute_all 内部会
        # 再次调用同样加锁的 execute。
        self._lock = threading.RLock()
        self.refresh()

    # ---------- 基础 ----------
    def reset(self):
        with self._lock:
            self.effects = Graph()
            self.retractions = Graph()
            self.vip_params = {"spend": 5000, "min_orders": 3}
            self.refresh()

    def refresh(self):
        merged = Graph()
        for t in self.declared:
            if t not in self.retractions:
                merged.add(t)
        for t in self.effects:
            merged.add(t)
        self.material = materialize(merged)
        # apply_vip_rules 的阈值形参名为 spend_threshold（非 spend），此处显式映射
        self.vip_out = apply_vip_rules(
            self.material, spend_threshold=self.vip_params["spend"],
            min_orders=self.vip_params["min_orders"])
        rule_input = self.material + self.vip_out
        self.actions, self.action_reasons = apply_action_rules(rule_input)

    # ---------- 场景 1：供应风险传导 ----------
    def supplier_risk(self, supplier, delayed: bool) -> dict:
        with self._lock:
            triple = (supplier, EX.status, Literal("delayed"))
            if delayed:
                self.effects.add(triple)
            else:
                self.effects.remove(triple)
            self.refresh()
            return risk_chain(self, supplier) if delayed else self._empty_risk()

    @staticmethod
    def _empty_risk() -> dict:
        return {"products": [], "bundles": [], "promotions": [],
                "pending_orders": [], "vip_customers": [], "chain": []}

    def risk_view(self) -> dict:
        """当前延迟供应商的风险视图（供执行后查看风险仍在、动作已处置）。

        若同时有多个延迟供应商，展示字典序第一个（sorted 后取首）。
        """
        delayed = list(self.material.subjects(EX.status, Literal("delayed")))
        if not delayed:
            return self._empty_risk()
        return risk_chain(self, sorted(delayed, key=str)[0])

    # ---------- 场景 2：VIP 分类 ----------
    def vip_classification(self, spend: int, min_orders: int) -> dict:
        with self._lock:
            self.vip_params = {"spend": int(spend), "min_orders": int(min_orders)}
            self.refresh()
            return vip_report(self, int(spend), int(min_orders))

    # ---------- 场景 3：语义推荐 ----------
    def recommend(self, product) -> dict:
        return recommend_report(self, product)

    # ---------- 决策执行闭环 ----------
    def list_actions(self) -> list:
        out = []
        for act, info in sorted(self.action_reasons.items(), key=lambda kv: str(kv[0])):
            out.append({"id": str(act).split("#")[-1], "type": info["type"],
                        "targets": [{"id": _id(t), "label": _label(self.material, t)}
                                     for t in info["targets"]],
                        "reason": info["reason"]})
        return out

    def execute(self, action_id: str) -> dict:
        with self._lock:
            from engine.actions import execute as run
            return run(self, action_id)

    def execute_all(self) -> dict:
        with self._lock:
            executed = 0
            for act in list(self.action_reasons):
                if self.execute(str(act).split("#")[-1])["ok"]:
                    executed += 1
            return {"executed": executed, "remaining": len(self.list_actions())}
