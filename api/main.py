"""FastAPI 接口 + 静态前端托管。启动：uvicorn api.main:app --reload"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rdflib import RDF, RDFS, Literal

from engine import events as ev
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

app = FastAPI(title="足球本体世界 Demo")
kb = KnowledgeBase()

OWL = "http://www.w3.org/2002/07/owl#"


def _cls_of(node) -> str:
    """声明类型的短名（按 URI 排序取首个，排除 owl: 词表）；类节点回退 "Class"。"""
    types = sorted(str(t) for t in kb.declared.objects(node, RDF.type)
                   if not str(t).startswith(OWL))
    return types[0].split("#")[-1] if types else "Class"


def _resolve(kind: str, local: str):
    node = EX[local]
    if (node, None, None) not in kb.material:
        raise HTTPException(404, f"未知的{kind}: {local}")
    return node


class EventBody(BaseModel):
    type: str                      # match | training | injury | recovery
    player_id: str
    minutes: Optional[int] = Field(None, ge=1, le=120)
    load: Optional[int] = Field(None, ge=1, le=100)
    weeks_out: Optional[int] = Field(None, ge=1, le=52)
    kind: Optional[str] = None


class ParamsBody(BaseModel):
    fitness_floor: int = Field(ge=0, le=100)


def _build_event(body: EventBody):
    player = EX[body.player_id]
    if (player, None, None) not in kb.material:
        raise HTTPException(400, f"未知球员: {body.player_id}")
    if body.type == "match":
        if body.minutes is None:
            raise HTTPException(400, "match 事件需要 minutes")
        return ev.MatchPlayedEvent(player, body.minutes)
    if body.type == "training":
        if body.load is None:
            raise HTTPException(400, "training 事件需要 load")
        return ev.TrainingLoadEvent(player, body.load)
    if body.type == "injury":
        if body.weeks_out is None:
            raise HTTPException(400, "injury 事件需要 weeks_out")
        return ev.InjuryEvent(player, body.weeks_out, body.kind or "伤病")
    if body.type == "recovery":
        return ev.RecoveryEvent(player)
    raise HTTPException(400, f"未知事件类型: {body.type}（可选 match/training/injury/recovery）")


@app.post("/api/events")
def inject_event(body: EventBody):
    """世界的事件入口（嘴）：感知 → 计算 → 建议，返回传导报告。"""
    return kb.dispatch(_build_event(body))


@app.get("/api/object/{oid}/describe")
def describe_object(oid: str):
    """对象的四问：是谁 / 现在状态 / 为什么 / 能做什么。"""
    try:
        return kb.describe(oid)
    except KeyError:
        raise HTTPException(404, f"未知对象: {oid}")


@app.get("/api/graph")
def graph():
    """图谱快照：实体为节点，三元组为边；声明实线、推断虚线由前端区分。"""
    nodes, edges = {}, []
    shown = (EX.playsFor, EX.squadOf, EX.hasContract, EX.injuredWith,
             EX.participatesIn, EX.trainsIn, RDF.type)

    def add_node(n):
        key = str(n)
        if key not in nodes:
            lbl = kb.material.value(n, RDFS.label)
            nodes[key] = {"id": key.split("#")[-1],
                          "label": str(lbl) if lbl else key.split("#")[-1],
                          "cls": _cls_of(n)}

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
            return {"id": uri.split("#")[-1], "label": uri.split("#")[-1],
                    "children": []}
        visited = visited | {uri}
        lbl = kb.material.value(EX[uri.split("#")[-1]], RDFS.label)
        return {"id": uri.split("#")[-1], "label": str(lbl) if lbl else uri,
                "children": [build(c, visited)
                             for c in sorted(children.get(uri, []))]}

    return build(str(EX.FootballEntity))


@app.get("/api/entity/{eid}")
def entity(eid: str):
    node = _resolve("实体", eid)
    declared, inferred = [], []

    def render(o):
        """字面量取词法值，EX 内 URI 取短名，其余原样字符串。"""
        if isinstance(o, Literal):
            return str(o), True
        s = str(o)
        return (s.split("#")[-1], False) if s.startswith(str(EX)) else (s, False)

    for s, p, o in kb.material.triples((node, None, None)):
        obj, is_literal = render(o)
        item = {"p": str(p).split("#")[-1], "o": obj, "is_literal": is_literal}
        (declared if (s, p, o) in kb.declared else inferred).append(item)
    key = lambda it: (it["p"], str(it["o"]))
    lbl = kb.material.value(node, RDFS.label)
    return {"id": eid, "label": str(lbl) if lbl else eid,
            "declared": sorted(declared, key=key),
            "inferred": sorted(inferred, key=key)}


@app.get("/api/actions")
def actions():
    return kb.list_actions()


@app.post("/api/preview-action/{aid}")
def preview_action(aid: str):
    result = kb.preview(aid)
    if not result["ok"]:
        raise HTTPException(404, result.get("message", "无法预览该动作"))
    return result


@app.post("/api/action/{aid}/execute")
def execute_action(aid: str):
    result = kb.execute(aid)
    if result.get("pending"):
        # 审批中间态是合法结果：200 + pending=true，前端据此显示"确认执行"
        return result
    if not result["ok"]:
        raise HTTPException(409, result["message"])
    return result


@app.post("/api/actions/execute-all")
def execute_all():
    return kb.execute_all()


@app.get("/api/audit")
def audit():
    return kb.audit_view()


@app.post("/api/params")
def set_params(body: ParamsBody):
    kb.set_params(body.fitness_floor)
    return {"ok": True, "params": dict(kb.params)}


@app.post("/api/reset")
def reset():
    kb.reset()
    return {"ok": True}


web_dir = Path(__file__).resolve().parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
