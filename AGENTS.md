# 项目协作约束

## 逻辑与设计变更

- 严格围绕用户明确的需求和已授权范围工作，不擅自增加业务规则、默认行为、推断逻辑或自动补充的关系与属性。
- 不在代码中新增业务规则，不编写定制业务规则类。业务语义（包括类型、关系、规则和适用条件）由 LLM 链路输出；代码层面对这些输出只做格式、完整性、一致性和约束校验，不推导、补齐、改写或用手写规则替代模型结果。校验失败时保留问题并报告，不自动生成兜底业务逻辑。
- 对逻辑或设计存在不确定性时，必须先查证 Palantir Foundry / AIP 的官方处理机制，尤其是 Ontology 建模、溯源、证据关联、数据血缘及关系展示；不得凭猜测直接增加逻辑。
- LLM 相关 skill 和 prompt 也可以参考 Palantir AIP 的官方文档与公开机制，包括上下文引用和结构化输出。保留参考来源，明确本项目的适配内容，不将公开产品机制描述为已知的 Palantir 内部提示词。
- LLM 链路按职责分阶段调用，避免单次要求模型输出完整抽取、修订和全部审计。各阶段设置输出上限，保留项优先引用已有 ID；技术校验失败仅反馈当前阶段，由模型修正并留档，不用代码补写业务内容，也不单纯通过不断增大 token 额度解决问题。
- 明确区分官方文档确认的机制、基于文档的推断和本项目的适配建议。说明相关设计时附上官方来源，不得将自定义实现描述为 Palantir 或 Semantica 的原生行为。
- 将调研写入 `docs/research/` 下的专门文档，并维护 `docs/research/README.md` 索引。文档记录调研日期、问题、官方来源、已确认机制、推断、本项目适配及尚未解决的问题；后续调研先查阅已有结果，再针对缺口或可能过期的内容补充查证，及时更新文档，避免重复调研。
- 参考 Palantir 不等于照搬。结合现有架构和用户需求采用最小必要变更，不以对标为由扩大任务范围。
- 如果查证后仍有会影响业务语义或任务范围的不确定性，先向用户澄清，再实施依赖该判断的变更；可以独立完成的已授权工作继续推进。

## Palantir 官方参考入口

- [Ontology 关系类型](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview)
- [Ontology 结构设计与关系建模](https://www.palantir.com/docs/foundry/ontology/ontology-structural-guidance)
- [创建关系类型与 Object-backed links](https://www.palantir.com/docs/foundry/object-link-types/create-link-type)
- [数据血缘](https://www.palantir.com/docs/foundry/data-lineage/overview)
- [AIP 引用与来源展示](https://www.palantir.com/docs/foundry/chatbot-studio/citations)
- [AIP 提示词最佳实践](https://www.palantir.com/docs/foundry/aip/best-practices-prompt-engineering)
- [AIP Logic 提示词、工具与输出](https://www.palantir.com/docs/foundry/logic/blocks)

# Commit Identity

- Use `starry3022 <starry3022@gmail.com>` as both the author and committer for new commits in this repository.
- Set repository-local Git identity to `user.name=starry3022` and `user.email=starry3022@gmail.com`; do not change global Git configuration.
- Before committing, verify that the effective author and committer identities match this requirement, including any environment overrides.

# Commit Message Format

Every commit message must use a summary followed by an item list. This repository-specific format takes precedence over the inherited Lore/native-trailer format.

- Write a concise, single-line summary describing the intent of the change.
- Separate the summary from the item list with exactly one blank line.
- Start each item with `- ` and describe a concrete change, rationale, validation result, or limitation.
- Keep all items consecutive, with no blank lines between items.
- Describe the behavior and validation directly; do not include issue identifiers in the summary or items.
- Put relevant constraints, decisions, tests, and risks in list items instead of standalone paragraphs or a separate Git trailer section.

Example:

```text
Preserve policy conditions and evidence in process knowledge queries

- Extract typed candidate rules with conditions, approvals, deadlines, and exact evidence.
- Export Explorer graphs and typed RDF with ontology and SHACL validation.
- Add regression coverage for evidence alignment, metadata protection, and offline replay.
```

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **semantica** (30952 symbols, 56377 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/semantica/context` | Codebase overview, check index freshness |
| `gitnexus://repo/semantica/clusters` | All functional areas |
| `gitnexus://repo/semantica/processes` | All execution flows |
| `gitnexus://repo/semantica/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
