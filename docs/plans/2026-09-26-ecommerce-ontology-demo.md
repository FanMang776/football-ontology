# 电商本体论 Demo 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建一个可交互学习的电商本体 demo：真实 OWL 推理引擎 + 五 Tab 可视化界面 + 决策执行闭环 + 配套教程。

**Architecture:** 本体（schema.ttl + data.ttl）由 RDFLib 加载、owlrl 做 OWL-RL 物化推理；规则层（SPARQL CONSTRUCT）做 VIP 分类和建议动作生成；执行器把动作效果作为新事实写回并重新推理；FastAPI 暴露 API 并托管静态前端（Cytoscape.js）。

**Tech Stack:** Python 3.10+, rdflib, owlrl, FastAPI, uvicorn, pytest, httpx, 原生 JS + Cytoscape.js (CDN)

**设计文档:** `docs/plans/2026-09-26-ecommerce-ontology-demo-design.md`

---

## 与设计文档的实现精化（两处偏差，均为简化）

1. **品类建模为类（categories-as-classes）**：设计文档中的 `belongsToCategory` 属性取消。品类（蓝牙耳机、耳机、数码配件…）直接建成 `owl:Class`，用 `rdfs:subClassOf` 组成品类树；商品用 `rdf:type` 挂到叶子品类上，祖先品类的归属完全由 OWL 子类推理得出。这是本体建模的经典手法，教学价值更高。
2. **数据规模精简**：15 个商品（含 3 个套装，1 个嵌套）、9 个品类节点、6 个供应商、10 个客户、18 个订单、4 个促销活动。小数据让每个测试期望都可手工核对。

**数据故事线（所有测试期望都基于此，务必核对）**：

- 供应商「声科电子」(sup_shengke) 供应 3 个商品：p_bt01、p_bt02、p_hub —— 被标记延迟后触发全场景。
- 嵌套套装：b_ultimate hasPart b_music + p_spk1；b_music hasPart p_bt01 + p_amp。传递推理后 b_ultimate hasPart p_bt01。
- 替代品：p_bt01 substituteFor p_x2（云音，库存 120）；p_bt02 substituteFor p_buds（蓝湾，库存 200）；p_hub 无替代品（教学案例：采购动作无法生成）。
- VIP 边界卡位：张伟 8200✓、王磊 5400✓、周宇 5200✓（>5000）；孙丽恰好 5000✗；李娜银卡 4 单✓、陈静银卡恰好 3 单✓、赵敏银卡 2 单✗；罗浩金卡但低消费✗（金卡不直接 VIP）。预期 VIP = {张伟, 王磊, 周宇, 李娜, 陈静}。
- 预期风险传导（声科延迟）：商品 [p_bt01, p_bt02, p_hub]；套装 [b_music, b_ultimate]；促销 [promo_618（推品类）, promo_music（推套装）]——promo_ultimate 因 status=paused 被排除、promo_travel 不含声科商品；待发货订单 [o1, o3, o4, o8, o14]；受影响 VIP 客户 [张伟, 李娜, 王磊]（赵敏的 o8 也是待发货含 p_bt02 但她不是 VIP，通知规则排除她）。
- 预期建议动作 9 条：暂停促销×2、通知客户×3、生成采购单×2（p_hub 无替代品故无）、推荐替代品×2。全部执行后，动作清单归零（每条规则都带 FILTER NOT EXISTS 前置检查，效果写回后条件不再成立——这是"建议动作也是推论"的关键设计）。

---

### Task 1: 项目骨架与环境

**Files:**
- Create: `requirements.txt`, `.gitignore`, `engine/__init__.py`, `api/__init__.py`, `tests/__init__.py`

**Step 1: 写入以下文件**

`requirements.txt`:
```
rdflib>=7.0
owlrl>=6.0.2
fastapi>=0.110
uvicorn>=0.29
pytest>=8.0
httpx>=0.27
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

空包文件 `engine/__init__.py`、`api/__init__.py`、`tests/__init__.py`（空文件即可）。

**Step 2: 安装依赖并验证**

Run: `pip install -r requirements.txt && python -c "import rdflib, owlrl, fastapi; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: 项目骨架与依赖"
```

---

### Task 2: schema.ttl —— 本体模式（TBox）

**Files:**
- Create: `ontology/schema.ttl`

**Step 1: 写入完整内容**（每个品类都显式声明 `a owl:Class`，保证动作规则的 `?x a owl:Class` 分支成立）

```turtle
@prefix ex: <http://example.org/ecom#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

########################
# 顶层类
########################
ex:BusinessObject a owl:Class ; rdfs:label "业务对象"@zh .
ex:Product  rdfs:subClassOf ex:BusinessObject ; rdfs:label "商品"@zh .
ex:Bundle   rdfs:subClassOf ex:Product ; rdfs:label "捆绑套装"@zh .
ex:Party    rdfs:subClassOf ex:BusinessObject ; rdfs:label "参与方"@zh .
ex:Supplier rdfs:subClassOf ex:Party ; rdfs:label "供应商"@zh .
ex:Customer rdfs:subClassOf ex:Party ; rdfs:label "客户"@zh .
# VIPCustomer 只会被规则层推断出来，数据中永远不声明
ex:VIPCustomer rdfs:subClassOf ex:Customer ; rdfs:label "高价值客户"@zh .
ex:Order     rdfs:subClassOf ex:BusinessObject ; rdfs:label "订单"@zh .
ex:OrderLine rdfs:subClassOf ex:BusinessObject ; rdfs:label "订单明细"@zh .
ex:Promotion rdfs:subClassOf ex:BusinessObject ; rdfs:label "促销活动"@zh .

########################
# 决策动作——本体不仅描述业务，也描述"可做的事"
########################
ex:Action              rdfs:subClassOf ex:BusinessObject ; rdfs:label "决策动作"@zh .
ex:PausePromotion      rdfs:subClassOf ex:Action ; rdfs:label "暂停促销"@zh .
ex:NotifyCustomer      rdfs:subClassOf ex:Action ; rdfs:label "通知客户"@zh .
ex:CreatePurchaseOrder rdfs:subClassOf ex:Action ; rdfs:label "生成采购单"@zh .
ex:PromoteSubstitute   rdfs:subClassOf ex:Action ; rdfs:label "推荐替代品"@zh .

########################
# 品类即类：品类树就是 subClassOf 树（实现精化①）
########################
ex:cat_electronics a owl:Class ; rdfs:subClassOf ex:Product ; rdfs:label "电子产品"@zh .
ex:cat_digital_acc a owl:Class ; rdfs:subClassOf ex:cat_electronics ; rdfs:label "数码配件"@zh .
ex:cat_headphone   a owl:Class ; rdfs:subClassOf ex:cat_digital_acc ; rdfs:label "耳机"@zh .
ex:cat_charger     a owl:Class ; rdfs:subClassOf ex:cat_digital_acc ; rdfs:label "充电设备"@zh .
ex:cat_cable       a owl:Class ; rdfs:subClassOf ex:cat_digital_acc ; rdfs:label "线材"@zh .
ex:cat_audio       a owl:Class ; rdfs:subClassOf ex:cat_digital_acc ; rdfs:label "音频设备"@zh .
ex:cat_speaker     a owl:Class ; rdfs:subClassOf ex:cat_audio ; rdfs:label "音箱"@zh .
ex:cat_home        a owl:Class ; rdfs:subClassOf ex:Product ; rdfs:label "智能家居"@zh .
ex:cat_bulb        a owl:Class ; rdfs:subClassOf ex:cat_home ; rdfs:label "智能灯泡"@zh .

########################
# 对象属性与公理（推理能力的来源）
########################
ex:suppliedBy     a owl:ObjectProperty ; rdfs:label "由…供应"@zh .
ex:hasPart        a owl:ObjectProperty , owl:TransitiveProperty ; rdfs:label "包含"@zh .
ex:isComponentOf  a owl:ObjectProperty ; owl:inverseOf ex:hasPart ; rdfs:label "是…的组成部分"@zh .
ex:substituteFor  a owl:ObjectProperty , owl:SymmetricProperty ; rdfs:label "替代"@zh .
ex:compatibleWith a owl:ObjectProperty , owl:SymmetricProperty ; rdfs:label "兼容"@zh .
ex:sameSeries     a owl:ObjectProperty , owl:SymmetricProperty ; rdfs:label "同系列"@zh .
ex:placedOrder    a owl:ObjectProperty ; rdfs:label "已下单"@zh .
ex:hasLine        a owl:ObjectProperty ; rdfs:label "包含明细"@zh .
ex:lineProduct    a owl:ObjectProperty ; rdfs:label "明细商品"@zh .
ex:promotes       a owl:ObjectProperty ; rdfs:label "推广"@zh .
ex:hasTarget      a owl:ObjectProperty ; rdfs:label "动作目标"@zh .
ex:hasSupplier    a owl:ObjectProperty ; rdfs:label "动作相关供应商"@zh .

