# Evidence-backed process rule extraction

`extract_process_rules` is an opt-in path for normative process documents. It
extracts candidate obligations, permissions and prohibitions directly from source
clauses, without first limiting the task to a named-entity inventory. Existing
entity/relation prompts and default entry points remain unchanged.

## What a candidate contains

- Activity and action, modality, acting roles and recipient roles.
- Text conditions and numeric intervals with explicit open/closed endpoints and
  units. Decimal values retain their precision.
- Approval groups with `all` or `any` semantics, required documents, and deadlines
  relative to an anchor event. A working-day duration is not converted to a date.
- A primary source clause, any supporting clauses needed to interpret inherited
  requirements, and exact source quotations for all referenced clauses.
- Program-computed Unicode character offsets and a source content hash.

This describes **what a policy requires or permits**, not an event that already
occurred. All results remain `candidate` / `unreviewed`.

## Python API

```python
from semantica.semantic_extract import (
    extract_process_rules,
    process_rules_to_graph,
    export_process_rdf,
)

result = extract_process_rules(
    text,
    source_id="maintenance-policy-v3",
    provider="openai",  # also used for a compatible configured gateway
    model=model_id,
    api_key=private_api_key,
    base_url=private_base_url,
    temperature=0,
    max_tokens=16384,
)
graph = process_rules_to_graph(result)
turtle = export_process_rdf(graph)
```

The API calls the existing `generate_typed` interface once. The provider can
perform its existing transport/format repair attempts; one API call is **not** a
promise of one HTTP request. Provider failures, invalid schema fields and invalid
quotations raise errors. There is no pattern-extraction fallback in this path.

All nested schemas forbid unknown fields. Bound flags and deadline/offset
integers reject coercions such as `"yes"` or `True`. Model-created fields are
still claims: valid structure and exact quotation do not establish that the
interpretation is correct.

## LLM stages and output budget

Only `extract_process_rules` calls the LLM. Its single typed response contains
rules, roles, conditions, approval groups, document requirements, deadlines,
evidence quotations and clause assessments. There are no separate NER or
relation-extraction model calls in this path.

| Stage | LLM call | Output token limit |
|---|---|---|
| Text parsing, source hashing and clause segmentation | No | Not applicable |
| Typed process-rule extraction and clause assessment | Yes | Caller-supplied `max_tokens`; the example above uses 16384 |
| Schema validation, exact evidence alignment and coverage consistency | No | Not applicable |
| Graph projection and instance RDF export | No | Not applicable |
| Declared ontology generation and OWL serialization | No | Not applicable |
| SHACL generation and validation | No | Not applicable |
| Offline replay and Explorer display | No | Not applicable |

`max_tokens` is a per-request output ceiling, not a document length, a promised
response size or a global SDK default. Provider fallback/repair paths can produce
additional requests; aggregate token consumption must be measured from actual
responses. The program validates the model's clause assessments for consistency;
it does not independently certify their semantic completeness.

## Source and coverage checks

Blank-line-delimited source units receive deterministic clause IDs. Their text
is sent as JSON so embedded newlines can be copied without alteration. The model
must assess every unit as `rule`, `non_normative` or `unresolved`, giving a reason.

`finalize_process_rules(text, source_id, response)` independently verifies:

- Unique rule IDs and known, nonduplicated primary/supporting clause references.
- Nonempty, verbatim evidence unique within the cited clause.
- Evidence for the primary clause and every supporting clause.
- Missing assessments, unresolved units and rule-labelled units without a
  primary extraction.

`coverage.complete` only reports consistency of this paragraph accounting. A
model can omit a requirement inside a paragraph or misclassify a normative
paragraph as descriptive. Therefore the coverage status stays `needs_review`.
Acceptance for an actual policy still requires a separate checklist of its
conditions, roles, documents, exceptions and time requirements.

Mixed/nested Boolean logic is not an executable expression language in this
version. The prompt requests separate rules when faithful decomposition is
possible and an unresolved assessment otherwise. Relative deadlines are stored;
no business-calendar scheduling or process execution is implemented.

