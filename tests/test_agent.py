"""Agent 工具表：六个本体操作工具的 schema、分发与治理路径。"""
import pytest

from engine.agent import SYSTEM_PROMPT, TOOLS, run_tool
from engine.knowledge_base import KnowledgeBase

TOOL_NAMES = {"list_players", "describe_object", "list_suggestions",
              "preview_action", "execute_action", "inject_event"}


@pytest.fixture()
def kb():
    kb = KnowledgeBase()
    kb.reset()
    return kb


def test_tools_schema_complete():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == TOOL_NAMES
    for t in TOOLS:
        assert t["type"] == "function" and t["function"]["description"]
        assert t["function"]["parameters"]["type"] == "object"


def test_list_players_sorted(kb):
    out = run_tool(kb, "list_players", {})
    ids = [p["id"] for p in out["players"]]
    assert ids == sorted(ids) and len(ids) == 20
    assert all("fitness" in p for p in out["players"])


def test_describe_object(kb):
    out = run_tool(kb, "describe_object", {"object_id": "p_yam1"})
    assert out["id"] == "p_yam1" and "现在状态" in out


def test_describe_unknown_player_ok_false(kb):
    out = run_tool(kb, "describe_object", {"object_id": "nobody"})
    assert out["ok"] is False


def test_inject_event_and_report(kb):
    out = run_tool(kb, "inject_event",
                   {"etype": "injury", "player_id": "p_yam1", "weeks_out": 4})
    assert out["ok"] is True and out["chain"]


def test_inject_event_unknown_player_ok_false(kb):
    out = run_tool(kb, "inject_event",
                   {"etype": "injury", "player_id": "x", "weeks_out": 4})
    assert out["ok"] is False and "message" in out


def test_execute_action_walks_governance(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    assert run_tool(kb, "preview_action", {"action_id": aid})["ok"] is True
    assert run_tool(kb, "execute_action", {"action_id": aid})["ok"] is True


def test_system_prompt_pins_discipline():
    for word in ("治理", "确认", "没有这个数据"):
        assert word in SYSTEM_PROMPT