########################
# 数据属性
########################
ex:price           a owl:DatatypeProperty ; rdfs:label "价格"@zh .
ex:stock           a owl:DatatypeProperty ; rdfs:label "库存"@zh .
ex:annualSpend     a owl:DatatypeProperty ; rdfs:label "年消费额"@zh .
ex:membershipLevel a owl:DatatypeProperty ; rdfs:label "会员等级"@zh .
ex:status          a owl:DatatypeProperty ; rdfs:label "状态"@zh .
ex:orderStatus     a owl:DatatypeProperty ; rdfs:label "订单状态"@zh .
ex:notified        a owl:DatatypeProperty ; rdfs:label "已通知"@zh .
ex:restockRequested a owl:DatatypeProperty ; rdfs:label "已请求补货"@zh .
ex:promoBoosted    a owl:DatatypeProperty ; rdfs:label "已加推"@zh .
ex:hasReason       a owl:DatatypeProperty ; rdfs:label "动作原因"@zh .
```

**Step 2: 解析验证**

Run: `python -c "from rdflib import Graph; g=Graph(); g.parse('ontology/schema.ttl', format='turtle'); print(len(g))"`
Expected: 一个 ≥ 80 的整数，无 ParseError

**Step 3: Commit**

```bash
git add ontology/schema.ttl && git commit -m "feat: 本体模式 schema.ttl（类层级、公理、动作类）"
```

---

### Task 3: data.ttl —— 业务事实（ABox）

**Files:**
- Create: `ontology/data.ttl`

**Step 1: 写入完整内容**（对照「数据故事线」，不要增删）

```turtle
@prefix ex: <http://example.org/ecom#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

########################
# 供应商（默认状态 active；"delayed" 由运行时动作写回，不在数据里）
########################
ex:sup_shengke a ex:Supplier ; rdfs:label "声科电子"@zh ; ex:status "active" .
ex:sup_lanwan  a ex:Supplier ; rdfs:label "蓝湾制造"@zh ; ex:status "active" .
ex:sup_xinglian a ex:Supplier ; rdfs:label "星联电子"@zh ; ex:status "active" .
ex:sup_hongda  a ex:Supplier ; rdfs:label "宏达配件"@zh ; ex:status "active" .
ex:sup_yunyin  a ex:Supplier ; rdfs:label "云音科技"@zh ; ex:status "active" .
ex:sup_huijin  a ex:Supplier ; rdfs:label "汇金数码"@zh ; ex:status "active" .

########################
# 商品
########################
ex:p_bt01 a ex:PhysicalProduct ; rdfs:label "降噪蓝牙耳机 BT-01"@zh ;
    ex:suppliedBy ex:sup_shengke ; ex:price 899 ; ex:stock 40 ;
    a ex:cat_headphone ;
    ex:substituteFor ex:p_x2 ;          # 声明一个方向，对称推理得出反向
    ex:sameSeries ex:p_bt02 ;
    ex:compatibleWith ex:p_amp .
ex:p_bt02 a ex:PhysicalProduct ; rdfs:label "蓝牙耳机 BT-02"@zh ;
    ex:suppliedBy ex:sup_shengke ; ex:price 599 ; ex:stock 25 ;
    a ex:cat_headphone ;
    ex:substituteFor ex:p_buds .
ex:p_x2   a ex:PhysicalProduct ; rdfs:label "头戴耳机 X2"@zh ;
    ex:suppliedBy ex:sup_yunyin ; ex:price 549 ; ex:stock 120 ;
    a ex:cat_headphone .
ex:p_amp  a ex:PhysicalProduct ; rdfs:label "便携耳放 Amp-Mini"@zh ;
    ex:suppliedBy ex:sup_yunyin ; ex:price 459 ; ex:stock 60 ;
    a ex:cat_audio .
ex:p_dac  a ex:PhysicalProduct ; rdfs:label "小尾巴解码 DAC"@zh ;
    ex:suppliedBy ex:sup_yunyin ; ex:price 429 ; ex:stock 90 ;
    a ex:cat_audio ; ex:compatibleWith ex:p_x2 .
ex:p_buds a ex:PhysicalProduct ; rdfs:label "无线耳塞 Buds3"@zh ;
    ex:suppliedBy ex:sup_lanwan ; ex:price 399 ; ex:stock 200 ;
    a ex:cat_headphone .
ex:p_ch65 a ex:PhysicalProduct ; rdfs:label "65W 氮化镓充电器"@zh ;
    ex:suppliedBy ex:sup_hongda ; ex:price 199 ; ex:stock 80 ;
    a ex:cat_charger ; ex:compatibleWith ex:p_bt01 .
ex:p_ch20 a ex:PhysicalProduct ; rdfs:label "20W 充电器"@zh ;
    ex:suppliedBy ex:sup_hongda ; ex:price 79 ; ex:stock 150 ;
    a ex:cat_charger .
ex:p_usbc a ex:PhysicalProduct ; rdfs:label "USB-C 编织线"@zh ;
    ex:suppliedBy ex:sup_hongda ; ex:price 39 ; ex:stock 500 ;
    a ex:cat_cable .
ex:p_spk1 a ex:PhysicalProduct ; rdfs:label "桌面音箱 S1"@zh ;
    ex:suppliedBy ex:sup_xinglian ; ex:price 429 ; ex:stock 60 ;
    a ex:cat_speaker .
ex:p_bulb1 a ex:PhysicalProduct ; rdfs:label "智能灯泡 L1"@zh ;
    ex:suppliedBy ex:sup_huijin ; ex:price 99 ; ex:stock 300 ;
    a ex:cat_bulb .
ex:p_hub  a ex:PhysicalProduct ; rdfs:label "六合一扩展坞 Hub6"@zh ;
    ex:suppliedBy ex:sup_shengke ; ex:price 349 ; ex:stock 15 ;
    a ex:cat_digital_acc .              # 无替代品——采购动作的教学案例

########################
# 套装（hasPart 传递；b_ultimate 嵌套 b_music）
########################
ex:b_music a ex:Bundle ; rdfs:label "音乐套装"@zh ;
    ex:price 1299 ; ex:stock 30 ;
    ex:hasPart ex:p_bt01 , ex:p_amp .
ex:b_travel a ex:Bundle ; rdfs:label "出行套装"@zh ;
    ex:price 599 ; ex:stock 50 ;
    ex:hasPart ex:p_ch65 , ex:p_usbc , ex:p_buds .
ex:b_ultimate a ex:Bundle ; rdfs:label "全家桶套装"@zh ;
    ex:price 1899 ; ex:stock 12 ;
    ex:hasPart ex:b_music , ex:p_spk1 .

########################
# 客户（VIP 边界卡位见故事线）
########################
ex:c_zhangwei a ex:Customer ; rdfs:label "张伟"@zh ; ex:annualSpend 8200 ; ex:membershipLevel "gold" .
ex:c_lina     a ex:Customer ; rdfs:label "李娜"@zh ; ex:annualSpend 4600 ; ex:membershipLevel "silver" .
ex:c_wanglei  a ex:Customer ; rdfs:label "王磊"@zh ; ex:annualSpend 5400 ; ex:membershipLevel "silver" .
ex:c_chenjing a ex:Customer ; rdfs:label "陈静"@zh ; ex:annualSpend 2100 ; ex:membershipLevel "silver" .
ex:c_zhaomin  a ex:Customer ; rdfs:label "赵敏"@zh ; ex:annualSpend 1999 ; ex:membershipLevel "silver" .
ex:c_sunli    a ex:Customer ; rdfs:label "孙丽"@zh ; ex:annualSpend 5000 ; ex:membershipLevel "gold" .
ex:c_zhouyu   a ex:Customer ; rdfs:label "周宇"@zh ; ex:annualSpend 5200 ; ex:membershipLevel "silver" .
ex:c_wufan    a ex:Customer ; rdfs:label "吴凡"@zh ; ex:annualSpend 800 ; ex:membershipLevel "none" .
ex:c_xuqian   a ex:Customer ; rdfs:label "徐倩"@zh ; ex:annualSpend 3200 ; ex:membershipLevel "none" .
ex:c_luohei   a ex:Customer ; rdfs:label "罗浩"@zh ; ex:annualSpend 1500 ; ex:membershipLevel "gold" .

