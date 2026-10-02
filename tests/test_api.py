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
