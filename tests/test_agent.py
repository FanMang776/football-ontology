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


# ---------- Task 2：run_turn 工具循环与客户端 ----------

from engine.agent import MAX_ROUNDS, run_turn


class FakeClient:
    """脚本化假模型：pop 序列，脚本耗尽后固定作答。"""

    def __init__(self, script):
        self.script = list(script)   # 每项: (text_delta_or_None, calls_or_None)

    def stream_chat(self, model, messages, tools):
        item = self.script.pop(0) if self.script else (f"回答 {len(messages)}", [])
        text, calls = item
        if text:
            yield {"type": "text-delta", "text": text}
        yield {"type": "tool_calls",
               "calls": [{"id": f"c{i}", "name": n, "arguments": a}
                         for i, (n, a) in enumerate(calls or [])]}


def collect(kb, client, msgs):
    return list(run_turn(kb, client, "m", msgs))


def test_run_turn_plain_answer(kb):
    evts = collect(kb, FakeClient([("你好，世界", [])]),
                   [{"role": "user", "content": "hi"}])
    assert [e["type"] for e in evts] == ["delta", "done"]
    assert evts[-1]["rounds_used"] == 1


def test_run_turn_tool_loop(kb):
    script = [(None, [("list_suggestions", {})]),
              ("共 N 条建议", [])]
    evts = collect(kb, FakeClient(script),
                   [{"role": "user", "content": "有什么建议"}])
    types = [e["type"] for e in evts]
    assert types == ["tool_call", "tool_result", "delta", "done"]
    assert evts[1]["summary"]


def test_run_turn_round_cap(kb):
    evts = collect(kb, FakeClient([(None, [("list_players", {})])] * 99),
                   [{"role": "user", "content": "名单"}])
    assert evts[-1]["type"] == "done" and evts[-1]["rounds_used"] == MAX_ROUNDS
    assert evts[-2]["type"] == "delta" and "上限" in evts[-2]["text"]


def test_run_turn_pending_approval_recorded(kb):
    run_tool(kb, "inject_event",
             {"etype": "injury", "player_id": "p_yam1", "weeks_out": 4})
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "StartTreatment")
    msgs = [{"role": "user", "content": "处理重伤员"}]
    evts = list(run_turn(kb, FakeClient(
        [(None, [("execute_action", {"action_id": aid})])]), "m", msgs))
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert "pending" in tr["summary"]
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert tool_msgs and "pending" in tool_msgs[-1]["content"]


def test_make_client_mock_needs_no_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    from engine.agent import MockClient, make_client
    assert isinstance(make_client(), MockClient)
