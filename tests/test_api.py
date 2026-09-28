from fastapi.testclient import TestClient

from api.main import app, kb

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


def test_entity_structured_triples():
    r = client.get("/api/entity/p_bt01")
    assert r.status_code == 200
    body = r.json()
    assert body["declared"] and body["inferred"]
    for item in body["declared"] + body["inferred"]:
        assert set(item) == {"p", "o", "is_literal"}
        assert isinstance(item["is_literal"], bool)
        assert "^^" not in str(item["o"])


def test_vip_scenario():
    r = client.post("/api/scenario/vip",
                    json={"spend_threshold": 5000, "order_threshold": 3})
    assert r.status_code == 200
    vips = r.json()["vips"]
    assert len(vips) == 5
    assert all(v["reason"] for v in vips)


def test_recommend_semantic_contains_substitute():
    r = client.get("/api/scenario/recommend/p_bt01")
    assert r.status_code == 200
    semantic = r.json()["semantic"]
    hit = next(x for x in semantic if x["id"] == "p_x2")
    assert hit["relation"] == "substituteFor"


def test_execute_unknown_action_409():
    r = client.post("/api/action/action_Nope_x/execute")
    assert r.status_code == 409


def test_execute_twice_second_409():
    client.post("/api/scenario/supplier-risk",
                json={"supplier_id": "sup_shengke", "delayed": True})
    aid = client.get("/api/actions").json()[0]["id"]
    assert client.post(f"/api/action/{aid}/execute").json()["ok"] is True
    assert client.post(f"/api/action/{aid}/execute").status_code == 409
    client.post("/api/reset")


def test_taxonomy_survives_reflexive_cycle():
    from rdflib import RDF, RDFS

    from engine.namespaces import EX
    reflexive = (EX.Product, RDFS.subClassOf, EX.Product)
    kb.declared.add(reflexive)
    try:
        r = client.get("/api/taxonomy")
        assert r.status_code == 200
        assert r.json()["id"] == "BusinessObject"
    finally:
        kb.declared.remove(reflexive)


def test_risk_view_endpoint_restores_state():
    client.post("/api/reset")
    assert client.get("/api/scenario/risk").json()["supplier"] is None
    client.post("/api/scenario/supplier-risk",
                json={"supplier_id": "sup_shengke", "delayed": True})
    body = client.get("/api/scenario/risk").json()
    assert body["supplier"] == "sup_shengke"
    assert body["chain"][0]["count"] == 3
    client.post("/api/scenario/supplier-risk",
                json={"supplier_id": "sup_shengke", "delayed": False})
    assert client.get("/api/scenario/risk").json()["supplier"] is None


def test_unknown_supplier_404():
    r = client.post("/api/scenario/supplier-risk",
                    json={"supplier_id": "sup_nope", "delayed": True})
    assert r.status_code == 404
