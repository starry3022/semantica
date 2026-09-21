# Palantir：LLM 链路泛化、结构约束与质量验证

调研日期：2026-09-21。

问题：针对当前链路的固定实体集合、关系导向验收、固定中文输出、长文档限制，
Palantir 如何处理？哪些可以支持本项目坚持“业务语义由 LLM 输出，代码校验”的方向？

调研前已查阅[代码约束审计](llm-pipeline-generalization-audit.md)、
[孤立实体与语义覆盖](palantir-isolated-entities-and-semantic-coverage.md)及调研索引。
本文补充官方公开机制及适配建议；没有运行 Palantir 实例、安装其示例或获取内部提示词。

## 结论

Palantir 提供类型化数据模型、可组合的 LLM 步骤、受约束的对象操作和任务评估。
这些机制支持我们保留技术校验，并改善当前输出契约过窄的问题。

Palantir 同时支持条件分支、代码函数和 Action rules，不能将其描述为“没有规则判断”
或“业务全部交给 LLM”。本项目禁止硬编码业务语义，是用户明确的项目约束；
参考厂商机制不能覆盖这一要求。[AIP Logic blocks](https://www.palantir.com/docs/foundry/logic/blocks)、
[Action rules](https://www.palantir.com/docs/foundry/action-types/rules)。

没有采购专用分支，只能说明缺少这类业务硬编码；是否适合其他材料，还要检查表示能力、
修订能力、输入规模和真实任务质量。当前的固定实体集及关系导向验收仍会限制泛化。

## 官方确认的机制

### 1. 属性与关系是不同的表达手段

Ontology 中，对象属性描述对象特征；link 表达两个对象之间的关系，link type 是其类型定义。
对象实例与对象类型定义也明确分层。
[Types reference](https://www.palantir.com/docs/foundry/object-link-types/type-reference)。

Pipeline Builder 的抽取模板可以输出字符串、整数、数组等类型。
配置 struct 输出后，平台严格按 schema 解析；不符合结构会报错，也可以配置输出错误信息。
这确认了“按输出契约校验”的机制，不代表类型正确就已经语义正确。
[Use LLM node：Entity extraction / Output types](https://www.palantir.com/docs/foundry/pipeline-builder/pipeline-builder-llm)。

本项目推论：日期、数值、名称等答案应能引用对应属性事实；不能把“存在关系引用”
作为所有问题回答成功的必要条件。某项内容应建成对象、属性还是关系，仍由 LLM 根据
材料和任务提出，代码不按关键词或值的外观替模型决定。

### 2. 分阶段输入输出可以组合

AIP Logic 的 block 有输入输出，前一步输出可以供后一步使用；可选择提供给模型的对象属性。
官方提示词指南建议分解复杂任务并使用连续提示。
[AIP Logic blocks](https://www.palantir.com/docs/foundry/logic/blocks)、
[Prompt engineering](https://www.palantir.com/docs/foundry/aip/best-practices-prompt-engineering)。

本项目适配：继续使用分阶段诊断、增量修订和验收。按阶段传必要证据及稳定 ID，
保留项引用已有 ID，设独立输入输出预算、有限重试并保存记录。
这些具体阶段、字段和重试次数是项目设计，不能称为 Palantir 的固定算法。

### 3. 对象修订与本体定义修订分开处理

Action rules 可以创建、修改或删除已有类型的对象和链接。LLM 可以通过配置好的
Apply actions 工具请求修改；AIP Logic 按调用者权限执行工具。
[Action rules](https://www.palantir.com/docs/foundry/action-types/rules)、
[AIP Logic tools](https://www.palantir.com/docs/foundry/logic/blocks)。

Logic 调试运行可查看拟议对象修改，而不立即写入实际本体数据。
本体资源定义的分支变更另有 ontology proposal，可查看差异、预览、评审并合并。
[Logic：Ontology edits](https://www.palantir.com/docs/foundry/logic/getting-started#make-ontology-edits-using-logic-functions)、
[Review ontology proposals](https://www.palantir.com/docs/foundry/ontologies/review-ontology-proposals)。

本项目适配：初次实体抽取遗漏时，可以增加独立的 LLM 实体修订候选阶段，输出新增、
更正或身份对齐提案及证据，再验证 ID、引用和变更一致性。新类、新属性的声明作为
另一种本体定义变更处理。不能直接取消端点存在校验，让未知 ID 进入关系图。

公开机制没有证明 Palantir 自动完成任意文本的实体去重、对象改类型或开放本体生成。
本项目的实体合并/改类型协议仍需单独设计和评估，不能把这些能力归因于 Action 本身。

### 4. 长文档拆分并保留来源

官方文档处理流程包括文本提取、分块、检索及原文展示；chunk 可以作为对象并关联源对象。
基础分块配置包含块大小、重叠和分隔符。
[Document processing](https://www.palantir.com/docs/foundry/ontology/document-processing)。

Palantir Developers 的语义分块示例还描述了文本完整性校验：检查分块内容与原文保持一致。
该示例说明可以把语义分段与文本校验分开。
[Advanced Document Parsing: Semantic Chunking](https://build.palantir.com/platform/f5f350c4-e5e1-4e81-a3e7-141902bac29e)。

上述示例介绍通过官方站点的检索正文核实；直接打开页面依赖 JavaScript，
本次没有检查其实际 prompt、安装包或执行实现，不对其内部算法作进一步断言。

本项目适配：长文本先建立保持原文位置的有限上下文窗口；需要语义分段时，由 LLM
提出原文边界/片段引用，代码校验范围、覆盖和文本一致性。跨块实体对齐与关系判定
继续由 LLM 完成，代码不能按同名自动合并实体。语义搜索中的分块机制本身不保证
完整事实抽取，仍需检查跨段条件、指代和遗漏。

### 5. 语言和任务配置可以显式表达

Use LLM 的翻译模板提供目标 Language 字段，也支持自行编写 prompt。
这能证明语言可以作为任务配置，不能证明平台对所有抽取任务都有统一的自动语言策略。
[Use LLM node：Translation / Empty prompt](https://www.palantir.com/docs/foundry/pipeline-builder/pipeline-builder-llm)。

本项目适配：去除溯源 prompt 中固定中文要求，优先采用显式输出语言；未配置时要求
LLM 沿用来源材料语言，并保留原文证据。混合语言、术语和显示标签的效果另行评估。
这项默认策略是项目建议，旧 prompt 版本与既有 bundle 的离线重放应继续保留。

### 6. 软件校验之外，使用任务评估

AIP Evals 用输入、预期输出和评价函数评估 LLM 链路，并比较版本、模型及多次运行的波动。
测试案例可以来自手动边界案例和真实对象集；评价器包括确定性比较及 LLM-as-a-judge。
[Evals overview](https://www.palantir.com/docs/foundry/aip-evals/overview)、
[Create an evaluation suite](https://www.palantir.com/docs/foundry/aip-evals/create-suite)。

本体设计验证文档还强调：结构正确不等于实际可用；问题应来自真实任务，不能只从现有
本体倒推它已能回答的问题。无法回答的重要问题应保留为失败结果，并检查缺失语义。
[Ontology design: Validation](https://www.palantir.com/docs/foundry/ontology/ontology-design-validation)。

本项目适配：把普通回归测试与真实模型语义评估分开记录。诊断应先从原文/任务提出问题，
再对照候选事实；不能只围绕初次抽取到的实体证明覆盖。LLM 自评有帮助，但不能单独
证明抽取完整，需独立预期结果及人工抽查。

## 对当前代码的具体影响

当前行为和代码位置见[代码约束审计](llm-pipeline-generalization-audit.md)。

| 当前限制 | 建议改动 | 代码继续校验的内容 |
| --- | --- | --- |
| `answered` 必须引用关系，实体必须作为关系端点 | 允许模型引用属性事实、关系事实或它们的组合；无答案时保留原因 | 所引事实存在、实体引用一致、证据可定位；不要求所有事实关系化 |
| 复核实体集合固定，只能改关系 | 增设 LLM 实体修订候选阶段，验证完成后供关系阶段引用 | ID 唯一、变更引用有效、保留项不变、变更及其影响有记录 |
| 溯源 prompt 固定中文 | 语言作为显式配置，或交给模型沿用来源语言 | 配置/版本记录、来源证据保持；不按中文业务词选择类型 |
| 单文档 32000 字符、无分块与跨块对齐 | 分块、分批抽取与 LLM 对齐；各次调用保留预算 | 原文位置与内容、批次完整性、跨块 ID、失败记录 |
| 最多 12 个诊断问题、两轮修订 | 保留有界运行；超出预算的待办显式留档，后续支持分批诊断 | 不静默丢弃超出预算的内容，不因达到次数上限自动判定成功 |
| 主要用采购材料验证语义效果 | 增加不同领域、语言、属性密集、无关系和长文档的真实模型案例 | 技术指标与语义指标分别报告，不以单测数量替代泛化证据 |

## 建议的分阶段职责

下表是本项目的设计建议，不是 Palantir 内部抽取流程，也未在本次调研中实施。
它扩展现有链路；每步输出都保留对应来源与版本，避免要求某次调用返回全部结果。

| 阶段 | LLM 负责 | 程序负责 |
| --- | --- | --- |
| 材料分段 | 需要时提出语义边界和上下文引用 | 保存原文，建立有界窗口，校验片段位置及覆盖 |
| 实体候选与修订 | 识别实体，提出遗漏补充、身份对齐和类型更正 | 验证候选变更契约、ID、证据和引用；按模型明确输出形成候选版本 |
| 属性事实 | 确定属性名称、值、适用对象及原文依据 | 校验结构、类型、引用和证据，不推导业务值 |
| 关系与条件 | 确定端点、谓词、方向、条件和证据 | 校验端点、事实引用及输出契约，不自动连孤点 |
| 语义覆盖 | 从原文/任务提出问题，对照事实诊断，局部修订后验收 | 维护问题及变更 ID、轮次和预算，保留未解决问题 |
| 本体及溯源声明 | 继续生成类、属性、关系声明和溯源建模内容 | 沿用结构一致性、RDF/SHACL 和重放校验 |
| 质量评估 | 按独立量表评估语义，输出缺陷及依据 | 比较版本与技术指标，保存结果，支持人工核查 |

优先级建议：先完善属性事实表达、回答引用契约和语言配置，同时建立跨材料评估基线；
随后增加实体修订，再处理长文档和跨块一致性。每一步都用旧材料验证回归，并用新材料
验证新增能力，避免一次性扩大所有契约。

## 尚未确认的边界

- 官方公开资料未确认一套适用于所有领域、全自动由原文生成并修复本体的通用算法。
- 本次没有证据证明 Palantir 的内部 prompt、实体对齐策略、重试次数与本项目相同。
- “允许属性回答”“增加实体修订”“默认沿用来源语言”均是本项目适配方案，
  不是官方要求的固定实现。
- 当前真实模型验证主要覆盖中文采购材料；结构测试通过和采用上述机制都不能直接
  证明其他材料质量。需要实际多材料、多次运行的评估结果。

本次交付为调研文档及索引更新，未修改运行代码。
