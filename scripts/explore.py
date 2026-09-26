"""本体学习实验台：python scripts/explore.py --step N

step 1  看原始三元组——本体就是"主语 谓语 宾语"
step 2  看类层级树——品类树是 subClassOf 树
step 3  跑推理，看声明 vs 推断的 diff——"机器理解业务"的时刻
step 4  跑三个决策场景的查询
step 5  触发一条建议动作并执行，看图谱回写前后 diff
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rdflib import RDF, RDFS

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

    walk(EX.BusinessObject)


def step3():
    before, after = load_declared(), materialize(load_declared())
    inferred = {t for t in after} - {t for t in before}
    print(f"声明 {len(before)} 条 → 物化后 {len(after)} 条，新推断 {len(inferred)} 条。\n")
    interesting = [t for t in sorted(inferred, key=lambda t: (str(t[1]) == str(RDF.type), str(t)))
                   if t[1] in (EX.substituteFor, EX.hasPart, EX.isComponentOf,
                               EX.compatibleWith, EX.sameSeries)
                   or (t[1] == RDF.type and "cat_" in str(t[2]))]
    print("有代表性的推断（前 30 条）：\n")
    for s, p, o in interesting[:30]:
        print(f"  [推断] {short(s):14} {short(p):18} {short(o)}")


def step4():
    kb = KnowledgeBase()
    print("== 场景 2：VIP 分类（阈值 5000/3）==")
    for v in kb.vip_classification(5000, 3)["vips"]:
        print(f"  [VIP] {v['label']:<6} 因为：{v['reason']}")
    print("\n== 场景 1：声科电子延迟的风险传导 ==")
    r = kb.supplier_risk(EX.sup_shengke, True)
    for step in r["chain"]:
        print(f"  第 {step['step']} 步（{step['count']} 项）：{step['explanation']}")
    print("\n== 场景 3：BT-01 的语义推荐 vs 同品类 ==")
    rec = kb.recommend(EX.p_bt01)
    print(f"  朴素版：{', '.join(x['label'] for x in rec['naive'])}")
    for x in rec["semantic"]:
        print(f"  语义版：{x['label']}（{x['relation_label']}）")


def step5():
    kb = KnowledgeBase()
    kb.supplier_risk(EX.sup_shengke, True)
    acts = kb.list_actions()
    act = next(a for a in acts if a["type"] == "PausePromotion")
    before = len(kb.material)
    print(f"执行动作 {act['id']}\n  原因：{act['reason']}")
    result = kb.execute(act["id"])
    print(f"  结果：{result['message']}")
    print(f"  图谱三元组 {before} → {len(kb.material)}（效果已作为新事实写回并重新推理）")
    print(f"  剩余建议动作 {len(kb.list_actions())} 条——已处置的自动消失")


STEPS = {1: step1, 2: step2, 3: step3, 4: step4, 5: step5}

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="本体学习实验台")
    parser.add_argument("--step", type=int, choices=STEPS, required=True)
    STEPS[parser.parse_args().step]()
