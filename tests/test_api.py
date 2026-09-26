from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_graph_has_nodes_and_edges():
    r = client.get("/api/graph")
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) > 20
    assert any(e["inferred"] for e in body["edges"])


def test_supplier_risk_endpoint():
    r = client.post("/api/scenario/supplier-risk",
                    json={"supplier_id": "sup_shengke", "delayed": True})
    assert r.status_code == 200
    body = r.json()
    assert {p["id"] for p in body["products"]} == {"p_bt01", "p_bt02", "p_hub"}


def test_actions_execute_flow():
    client.post("/api/scenario/supplier-risk",
                json={"supplier_id": "sup_shengke", "delayed": True})
    actions = client.get("/api/actions").json()
    assert len(actions) == 9
    r = client.post(f"/api/action/{actions[0]['id']}/execute")
    assert r.json()["ok"] is True
    client.post("/api/actions/execute-all")
    assert client.get("/api/actions").json() == []
    client.post("/api/reset")
    assert client.get("/api/actions").json() == []


def test_taxonomy_tree():
    r = client.get("/api/taxonomy")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "BusinessObject"
    child_ids = {c["id"] for c in body["children"]}
    assert {"Product", "Party", "Order", "Action"} <= child_ids
    # 品类树挂在 Product 下
    product = next(c for c in body["children"] if c["id"] == "Product")
    product_child_ids = {c["id"] for c in product["children"]}
    assert "PhysicalProduct" in product_child_ids and "cat_electronics" in product_child_ids


def test_unknown_supplier_404():
    r = client.post("/api/scenario/supplier-risk",
                    json={"supplier_id": "sup_nope", "delayed": True})
    assert r.status_code == 404
