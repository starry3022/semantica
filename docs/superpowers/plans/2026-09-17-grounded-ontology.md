# Grounded business ontology implementation plan

**Goal:** Generate a reviewable business ontology with the configured LLM and clear labels, while preserving exact process evidence and its RDF identifiers.

**Architecture:** Reuse `LLMOntologyGenerator` and existing OWL serialization. Validate generated vocabulary at the LLM boundary; expose business ontology and deterministic process/evidence vocabulary as separately named resources. Keep extracted rules and instance RDF unchanged.

**Tech stack:** Existing Python, rdflib, pytest, Explorer and browser automation. No dependencies added.

**Spec:** User requests business class naming via LLM, prompt review, and an audit of RDF names such as `start_char`.

## Constraints

- Work on `feat/opt-0917`; preserve original artifacts and services on 8004–8008.
- Never print API credentials or modify global LLM settings.
- Run GitNexus impact before changing existing symbols, then detect_changes before commit.
- Require candidate/unreviewed status and exact source quotes; do not claim ontology correctness from structural validation.
- Commit messages use summary and consecutive list items without issue identifiers.

## Execution

1. Add failing tests in `tests/ontology/test_llm_generator.py` for provider/token options, full IRI references and parent serialization, malformed output, duplicates, cycles, source grounding, prompt constraints, and no fallback.
2. Fix `semantica/ontology/llm_generator.py`: pass explicit config, preserve per-call overrides, use a source-grounded business modeling prompt, validate names/references, and retain source/model/prompt provenance. Keep generic callers compatible; the new artifact workflow explicitly requires grounding.
3. Independently add complete label/comment coverage to `process_rule_ontology`, including a Chinese label option. Assert graph equivalence after excluding annotations and document Unicode offsets without changing their IRIs or values.
4. Add `examples/ontology_from_text.py` and CLI regression tests. Inputs are an explicit UTF-8 source and private model config (or a saved response for offline replay); output must be empty. Save prompt, candidate JSON, Turtle/OWL and a structural validation report. Failure produces no successful ontology artifacts and no static fallback.
5. Run a bounded, audited LLM call using the existing private configuration into a fresh `.local` directory. Inspect every generated class/property and exact quote. Keep actual model/token evidence, with secrets redacted.
6. Start a separate Explorer on free port 8009 with the unchanged process graph and registered source. Load the LLM business ontology and the clearly named support vocabulary; verify Chinese labels, hierarchy/domain/range, evidence metadata and source navigation in a real browser.
7. Run relevant Python regressions, frontend tests/build and changed-file static checks. Update final usage docs and the original issue ledger only where supported by evidence; record remaining semantic review limits. Run detect_changes and commit verified changes without pushing.

## Validation examples

```python
assert options['max_tokens'] == 12000
assert (child, RDFS.subClassOf, parent) in exported_graph
assert all(item['evidence_quote'] in source for item in ontology['classes'])
assert ontology['metadata']['review_status'] == 'unreviewed'
assert isomorphic(strip_annotations(old_support), strip_annotations(new_support))
```
