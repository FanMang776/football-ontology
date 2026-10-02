"""本体学习实验台：python scripts/explore.py --step N

step 1  看原始三元组——本体就是"主语 谓语 宾语"
step 2  看类层级树——位置树是 subClassOf 树
step 3  跑推理，看声明 vs 推断的 diff——"机器理解业务"的时刻
step 4  注入事件，看"感知 → 状态 → 建议"的传导链
step 5  治理动作：预览 → 审批两步流 → 审计日志
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rdflib import RDF, RDFS

from engine.events import InjuryEvent
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX
from engine.loader import load_declared, materialize


def short(node) -> str:
    return str(node).split("#")[-1]


def label(g, node) -> str:
    v = g.value(node, RDFS.label)
    return f"{short(node)}（{v}）" if v else short(node)


def step1():
    g = load_declared()
    print(f"声明三元组共 {len(g)} 条。前 25 条：\n")
    for i, (s, p, o) in enumerate(sorted(g, key=str)):
        if i >= 25:
            break
        print(f"  {short(s):18} {short(p):22} {o.n3()[:60]}")


def step2():
    g = load_declared()
    children = {}
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        children.setdefault(o, []).append(s)

    def walk(node, depth=0):
        print("  " * depth + label(g, node))
        for c in sorted(children.get(node, []), key=str):
            walk(c, depth + 1)

    walk(EX.FootballEntity)


def step3():
    before, after = load_declared(), materialize(load_declared())
    inferred = {t for t in after} - {t for t in before}
    print(f"声明 {len(before)} 条 → 物化后 {len(after)} 条，新推断 {len(inferred)} 条。\n")
    # 最有教学价值的推断：位置泛化（子类成员 → 祖先成员）与青年队归类
    position_classes = {EX.Position} | {o for s, _, o in after.triples(
        (None, RDFS.subClassOf, EX.Position))}
    interesting = [t for t in sorted(inferred, key=str)
                   if t[1] == RDF.type and t[2] in position_classes]
    print("位置泛化：声明的是最细位置，祖先成员关系全部是推理补全（前 30 条）：\n")
    for s, p, o in interesting[:30]:
        print(f"  [推断] {short(s):14} {short(p):6} {short(o)}")
    youth = [t for t in sorted(inferred, key=str)
             if t[1] == RDF.type and t[2] == EX.Player]
    print(f"\n青年队归类：{len(youth)} 条 YouthPlayer ⊑ Player 的推论（前 5 条）：")
    for s, p, o in youth[:5]:
        print(f"  [推断] {short(s):14} {short(p):6} {short(o)}")


def step4():
    kb = KnowledgeBase()
    print("== 开局世界的状态（bootstrap 已算好）==")
    print(f"  德布劳内体能：{int(kb.state.value(EX.p_am1, EX.fitness))}"
          f"（声明出场史 90/88/85 算出：100 − (15+15+14)）")
    print(f"  开局建议 {len(kb.list_actions())} 条：")
    for a in kb.list_actions():
        print(f"    [{a['type']}] {', '.join(t['label'] for t in a['targets'])}")

    print("\n== 注入事件：德布劳内也伤了（4 周）==")
    r = kb.dispatch(InjuryEvent(EX.p_am1, 4, "腿筋拉伤"))
    for i, step in enumerate(r["chain"], 1):
        print(f"  传导 {i}: {step}")
    print(f"  状态变化：{r['state_changes']}")
    print(f"  建议清单刷新为 {len(r['suggestions'])} 条：")
    for a in r["suggestions"]:
        print(f"    [{a['type']}] {', '.join(t['label'] for t in a['targets'])}"
              f" —— {a['reason'][:48]}…")


def step5():
    kb = KnowledgeBase()
    act = next(a for a in kb.list_actions() if a["type"] == "StartTreatment")
    print(f"建议动作：{act['id']}\n  原因：{act['reason']}")
    print(f"\n== 预览影响（不落库）==")
    p = kb.preview(act["id"])
    for t in p["additions"]:
        print(f"  将写入：{t}")

    print(f"\n== 执行（第一次：审批门）==")
    first = kb.execute(act["id"])
    print(f"  ok={first['ok']} {first.get('message', '')}")

    print(f"\n== 再执行同一动作（队医确认，放行）==")
    second = kb.execute(act["id"])
    print(f"  ok={second['ok']} {second.get('message', '')}")

    print(f"\n== 审计日志 ==")
    for e in kb.audit_view():
        print(f"  [step {e['step']}] {e['result']:<8} {e['action']} {e['target']}")
    rest = [a for a in kb.list_actions()]
    print(f"\n剩余建议 {len(rest)} 条——已处置的自动消失")


STEPS = {1: step1, 2: step2, 3: step3, 4: step4, 5: step5}

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="本体学习实验台")
    parser.add_argument("--step", type=int, choices=STEPS, required=True)
    STEPS[parser.parse_args().step]()