########################
# 订单与明细（pending 且含声科商品的才触发通知）
########################
ex:o1  a ex:Order ; ex:placedBy ex:c_zhangwei ; ex:orderStatus "pending" ;
    ex:hasLine ex:o1_l1 . ex:o1_l1 a ex:OrderLine ; ex:lineProduct ex:p_bt01 .
ex:o2  a ex:Order ; ex:placedBy ex:c_zhangwei ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o2_l1 . ex:o2_l1 a ex:OrderLine ; ex:lineProduct ex:p_spk1 .
ex:o3  a ex:Order ; ex:placedBy ex:c_lina ; ex:orderStatus "pending" ;
    ex:hasLine ex:o3_l1 , ex:o3_l2 . ex:o3_l1 a ex:OrderLine ; ex:lineProduct ex:p_bt01 .
ex:o3_l2 a ex:OrderLine ; ex:lineProduct ex:p_amp .
ex:o4  a ex:Order ; ex:placedBy ex:c_wanglei ; ex:orderStatus "pending" ;
    ex:hasLine ex:o4_l1 . ex:o4_l1 a ex:OrderLine ; ex:lineProduct ex:p_hub .
ex:o5  a ex:Order ; ex:placedBy ex:c_chenjing ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o5_l1 . ex:o5_l1 a ex:OrderLine ; ex:lineProduct ex:p_ch65 .
ex:o6  a ex:Order ; ex:placedBy ex:c_chenjing ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o6_l1 . ex:o6_l1 a ex:OrderLine ; ex:lineProduct ex:p_usbc .
ex:o7  a ex:Order ; ex:placedBy ex:c_chenjing ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o7_l1 . ex:o7_l1 a ex:OrderLine ; ex:lineProduct ex:p_buds .
ex:o8  a ex:Order ; ex:placedBy ex:c_zhaomin ; ex:orderStatus "pending" ;
    ex:hasLine ex:o8_l1 . ex:o8_l1 a ex:OrderLine ; ex:lineProduct ex:p_bt02 .
ex:o9  a ex:Order ; ex:placedBy ex:c_sunli ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o9_l1 . ex:o9_l1 a ex:OrderLine ; ex:lineProduct ex:p_x2 .
ex:o10 a ex:Order ; ex:placedBy ex:c_zhouyu ; ex:orderStatus "pending" ;
    ex:hasLine ex:o10_l1 . ex:o10_l1 a ex:OrderLine ; ex:lineProduct ex:p_spk1 .
ex:o11 a ex:Order ; ex:placedBy ex:c_luohei ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o11_l1 . ex:o11_l1 a ex:OrderLine ; ex:lineProduct ex:p_ch20 .
ex:o12 a ex:Order ; ex:placedBy ex:c_wufan ; ex:orderStatus "pending" ;
    ex:hasLine ex:o12_l1 . ex:o12_l1 a ex:OrderLine ; ex:lineProduct ex:p_usbc .
ex:o13 a ex:Order ; ex:placedBy ex:c_xuqian ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o13_l1 . ex:o13_l1 a ex:OrderLine ; ex:lineProduct ex:p_bulb1 .
ex:o14 a ex:Order ; ex:placedBy ex:c_zhangwei ; ex:orderStatus "pending" ;
    ex:hasLine ex:o14_l1 . ex:o14_l1 a ex:OrderLine ; ex:lineProduct ex:p_hub .
# 李娜补足 4 单（银卡 ≥3 判 VIP），赵敏补足 2 单（卡在边界外）
ex:o15 a ex:Order ; ex:placedBy ex:c_lina ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o15_l1 . ex:o15_l1 a ex:OrderLine ; ex:lineProduct ex:p_bulb1 .
ex:o16 a ex:Order ; ex:placedBy ex:c_lina ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o16_l1 . ex:o16_l1 a ex:OrderLine ; ex:lineProduct ex:p_ch20 .
ex:o17 a ex:Order ; ex:placedBy ex:c_lina ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o17_l1 . ex:o17_l1 a ex:OrderLine ; ex:lineProduct ex:p_usbc .
ex:o18 a ex:Order ; ex:placedBy ex:c_zhaomin ; ex:orderStatus "shipped" ;
    ex:hasLine ex:o18_l1 . ex:o18_l1 a ex:OrderLine ; ex:lineProduct ex:p_ch20 .

########################
# 促销活动
########################
ex:promo_618 a ex:Promotion ; rdfs:label "数码配件 618 大促"@zh ;
    ex:promotes ex:cat_digital_acc ; ex:status "active" .      # 推广的是"品类"（一个类）
ex:promo_music a ex:Promotion ; rdfs:label "音乐套装限时购"@zh ;
    ex:promotes ex:b_music ; ex:status "active" .
ex:promo_travel a ex:Promotion ; rdfs:label "出行装备节"@zh ;
    ex:promotes ex:b_travel ; ex:status "active" .
ex:promo_ultimate a ex:Promotion ; rdfs:label "全家桶预售"@zh ;
    ex:promotes ex:b_ultimate ; ex:status "paused" .
```

注意：客户→订单的谓词是 `ex:placedBy`（订单指向客户，方向与 schema 中 `placedOrder` 相反）。为一致性，把 schema.ttl 中的 `ex:placedOrder` 改为：

```turtle
ex:placedBy a owl:ObjectProperty ; rdfs:label "下单人"@zh .
```

**Step 2: 解析验证**

Run: `python -c "from rdflib import Graph; g=Graph(); g.parse('ontology/data.ttl', format='turtle'); print(len(g))"`
Expected: ≥ 200 的整数，无 ParseError

**Step 3: Commit**

```bash
git add ontology/data.ttl ontology/schema.ttl && git commit -m "feat: 业务实例 data.ttl（15 商品、10 客户、18 订单、4 促销）"
```

---

### Task 4: engine/namespaces.py + loader.py + 推理测试

**Files:**
- Create: `engine/namespaces.py`, `engine/loader.py`, `tests/test_reasoning.py`

**Step 1: 写失败测试** `tests/test_reasoning.py`：

```python
"""验证 OWL-RL 推理：子类传递、属性传递、对称性、逆属性。"""
from rdflib import RDF

from engine.loader import load_declared, materialize
from engine.namespaces import EX


def kb():
    return materialize(load_declared())


def test_subclass_chain_inferred():
    """蓝牙耳机 BT-01 挂在 cat_headphone 上，应推断出属于全部祖先品类。"""
    g = kb()
    for cat in (EX.cat_headphone, EX.cat_digital_acc, EX.cat_electronics, EX.Product):
        assert (EX.p_bt01, RDF.type, cat) in g


def test_transitive_has_part():
    """b_ultimate hasPart b_music，b_music hasPart p_bt01 → 推断 b_ultimate hasPart p_bt01。"""
    g = kb()
    assert (EX.b_ultimate, EX.hasPart, EX.p_bt01) in g
    assert (EX.b_ultimate, EX.hasPart, EX.p_amp) in g


def test_inverse_is_component_of():
    """hasPart 的逆属性 isComponentOf 应双向物化。"""
    g = kb()
    assert (EX.p_bt01, EX.isComponentOf, EX.b_music) in g
    assert (EX.p_bt01, EX.isComponentOf, EX.b_ultimate) in g


def test_symmetric_substitute():
    """只声明 p_bt01 substituteFor p_x2，应推断出反向。"""
    g = kb()
    assert (EX.p_bt01, EX.substituteFor, EX.p_x2) in g          # 声明的
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) in g          # 推断的


def test_declared_vs_inferred_split():
    """p_x2 substituteFor p_bt01 在原始图中不存在，在物化图中存在。"""
    declared = load_declared()
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) not in declared
    assert (EX.p_x2, EX.substituteFor, EX.p_bt01) in kb()
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_reasoning.py -v`
Expected: FAIL（ModuleNotFoundError: engine）

**Step 3: 写实现**

`engine/namespaces.py`：

```python
from rdflib import Namespace

EX = Namespace("http://example.org/ecom#")
```

`engine/loader.py`：

```python
"""本体加载与 OWL-RL 物化推理。

核心心智模型：图谱有两层——
  声明的三元组 (declared)：schema.ttl + data.ttl 里白纸黑字写的
  推断的三元组 (inferred)：推理机物化出来的，永远不落库、随事实即时重算
"""
from pathlib import Path

from owlrl import OWLRL_Semantics, DeductiveClosure
from rdflib import Graph

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "ontology" / "schema.ttl"
DATA = ROOT / "ontology" / "data.ttl"


def load_declared() -> Graph:
    """加载 TBox + ABox，返回仅含声明三元组的图。TTL 语法错误在此暴露。"""
    g = Graph()
    g.parse(SCHEMA, format="turtle")
    g.parse(DATA, format="turtle")
    return g


