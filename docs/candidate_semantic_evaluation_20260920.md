# 中文候选本体语义修复实跑（2026-09-20）

结论：**提示词能改善漏抽，但不能单独保证本体语义正确。** 本轮补齐了原文高金额档位的继承审批，并修复了 facts → RDF → ontology 输入之间的限定信息丢失。两份材料仍存在模型分类、模态和时序表达不足，产物继续标记为 candidate / unreviewed。

## 输入与方法

- 原文为《财务付款与采购管理制度》FIN-POLICY-2026-008 V1.3，共426个 Unicode 字符；SHA-256：`88cc9321f13f40fdb9b6844c46f0701180e38da89e825b8763c932814be0d674`。
- 使用另一个变更管理材料检查通用性：普通审核、影响十台以上时追加审核、测试环境特例替换与豁免、应急授权及两个工作日内补交。
- 两份材料的实体、关系、ontology 均由 `deepseek-v4-flash` 实际生成，temperature=0；最终每份材料三次模型请求，均 HTTP 200。先保存真实抽取响应，再严格重放这两次响应并调用 ontology 模型，未人工补写 facts。
- 抽取提示版本为 `candidate-facts-extraction-v4`，限定事实 ontology 提示为 `candidate-facts-ontology-v3`；旧 extraction-v3 和 bundle-v1 保持原合同。
- 业务审查使用源文独立问题，不以 SHACL 或同源保真检查作为业务完整性证明。三轮提示迭代的中间缺口均保留在本地审查记录中，不能据此估计稳定成功率。

完整证据上下文也带来开销：原文三次请求合计64,063 tokens，其中ontology输入39,399 tokens。当前优先保真；长材料仍需控制重复来源元数据的体积，不能用截断条件和证据来降低成本。

## 原文结果

| 项目 | 旧结果 | 本轮最终结果 |
|---|---|---|
| 采购低／中／高金额审批角色数 | 2 / 3 / 1 | **2 / 3 / 4** |
| 单笔付款低／高金额审批角色数 | 2 / 1 | **2 / 3** |
| 普通采购提前提交 | 仅证据中清楚表达 | `submitsAdvancePurchaseRequest` 及本体释义明确表达 |
| 合同资格 | 表达不充分 | 实体文本保留“合法有效的合同” |
| 紧急采购补齐 | 动作含义容易丢失 | 两条 `supplementsDocument`，分别连接采购审批、财务材料，保留“必须”及完成后3个工作日内 |
| 关系条件、模态、否定、证据 | RDF不携带，ontology输入丢失 | 独立命名 RDF 断言、完整记录及完整 ontology 上下文 |
| OWL属性说明 | 0 / 9 导出为 comment | **8 / 8** 导出为 `rdfs:comment` |

本轮18实体、21关系、8类、8属性。21条关系均有独立 `rdf:Statement`，不额外断言其裸业务三元组；RDF共538三元组。52项引文均与源文 Unicode 区间精确一致。同 SPO 的多个条件不会因 RDF 集合语义而丢掉断言身份。

原文核心问题可回答，不等于本体已可直接用于业务执行。仍有以下实质问题：

- “采购审批”被归为 `Document`，ontology 也把它解释为文件；审批手续／活动和文件的区分仍不合理。
- “申请人”被归为 `Employee`，原文没有明确支持这个收窄；材料要求与已存在材料的区分仍不充分。
- 14条审批关系的 `modality` 为空，义务性质需结合制度语境和证据理解。
- 金额边界保留在断言条件中，ontology comment 的“5000-20000元”简写不够严谨。紧急授权实体仍缺显式连接，“先”没有形式化先后关系。

## 变体结果与提示词边界

变体16实体、12关系、6类、6属性；12个限定断言、283个RDF三元组，31项引文精确对齐，6个属性说明全部进入OWL。

