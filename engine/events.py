"""事件类型：世界对对象的"说话方式"（文章里的嘴和鼻子）。

事件是纯数据（frozen dataclass），不带行为——感知与计算在对象运行时里。
player 字段一律是完整 IRI（engine.namespaces.EX[短名]）。
"""
from dataclasses import dataclass

from rdflib import URIRef


@dataclass(frozen=True)
class MatchPlayedEvent:
    """一场比赛结束：minutes 为出场分钟，体能按 round(minutes/6) 消耗。"""
    player: URIRef
    minutes: int


@dataclass(frozen=True)
class TrainingLoadEvent:
    """一节训练课：load 为负荷（0-100），体能按 load//10 消耗。"""
    player: URIRef
    load: int


@dataclass(frozen=True)
class InjuryEvent:
    """受伤：写入伤停记录（weeksOut 周）；未恢复再受伤取 max，不新增记录。"""
    player: URIRef
    weeks_out: int
    kind: str = "伤病"


@dataclass(frozen=True)
class RecoveryEvent:
    """痊愈：移除该球员的运行时伤病记录（声明层伤病不受影响）。"""
    player: URIRef