def materialize(g: Graph) -> Graph:
    """在副本上运行 OWL-RL 推理闭包，返回物化后的图。

    axioms=False / datatype_axioms=False：关掉 OWL 词汇表的公理三元组，
    否则"推断三元组"里会混入上千条和业务无关的公理，无法教学演示。
    """
    m = Graph()
    for t in g:
        m.add(t)
    DeductiveClosure(OWLRL_Semantics, rdfs_closure=True,
                     axioms=False, datatype_axioms=False).expand(m)
    return m
```

注意：`from owlrl import DeductiveClosure, OWLRL_Semantics`。若运行后子类推理缺失，先确认 `rdfs_closure=True` 没被改动；若"推断三元组"里出现大量 `owl:Thing`、`rdfs:Resource` 之类的公理三元组，说明 `axioms=False` 没生效——Task 4 的第 5 个测试会把它拦下来。

**Step 4: 运行确认通过**

Run: `python -m pytest tests/test_reasoning.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add engine/ tests/test_reasoning.py && git commit -m "feat: 本体加载器与 OWL-RL 物化推理（子类/传递/对称/逆属性）"
```

---

### Task 5: engine/rules.py —— 分类规则（VIP）

**Files:**
- Create: `engine/rules.py`, `tests/test_rules.py`

**Step 1: 写失败测试**（追加到 `tests/test_rules.py`）：

```python
"""业务规则层测试：VIP 分类规则（含边界卡位）与动作规则。"""
from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_vip_rules

EXPECTED_VIP = {EX.c_zhangwei, EX.c_wanglei, EX.c_zhouyu, EX.c_lina, EX.c_chenjing}


def kb_with_delay() -> "tuple[Graph, Graph]":
    """返回（物化图, 附加事实图），附加事实里声科电子被标记为延迟。"""
    from rdflib import Graph, Literal
    base = materialize(load_declared())
    extra = Graph()
    extra.add((EX.sup_shengke, EX.status, Literal("delayed")))
    merged = Graph()
    for t in base:
        merged.add(t)
    for t in extra:
        merged.add(t)
    return merged, extra


def test_vip_default_thresholds():
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    vips = set(out.subjects(None, EX.VIPCustomer))
    assert vips == EXPECTED_VIP


def test_vip_boundary_exact_5000_excluded():
    """孙丽年消费恰好 5000（默认阈值 >5000）不应是 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_sunli, None, EX.VIPCustomer) not in out


def test_vip_silver_needs_three_orders():
    """赵敏银卡只有 2 单，不满足 ≥3；陈静恰好 3 单满足。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_zhaomin, None, EX.VIPCustomer) not in out
    assert (EX.c_chenjing, None, EX.VIPCustomer) in out


def test_vip_gold_alone_insufficient():
    """罗浩是金卡但年消费低——金卡本身不构成 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g)
    assert (EX.c_luohei, None, EX.VIPCustomer) not in out


def test_vip_custom_thresholds():
    """阈值降到 1500 后罗浩（1500 不大于 1500）仍不是，孙丽（5000）成为 VIP。"""
    g = materialize(load_declared())
    out = apply_vip_rules(g, spend_threshold=1500)
    vips = set(out.subjects(None, EX.VIPCustomer))
    assert EX.c_sunli in vips
    assert EX.c_luohei not in vips
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL（No module named engine.rules）

**Step 3: 写实现** `engine/rules.py`：

```python
"""业务规则层：SPARQL CONSTRUCT 产出新三元组。

OWL 负责"分类学与结构逻辑"（Task 4 已验证）；含算术/聚合的业务规则放这里。
规则分两类：分类规则（本文件上半部）与动作规则（下半部）。
"""
from rdflib import Graph, Literal, URIRef
from rdflib.plugins.sparql import prepareQuery

from engine.namespaces import EX

PREFIX = ("PREFIX ex: <http://example.org/ecom#> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX owl: <http://www.w3.org/2002/07/owl#>")

# ---------- 分类规则 ----------

VIP_SPEND = PREFIX + """
CONSTRUCT { ?c a ex:VIPCustomer . }
WHERE {
    ?c a ex:Customer ; ex:annualSpend ?s .
    FILTER(?s > %(spend)d)
}
"""

VIP_SILVER = PREFIX + """
CONSTRUCT { ?c a ex:VIPCustomer . }
WHERE {
    { SELECT ?c (COUNT(DISTINCT ?o) AS ?n)
      WHERE { ?o ex:placedBy ?c . } GROUP BY ?c }
    ?c ex:membershipLevel "silver" .
    FILTER(?n >= %(min_orders)d)
}
"""


def apply_vip_rules(g: Graph, spend_threshold: int = 5000,
                    min_orders: int = 3) -> Graph:
    """返回仅含推断出的 VIPCustomer 类型三元组的图。"""
    out = Graph()
    for tmpl in (VIP_SPEND, VIP_SILVER):
        res = g.query(tmpl % {"spend": spend_threshold, "min_orders": min_orders})
        for t in res:
            out.add(t)
    return out
```

**Step 4: 运行确认通过**

Run: `python -m pytest tests/test_rules.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add engine/rules.py tests/test_rules.py && git commit -m "feat: VIP 分类规则（SPARQL CONSTRUCT，边界卡位验证）"
```

---

### Task 6: engine/rules.py —— 动作规则（情况 → 建议动作）

**Files:**
- Modify: `engine/rules.py`（追加）
- Modify: `tests/test_rules.py`（追加）

**Step 1: 追加失败测试**（`tests/test_rules.py` 末尾，替换 `kb_with_delay` 辅助函数为完整输入版）：

```python
def kb_with_delay() -> "Graph":
    """动作规则的完整输入：物化图 + VIP 推断 + 声科电子延迟。"""
    from rdflib import Graph, Literal

    from engine.rules import apply_vip_rules

    g = materialize(load_declared())
    for t in apply_vip_rules(g):
        g.add(t)
    g.add((EX.sup_shengke, EX.status, Literal("delayed")))
    return g


def test_action_rules_expected_nine():
    """声科延迟 → 2 暂停 + 3 通知 + 2 采购 + 2 推荐 = 9 条建议动作。"""
    from engine.rules import apply_action_rules

    actions, reasons = apply_action_rules(kb_with_delay())
    assert len(actions) == 9
    assert all(v["reason"] for v in reasons.values())


def test_pause_rule_only_active_promos():
    """promo_ultimate 已是 paused、promo_travel 不含声科商品——都不生成暂停建议。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    targets = set(actions.objects(None, EX.hasTarget))
    assert {EX.promo_618, EX.promo_music} <= targets
    assert EX.promo_travel not in targets and EX.promo_ultimate not in targets


def test_notify_only_vip_customers():
    """赵敏有待发货订单 o8 含 p_bt02，但她不是 VIP——通知规则必须排除她。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    notified = set(actions.subjects(RDF.type, EX.NotifyCustomer))
    assert notified == {EX.c_zhangwei, EX.c_lina, EX.c_wanglei}


def test_purchase_order_needs_substitute():
    """p_hub 无替代品 → 无采购动作；p_bt01/p_bt02 各一条。"""
    from rdflib import RDF

    from engine.rules import apply_action_rules

    actions, _ = apply_action_rules(kb_with_delay())
    subs = set(actions.subjects(RDF.type, EX.CreatePurchaseOrder))
    assert subs == {EX.action_CreatePurchaseOrder_p_bt01, EX.action_CreatePurchaseOrder_p_bt02}


def test_actions_deterministic_ids():
    """动作 URI 由（类型, 目标）派生，重复刷新必须稳定（可执行、可测试）。"""
    from engine.rules import apply_action_rules

    a1, _ = apply_action_rules(kb_with_delay())
    a2, _ = apply_action_rules(kb_with_delay())
    assert set(a1.subjects()) == set(a2.subjects())
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_rules.py -v`
Expected: 新增 5 条 FAIL（cannot import name 'apply_action_rules'），原 5 条 PASS

**Step 3: 在 `engine/rules.py` 末尾追加实现**（动作规则用 SELECT 匹配情况，动作三元组与确定性 ID 在 Python 侧组装——rdflib 的 CONSTRUCT 里不便拼接 URI；解释文本也在 Python 侧生成，SPARQL 里拼中文句子不可读）：

```python
# ---------- 动作规则（情况 → 建议动作）----------
# 每条查询末尾的 FILTER NOT EXISTS 是"建议不重复"的关键：
# 执行器把动作效果写回后（status=paused / notified=true / …），
# 条件不再成立，动作自然从建议清单消失——建议动作也是推论，不落库。

Q_PAUSE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?promo WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?promo a ex:Promotion ; ex:status "active" .
    { ?promo ex:promotes ?p . }
    UNION { ?promo ex:promotes ?b . ?p ex:isComponentOf ?b . }
    UNION { ?promo ex:promotes ?c . ?p a ?c . ?c a owl:Class . }
}
""")