## Graph, RDF, ontology and SHACL

The projection reifies rules and complex components:

```text
ProcessRule → Activity / Role / Condition / ApprovalGroup
            → RequiredDocument / RelativeDeadline / Evidence → SourceDocument
ApprovalGroup → Role
```

IDs bind both source identity and content hash. Identical documents from different
sources do not silently share rule/evidence IDs. Projection revalidates schemas,
clause references, and evidence offsets against the supplied clause text.
The original source remains necessary to independently verify its hash; a saved
candidate document is not its own authority.

`export_process_rdf` preserves scalar properties with RDF datatypes and complete
rule structures as `rdf:JSON` literals. Amounts use `xsd:decimal`, deadline counts
use `xsd:integer`, and approval membership is represented by edges. This dedicated
export avoids silently dropping complex rule data in a generic triple adapter.

`process_rule_ontology` supplies a declared vocabulary; it is not an ontology
induced from whatever the model happened to extract. `process_rule_shapes` checks
required activities/evidence, modalities, approval groups, numeric condition
fields and interval consistency, positive integer deadlines and anchors, and
evidence/document source consistency. Evidence spans must stay within the source
length and match the Unicode character count of their quotation; these checks
do not independently compare an RDF quotation to the original document.

SHACL validates the represented structure. It does not validate factual truth,
complete interpretation, source authority, permissions, policy currency or
organizational approval to publish the knowledge.

## Reusable CLI example

Run from this checkout, with the existing optional LLM and SHACL dependencies
available. Keep credentials outside the repository.

```bash
python examples/process_rules_from_text.py \
  --source-file /path/to/policy.txt \
  --source-id maintenance-policy-v3 \
  --config /private/path/llm-config.json \
  --output-dir /path/to/new-artifacts
```

The config accepts provider/model and optional api_key, base_url, temperature,
max_tokens and max_retries. This example does not apply application-specific
transport options such as a separate `timeout_seconds`; applications can manage
transport settings and request auditing through their configured provider.

The output directory must be empty. Artifacts include original text, typed
candidates, Explorer graph, instance Turtle, ontology Turtle/RDF/XML, SHACL,
validation coverage and a summary. Missing paragraph coverage, zero candidate
rules or structural validation failure return a nonzero exit code; produced
diagnostic artifacts remain available for review.

Replay a saved extraction without calling a model:

```bash
python examples/process_rules_from_text.py \
  --source-file /path/to/policy.txt \
  --replay /path/to/previous-artifacts/process-rules.json \
  --output-dir /path/to/new-replay-artifacts
```

Replay checks the original source hash and reconstructs evidence offsets. It
does not trust offsets or a coverage verdict merely because they occur in JSON.
The CLI suppresses provider logs and redacts the explicitly configured API key
from reported exceptions; it never exports the private config.

## Inspecting source materials in Explorer

Register the original UTF-8 text explicitly when starting Explorer. Place a
`sources.json` manifest next to `source.txt`:

```json
{
  "sources": [
    {
      "source_id": "maintenance-policy-v3",
      "path": "source.txt",
      "title": "Maintenance policy"
    }
  ]
}
```

The `source_id` must match the graph. Optional `version` and `source_uri` fields
describe known metadata; omitted versions are displayed as unknown. Do not invent
a version or effective date. Multiple entries can register different sources or
different content hashes for one source ID.

```bash
SEMANTICA_ALLOW_ANONYMOUS=true python -m semantica.explorer \
  --graph /path/to/artifacts/candidate-graph.json \
  --source-manifest /path/to/artifacts/sources.json \
  --host 127.0.0.1 --port 8007 --no-browser
```

The candidate graph contains rule instances. Load the separate, explicitly
generated `ontology.ttl` into each new Explorer session to browse the schema.
In **Ontology Hub → Load Ontology → File Upload**, select that file and load it.
The registry then lists **Process Rule Ontology**; **Editor** displays its classes
and properties. A graph-only startup has an empty ontology registry.