模型保留了审核角色从2到3的继承、测试负责人的替代、原两角色的否定关系、完整紧急合取条件、授权请求接收人，以及两项材料／两个工作日的补交义务。但是：

- 常规审核的“提前”和紧急路径的“先”仍仅在证据中；原文上的改善未稳定泛化。
- 两条豁免只有 `negation=true`、`modality=null`，不足以区分“不必审核”和“禁止审核”。“单独”及例外优先级未形式化，不能自动裁决例外与十台阈值重叠的情况。
- 变更活动被统一归为 `ChangeRequest`，存在活动向申请的类型收窄。

因此，代码保真修复已经成立，prompt 改善也有实跑证据；“所有漏抽／语义错误已经解决”不成立。后续若需要自动执行规则，应引入独立语义验收及更明确的活动、材料要求、规范模态和例外表示，继续让模型提出候选，而非将当前输出直接晋升为已审核规则。

## 实现与验证

| 文件 | 变化 |
|---|---|
| `semantica/semantic_extract/candidate_profile.py` | 通用继承、替代／豁免、并列对象、参与方、动作和期限提示；按版本严格重放 |
| `semantica/ontology/candidate_statements.py` | 候选限定断言及同源保真检查；复用原生IRI；保留原始记录，拒绝身份／传输词汇冲突 |
| `semantica/ontology/candidate_ontology.py` | 显式限定事实模式；完整上下文及输入hash绑定，业务词汇排除传输词汇 |
| `semantica/explorer/candidate_bundle.py` | v2限定断言显示、三个输入hash校验；v1投影不变 |
| `examples/extract_candidate_facts.py` | 新包v2、旧包重放；分开报告保真和内部业务投影SHACL |
| `semantica/ontology/owl_generator.py` | 各导出格式保留属性comment |

通用 RDFExporter 的默认行为不变；复用其IRI和内部业务投影，没有增加业务专用金额、角色表或新依赖。业务ontology不承担RDF传输结构的定义。

- 最终相关回归：**509 passed**。Ruff检查通过；五个新增／适配源文件的Mypy检查通过；新增模块及主线程修改文件Black检查通过。
- OWL生成器已有格式、未用导入和Optional参数类型告警与HEAD一致，无新增诊断。较广Explorer回归另有既有 `_IncludedRouter.path` 测试失败，已在相同提交的未修改工作树复现；本轮未修改该路由。
- 独立代码审查发现的保留RDF词汇混入业务schema问题已修复，16个属性／类／实体／断言身份反例通过，复查批准。
- 两份最终v2包各15个非SUMMARY产物在禁止模型调用的离线重放后**逐字节一致**；真实产物的Explorer图查询返回HTTP 200。
- 两份包分别验证删除断言、改变条件、注入裸关系三类反例，保真检查全部拒绝。保真检查不能发现模型最初未抽出的事实。
- 原始真实v1包离线重放后13个非SUMMARY产物逐字节不变，仅`ontology.ttl`因补回属性comment发生预期变化。
- GitNexus提交范围检查：本次32文件、83符号、5条受影响流程，MEDIUM；相对main的整条分支累计162文件、55条流程，CRITICAL，包含此前已有工作，不等同于本次修复范围。

## 本地证据

以下运行产物不含私有模型配置，独立于Git提交保存：

- [原文最终bundle](../.local/candidate-semantics-20260920/accepted/original-bundle/SUMMARY.json)
- [变体最终bundle](../.local/candidate-semantics-20260920/accepted/variant-bundle/SUMMARY.json)
- [逐项语义审查](../.local/candidate-semantics-20260920/semantic-review.md)
- [技术验证数据](../.local/candidate-semantics-20260920/technical-verification.json)

`accepted`仅是本次最终检查目录名；其中facts和ontology的审核状态仍为unreviewed。三轮提示的过程产物在同级`live`、`live-final`和`accepted`目录中，旧基线仍保存在原worktree的评估目录。