Q_NOTIFY = prepareQuery(PREFIX + """
SELECT DISTINCT ?cust WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?o ex:lineProduct ?p ; ex:orderStatus "pending" ; ex:placedBy ?cust .
    ?cust a ex:VIPCustomer .
    FILTER NOT EXISTS { ?cust ex:notified true }
}
""")

Q_PURCHASE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?p2 ?s2 WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?p2 ex:substituteFor ?p ; ex:suppliedBy ?s2 .
    FILTER NOT EXISTS { ?p ex:restockRequested true }
}
""")

Q_SUBSTITUTE = prepareQuery(PREFIX + """
SELECT DISTINCT ?p ?p2 WHERE {
    ?sup ex:status "delayed" .
    ?p ex:suppliedBy ?sup .
    ?p2 ex:substituteFor ?p .
    ?p2 ex:stock ?s . FILTER(?s > 0)
    FILTER NOT EXISTS { ?p2 ex:promoBoosted true }
}
""")


def _action_id(kind: str, *parts) -> URIRef:
    """由（类型, 目标）派生确定性 URI，如 ex:action_NotifyCustomer_c_lina。"""
    names = "_".join([kind] + [str(p).split("#")[-1] for p in parts])
    return URIRef(f"http://example.org/ecom#action_{names}")


def apply_action_rules(g: Graph):
    """返回 (动作三元组图, {动作URI: {"type", "targets", "reason"}})。

    动作实例和推理结论一样是派生物：每次刷新重算，不落库。
    注意：g 必须是已物化且已叠加 VIP 推断的图（Q_NOTIFY 依赖 VIPCustomer 类型）。
    """
    from rdflib.namespace import RDF

    actions = Graph()
    reasons: dict = {}

    def label_of(n) -> str:
        v = g.value(n, RDFS.label)
        return str(v) if v else str(n).split("#")[-1]

    def put(act, kind, targets, reason, extra=()):
        actions.add((act, RDF.type, kind))
        for t in targets:
            actions.add((act, EX.hasTarget, t))
        for p, o in extra:
            actions.add((act, p, o))
        actions.add((act, EX.hasReason, Literal(reason, lang="zh")))
        reasons[act] = {"type": str(kind).split("#")[-1],
                        "targets": list(targets), "reason": reason}

    for row in g.query(Q_PAUSE):
        p, promo = row.p, row.promo
        put(_action_id("PausePromotion", promo), EX.PausePromotion, [promo],
            f"活动「{label_of(promo)}」覆盖了延迟供应商的商品「{label_of(p)}」"
            f"（直接推广该商品、推广其所属套装、或推广其所属品类），建议先暂停。")

    for row in g.query(Q_NOTIFY):
        cust = row.cust
        put(_action_id("NotifyCustomer", cust), EX.NotifyCustomer, [cust],
            f"VIP 客户「{label_of(cust)}」有待发货订单包含延迟供应商的商品，建议主动通知。")

    for row in g.query(Q_PURCHASE):
        p, p2, s2 = row.p, row.p2, row.s2
        put(_action_id("CreatePurchaseOrder", p), EX.CreatePurchaseOrder, [p],
            f"「{label_of(p)}」受供应风险影响，其替代品「{label_of(p2)}」由"
            f"「{label_of(s2)}」供应——采购转向依据 substituteFor 关系。",
            extra=[(EX.hasSupplier, s2)])

    for row in g.query(Q_SUBSTITUTE):
        p, p2 = row.p, row.p2
        put(_action_id("PromoteSubstitute", p2), EX.PromoteSubstitute, [p2],
            f"「{label_of(p)}」受供应风险影响，推荐位切换到有货的替代品「{label_of(p2)}」。")

    return actions, reasons
```

同时补齐文件顶部 import（`from rdflib.namespace import RDF, RDFS` 并删掉原函数内零散的同名 import）。

**Step 4: 运行确认通过**

Run: `python -m pytest tests/test_rules.py -v`
Expected: 10 passed

**Step 5: Commit**

```bash
git add engine/rules.py tests/test_rules.py && git commit -m "feat: 动作规则——情况到建议动作的映射（含确定性动作 ID 与不重复前置）"
```

---

### Task 7: engine/scenarios.py —— 三个决策场景

**Files:**
- Create: `engine/queries.py`, `engine/scenarios.py`, `tests/test_scenarios.py`

**Step 1: 写失败测试** `tests/test_scenarios.py`：

```python
"""场景级测试：声科电子延迟的完整传导结果必须与手工核对一致。"""
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

kb = KnowledgeBase()   # 模块级共享一个实例，测试间用 reset 隔离


def setup_function(_):
    kb.reset()


def test_supplier_risk_full_chain():
    result = kb.supplier_risk(EX.sup_shengke, delayed=True)
    assert [p["id"] for p in result["products"]] == ["p_bt01", "p_bt02", "p_hub"]
    assert {b["id"] for b in result["bundles"]} == {"b_music", "b_ultimate"}
    assert {x["id"] for x in result["promotions"]} == {"promo_618", "promo_music"}
    assert {o["id"] for o in result["pending_orders"]} == {"o1", "o3", "o4", "o8", "o14"}
    assert {c["id"] for c in result["vip_customers"]} == {"c_zhangwei", "c_lina", "c_wanglei"}
    # 每一步传导都要有解释
    assert all(step["explanation"] for step in result["chain"])
    assert len(result["chain"]) == 5


def test_supplier_risk_unmark_resolves():
    kb.supplier_risk(EX.sup_shengke, delayed=True)
    result = kb.supplier_risk(EX.sup_shengke, delayed=False)
    assert result["products"] == [] and result["vip_customers"] == []


def test_vip_classification_reasons():
    result = kb.vip_classification(5000, 3)
    ids = {v["id"] for v in result["vips"]}
    assert ids == {"c_zhangwei", "c_wanglei", "c_zhouyu", "c_lina", "c_chenjing"}
    reasons = {v["id"]: v["reason"] for v in result["vips"]}
    assert "5000" in reasons["c_zhangwei"]      # 年消费路径
    assert "3" in reasons["c_chenjing"]         # 银卡订单数路径
    assert "4" in reasons["c_lina"]


def test_recommend_contrast():
    result = kb.recommend(EX.p_bt01)
    naive = {x["id"] for x in result["naive"]}
    semantic = {x["id"] for x in result["semantic"]}
    assert naive == {"p_bt02", "p_x2", "p_buds"}           # 同品类（含推理出的品类成员）
    assert semantic == {"p_x2", "p_bt02", "p_amp", "p_ch65"}
    by_id = {x["id"]: x for x in result["semantic"]}
    assert "替代" in by_id["p_x2"]["relation_label"]
    assert by_id["p_ch65"]["relation"] == "compatibleWith"  # 声明的反向（对称推理）
    assert all(x["relation"] for x in result["semantic"])   # 每条推荐都有语义依据
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_scenarios.py -v`
Expected: FAIL（No module named engine.knowledge_base）

**Step 3: 写实现**

`engine/knowledge_base.py`（把加载、推理、规则、效果写回编排成一个小引擎——API 与测试都面对它）：

```python
"""知识库引擎：声明层 + 效果层 + 推理 + 规则，全部内存态。

分层（自底向上）：
  declared  schema.ttl + data.ttl（不可变）
  effects   运行时写回的事实（供应商延迟、动作执行效果）——可 reset
  material  declared+effects 过 OWL-RL 闭包
  rule_out  VIP 分类规则 + 动作规则的产出（每次刷新重算，是推论不是数据）
