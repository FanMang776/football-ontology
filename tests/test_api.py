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


def test_execute_pending_returns_200(client):
    """审批动作第一次执行是合法中间态：200 + pending=true，不是 409。"""
    client.post("/api/events", json={"type": "injury", "player_id": "p_st1", "weeks_out": 4})
    acts = client.get("/api/actions").json()
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
