"""API 契约：事件注入、对象 describe、治理端点、参数。"""
import pytest
from fastapi.testclient import TestClient

from api.main import app, kb


@pytest.fixture()
def client():
    kb.reset()
    return TestClient(app)


def test_event_invalid_minutes_422(client):
    r = client.post("/api/events", json={"type": "match", "player_id": "p_st1", "minutes": 0})
    assert r.status_code == 422


def test_event_unknown_type_400(client):
    r = client.post("/api/events", json={"type": "party", "player_id": "p_st1"})
    assert r.status_code == 400


def test_event_unknown_player_400(client):
    r = client.post("/api/events", json={"type": "match", "player_id": "p_nope", "minutes": 90})
    assert r.status_code == 400


def test_injury_event_returns_report(client):
    r = client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert r.status_code == 200
    body = r.json()
    assert "chain" in body and "suggestions" in body


def test_event_chain_steps_structured(client):
    r = client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert r.status_code == 200
    steps = r.json()["chain"]
    assert steps and all(set(s) == {"stage", "text"} and s["text"] for s in steps)
    stages = [s["stage"] for s in steps]
    assert stages == ["perceive", "settle", "compute", "rules"]
    audit = client.get("/api/audit").json()
    assert audit[0]["detail"]              # 审计 detail 取 settle 步文案，非空且是字符串
    assert isinstance(audit[0]["detail"], str)


def test_describe_object(client):
    r = client.get("/api/object/p_am1/describe")
    assert r.status_code == 200
    assert set(("是谁", "现在状态", "为什么", "能做什么")) <= set(r.json())


def test_describe_unknown_404(client):
    assert client.get("/api/object/p_nope/describe").status_code == 404


def test_audit_and_params(client):
    client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    assert client.get("/api/audit").status_code == 200
    r = client.post("/api/params", json={"fitness_floor": 70})
    assert r.status_code == 200 and r.json()["params"]["fitness_floor"] == 70


def test_taxonomy_root(client):
    assert client.get("/api/taxonomy").status_code == 200


def test_graph_has_nodes_and_inferred_edges(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) >= 20
    assert any(e["inferred"] for e in body["edges"])   # 位置泛化的推断边


def test_graph_cls_picks_most_specific_type(client):
    """多重类型取最具体者，不能按 URI 字母序（Player < Striker 会取错）。"""
    nodes = {n["id"]: n["cls"] for n in client.get("/api/graph").json()["nodes"]}
    assert nodes["p_st2"] == "Striker"          # Player + Striker → 中锋（曾被染成白色回退）
    assert nodes["p_wg1"] == "Winger"
    assert nodes["p_gk1"] == "Goalkeeper"
    assert nodes["p_yam1"] == "AttackingMidfielder"   # 与 YouthPlayer 同深，字母序兜底


def test_static_no_cache_header(client):
    """静态资源必须协商缓存：改版后浏览器强刷新不再必要。"""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_rules_endpoint_lists_all(client):
    rules = client.get("/api/rules").json()["rules"]
    assert len(rules) == 7
    assert {r["id"] for r in rules} == {
        "rest-player", "callup-youth", "start-treatment",
        "roster-limit", "treatment-approval", "veto-suppression", "audit-trail"}


def test_rules_reflect_current_params(client):
    client.post("/api/params", json={"fitness_floor": 90})
    rules = client.get("/api/rules").json()["rules"]
    rest = next(r for r in rules if r["id"] == "rest-player")
    assert "90" in rest["conditions"][0]["text"]


def test_actions_includes_roster(client):
    """/api/actions 携带报名名单计数（一线队 + 已征调青年队 / 上限 16）。"""
    body = client.get("/api/actions").json()
    assert body["roster"] == {"count": 14, "limit": 16}


def test_roster_grows_after_callup(client):
    """征调执行后报名 +1：效果事实（calledUp）计入名单。初始 14 + 执行 2 = 16。"""
    acts = client.get("/api/actions").json()["actions"]
    callups = [a for a in acts if a["type"] == "CallUpYouth"]
    assert len(callups) == 2
    for a in callups:
        r = client.post(f"/api/action/{a['id']}/execute")
        assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/actions").json()["roster"]["count"] == 16


def test_execute_pending_returns_200(client):
    """审批动作第一次执行是合法中间态：200 + pending=true，不是 409。"""
    client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    acts = client.get("/api/actions").json()["actions"]
    aid = next(a["id"] for a in acts
               if a["type"] == "StartTreatment"
               and any(t["id"] == "p_st1" for t in a["targets"]))
    r = client.post(f"/api/action/{aid}/execute")
    assert r.status_code == 200
    assert r.json().get("pending") is True
    r2 = client.post(f"/api/action/{aid}/execute")
    assert r2.status_code == 200 and r2.json()["ok"] is True


def test_preview_unknown_404(client):
    r = client.post("/api/preview-action/action_Nonexistent_x")
    assert r.status_code == 404


def test_execute_unknown_409(client):
    r = client.post("/api/action/action_Nonexistent_x/execute")
    assert r.status_code == 409


def test_execute_all_ok(client):
    r = client.post("/api/actions/execute-all")
    assert r.status_code == 200
    assert "executed" in r.json()