"""
from rdflib import Graph, Literal

from engine.loader import load_declared, materialize
from engine.namespaces import EX
from engine.rules import apply_action_rules, apply_vip_rules


class KnowledgeBase:
    def __init__(self):
        self.declared = load_declared()
        self.effects = Graph()
        self.vip_params = {"spend": 5000, "min_orders": 3}
        self.refresh()

    # ---------- 基础 ----------
    def reset(self):
        self.effects = Graph()
        self.vip_params = {"spend": 5000, "min_orders": 3}
        self.refresh()

    def refresh(self):
        merged = Graph()
        for t in self.declared:
            merged.add(t)
        for t in self.effects:
            merged.add(t)
        self.material = materialize(merged)
        self.vip_out = apply_vip_rules(self.material, **self.vip_params)
        rule_input = Graph()
        for t in self.material:
            rule_input.add(t)
        for t in self.vip_out:
            rule_input.add(t)
        self.actions, self.action_reasons = apply_action_rules(rule_input)

    def _add_effect(self, s, p, o):
        self.effects.add((s, p, o))

    # ---------- 场景 1：供应风险传导 ----------
    def supplier_risk(self, supplier, delayed: bool) -> dict:
        triple = (supplier, EX.status, Literal("delayed"))
        if delayed:
            self._add_effect(*triple)
        else:
            self.effects.remove(triple)
        self.refresh()
        return self.risk_snapshot(supplier) if delayed else self._empty_risk()

    def risk_snapshot(self, supplier) -> dict:
        from engine.scenarios import risk_chain
        return risk_chain(self, supplier)

    @staticmethod
    def _empty_risk() -> dict:
        return {"products": [], "bundles": [], "promotions": [],
                "pending_orders": [], "vip_customers": [], "chain": []}

    # ---------- 场景 2：VIP 分类 ----------
    def vip_classification(self, spend: int, min_orders: int) -> dict:
        self.vip_params = {"spend": spend, "min_orders": min_orders}
        self.refresh()
        from engine.scenarios import vip_report
        return vip_report(self, spend, min_orders)

    # ---------- 场景 3：语义推荐 ----------
    def recommend(self, product) -> dict:
        from engine.scenarios import recommend_report
        return recommend_report(self, product)
```

`engine/queries.py`（完整实现——每个决策问题就是一条图谱查询；绑定变量 `?sup` / `?p` 通过 `initBindings` 传入；谓词名必须用 `BIND` 显式绑定，SPARQL 属性路径写法拿不到谓词）：

```python
"""场景 SPARQL 查询：每个决策问题就是一条图谱查询。"""
PREFIX = ("PREFIX ex: <http://example.org/ecom#> "
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX owl: <http://www.w3.org/2002/07/owl#>")

PRODUCTS_OF_SUPPLIER = PREFIX + """
SELECT ?p ?label WHERE {
    ?p ex:suppliedBy ?sup ; rdfs:label ?label .
} ORDER BY ?p
"""

# ?p 的所有祖先套装——isComponentOf 的传递 + 逆属性物化结果，一条查询直达任意深度
BUNDLES_OF_PRODUCT = PREFIX + """
SELECT ?b ?label WHERE {
    ?p ex:isComponentOf ?b ; rdfs:label ?label .
} ORDER BY ?b
"""

PROMOS_TOUCHING_PRODUCT = PREFIX + """
SELECT DISTINCT ?promo ?label WHERE {
    ?promo rdfs:label ?label ; ex:status "active" .
    { ?promo ex:promotes ?p . }                                    # 直接推广该商品
    UNION { ?promo ex:promotes ?b . ?p ex:isComponentOf ?b . }     # 推广其所属套装
    UNION { ?promo ex:promotes ?c . ?p a ?c . ?c a owl:Class . }   # 推广其所属品类
}
"""

PENDING_ORDERS_WITH_PRODUCT = PREFIX + """
SELECT DISTINCT ?o ?cust ?custLabel WHERE {
    ?o ex:orderStatus "pending" ; ex:placedBy ?cust .
    ?cust rdfs:label ?custLabel .
}
"""

LINES_OF_ORDER = PREFIX + """
SELECT ?product WHERE { ?o ex:hasLine ?line . ?line ex:lineProduct ?product . }
"""

ORDER_COUNTS = PREFIX + """
SELECT ?c (COUNT(DISTINCT ?o) AS ?n) WHERE { ?o ex:placedBy ?c . } GROUP BY ?c
"""

# 朴素推荐：同品类其他商品。品类成员关系（?other a ?cat）本身是子类推理的结果；
# 用 cat_ 前缀限定排除 Product/Bundle 这类结构性父类
NAIVE_SAME_CATEGORY = PREFIX + """
SELECT DISTINCT ?other ?label WHERE {
    ?p a ?cat . ?other a ?cat ; rdfs:label ?label .
    ?cat a owl:Class .
    FILTER(STRSTARTS(STR(?cat), "http://example.org/ecom#cat_"))
    FILTER(?other != ?p)
} ORDER BY ?other
"""

# 语义推荐：三条语义边，双向匹配（对称属性的反向是推理出来的，一样有效）
SEMANTIC_RELATIONS = PREFIX + """
SELECT DISTINCT ?other ?rel ?label WHERE {
    { ?p ex:substituteFor ?other . BIND("substituteFor" AS ?rel) }
    UNION { ?other ex:substituteFor ?p . BIND("substituteFor" AS ?rel) }
    UNION { ?p ex:compatibleWith ?other . BIND("compatibleWith" AS ?rel) }
    UNION { ?other ex:compatibleWith ?p . BIND("compatibleWith" AS ?rel) }
    UNION { ?p ex:sameSeries ?other . BIND("sameSeries" AS ?rel) }
    UNION { ?other ex:sameSeries ?p . BIND("sameSeries" AS ?rel) }
    ?other rdfs:label ?label .
    FILTER(?other != ?p)
} ORDER BY ?other
"""
```

`engine/scenarios.py`（完整实现）：

```python
"""决策场景编排：图谱查询 → 结构化结果 → 每一步传导的自然语言解释。"""
from rdflib import RDF, RDFS

from engine import queries as q
from engine.namespaces import EX

REL_ZH = {"substituteFor": "替代品", "compatibleWith": "兼容配件", "sameSeries": "同系列"}


def _label(g, node) -> str:
    v = g.value(node, RDFS.label)
    return str(v) if v else str(node).split("#")[-1]


def _id(node) -> str:
    return str(node).split("#")[-1]


def _rows(g, query, bindings=None):
    return list(g.query(query, initBindings=bindings or {}))


def risk_chain(kb, supplier) -> dict:
    """声科延迟后的完整风险视图：每一步传导都标注它依赖的公理/规则。"""
    g = kb.material

    products = [{"id": _id(r.p), "label": str(r.label)}
                for r in _rows(g, q.PRODUCTS_OF_SUPPLIER, {"sup": supplier})]
    product_nodes = [EX[p["id"]] for p in products]

    bundles, seen = [], set()
    for pnode in product_nodes:
        for r in _rows(g, q.BUNDLES_OF_PRODUCT, {"p": pnode}):
            if r.b not in seen:
                seen.add(r.b)
                bundles.append({"id": _id(r.b), "label": str(r.label)})

    promos, seen = [], set()
    for pnode in product_nodes:
        for r in _rows(g, q.PROMOS_TOUCHING_PRODUCT, {"p": pnode}):
            if r.promo not in seen:
                seen.add(r.promo)
                promos.append({"id": _id(r.promo), "label": str(r.label)})

    pending, vip_affected, seen_c = [], [], set()
    vip_now = set(kb.vip_out.subjects(RDF.type, EX.VIPCustomer))
    for r in _rows(g, q.PENDING_ORDERS_WITH_PRODUCT):
        hits = [x.product for x in _rows(g, q.LINES_OF_ORDER, {"o": r.o})
                if x.product in product_nodes]
        if not hits:
            continue
        pending.append({"id": _id(r.o), "customer": _id(r.cust),
                        "customer_label": str(r.custLabel),
                        "products": [_id(h) for h in hits]})
        if r.cust in vip_now and r.cust not in seen_c:
            seen_c.add(r.cust)
            vip_affected.append({"id": _id(r.cust), "label": str(r.custLabel)})

    chain = [
        {"step": 1, "count": len(products),
         "explanation": "suppliedBy 关系直接反查：哪些商品由该供应商供应"},
        {"step": 2, "count": len(bundles),
         "explanation": "isComponentOf 逆属性 + hasPart 传递推理：套装在任意嵌套深度受影响"},
        {"step": 3, "count": len(promos),
         "explanation": "促销覆盖面：直接推广商品、推广其套装、或推广其品类（品类归属来自子类推理）"},
        {"step": 4, "count": len(pending),
         "explanation": "订单→明细→商品路径：包含受影响商品的待发货订单"},
        {"step": 5, "count": len(vip_affected),
         "explanation": "叠加规则层推断的 VIP 客户：需要优先安抚的高价值客户"},
    ]
    return {"products": products, "bundles": bundles, "promotions": promos,
            "pending_orders": pending, "vip_customers": vip_affected,
            "chain": chain}


def vip_report(kb, spend: int, min_orders: int) -> dict:
    g = kb.material
    order_counts = {r.c: int(r.n) for r in g.query(q.ORDER_COUNTS)}
    vips = []
    for c in sorted(set(kb.vip_out.subjects(RDF.type, EX.VIPCustomer)), key=str):
        reasons = []
        s = g.value(c, EX.annualSpend)
        lvl = g.value(c, EX.membershipLevel)
        if s is not None and int(s) > spend:
            reasons.append(f"年消费 {int(s)} > 阈值 {spend}")
        if str(lvl) == "silver" and order_counts.get(c, 0) >= min_orders:
            reasons.append(f"银卡会员且订单数 {order_counts.get(c, 0)} ≥ {min_orders}")
        vips.append({"id": _id(c), "label": _label(g, c),
                     "reason": "；".join(reasons) or "满足规则"})
    return {"vips": vips}


def recommend_report(kb, product) -> dict:
    g = kb.material
    naive = [{"id": _id(r.other), "label": str(r.label)}
             for r in _rows(g, q.NAIVE_SAME_CATEGORY, {"p": product})]
    semantic = [{"id": _id(r.other), "label": str(r.label), "relation": str(r.rel),
                 "relation_label": REL_ZH[str(r.rel)]}
                for r in _rows(g, q.SEMANTIC_RELATIONS, {"p": product})]
    return {"product": {"id": _id(product), "label": _label(g, product)},
            "naive": naive, "semantic": semantic}
```

**Step 4: 运行确认通过**

Run: `python -m pytest tests/test_scenarios.py -v`
Expected: 4 passed（连同 Task 5/6 的 10 条全绿）

**Step 5: Commit**

```bash
git add engine/ tests/test_scenarios.py && git commit -m "feat: 三个决策场景（风险传导/VIP 分类/语义推荐）带逐步解释"
```

---

### Task 8: engine/actions.py —— 执行器（决策执行闭环）

**Files:**
- Create: `engine/actions.py`, `tests/test_actions.py`

**Step 1: 写失败测试** `tests/test_actions.py`：

```python
"""执行器测试：建议动作 → 校验 → 写回 → 再推理 → 清单消解。"""
from engine.knowledge_base import KnowledgeBase
from engine.namespaces import EX

kb = KnowledgeBase()


def setup_function(_):
    kb.reset()
    kb.supplier_risk(EX.sup_shengke, delayed=True)


def test_actions_listed_with_reasons():
    actions = kb.list_actions()
    assert len(actions) == 9
    assert all(a["reason"] for a in actions)
    types = {a["type"] for a in actions}
    assert types == {"PausePromotion", "NotifyCustomer",
                     "CreatePurchaseOrder", "PromoteSubstitute"}


def test_execute_notify_then_prerequisite_blocks():
    act = next(a for a in kb.list_actions() if a["type"] == "NotifyCustomer")
    result = kb.execute(act["id"])
    assert result["ok"]
    # 同一客户不再出现在建议清单（规则里 FILTER NOT EXISTS notified）
    remaining = kb.list_actions()
    assert len(remaining) == 8


def test_execute_pause_promotion_removes_it():
    act = next(a for a in kb.list_actions() if a["id"] == "action_PausePromotion_promo_618")
    kb.execute(act["id"])
    ids = {a["id"] for a in kb.list_actions()}
    assert act["id"] not in ids
    # 效果已写回：活动状态变为 paused
    from rdflib import Literal
    assert (EX.promo_618, EX.status, Literal("paused")) in kb.material


def test_execute_all_clears_everything():
    result = kb.execute_all()
    assert result["executed"] == 9
    assert kb.list_actions() == []
    # 风险清单消解：受影响 VIP 全部已通知
    snap = kb.risk_snapshot(EX.sup_shengke)
    assert len(snap["vip_customers"]) == 3  # 风险仍在，但动作已全部处置


def test_reset_restores():
    kb.execute_all()
    kb.reset()
    assert kb.list_actions() == []
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_actions.py -v`
Expected: FAIL（KnowledgeBase 没有 list_actions/execute/execute_all）

**Step 3: 写实现**

`engine/actions.py`（完整实现）：

```python
"""动作执行器：效果即事实——写回后重新推理，已处置建议自动消失。

