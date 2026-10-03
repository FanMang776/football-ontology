# 规则手册(Rule Handbook)设计 spec

日期:2026-10-03
状态:待用户评审

## 目标与受众

让 Web 界面的使用者(教学观众:看 demo 学本体的人)能看到引擎里**全部**规则的
完整定义——3 条状态建议规则 + 4 条治理机制——而不只是命中建议时才见到的理由文案。

成功标准:

1. 打开学习路径 Tab,能看到全部 7 条规则及其触发条件;
2. 规则定义只有一处权威来源,改规则不改手册会被测试抓住(防漂移);
3. 阈值类条件展示**当前生效值**(滑杆调完,手册跟着变——"参数是活的"本身是教学点);
4. 每条规则能指出代码位置与对应 learn/ 章节,和教程互为索引。

非目标(明确排除):逐对象的"为什么没命中我"解释;一键触发演示;
规则说明的自动推导。这些可作后续迭代。

## 方案(A,已确认)

Python 声明式规则注册表(`engine/rule_meta.py`)+ `GET /api/rules` + 学习路径 Tab 渲染。
否决的备选:Markdown 手册(两处维护,漂移风险与 AGENTS.md 纪律相悖)、
前端推导 SPARQL 说明(人工映射换载体,徒增复杂度)。

## 规则清单(7 条)

状态建议规则(engine/rules.py,"情况 → 建议",每次刷新重算,是推论不是数据):

| id | 名称 | 触发条件 | 教学点 | 章节 |
|----|------|---------|--------|------|
| rest-player | 轮休 | 体能 < {fitness_floor} 且 近期高强度出场(任一场 ≥ 60 分钟)≥ 3 场 | 阈值/计数类业务规则放 Python 不放 OWL;两个条件缺一不可(阿利松案例) | learn/04 |
| callup-youth | 征调青年队 | 某位置可用一线队球员 < 2(可用 = 未伤停)且存在未征调的该位置青年队球员 | 位置是类成员建模;YouthPlayer ⊑ Player 的类型推理进建议 | learn/03、04 |
| start-treatment | 启动治疗 | 伤停 ≥ 3 周 | 严重度阈值;触发审批而非直接执行 | learn/04 |

治理机制(engine/actions.py,"建议 → 行动的边界"):

| id | 名称 | 语义 | 教学点 | 章节 |
|----|------|------|--------|------|
| roster-limit | 报名上限(征调前置条件) | 报名名单(一线队 + 已征调)< {roster_limit};违反则写 veto 并拒绝执行 | 前置条件是否决不是报错;veto 是写进 effects 的事实 | learn/04(步骤 5) |
| treatment-approval | 治疗两步审批 | StartTreatment 首次执行 pending,对同一动作再次执行才确认 | 审批动作的中间态:200 + pending,不是 409 | learn/04 |
| veto-suppression | veto 抑制 | 被否决的动作不再出现在建议清单 | 建议是推论:条件事实在,推论自然消失 | learn/04 |
| audit-trail | 审计留痕 | 每次执行/否决/事件写审计,step 为确定性步进计数器 | 治理可追溯;不引入 wall-clock | learn/04 |

## 数据结构

新建 `engine/rule_meta.py`,模块 docstring 说明"规则手册是规则的声明式元数据,
权威语义仍在 rules.py / actions.py 的实现与测试里"。

```python
RULES = [
    {
        "id": "rest-player",
        "name": "轮休",
        "category": "suggestion",          # suggestion | governance
        "summary": "过度使用的球员应当轮休恢复。",
        "conditions": [                     # 条件列表,全部满足才触发
            {"text": "体能低于阈值 {fitness_floor}", "params": ["fitness_floor"]},
            {"text": "近期高强度出场(任一场 ≥ 60 分钟)至少 3 场", "params": []},
        ],
        "code": "engine/rules.py:104",      # 阅读入口
        "chapter": "learn/04-从状态到行动.md",
    },
    ...
]

def render(params: dict) -> list:
    """代入当前参数,返回前端可直接渲染的条目(conditions.text 已格式化)。"""
```

单一来源的两道锁:

1. **import 层**:`rule_meta` 引用 `actions.ROSTER_LIMIT`、`EFFECTS` 的类型键、
   `APPROVAL` 集合,常量改动自动传导;
2. **契约测试**:断言 `RULES` 覆盖 `EFFECTS` 的全部动作类型(3 条建议规则各有一条目)
   且 governance 条目数 ≥ 4——手册漏了规则,测试红。

参数解析:`fitness_floor` 来自 `kb.params`(滑杆实时值);
`roster_limit` 来自 `actions.ROSTER_LIMIT`(常量)。
`render(params)` 只做 `str.format`,不引入新逻辑。

## API

`GET /api/rules`(只读,经 `kb._lock`):

```json
{"rules": [{"id": "rest-player", "name": "轮休", "category": "suggestion",
            "summary": "…", "conditions": ["体能低于阈值 75", "…"],
            "code": "engine/rules.py:104", "chapter": "learn/04-…"}, …]}
```

`KnowledgeBase.rules_view()` 委托 `rule_meta.render(dict(self.params) | {"roster_limit": ROSTER_LIMIT})`。

## 前端

学习路径 Tab,四章卡片之后新增"规则手册"区(kicker + 两组):

- **状态建议规则**(3 张小卡)/ **治理边界**(4 张小卡);
- 卡片:规则名、summary、条件列表(动态阈值加高亮样式,如 `<b>75</b>`)、
  底部小标签:代码位置 + 教程章节文件名;
- `loadRules()`:初始加载;`onFloorSlider` 的防抖回调里追加调用,
  滑杆一动手册里的阈值同步刷新;
- 样式沿用 `.learn-card` 的视觉语言,新增少量 `.rule-*` 类。

## 测试

- `tests/test_api.py`:`/api/rules` 返回 7 条;`POST /api/params` 改阈值后,
  再查 `/api/rules`,条件文本里的阈值随之变化。
- `tests/test_rules.py` 增补契约测试:RULES 覆盖 EFFECTS 全部动作类型;
  治理条目 ≥ 4;`render` 对缺参数抛 KeyError(防手滑写错参数名)。

## 收尾

- AGENTS.md「关键模块」小节补一行 `engine/rule_meta.py`;
- learn/04 若有"规则清单"式表述,核对手册条件与正文一致(以实现为准)。

## 改动文件清单

新:`engine/rule_meta.py`
改:`engine/knowledge_base.py`、`api/main.py`、`web/index.html`、`web/app.js`、
`web/style.css`、`tests/test_api.py`、`tests/test_rules.py`、`AGENTS.md`