For a repeatable local startup, run the following in another terminal after
Explorer is healthy. Send the existing file's text to the ontology import API;
the server does not need filesystem access to that path or an external URL:

```bash
python - /path/to/artifacts/ontology.ttl <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

request = urllib.request.Request(
    "http://127.0.0.1:8007/api/ontology/load",
    data=json.dumps({
        "content": Path(sys.argv[1]).read_text(encoding="utf-8"),
        "format": "turtle",
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(json.load(response))
PY
```

This import adds schema nodes and edges to the running session. It preserves the
saved candidate graph, source registration and evidence review states. Repeat
the import after restarting a session from the candidate graph. For the supplied
procurement artifacts, the ontology has 9 classes and 40 properties; importing it
adds 56 nodes and 72 edges to the 54-node, 96-edge candidate graph.

Select a relationship in Knowledge Explorer and expand **Properties · N — View
all / collapse** to read every recorded property. Source, context/evidence and
review/status fields have stable sections regardless of input order. Long text
keeps its line breaks, nested values use indented JSON, and null, empty text,
false and zero remain distinct. The list scrolls; collapse it to restore graph
space. Selecting another relationship clears the previous values and closes
the list. A relationship without properties shows an explicit empty state.
These raw fields do not imply verified evidence or business approval; use the
separate **Source material & evidence** entry for validated source alignment.

Manifest paths must be relative files inside the manifest directory. Absolute
paths, directory escapes and symlinks escaping that directory are rejected.
HTTP requests select graph node or edge IDs; they cannot register files or request
arbitrary filesystem paths. Source URIs are metadata and are never fetched.
Registered text is a startup snapshot: restart with the appropriate manifest to
load changed materials. Graph imports do not automatically register source files.

Select a ProcessRule, Evidence or SourceDocument and open **Source material**.
The full-text viewer shows the material identity, version, SHA-256 and evidence
status. Select a primary or supporting clause to scroll to and highlight its exact
span. **Markdown source** in the existing Content viewer means the node's Markdown,
not the original material.

Only explicit evidence associations are used: `hasEvidence` targets,
`fromSource` evidence sources, or a relationship's `evidence_id` / `evidence_ids`
properties. Unrelated neighbors do not count as evidence. Old graphs remain
browsable and show an explicit empty state when these associations are absent.

The viewer checks the registered content hash, Unicode character offsets
`[start_char, end_char)`, and the exact quotation. Chinese characters, emoji and
newlines retain their positions; repeated quotations use the supplied offsets
instead of searching for the first occurrence. Missing materials, mismatched
hashes and invalid spans are reported without a successful highlight. Source text
is displayed literally, including any HTML or Markdown it contains.

**Quote alignment is not business approval.** These checks do not establish policy
authority, semantic completeness or business correctness, and do not change
`candidate / unreviewed` states. Source registration and viewing do not modify
saved extraction results, graph data or RDF exports.

## Compatibility and tests

The existing generic entity/relation conversion now preserves model-provided
business metadata. Runtime provider/model/extraction_method fields take priority,
and temporal provenance keys only come from the enabled temporal parser.
Model-supplied `fact_status`, `review_status` and `evidence_verified` keys are
discarded; business metadata cannot promote these reserved governance states.
Preserved metadata is not automatically treated as verified evidence.

Tests cover non-procurement examples, AND/OR approval groups, inherited evidence,
interval boundaries, strict types, unknown fields, source isolation, invalid
citations, empty/missing output, RDF precision and negative SHACL mutations.
The CLI integration tests use offline replay and real RDF/SHACL components.

```bash
python -m pytest -q \
  tests/semantic_extract/test_process_extractor.py \
  tests/semantic_extract/test_process_graph.py \
  tests/semantic_extract/test_process_rules_example.py \
  tests/semantic_extract/test_llm_metadata_preservation.py \
  tests/semantic_extract/test_structured_output.py \
  tests/semantic_extract/test_temporal_extraction.py
```
