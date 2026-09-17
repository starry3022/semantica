# Business ontology view implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independently owned frontend and regression-test tasks. The parent owns backend integration and final verification.

**Goal:** Present one business ontology browsing entry with expandable links to process rules, validated evidence and original materials.

**Architecture:** Keep existing business and support RDF resources unchanged. Register an explicit sidecar containing business/support roles, immutable term definitions and exact source spans. At read time intersect validated term spans with validated rule evidence from the same source identity/hash, following only ProcessRule hasEvidence and declared business-property domain/range relationships. Reuse the existing graph and source viewer.

**Tech stack:** Existing Python/Pydantic/rdflib/FastAPI and React/TypeScript/ReactFlow; existing tests and real Chrome.

**Spec:** User approved one business main view with expandable rule/evidence support; technical vocabulary is an auxiliary entry. No name-based mappings, instance retyping or business approval.

## Constraints

- Worktree `.local/worktrees/business-ontology-view`, branch `feat/business-ontology-view`, base `5dfa863d`.
- Preserve 8004–8009, original artifacts and private model configuration. Use a free isolated port such as 8010.
- No LLM calls or new dependencies are needed; replay the existing business candidate and original source.
- Keep source IDs, Unicode offsets, hashes, RDF IRIs and original candidate/review states unchanged.
- Run impact before modifying existing symbols and detect_changes before commit. Commit summary plus consecutive items, without issue identifiers. Do not push or merge.

## Task 1: Verifiable citation links

Files: new `semantica/ontology/evidence_context.py`, new `semantica/explorer/routes/ontology_evidence.py`; wire router in `semantica/explorer/app.py`; tests `tests/explorer/test_ontology_rule_links.py`.

Interfaces:

```text
POST /api/ontology/evidence-context
  {schema_version:1,business_ontologies:[{uri,terms:[
    {uri,label,type,comment,domain,range,parents,
     source_id,source_sha256,start_char,end_char,quote}
  ]}],support_ontologies:[uri]}
GET /api/ontology/evidence-context
  {configured,business_ontologies:[uri],support_ontologies:[uri]}
GET /api/ontology/related-rules?ontology_uri=...&term_uri=...
  {term,status,association_status:'candidate',associations,anchors,notice}
```

- [x] Write a real API test with a literal Chinese/emoji source, a business term, a rule and explicit Evidence; verify the new endpoint is missing before implementation.
- [x] Add strict manifest validation, atomic session registration, authenticated routes and read-only graph access. Reject duplicate or contradictory ontology roles; do not accept paths/URLs to read.
- [x] Check current term label/comment/type/schema edges against the registered snapshot. Validate source identity, SHA-256 and exact codepoint spans. Reuse source viewer validation for graph Evidence. Whitespace-only intersection, arbitrary neighbors, different sources/hashes and missing hasEvidence never create a link.
- [x] Return primary/supporting roles and every direct/property basis; deduplicate rule/evidence lists. Return explicit missing/mismatched/stale states, without altering RDF or review status.
- [x] Run source viewer and new API regressions, including missing source, quote/hash/range errors, repeated quotes, multiple sources, stale schema, authentication, malformed registration and unchanged graph assertions.

## Task 2: Reproducible context export

Files: `examples/ontology_from_text.py`, new `tests/ontology/test_evidence_context.py`, additions to `tests/ontology/test_ontology_from_text.py`.

- [x] Add failing behavior tests for an optional `--source-id` that exports `ontology-evidence-context.json`, and exact emoji/CRLF line-span registration.
- [x] Build snapshots from the actual serialized RDF and original quoted source lines. Exact-quote-only legacy records require a unique occurrence; ambiguous records fail rather than bind an arbitrary occurrence.
- [x] Include the optional sidecar in existing atomic output and checksum manifest. Keep the old CLI without source-id compatible. Replaying must not call a provider or change source/rule/RDF semantics.

## Task 3: Business graph and evidence navigation

Files: OntologyWorkspace index, Editor/model/API and a new rule-evidence panel; optional initial evidence selection in SourceEvidencePanel; corresponding frontend tests/package test script.

- [x] Add failing tests for business default selection independent of registry order, explicit/deep-linked technical selection and legacy fallback.
- [x] When a context is configured, default to business browsing and hide technical vocabulary/editing under an auxiliary entry. Preserve explicit existing links and registry management.
- [x] Display source-grounded definitions and expandable related rules with direct/property citation basis and primary/supporting roles. Open the existing source modal at the chosen evidence with all rule evidence still switchable.
- [x] Key/reset the whole panel by ontology+term; cancel late requests and close old modals even when two terms share a rule. Cover empty/errors/missing source and literal HTML rendering.

## Task 4: Integration and delivery

- [x] Replay existing artifacts into a new local directory with the original source ID; register both ontologies then the sidecar on an isolated service.
- [x] Verify real browser defaults, technical auxiliary access, a procurement term/property through rules to primary and inherited evidence, missing/stale states and legacy access. Inspect screenshots before completion.
- [x] Run relevant Python tests, frontend tests, production build/typecheck and changed-file static checks. Preserve known unrelated lint/test baseline findings.
- [x] Update the original issue ledger and final usage document with scope, evidence and remaining semantic limits. Verify original hashes and old service health.
- [x] Run GitNexus staged/compare checks and save verification artifacts. Final commit identity is recorded in the local acceptance README and issue ledger; do not push or merge.

## Verification outcome

570 related Python tests (plus 26 subtests) passed in two cleanly exiting groups; 200 frontend tests and TypeScript/Vite build passed. Real Chrome passed 14 main/legacy cases and 6 synthetic Unicode/HTML/status cases. Full ESLint has the unchanged 58 errors and 17 warnings. The combined Python shutdown anomaly is recorded for separate investigation. Original 13 extraction artifacts and RDF semantics are preserved, with no new model call. Independent review has no remaining blocking findings.
