"""World：把对象运行时串成一条"感知 → 计算 → 建议"的传导线（脚：运行时）。

dispatch(event) 的钉死流程：
  1. 路由：把事件投给目标对象的收件箱（perceive）；
  2. 结算：事件效果作为新事实写入 effects 层（伤病/痊愈）——效果即事实；
  3. 重算：全部对象 compute() → 写 state 层 → kb.refresh()（推理 + 规则）；
  4. 报告：状态变化 diff + 中文传导链 + 当前建议清单。

伤病语义（计划钉死）：
  InjuryEvent 写 (球员, injuredWith, inj_节点)、(inj_节点, weeksOut, n)、
  类型与中文 label；未恢复再受伤取 max，不新增记录。
  RecoveryEvent 从 effects 层移除该球员伤病；声明层伤病不可移除/改写（no-op）。
"""
from rdflib import Literal, RDF, RDFS

from engine import events as ev
from engine.namespaces import EX
from engine.objects import (ClubObject, PlayerObject, YouthPlayerObject,
                            _id, _label)


def _weeks_of(g, p) -> int:
    """该球员当前最重伤停周数（0 = 健康）。"""
    return max((int(g.value(r, EX.weeksOut) or 0)
                for r in g.objects(p, EX.injuredWith)), default=0)


class World:
    def __init__(self, kb):
        self.kb = kb

    # ---------- 对象表 ----------
    def _objects(self):
        """按物化图重建对象表（对象不落库，随图刷新）。"""
        out = {}
        g = self.kb.material
        subjects = set(g.subjects(RDF.type, EX.Player)) | set(g.subjects(RDF.type, EX.Club))
        for s in subjects:
            types = set(g.objects(s, RDF.type))
            if EX.Club in types:
                cls = ClubObject
            elif EX.YouthPlayer in types:
                cls = YouthPlayerObject
            else:
                cls = PlayerObject
            out[_id(s)] = cls(self, s)
        return out

    def bootstrap(self):
        """初始重算：构造/重置后先填一次 state 层——
        否则首次 dispatch 的状态 diff 会把全队当成"新变化"。"""
        self._compute_all(self._objects())

    # ---------- 主入口 ----------
    def dispatch(self, event) -> dict:
        kb = self.kb
        before = {str(s): int(v) for s, v in kb.state.subject_objects(EX.fitness)}
        target_id = _id(event.player) if getattr(event, "player", None) else None
        report_event = {"type": type(event).__name__, "target": target_id}

        objs = self._objects()
        target = objs.get(target_id)
        if target is not None:
            target.perceive(event)
        chain = self._settle(event)
        kb.refresh()          # 事件效果进物化图，compute 才能看到新事实
        self._compute_all(objs)
        after = {str(s): int(v) for s, v in kb.state.subject_objects(EX.fitness)}

        changes = [{"id": _id(s), "prop": "fitness", "old": before.get(str(s)),
                    "new": after.get(str(s))}
                   for s in sorted(set(before) | set(after), key=str)
                   if before.get(str(s)) != after.get(str(s))]

        return {"event": report_event,
                "state_changes": changes,
                "chain": chain,
                "suggestions": kb.list_actions()}

    # ---------- 事件效果结算（嘴：世界里的新事实） ----------
    def _settle(self, event) -> list:
        kb = self.kb
        chain = []
        name = _label(kb.material, event.player) if getattr(event, "player", None) else "?"
        if isinstance(event, ev.InjuryEvent):
            existing = list(kb.material.objects(event.player, EX.injuredWith))
            if existing:
                rec = sorted(existing, key=str)[0]
                old = _weeks_of(kb.material, event.player)
                if event.weeks_out > old:
                    if (rec, EX.weeksOut, None) in kb.effects:
                        # 运行时伤情：直接改 effects 里的周数
                        kb.effects.remove((rec, EX.weeksOut, None))
                    else:
                        # 声明层伤情：撤销声明的周数三元组——撤销也是写回
                        for t in list(kb.declared.triples((rec, EX.weeksOut, None))):
                            kb.retractions.add(t)
                    kb.effects.add((rec, EX.weeksOut, Literal(event.weeks_out)))
                    chain.append(f"「{name}」伤情加重：伤停周数 "
                                 f"max({old}, {event.weeks_out}) = {event.weeks_out}，"
                                 f"记录已更新（不新增记录）")
                else:
                    chain.append(f"「{name}」已有伤情（伤停 {old} 周），"
                                 f"新事件 {event.weeks_out} 周不更重，记录不变")
            else:
                rec = EX[f"inj_{_id(event.player)}"]
                kb.effects.add((event.player, EX.injuredWith, rec))
                kb.effects.add((rec, RDF.type, EX.InjuryRecord))
                kb.effects.add((rec, RDFS.label, Literal(event.kind, lang="zh")))
                kb.effects.add((rec, EX.weeksOut, Literal(event.weeks_out)))
                chain.append(f"事件命中「{name}」：伤情「{event.kind}」写入 effects 层，"
                             f"伤停 {event.weeks_out} 周——效果即事实，下次刷新即可查询")
        elif isinstance(event, ev.RecoveryEvent):
            recs = list(kb.effects.objects(event.player, EX.injuredWith))
            for rec in recs:
                for t in list(kb.effects.triples((rec, None, None))):
                    kb.effects.remove(t)
                kb.effects.remove((event.player, EX.injuredWith, rec))
            if recs:
                chain.append(f"「{name}」痊愈：伤病记录从 effects 层移除")
            else:
                chain.append(f"「{name}」本无运行时伤情，痊愈事件无事发生")
        elif isinstance(event, ev.MatchPlayedEvent):
            # 效果即事实：出场分钟写入 effects 层（注意 RDF 集合语义——
            # 与既有值相同的分钟数不重复累加惩罚，教学上视为同一事实）
            kb.effects.add((event.player, EX.minutesPlayed, Literal(event.minutes)))
            chain.append(f"「{name}」感知到比赛事件：出场 {event.minutes} 分钟"
                         f"（minutesPlayed 写入 effects，状态由 compute 重算）")
        elif isinstance(event, ev.TrainingLoadEvent):
            base = f"t_evt_{_id(event.player)}"
            k = 1
            node = EX[f"{base}_{k}"]
            while any((node, None, None) in g for g in (kb.declared, kb.effects)):
                k += 1
                node = EX[f"{base}_{k}"]
            kb.effects.add((event.player, EX.trainsIn, node))
            kb.effects.add((node, RDF.type, EX.TrainingSession))
            kb.effects.add((node, RDFS.label, Literal("事件注入的训练课", lang="zh")))
            kb.effects.add((node, EX.load, Literal(event.load)))
            chain.append(f"「{name}」感知到训练事件：负荷 {event.load}"
                         f"（新训练课节点写入 effects）")
        else:
            chain.append(f"未知事件类型 {type(event).__name__}，世界无变化")
        return chain

    # ---------- 全量重算（脑：派生状态 → 推理 → 规则） ----------
    def _compute_all(self, objs):
        kb = self.kb
        triples = []
        for obj in objs.values():
            for prop, val in obj.compute(kb).items():
                triples.append((obj.iri, EX[prop], Literal(val)))
        kb.set_state(triples)
        kb.refresh()

    # ---------- 四问 ----------
    def describe(self, object_id: str) -> dict:
        obj = self._objects().get(object_id)
        if obj is None:
            raise KeyError(object_id)
        return obj.describe()