生产环境中 execute 是对 CRM/ERP/营销平台 API 的调用；
demo 里把动作效果作为新三元组写回 effects 层，接口形态一致。
"""
from rdflib import Literal

from engine.namespaces import EX

EFFECTS = {
    "PausePromotion": lambda targets: [(targets[0], EX.status, Literal("paused"))],
    "NotifyCustomer": lambda targets: [(targets[0], EX.notified, Literal(True))],
    "CreatePurchaseOrder": lambda targets: [(targets[0], EX.restockRequested, Literal(True))],
    "PromoteSubstitute": lambda targets: [(targets[0], EX.promoBoosted, Literal(True))],
}


def execute(kb, action_id: str) -> dict:
    """执行一条建议动作，返回 {ok, message}。"""
    act = EX[action_id]
    if act not in kb.action_reasons:
        return {"ok": False,
                "message": f"动作 {action_id} 不在当前建议清单中（可能已执行或条件已变化）"}
    info = kb.action_reasons[act]
    factory = EFFECTS.get(info["type"])
    if factory is None:
        return {"ok": False, "message": f"未知动作类型 {info['type']}"}
    for s, p, o in factory(info["targets"]):
        kb.effects.add((s, p, o))
    kb.refresh()
    if act in kb.action_reasons:
        # 二次防护：执行后条件应已消除；未消除则回滚本次效果
        kb.effects.remove((info["targets"][0], None, None))
        kb.refresh()
        return {"ok": False, "message": "动作执行后条件未消除，已回滚"}
    return {"ok": True, "message": info["reason"]}
```

`KnowledgeBase` 追加方法（Task 7 的文件里加）：

```python
    # ---------- 决策执行闭环 ----------
    def list_actions(self) -> list:
        out = []
        for act, info in sorted(self.action_reasons.items(), key=lambda kv: str(kv[0])):
            out.append({"id": str(act).split("#")[-1], "type": info["type"],
                        "targets": [{"id": _id(t), "label": _label(self.material, t)}
                                     for t in info["targets"]],
                        "reason": info["reason"]})
        return out

    def execute(self, action_id: str) -> dict:
        from engine.actions import execute as run
        result = run(self, action_id)
        return result

    def execute_all(self) -> dict:
        executed = 0
        for act in list(self.action_reasons):
            result = self.execute(str(act).split("#")[-1])
            if result["ok"]:
                executed += 1
        return {"executed": executed, "remaining": len(self.list_actions())}
```

（`_id`/`_label` 从 scenarios 导入复用，避免重复定义。）

**Step 4: 运行确认通过**

Run: `python -m pytest tests/test_actions.py -v`
Expected: 5 passed

**Step 5: 全量回归 + Commit**

Run: `python -m pytest -q`
Expected: 全部通过

```bash
git add engine/ tests/ && git commit -m "feat: 动作执行器——效果写回、再推理、建议清单自动消解"
```

---

### Task 9: scripts/explore.py —— 命令行实验台

**Files:**
- Create: `scripts/explore.py`

**Step 1: 写实现**（五个步骤对应 learn/ 教程四章 + 执行闭环）：

```python
"""本体学习实验台：python scripts/explore.py --step N

step 1  看原始三元组——本体就是"主语 谓语 宾语"
step 2  看类层级树——品类树是 subClassOf 树
step 3  跑推理，看声明 vs 推断的 diff——"机器理解业务"的时刻
step 4  跑三个决策场景的查询
step 5  触发一条建议动作并执行，看图谱回写前后 diff
"""
import argparse

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

    for top in sorted({s for s in g.subjects(RDF.type, None) if (s, RDFS.subClassOf, EX.BusinessObject) in g}, key=str):
        walk(top)


def step3():
    before, after = load_declared(), materialize(load_declared())
    inferred = {t for t in after} - {t for t in before}
    print(f"声明 {len(before)} 条 → 物化后 {len(after)} 条，新推断 {len(inferred)} 条。\n")
    interesting = [t for t in sorted(inferred, key=str)
                   if t[1] in (EX.substituteFor, EX.hasPart, EX.isComponentOf,
                               EX.compatibleWith, EX.sameSeries)
                   or t[1] == RDF.type and "cat_" in str(t[2])]
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
    parser = argparse.ArgumentParser(description="本体学习实验台")
    parser.add_argument("--step", type=int, choices=STEPS, required=True)
    STEPS[parser.parse_args().step]()
```

**Step 2: 手工验证**

Run: `python scripts/explore.py --step 3`（以及 1、2、4、5 各跑一次）
Expected: step3 输出中能看到 `[推断] p_bt01 isComponentOf b_ultimate` 与 `[推断] p_x2 substituteFor p_bt01`；step5 结束时剩余动作从 9 变 8

**Step 3: Commit**

```bash
git add scripts/explore.py && git commit -m "feat: 命令行学习实验台 explore.py（5 步）"
```

---

### Task 10: api/main.py —— FastAPI 接口

**Files:**
- Create: `api/main.py`, `tests/test_api.py`

**Step 1: 写失败测试** `tests/test_api.py`：

```python
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


def test_unknown_supplier_404():
    r = client.post("/api/scenario/supplier-risk",
                    json={"supplier_id": "sup_nope", "delayed": True})
    assert r.status_code == 404
```

**Step 2: 运行确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL（No module named api.main）

**Step 3: 写实现** `api/main.py`：

```python
"""FastAPI 接口 + 静态前端托管。启动：uvicorn api.main:app --reload"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.actions import execute as run_action
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
    from rdflib import RDF, RDFS

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
    return {"nodes": list(nodes.values()), "edges": edges}


