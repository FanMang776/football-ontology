"""规则手册:全部规则的声明式展示元数据。

权威语义仍在 rules.py / actions.py 的实现与测试里;改规则必须同步改这里
(契约测试 test_rule_handbook_* 会抓漏改)。render() 只做参数格式化,
不引入任何新逻辑——条件文本由本文件钉死,阈值等动态值在渲染时代入当前参数。
"""
from engine.actions import ROSTER_LIMIT

# 阈值等动态参数的默认表:roster_limit 来自 actions.ROSTER_LIMIT(单一来源),
# fitness_floor 与 KnowledgeBase.params 的键一致。
DEFAULT_PARAMS = {"fitness_floor": 60, "roster_limit": ROSTER_LIMIT}

RULES = [
    {
        "id": "rest-player",
        "name": "轮休",
        "category": "suggestion",
        "summary": "过度使用的球员应当轮休恢复。",
        "conditions": [
            {"text": "体能低于阈值 {fitness_floor}", "params": ["fitness_floor"]},
            {"text": "近期高强度出场(任一场 ≥ 60 分钟)至少 3 场", "params": []},
        ],
        "code": "engine/rules.py:104",
        "chapter": ["learn/04-从状态到行动.md"],
    },
    {
        "id": "callup-youth",
        "name": "征调青年队",
        "category": "suggestion",
        "summary": "位置出现一线队缺口时,从青年队征调补缺。",
        "conditions": [
            {"text": "位置可用一线队球员(未伤停)不足 2 人", "params": []},
            {"text": "存在可征调的该位置青年队球员(未伤停)", "params": []},
        ],
        "code": "engine/rules.py:111",
        "chapter": ["learn/03-推理如何发生.md", "learn/04-从状态到行动.md"],
    },
    {
        "id": "start-treatment",
        "name": "启动治疗",
        "category": "suggestion",
        "summary": "重伤球员需要队医启动治疗。",
        "conditions": [
            {"text": "伤停周数 ≥ 3 周", "params": []},
        ],
        "code": "engine/rules.py:124",
        "chapter": ["learn/04-从状态到行动.md"],
    },
    {
        "id": "roster-limit",
        "name": "报名上限",
        "category": "governance",
        "summary": "征调有前置条件:报名名单不能超员。",
        "conditions": [
            {"text": "报名名单(一线队 + 已征调)< {roster_limit} 人,违反则写 veto 并拒绝执行",
             "params": ["roster_limit"]},
        ],
        "code": "engine/actions.py:45",
        "chapter": ["learn/04-从状态到行动.md"],
    },
    {
        "id": "treatment-approval",
        "name": "治疗两步审批",
        "category": "governance",
        "summary": "治疗动作需队医确认,不是一次执行即生效。",
        "conditions": [
            {"text": "首次执行返回待审批(pending),对同一动作再次执行即确认", "params": []},
        ],
        "code": "engine/actions.py:30",
        "chapter": ["learn/04-从状态到行动.md"],
    },
    {
        "id": "veto-suppression",
        "name": "veto 抑制",
        "category": "governance",
        "summary": "被否决的动作不再出现在建议清单——建议是推论。",
        "conditions": [
            {"text": "动作被否决时写 veto 事实,规则层每次刷新都会跳过它", "params": []},
        ],
        "code": "engine/rules.py:95",
        "chapter": ["learn/04-从状态到行动.md"],
    },
    {
        "id": "audit-trail",
        "name": "审计留痕",
        "category": "governance",
        "summary": "每一次执行、否决与事件注入都进审计日志。",
        "conditions": [
            {"text": "每次执行/否决/事件注入写入审计,step 为确定性步进计数器", "params": []},
        ],
        "code": "engine/actions.py:60",
        "chapter": ["learn/04-从状态到行动.md"],
    },
]


def render(params: dict) -> list:
    """代入当前参数,返回前端可直接渲染的条目;参数缺失由 str.format 抛 KeyError。"""
    out = []
    for r in RULES:
        conds = [{"text": c["text"].format(**params) if c["params"] else c["text"],
                  "dynamic": bool(c["params"])} for c in r["conditions"]]
        out.append({**r, "conditions": conds})
    return out
