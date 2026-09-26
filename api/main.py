"""FastAPI 接口 + 静态前端托管。启动：uvicorn api.main:app --reload"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rdflib import RDF, RDFS

from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

app = FastAPI(title="电商本体论 Demo")
kb = KnowledgeBase()


def _resolve(kind: str, local: str):
    node = EX[local]
    if (node, None, None) not in kb.material:
        raise HTTPException(404, f"未知的{kind}: {local}")
    return node


class RiskBody(BaseModel):
    supplier_id: str
    delayed: bool


class VipBody(BaseModel):
    spend_threshold: int = 5000
    order_threshold: int = 3


@app.get("/api/graph")
def graph():
    """图谱快照：实体为节点，三元组为边；声明实线、推断虚线由前端区分。"""
    nodes, edges = {}, []
    shown = (EX.suppliedBy, EX.hasPart, EX.isComponentOf, EX.substituteFor,
             EX.compatibleWith, EX.sameSeries, EX.promotes, EX.placedBy,
             EX.hasLine, EX.lineProduct, RDF.type)

    def add_node(n):
        key = str(n)
        if key not in nodes:
            lbl = kb.material.value(n, RDFS.label)
            cls = kb.material.value(n, RDF.type)
            nodes[key] = {"id": key.split("#")[-1],
                          "label": str(lbl) if lbl else key.split("#")[-1],
                          "cls": str(cls).split("#")[-1] if cls else "?"}

    for s, p, o in kb.material:
        if (p in shown and str(s).startswith(str(EX))
                and str(o).startswith(str(EX))):
            add_node(s)
            add_node(o)
            edges.append({"s": str(s).split("#")[-1], "p": str(p).split("#")[-1],
                          "o": str(o).split("#")[-1],
                          "inferred": (s, p, o) not in kb.declared})
    edges.sort(key=lambda e: (e["s"], e["p"], e["o"]))
    return {"nodes": list(nodes.values()), "edges": edges}


@app.get("/api/taxonomy")
def taxonomy():
    # 用声明图而非物化图：OWL-RL 闭包含自反推断（c subClassOf c），
    # 无守卫的递归会无限爆栈；visited 兜底防环。
    children = {}
    for s, _, o in kb.declared.triples((None, RDFS.subClassOf, None)):
        children.setdefault(str(o), []).append(str(s))

    def build(uri, visited=frozenset()):
        if uri in visited:
            return {"id": uri.split("#")[-1], "label": uri, "children": []}
        visited = visited | {uri}
        lbl = kb.material.value(EX[uri.split("#")[-1]], RDFS.label)
        return {"id": uri.split("#")[-1], "label": str(lbl) if lbl else uri,
                "children": [build(c, visited)
                             for c in sorted(children.get(uri, []))]}

    return build(str(EX.BusinessObject))


@app.get("/api/entity/{eid}")
def entity(eid: str):
    node = _resolve("实体", eid)
    declared, inferred = [], []
    for s, p, o in kb.material.triples((node, None, None)):
        obj = str(o).split("#")[-1] if str(o).startswith(str(EX)) else o.n3()
        text = f"{str(p).split('#')[-1]}  →  {obj}"
        (declared if (s, p, o) in kb.declared else inferred).append(text)
    lbl = kb.material.value(node, RDFS.label)
    return {"id": eid, "label": str(lbl) if lbl else eid,
            "declared": sorted(declared), "inferred": sorted(inferred)}


@app.post("/api/scenario/supplier-risk")
def supplier_risk(body: RiskBody):
    _resolve("供应商", body.supplier_id)
    return kb.supplier_risk(EX[body.supplier_id], body.delayed)


@app.post("/api/scenario/vip")
def vip(body: VipBody):
    return kb.vip_classification(body.spend_threshold, body.order_threshold)


@app.get("/api/scenario/recommend/{pid}")
def recommend(pid: str):
    _resolve("商品", pid)
    return kb.recommend(EX[pid])


@app.get("/api/actions")
def actions():
    return kb.list_actions()


@app.post("/api/action/{aid}/execute")
def execute_action(aid: str):
    result = kb.execute(aid)
    if not result["ok"]:
        raise HTTPException(409, result["message"])
    return result


@app.post("/api/actions/execute-all")
def execute_all():
    return kb.execute_all()


@app.post("/api/reset")
def reset():
    kb.reset()
    return {"ok": True}


web_dir = Path(__file__).resolve().parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