@app.get("/api/taxonomy")
def taxonomy():
    from rdflib import RDFS
    children = {}
    for s, _, o in kb.material.triples((None, RDFS.subClassOf, None)):
        children.setdefault(str(o), []).append(str(s))

    def build(uri):
        lbl = kb.material.value(EX[uri.split("#")[-1]], RDFS.label)
        return {"id": uri.split("#")[-1], "label": str(lbl) if lbl else uri,
                "children": [build(c) for c in sorted(children.get(uri, []))]}

    return build(str(EX.BusinessObject))


@app.get("/api/entity/{eid}")
def entity(eid: str):
    from rdflib import RDFS
    node = _resolve("实体", eid)
    declared, inferred = [], []
    for s, p, o in kb.material.triples((node, None, None)):
        text = f"{str(p).split('#')[-1]}  →  {o.n3() if not str(o).startswith(str(EX)) else str(o).split('#')[-1]}"
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
```

**Step 4: 运行确认通过 + 全量回归**

Run: `python -m pytest -q`
Expected: 全部通过

**Step 5: Commit**

```bash
git add api/ tests/test_api.py && git commit -m "feat: FastAPI 接口（图谱/场景/动作执行/静态托管）"
```

---

### Task 11: 前端骨架（index.html + style.css）

**Files:**
- Create: `web/index.html`, `web/style.css`

**Step 1: 写实现。** 要求（完整代码由实现者按此规格编写，遵循 example-skills:frontend-design 的克制风格）：

- `index.html`：顶部 5 个 Tab（图谱总览 / 风险传导 / 客户分类 / 语义推荐 / 决策中心）；`<script src="https://cdn.jsdelivr.net/npm/cytoscape@3/dist/cytoscape.min.js">`；图谱容器 `#cy` 全高；每 Tab 一个 `<section>`；公共侧栏 `#detail`（实体声明/推断面板）。
- 视觉：浅色学术风、中文界面、类→颜色的固定映射（商品蓝/套装紫/供应商橙/客户绿/订单灰/促销红/动作黄）；推断边虚线、声明边实线；"为什么"解释用浅黄背景引用块。
- `style.css`：CSS 变量定色板；Tab 与卡片布局；响应式 ≥1024px 最佳。

**Step 2: 验证**

Run: `python -m uvicorn api.main:app --reload` 后浏览器打开 `http://127.0.0.1:8000`
Expected: 页面出现 5 个 Tab 与空图谱容器，无 404

**Step 3: Commit**

```bash
git add web/ && git commit -m "feat: 前端骨架（五 Tab 布局与样式）"
```

---

### Task 12: web/app.js —— 图谱渲染与全部交互

**Files:**
- Create: `web/app.js`

**Step 1: 写实现。** 规格（实现者据此编写完整 JS，约 400 行）：

1. **图谱总览**：fetch `/api/graph` → cytoscape elements（node=实体按 cls 着色；edge=三元组，`inferred` 用 `line-style: dashed`）；force 布局 `cose`；点节点 → fetch `/api/entity/{id}` → 侧栏列 declared/inferred 两组（推断组带"由推理得出"徽标）。
2. **风险传导**：供应商下拉 + 「标记延迟/解除」按钮 → POST `/api/scenario/supplier-risk` → 右侧按 chain 顺序渲染 5 步清单（每步：数量 + explanation）；图谱高亮 products→bundles→promotions→orders→vip_customers 的节点（按 step 延时逐层点亮）；"重置演示"按钮 POST `/api/reset` 后刷新图谱。
3. **客户分类**：两个滑块（年消费阈值 0-10000、订单阈值 1-10）→ debounce 300ms POST `/api/scenario/vip` → 列出 VIP（label + reason 引用块）；图谱上 VIP 节点加高亮环。
4. **语义推荐**：商品下拉（从 /api/graph 过滤 PhysicalProduct/Bundle）→ GET `/api/scenario/recommend/{id}` → 左右两栏对比：朴素版（纯列表）vs 语义版（每条带 relation_label 徽标）；下方一段固定文案解释两者差异。
5. **决策中心**：GET `/api/actions` 渲染卡片列表（类型徽标 + 目标 + reason）；每卡「执行」按钮 → POST `/api/action/{id}/execute` → 刷新清单与图谱；「全部执行」「重置演示」按钮；空清单时显示"没有待处置的建议动作——执行效果已写回图谱"。

通用：所有 fetch 失败在页面顶部 toast 提示并附 `uvicorn api.main:app` 启动指引；Tab 切换只显隐 section，图谱实例全局复用。

**Step 2: 手工验收清单**（逐项过）

- 标记延迟 → 决策中心恰好 9 条建议，promo_ultimate/promo_travel 不在暂停建议里
- 执行 `action_NotifyCustomer_c_zhaomin` 应 409（赵敏不在建议里；用不存在的 id 验证 409 提示）
- 全部执行 → 建议清单归零 → 风险传导 Tab 再点「解除延迟」→ 数据复位
- 语义推荐 p_bt01：语义版恰 4 条且含「替代品/兼容配件/同系列」徽标

**Step 3: Commit**

```bash
git add web/app.js && git commit -m "feat: 前端交互——图谱、三个场景、决策中心"
```

---

### Task 13: learn/ 四章教程 + README

**Files:**
- Create: `learn/01-本体是什么.md`, `learn/02-用本体建模电商业务.md`, `learn/03-推理如何发生.md`, `learn/04-从查询到决策.md`, `README.md`

**Step 1: 按以下大纲撰写**（每章 800-1500 字，所有代码块从仓库真实文件摘录并标注文件路径；每章末尾附 explore.py 对应 step 的动手任务与 2-3 道思考题）：

- **01-本体是什么**：三元组世界观；TBox/ABox = 语法书/事实库；本体 vs 关系库 vs 面向对象三种世界观对比表；用 `p_bt01 suppliedBy sup_shengke` 这条真实三元组开场。动手：`--step 1`。
- **02-用本体建模电商业务**：为什么品类是类不是属性字段（categories-as-classes，实现精化①的动机）；传递/对称/逆属性各配 data.ttl 真实例子；Action 类层级——本体也描述"可做的事"。动手：`--step 2` + 给 cat_earbuds（耳塞品类）加进 schema.ttl 并重启观察。
- **03-推理如何发生**：OWL-RL 物化 = 把所有逻辑结论一次算全；声明 vs 推断 diff；为什么 VIP 规则不进 OWL 层（算术/聚合的边界），规则层两分类（分类规则/动作规则）；"建议动作也是推论"的执行闭环原理（效果写回 → NOT EXISTS 失效 → 建议消失）。动手：`--step 3`、`--step 5`。
- **04-从查询到决策**：三个场景的查询逐条精读（queries.py 全文注解）；风险传导每一步对应哪条公理；本体驱动决策的工程范式图（本体=语义层 → 规则=决策层 → 执行器=行动层，生产中执行器换 HTTP 调用）；什么场景**不该**用本体（单表 CRUD、纯统计报表）。动手：`--step 4`。
- **README.md**：一分钟简介、安装运行（pip install / pytest / uvicorn 命令）、学习路径（learn/01→04 + explore 步骤对照表）、界面五 Tab 截图位说明。

**Step 2: Commit**

```bash
git add learn/ README.md && git commit -m "docs: 四章教程与 README"
```

---

### Task 14: 全量验证收尾

**Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 约 24 条全部通过，0 failed

**Step 2: 端到端手工核验**（按顺序执行并在回复中报告结果）

```bash
python -m uvicorn api.main:app --reload
```

浏览器核验：五 Tab 全部可用；风险传导 9 条建议；全部执行后归零；reset 复位；`python scripts/explore.py --step 3` 推断数 > 100。

**Step 3: 最终提交**

```bash
git add -A && git commit -m "chore: 全量验证通过，demo 完成" && git log --oneline
```
