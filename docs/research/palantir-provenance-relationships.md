# Palantir 本体关系与证据溯源

调研日期：2026-09-21。范围：Foundry / AIP 公开官方文档。

## 问题与当前诊断

部门负责人的类侧栏显示 `Provenance relationships · 1`，但本体图没有对应关系。
这个 1 来自实例已使用的属性种数，并不是已声明的类级关系数，也不是 4 条引用的数量。
原 v2 溯源提示词只允许 Evidence / SourceDocument 内部的 domain / range，要求业务主体
的 domain 留空。因此 hasEvidence 的 OWL 定义合法，但没有表达业务类的适用关系。
它同时用于实体记录和 rdf:Statement 关系断言，不能把全局 domain 收窄到某个业务类。

## 官方文档确认

| 机制 | 官方说明及来源 |
| --- | --- |
| 类型与实例分层 | [Link Type](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview) 定义两个对象类型之间的关系；Link 是具体对象之间的关系实例。每个关系类型的两侧有独立名称，支持双向遍历。 |
| 多类复用 | [Interface Link Type Constraint](https://www.palantir.com/docs/foundry/interfaces/interface-link-types-overview) 定义共同的关系约束；实现接口的对象类型仍需映射到符合约束的具体 Link Type。 |
| 关系自身的信息 | [结构设计指南](https://www.palantir.com/docs/foundry/ontology/ontology-structural-guidance) 建议用 object-backed link 承载关系的日期、角色、状态等信息，应用按场景展示直接连接或中间对象。 |
| 来源元数据 | 同一结构设计指南说明 struct 可将 LLM 结果与来源、置信度等元数据放在一起；没有要求所有引用都建成 Evidence 对象。 |
| 应用显隐 | [Link Type 元数据](https://www.palantir.com/docs/foundry/object-link-types/link-type-metadata) 的 visibility 分为 prominent / normal / hidden；展示配置与关系定义分开。 |
| 引用交互 | [AIP Citations](https://www.palantir.com/docs/foundry/chatbot-studio/citations) 使用行内引用和 Sources，支持打开对象、PDF 指定页和外部 URL。特定上下文之外需要提示 LLM 按引用格式输出。 |

## 结论与边界

- 可借鉴的是明确关系两端类型、类型与实例分层、按场景展开来源。
- 未找到公开依据证明 Palantir 自动创建通用 Evidence / hasEvidence 本体模型，
  或通过实例使用次数自动画出正式本体关系。
- “根据实例用法画虚线”是曾考虑的项目展示方案，不是已确认的 Palantir 机制；
  它不能替代正式关系声明，本次不采用它补齐本体。
- Foundry Link Type 不等同于 OWL ObjectProperty；Foundry Ontology 边界也不等同于 RDF 命名空间。

## 本项目适配：LLM 声明，代码校验和展示

保留已有 Evidence / SourceDocument 模型和通用属性，新增由 LLM 输出的按类关系约束。
采用 [W3C SHACL](https://www.w3.org/TR/shacl/) 的 property shape：
`sh:targetClass` 指定主体类型，`sh:path` 指定属性，`sh:class` 指定值的类型。
不设置 minCount / maxCount，不补充事实，不生成新的业务分类、审批规则或条件。
SHACL 是这里对公开机制的标准化适配，不是 Palantir 的内部实现声明。

LLM 输入包含已有类型、实体引用、关系断言引用及其来源。LLM 输出具体形状的 IRI、
主体类、属性、目标类和定义。代码只能验证引用存在、覆盖完整、值类型相容、IRI 不冲突，
并将模型输出序列化成 SHACL；验证失败直接报告，不合成或修补语义。

本体图将这些明确声明投影成“主体类 → 目标类”的关系，边上显示属性的名称与标识，
可查看属性与声明来源。此图是约束的可视化，不是给两个类新增实例事实三元组。
侧栏区分声明的关系与仅在实例中观察到的用法。证据正文仍在来源查看器中，
关系条件和证据保留在各自断言上。

## 验证要求

- 所有新增关系声明都可追溯到保存的 LLM 原始响应，并能离线重放。
- 全局 hasEvidence domain 不被改成某一个业务类；关系断言主体也被覆盖。
- 原事实、业务本体、base RDF 和原始投影保持逐字节一致。
- 图与侧栏在无实例、仅有实例用法、已有正式声明时仍准确区分来源。
- 缺项、错误端点、伪造约束和改变输入的重放必须失败；不能用代码兜底补全。

实现说明与操作入口见 [candidate-provenance.md](../candidate-provenance.md)。

## 实施与验证记录（2026-09-21）

- 使用真实 DeepSeek `deepseek-v4-flash` 生成 v3 溯源模型：2 个类、2 个共享属性、
  20 个按类声明的关系形状，包括部门负责人及 rdf:Statement。
- `relationship_shapes` 与保存的原始模型响应逐项一致；离线重放通过。
  原始 15 个事实、RDF、本体、投影及来源文件逐字节保留。
- 标准 pySHACL 验证器确认实际数据符合形状；没有引用的实例允许通过，错误值类型被拒绝。
- 本体图的选中类关系视图以边表示属性，避免把同一属性再次画成孤立框。
  可以切换回完整本体；连线详情提供模型定义和属性定义入口。
- 后端相关回归 347 项通过；1 项符号链接测试因 Windows 缺少创建权限而排除。
  前端工作区 349 项通过，最后一轮关系视图调整的 26 项相关回归及构建通过。
- 浏览器确认部门负责人到证据的声明连线、类侧栏分组、定义跳转，以及来源查看器、
  各断言的条件/引用、Full / Focus / Grouped 展示开关；查看前后原图 API 内容一致。

本地复现产物位于 `.local/candidate-profile-v3-provenance-v3/`，离线重放位于
`.local/candidate-profile-v3-provenance-v3-replay/`。本地目录不入库且不包含提供方密钥。
验证脚本为 `.local/verify-provenance.cjs`，报告为 `.local/logs/provenance-verification.json`，
本体图截图为 `.local/logs/provenance-v3-ontology.png`。

## 补充：业务关系遗漏、连线命名与完整图（2026-09-21）

### 问题与原因

v3 实施只生成了溯源关系形状，而选中类的关系图只收集这些形状，造成两个问题：
已有 `requestsAuthorization` 的 OWL domain/range 被视图漏掉；共享的 `approves`
尚无对应的按类业务关系声明。实例图里能看到业务关系不等于本体已声明其适用类型。
这个缺漏来自本项目的生成范围与显示过滤，不是 Palantir 要求只显示证据关系。

同时，连线曾直接显示形状标题“部门负责人有证据”，重复了源节点；完整图的透明卡片、
常驻连线标签、较粗的证据线和过长的单列布局，使类名与类型文字附近显得拥挤。

### 已确认的标准与项目适配

继续沿用上面的 Palantir 类型/实例分层与显式 Link Type 机制。新增标准查证：
[W3C SHACL sh:or](https://www.w3.org/TR/shacl/#OrConstraintComponent)
要求每个值至少符合列表中的一个形状。这里将同一属性的多个可选目标类型表达为
`sh:or ([sh:class TypeA] [sh:class TypeB])`。不能对同一主体类与路径添加两个
独立 `sh:class` 形状，否则会错误地要求每个值同时属于两类。

- v4 提示词要求 LLM 同时输出业务与溯源的完整关系形状、角色和可选目标类型。
  业务属性与类型使用既有 IRI；代码只校验覆盖、类型集合、角色归属和标识一致性。
- 本体图显示入向和出向的明确声明。单个命名 OWL domain/range 也可以直接可视化；
  这是已有定义的展示，不是从实例推断。复杂表达式继续保持原结构。
- 业务断言的条件、否定、模态和独立引用保留在各自断言上。校验用的临时业务连接
  不能回写成无条件 base RDF 事实。
- 连线显示属性标签与标识，例如“有证据（hasEvidence）”；形状的标题及说明在详情中。
  多个可选目标在侧栏合并为一份声明，不重复计数。
- 完整图使用多列排布和不透明卡片，证据线为 1px、降低色彩强度；只在悬停或选中时
  显示边标签，选中类的关系视图保留全部属性标签。这些视觉选择是本项目适配，
  不声称是 Palantir 的像素样式或内部布局算法。

### 产物与验证

- 真实 DeepSeek `deepseek-v4-flash` 输出 28 个形状：20 个溯源、8 个业务主体类/属性声明。
  部门负责人关系图有 3 条业务类型连线（两类审批目标、一条入向请求授权）和 1 条证据
  类型连线；这不表示新增了审批事实，也不等同于 4 条原文引用的数量。
- 模型原始形状逐项保留，原 15 个业务及来源产物字节一致；v4 离线重放产物字节一致，
  既有 v3 模型仍通过其原始提示词绑定校验。
- 标准 pySHACL 对全部实际类型连接验证通过；错误目标类型被拒绝，缺少连接的实例
  允许通过。单元测试覆盖省略业务声明、伪造角色、遗漏可选类型、保留条件及旧版重放。
- 后端相关回归 351 项通过，1 项 Windows 符号链接权限测试仍排除；前端工作区 352 项
  通过，最后布局调整的 29 项相关测试通过，构建通过。
- 本地服务使用 `.local/candidate-profile-v3-provenance-v4/`；重放目录为同名前缀加
  `-replay`。浏览器脚本为 `.local/verify-provenance.cjs`，报告位于
  `.local/logs/provenance-verification.json`。截图前缀为 `provenance-v4-ontology`，
  覆盖部门负责人关系图、完整图和紧急采购授权附近的放大图。
- 最终浏览器检查通过：完整图的 30 个节点均进入视野，卡片互不覆盖，紧急采购授权
  的名称与类型行不重叠；属性标签点击可打开声明和定义。实例图仍为 3 条业务关系、
  展开证据后 7 个邻居，原图 API 查看前后内容相同，无浏览器脚本错误或 API 错误。

仍无公开依据把本项目的 Evidence 模型、SHACL 结构或图样式视为 Palantir 原生实现。

对于“办公设备”“软件服务”等在 Explorer 中缺少业务连线的问题，见后续专题
[孤立实体、类别建模与语义覆盖](palantir-isolated-entities-and-semantic-coverage.md)。
该问题属于源关系抽取覆盖，区别于本篇处理的已有关系在本体图中如何展示。

2026-09-21 后续补充：声明提示词 v5 将显式来源类型/关系路径/目标类型整理成紧凑
输入索引，减少模型重复拆分多目标声明；模型仍提供所有声明，代码只校验输入约束。
v2/v3/v4 的原提示词及模型记录继续支持离线重放。真实调用、失败案例和浏览器结果见
上述专题的“本体声明及浏览器验收”，操作说明见
[Candidate provenance](../candidate-provenance.md)。
