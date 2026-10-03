"""对象运行时：每个本体对象是一个会自己说话的运行时实体。

这是"现代本体"和知识图谱的代码分界线（对照教程第四章的五官隐喻）：
  perceive —— 嘴+鼻：事件进收件箱，对象"知道发生事了"；
  compute  —— 脑：从图谱算自己的派生状态（fitness 公式是全项目唯一定义，
              见下）；
  describe —— 回答四问：是谁 / 现在状态 / 为什么 / 能做什么。

对象是壳，事实仍是三元组：compute 的结果写入 KnowledgeBase 的 state 层，
规则层照常从物化图里消费。对象不缓存状态，每次 dispatch 全量重算。

fitness 公式（计划钉死，禁止改动处）：
  penalty = Σ round(minutes/6)（minutesPlayed 各值） + Σ load//10（trainsIn 各课）
  relief  = 20 × restGiven 标记数
  fitness = max(0, min(100, 100 − penalty + relief))
"""
from rdflib import Literal, RDFS, RDF

from engine.namespaces import EX


def _id(n) -> str:
    return str(n).split("#")[-1]


def _label(g, n) -> str:
    v = g.value(n, RDFS.label)
    return str(v) if v else _id(n)


class BaseObject:
    """所有运行时对象的骨架：收件箱 + 从图谱重算状态。"""
    type = EX.FootballEntity

    def __init__(self, world, iri):
        self.world = world
        self.iri = iri
        self.inbox = []

    def perceive(self, event):
        """嘴+鼻：事件入收件箱。副作用由 World 统一结算，对象只感知。"""
        self.inbox.append(event)

    def compute(self, kb) -> dict:
        """脑：从物化图算自己的派生状态，返回 {状态短名: 值}。"""
        raise NotImplementedError

    def describe(self) -> dict:
        kb = self.world.kb
        label = _label(kb.material, self.iri)
        state = self.compute(kb)
        now, why = self._explain(kb, state)
        can = [{"id": a["id"], "type": a["type"]}
               for a in kb.list_actions()
               if any(t["id"] == _id(self.iri) for t in a["targets"])]
        return {"id": _id(self.iri), "label": label,
                "type": _id(self.type),
                "是谁": f"{label}（{_label(kb.material, self.type)}）",
                "现在状态": now, "为什么": why, "能做什么": can}

    def _explain(self, kb, state):
        """(现在状态, 为什么) 两栏文案，子类各自表述。"""
        return [], []


class PlayerObject(BaseObject):
    type = EX.Player

    def compute(self, kb):
        g = kb.material
        penalty = sum(round(int(v) / 6)
                      for v in g.objects(self.iri, EX.minutesPlayed))
        penalty += sum(int(v) // 10
                       for s in g.objects(self.iri, EX.trainsIn)
                       for v in g.objects(s, EX.load))
        relief = 20 * sum(1 for v in g.objects(self.iri, EX.restGiven)
                          if bool(v))
        fitness = max(0, min(100, 100 - penalty + relief))
        return {"fitness": fitness}

    def _explain(self, kb, state):
        g = kb.material
        now = [f"体能 {state['fitness']}"]
        why = [f"体能 = 100 − 出场/训练消耗 + 轮休恢复（fitness 公式，见 engine/objects.py）"]
        recs = list(g.objects(self.iri, EX.injuredWith))
        if recs:
            for rec in sorted(recs, key=str):
                w = int(g.value(rec, EX.weeksOut) or 0)
                now.append(f"伤停 {w} 周（{_label(g, rec)}）")
                why.append("伤病记录在 effects 层（效果即事实），痊愈事件会移除它")
        else:
            now.append("可出场")
        return now, why


class YouthPlayerObject(PlayerObject):
    type = EX.YouthPlayer


class ClubObject(BaseObject):
    type = EX.Club

    def compute(self, kb):
        g = kb.material
        total = 0
        for p in g.subjects(EX.playsFor, self.iri):
            if list(g.objects(p, EX.injuredWith)):
                continue
            f = kb.state.value(p, EX.fitness)
            if f is not None:
                total += int(f)
        return {"squadStrength": total}

    def _explain(self, kb, state):
        g = kb.material
        n = len(list(g.subjects(EX.playsFor, self.iri)))
        return [f"可用一线队球员体能合计（阵容强度）{state['squadStrength']}",
                f"一线队 {n} 人"], ["阵容强度 = Σ 可用球员的 fitness（伤员不计入）"]
