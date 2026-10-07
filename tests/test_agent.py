"""Agent 工具表：六个本体操作工具的 schema、分发与治理路径。"""
import pytest

from engine.agent import SYSTEM_PROMPT, TOOLS, run_tool, _summarize
from engine.knowledge_base import KnowledgeBase

TOOL_NAMES = {"list_players", "describe_object", "list_suggestions",
              "preview_action", "execute_action", "inject_event",
              "simulate_actions"}


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


def test_simulate_actions_tool(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    out = run_tool(kb, "simulate_actions", {"actions": [aid]})
    assert out["ok"] is True and out["steps"][0]["action_id"] == aid


def test_simulate_actions_bad_args_ok_false(kb):
    assert run_tool(kb, "simulate_actions", {})["ok"] is False
    assert run_tool(kb, "simulate_actions", {"actions": []})["ok"] is False


def test_summarize_simulate_one_line(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    out = run_tool(kb, "simulate_actions", {"actions": [aid]})
    s = _summarize("simulate_actions", out)
    assert s.startswith("推演 1 步（1 成功）") and "fitness" in s


def test_system_prompt_pins_sandbox_discipline():
    assert "沙盒" in SYSTEM_PROMPT and "execute_action" in SYSTEM_PROMPT


def test_run_turn_simulate_via_fake_client(kb):
    sug = run_tool(kb, "list_suggestions", {})
    aid = next(a["id"] for a in sug["actions"] if a["type"] == "RestPlayer")
    evts = collect(kb, FakeClient(
        [(None, [("simulate_actions", {"actions": [aid]})]),
         ("推演完成", [])]),
        [{"role": "user", "content": "如果轮休他会怎样"}])
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert tr["summary"].startswith("推演")


# ---------- Task 2：run_turn 工具循环与客户端 ----------

from engine.agent import MAX_ROUNDS, MockClient, run_turn


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


def test_mock_second_turn_same_keyword_still_calls_tools(kb):
    """回归（审查 #1）：前端历史保留 assistant tool_calls 消息，
    MockClient 的脚本步进必须只数最后一条 user 之后的消息，
    否则第二轮起工具卡片永久消失。"""
    client = MockClient()
    msgs = [{"role": "user", "content": "有什么建议"}]
    first = list(run_turn(kb, client, "m", msgs))
    assert any(e["type"] == "tool_call" for e in first)

    msgs += [{"role": "assistant", "content": "以上是建议",
              "tool_calls": [{"id": "h0", "type": "function",
                              "function": {"name": "list_suggestions",
                                           "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "h0", "content": "共 4 条建议"},
             {"role": "user", "content": "球队名单"}]
    second = list(run_turn(kb, client, "m", msgs))
    assert any(e["type"] == "tool_call" for e in second), \
        "换了关键词也应重新走脚本，而不是直接落到收尾文案"


def test_run_tool_holds_kb_lock(kb, monkeypatch):
    """回归（审查 #2）：工具执行整体经 kb._lock 串行化（RLock 可重入，
    内部再进 kb 方法不会死锁）。"""
    from engine import agent as ag
    seen = []

    def probe(_kb, _args):
        seen.append(kb._lock._is_owned())
        return {"ok": True}

    monkeypatch.setitem(ag._TOOLS_IMPL, "list_players", probe)
    ag.run_tool(kb, "list_players", {})
    assert seen == [True]


def test_inject_event_rejects_out_of_range(kb):
    """回归（审查 #4）：数值边界在 build_event 单点校验，
    Agent 工具与 REST 端点同一契约。"""
    for args in ({"etype": "match", "player_id": "p_yam1", "minutes": 300},
                 {"etype": "training", "player_id": "p_yam1", "load": 0},
                 {"etype": "injury", "player_id": "p_yam1", "weeks_out": 99}):
        out = run_tool(kb, "inject_event", args)
        assert out["ok"] is False, args


def test_make_client_clear_error_when_config_missing(monkeypatch, tmp_path):
    """显式配了真实模型但缺 base_url/key 时，报中文错误而非裸 KeyError。
    传入不存在的配置文件路径——开发者机器上可能有真实 config.ini。"""
    import pytest as _pytest
    monkeypatch.setenv("LLM_MODEL", "glm-4.6")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    from engine.agent import make_client
    with _pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        make_client(tmp_path / "none.ini")


def test_mock_rest_closing_reflects_result(kb):
    """Minor 修复：轮休收尾文案取自工具结果，不在建议已消费时谎报已执行。"""
    run_tool(kb, "execute_action", {"action_id": "action_RestPlayer_p_am1"})
    evts = list(run_turn(kb, MockClient(), "m",
                         [{"role": "user", "content": "帮德布劳内轮休"}]))
    text = "".join(e["text"] for e in evts if e["type"] == "delta")
    assert "不在当前建议清单" in text, "建议已消费，执行应失败且收尾如实汇报"


# ---------- 配置文件：环境变量 > config.ini > 默认 mock ----------

def _write_cfg(tmp_path, body):
    p = tmp_path / "config.ini"
    p.write_text(body, encoding="utf-8")
    return p


def test_make_client_reads_config_file(tmp_path, monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from engine.agent import OpenAIClient, make_client
    p = _write_cfg(tmp_path,
                   "[llm]\nbase_url = https://open.bigmodel.cn/api/paas/v4\n"
                   "api_key = k77\nmodel = glm-5.3-flash\n")
    c = make_client(p)
    assert isinstance(c, OpenAIClient)
    assert c.api_key == "k77"
    assert c.model == "glm-5.3-flash"
    assert "bigmodel.cn" in c.base_url


def test_env_overrides_config_file(tmp_path, monkeypatch):
    from engine.agent import MockClient, make_client
    p = _write_cfg(tmp_path,
                   "[llm]\nbase_url = https://x/v4\napi_key = k\nmodel = glm-5.3-flash\n")
    monkeypatch.setenv("LLM_MODEL", "mock")
    assert isinstance(make_client(p), MockClient)


def test_missing_config_file_is_silent(tmp_path, monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from engine.agent import MockClient, make_client
    assert isinstance(make_client(tmp_path / "nope.ini"), MockClient)


def test_run_turn_llm_error_becomes_delta_not_crash(kb):
    """模型侧异常（如 401）转成可见的 delta 事件 + done 收尾，不炸 SSE。"""
    class BoomClient:
        def stream_chat(self, model, messages, tools):
            raise RuntimeError("Error code: 401 - 令牌已过期或验证不正确")

    evts = list(run_turn(kb, BoomClient(), "m",
                         [{"role": "user", "content": "hi"}]))
    assert evts[-1]["type"] == "done"
    text = "".join(e.get("text", "") for e in evts if e["type"] == "delta")
    assert "401" in text and "模型调用失败" in text
