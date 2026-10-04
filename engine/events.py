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


def _bounded(value, low, high, field):
    """数值边界单点校验（与 api.EventBody 的 ge/le 同一契约）：
    REST 层的 422 是快路径，这里是 Agent 工具路径的唯一关口。"""
    if not (isinstance(value, int) and low <= value <= high):
        raise ValueError(f"{field} 需在 {low}-{high} 之间")
    return value


def build_event(kb, etype: str, player_id: str, *, minutes=None, load=None,
                weeks_out=None, kind=None):
    """统一的事件构造入口（API 端点与 Agent 工具共用）。

    kb 只用于球员存在性校验。校验失败（未知类型/未知球员/缺参数/越界）
    raise ValueError——调用方各自决定报错形态：HTTP 层转 400，
    Agent 工具层转 {"ok": False}。
    """
    from engine.namespaces import EX

    player = EX[player_id]
    if (player, None, None) not in kb.material:
        raise ValueError(f"未知球员: {player_id}")
    if etype == "match":
        _bounded(minutes, 1, 120, "minutes")
        return MatchPlayedEvent(player, minutes)
    if etype == "training":
        _bounded(load, 1, 100, "load")
        return TrainingLoadEvent(player, load)
    if etype == "injury":
        _bounded(weeks_out, 1, 52, "weeks_out")
        return InjuryEvent(player, weeks_out, kind or "伤病")
    if etype == "recovery":
        return RecoveryEvent(player)
    raise ValueError(f"未知事件类型: {etype}（可选 match/training/injury/recovery）")
