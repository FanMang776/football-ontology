"""知识库引擎：声明层 + 撤销层 + 效果层 + 状态层 + 推理 + 规则，全部内存态。

分层（自底向上）：
  declared    schema.ttl + data.ttl（不可变）
  retractions 运行时撤销的声明事实——撤销也是写回
  effects     运行时新增的事实（伤病、痊愈、动作效果……）
  state       对象运行时的派生状态（fitness 等），每次 dispatch 全量重写，
              是"算出来的"不是"写进去的"——所以不落 declared/effects
  material    (declared − retractions + effects + state) 过 OWL-RL 闭包
  rule_out    动作建议规则的产出（每次刷新重算，是推论不是数据）

全部可变入口经 RLock 串行化（FastAPI 线程池并发 + rdflib 图不支持并发读写）。
"""
import threading

from rdflib import Graph, Literal, RDFS

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_player_rules
from engine.world import World


def _id(n) -> str:
    return str(n).split("#")[-1]


def _label(g, n) -> str:
    v = g.value(n, RDFS.label)
    return str(v) if v else _id(n)


class KnowledgeBase:
    def __init__(self):
        self.declared = load_declared()
        self.effects = Graph()
        self.retractions = Graph()
        self.state = Graph()
        self.params = {"fitness_floor": 60}
        self.tick = 0
        self.audit = []          # Task 4：审计日志
        self.pending = set()     # Task 4：待审批动作
        # FastAPI 会把同步端点放进线程池并发调用，而 rdflib 图不支持并发读写；
        # 全部可变入口（含 refresh）经此锁串行化。用 RLock：execute_all 内部会
        # 再次调用同样加锁的 execute。
        self._lock = threading.RLock()
        self.refresh()
        self.world = World(self)
        self.world.bootstrap()

    # ---------- 基础 ----------
    def reset(self):
        with self._lock:
            self.effects = Graph()
            self.retractions = Graph()
            self.state = Graph()
            self.params = {"fitness_floor": 60}
            self.tick = 0
            self.audit = []
            self.pending = set()
            self.refresh()
            self.world.bootstrap()

    def refresh(self):
        merged = Graph()
        for t in self.declared:
            if t not in self.retractions:
                merged.add(t)
        for t in self.effects:
            merged.add(t)
        for t in self.state:
            merged.add(t)
        self.material = materialize(merged)
        self.actions, self.action_reasons = apply_player_rules(
            self.material, floor=self.params["fitness_floor"])

    def next_step(self) -> int:
        """确定性步进计数器：审计与演示用，不引入 wall-clock。"""
        self.tick += 1
        return self.tick

    # ---------- 对象运行时入口 ----------
    def set_state(self, triples):
        self.state = Graph()
        for t in triples:
            self.state.add(t)

    def set_params(self, fitness_floor: int):
        with self._lock:
            self.params["fitness_floor"] = max(0, min(100, int(fitness_floor)))
            self.refresh()

    def dispatch(self, event) -> dict:
        with self._lock:
            report = self.world.dispatch(event)

            def settle_text():
                for step in report["chain"]:
                    if step["stage"] == "settle":
                        return step["text"]
                return report["chain"][0]["text"] if report["chain"] else ""

            self.audit.append({"step": self.next_step(),
                               "action": "-",
                               "type": report["event"]["type"],
                               "target": report["event"]["target"] or "",
                               "result": "event",
                               "detail": settle_text()})
            return report

    def describe(self, object_id: str) -> dict:
        with self._lock:
            return self.world.describe(object_id)

    # ---------- 治理：预览与审计 ----------
    def preview(self, action_id: str) -> dict:
        with self._lock:
            from engine.actions import preview as run
            return run(self, action_id)

    def audit_view(self) -> list:
        with self._lock:
            return sorted(self.audit, key=lambda e: e["step"])

    def roster_view(self) -> dict:
        """报名名单计数：一线队 + 已征调青年队（与征调前置条件同一实现点）。"""
        with self._lock:
            from engine.actions import _roster_count, ROSTER_LIMIT
            return {"count": _roster_count(self), "limit": ROSTER_LIMIT}

    def rules_view(self) -> list:
        """规则手册：阈值代入当前参数。"""
        with self._lock:
            from engine.rule_meta import DEFAULT_PARAMS, render
            return render(DEFAULT_PARAMS | dict(self.params))

    # ---------- 决策执行闭环 ----------
    def list_actions(self) -> list:
        out = []
        for act, info in sorted(self.action_reasons.items(), key=lambda kv: str(kv[0])):
            out.append({"id": _id(act),
                        "type": info["type"],
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
                if self.execute(_id(act))["ok"]:
                    executed += 1
            return {"executed": executed, "remaining": len(self.list_actions())}
