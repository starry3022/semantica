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

`extract_process_rules` calls the LLM for process rules. Its typed response contains
rules, roles, conditions, approval groups, document requirements, deadlines,
evidence quotations and clause assessments. There are no separate NER or
relation-extraction model calls in this path. The separate business-ontology
command below makes its own explicit LLM call; it reuses the original text and
does not regenerate or rewrite the rules.

| Stage | LLM call | Output token limit |
|---|---|---|
| Text parsing, source hashing and clause segmentation | No | Not applicable |
| Typed process-rule extraction and clause assessment | Yes | Caller-supplied `max_tokens`; the example above uses 16384 |
| Schema validation, exact evidence alignment and coverage consistency | No | Not applicable |
| Graph projection and instance RDF export | No | Not applicable |
| Business ontology proposal with `LLMOntologyGenerator` | Yes, when explicitly requested | Caller-supplied `max_tokens` |
| Fixed process/evidence vocabulary and RDF/OWL serialization | No | Not applicable |
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
  --host 127.0.0.1 --port 8013 --no-browser
```

The candidate graph contains rule instances. Each new Explorer session needs an
explicit schema import. In **Ontology Hub → Registry → Load Ontology → File
Upload**, load the business `ontology.ttl` and the separate
`process-vocabulary.ttl` produced by the command below. Then register
`ontology-evidence-context.json` through the API. Source registration, both
ontology imports and the evidence context are required for business-to-rule
navigation. A graph-only startup has an empty registry.

For a repeatable local startup, run the following in another terminal after
Explorer is healthy. Send the existing file's text to the ontology import API;
the server does not need filesystem access to that path or an external URL:

```bash
python - /path/to/business-artifacts <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

artifacts = Path(sys.argv[1])
base_url = "http://127.0.0.1:8013"

def post(path, payload):
    request = urllib.request.Request(
        base_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print(json.load(response))

for name in ("ontology.ttl", "process-vocabulary.ttl"):
    post("/api/ontology/load", {
        "content": (artifacts / name).read_text(encoding="utf-8"),
        "format": "turtle",
    })
post("/api/ontology/evidence-context", json.loads(
    (artifacts / "ontology-evidence-context.json").read_text(encoding="utf-8")
))
PY
```

The ontology imports add schema nodes and edges to the running session. The
evidence context only registers navigation metadata; it adds no RDF assertions,
files or source URLs. These operations preserve the saved candidate graph and
evidence review states. Repeat the imports and context registration after
restarting a session. Reopen Ontology Hub after registering the context.

With a registered business context, **Ontology Hub → Business graph** is the
default view. **Active ontology** lists business ontologies. The graph starts in
read-only mode; **Technical vocabulary & advanced editing** contains the support
vocabulary and an explicit **Enable advanced editing** option. **Advanced
ontology tools** contains Registry and the other existing tools. The support
vocabulary is named **流程与证据支持词汇** in Chinese and **Process evidence
vocabulary** in English. Sessions without this context keep the Registry default;
explicit tab links and technical-term links remain usable.

In **Knowledge Explorer**, schema definitions are hidden by default so the
business instances, rules and evidence remain the main graph. **Include ontology
schema** restores the loaded definitions and structural endpoints. The counters
separate the visible graph from the complete session. Searching for a schema
term enables that scope explicitly; turning it off clears hidden selections.
This display projection does not delete triples, map instance types or merge
ontologies. Legacy resources without explicit schema types are kept visible.

Selecting a class shows **Declared properties**, **Inherited properties** from
loaded parent-class declarations, and a separate **Referenced as range** group.
Rows show property type, domain and range; select a row to open its definition.
These RDFS declarations do not make fields mandatory and are not instance values.

**Edit class** changes label, definition and parent classes. **Edit property**
changes label, definition, domain and range. **Save changes** writes the current
graph session and reloads its definition; it does not publish a version, edit
source files or approve candidate knowledge. References use one full IRI per
line and must already be loaded; datatype ranges must also be recognized XSD
IRIs. URI, term type, ownership and review metadata cannot be changed by this
form. External or unsupported legacy terms keep their read-only details.

The API is GET/PATCH `/api/ontology/term?ontology_uri=...&term_uri=...`. PATCH
requires `expected_revision`, `label`, `comment`, `parents`, `domain` and `range`.
A concurrent edit returns 409 without overwriting the other change. The form
keeps its draft and offers **Reload current definition**; **Cancel editing**
discards only the local draft. Session edits survive browser reload but not
server restart. The older advanced **Save draft** workflow remains separate;
it is not the session-save action.

Select a business class or property, read its definition, and expand **Related
rules & evidence**. Each association identifies **Direct term citation** or
**Via property**, with a primary or supporting clause. Select **Primary** or
**Supporting**, then **Open source material** to inspect the exact highlighted
span. The full-text dialog still offers all evidence for that rule. Changing the
concept, ontology or citation clears the previous selection and closes its
dialog.

Links require the same source ID and content hash, valid exact quotations,
overlapping nonblank Unicode character spans and an explicit `ProcessRule →
hasEvidence → Evidence` association. A class may also use a property's citation
when that property explicitly declares the class in `rdfs:domain` or
`rdfs:range`; the panel identifies that property. These are candidate citation
links, not instance type assignments or a complete inventory of rules governing
the concept. Missing sources, changed definitions, hash/range/quote failures and
invalid rule evidence show their reasons instead of an apparent successful link.

Select a relationship in Knowledge Explorer and expand **Properties · N — View
all / collapse** to read every recorded property. Source, context/evidence and
review/status fields have stable sections regardless of input order. Long text
keeps its line breaks, nested values use indented JSON, and null, empty text,
false and zero remain distinct. The list scrolls; collapse it to restore graph
space. Selecting another relationship clears the previous values and closes
the list. A relationship without properties shows an explicit empty state.
These raw fields do not imply verified evidence or business approval; use the
separate **Source material & evidence** entry for validated source alignment.

## LLM business ontology and technical RDF fields

Generate a separate candidate business ontology with the configured model:

```bash
python examples/ontology_from_text.py \
  --source /path/to/artifacts/source.txt \
  --source-id maintenance-policy-v3 \
  --config /private/llm-config.json \
  --max-tokens 16384 \
  --base-uri https://example.org/procurement-business/ \
  --process-base-uri https://example.org/procurement-process/ \
  --name '采购与付款业务候选本体' \
  --output /path/to/new-business-ontology
```

The private JSON specifies `provider`, `model` and optional `api_key`, `base_url`
and generation options. `--max-tokens` overrides only this request. The example
does not implement the local audit runner's separate `timeout_seconds` setting.
The output must be a new or empty directory. No dependencies, URL fetching,
global model configuration changes or implicit static fallback are involved.

The output contains `ontology.json`, `ontology.ttl`, `ontology.owl`, the separate
Chinese `process-vocabulary.ttl`, exact `source.txt`, `prompt.txt`,
`validation.json` and `SUMMARY.json`. For offline validation/export, replace
`--config ... --max-tokens ...` with `--replay /saved/ontology.json`; retain the
saved `prompt.txt` beside it. Replay checks source and prompt hashes and makes no
model call. Successful artifacts are published only after all checks pass.

The optional `--source-id` must match the Explorer source registry and candidate
graph. It also exports `ontology-evidence-context.json`, separating business and
support ontology roles and binding each term to its exact exported snapshot
(IRI, label, type, comment, domain, range and parents), source ID/hash, quote and
Unicode span. Line references disambiguate repeated quotations. Older candidates
without line references need a unique exact quote. An edited definition or schema
invalidates its previous binding until an updated context is explicitly
registered. Omitting `--source-id` retains the ontology export without this
optional navigation artifact. Registration does not fetch URLs or local paths,
modify the original extraction, or promote `candidate / unreviewed` results.

The prompt requires source-language business labels and definitions, PascalCase
class identifiers, camelCase property identifiers and evidence selected by
inclusive, 1-based `evidence_lines`. Code copies the quote from the selected
source lines with Unicode and line endings unchanged; the model does not invent
character offsets. Replay also accepts earlier exact-quote candidates.
For an explicit revision, the Python API accepts `draft_ontology` and
`review_feedback` in `generate_ontology_from_text`. The draft remains untrusted;
the model must check it against the original source. Feedback and draft are
included in the saved prompt/hash, and the result passes the same validation.
This is another model call, not a silent repair or an approval action.
It distinguishes classes from individuals, people from role types, authorization
requests from grants, and required approval from completed approval. A class's
name, label and definition must describe the same concept. Source instructions
are document data. Fixed evidence terms cannot be redefined by the model.

The boundary rejects malformed/empty results, duplicate names/IRIs, undeclared
references, hierarchy cycles, unsupported datatypes, invalid/blank line selections
and nonmatching quotes.
Grounded mode requires one declared domain/range per property, avoiding an
accidental intersection when the model intended alternatives. References become
full HTTP(S) IRIs, and parent relationships survive both OWL serializers. The
bundle verifies Turtle/RDF/XML graph equivalence. Quotes and provenance remain
visible as RDF comments. These checks establish structure and exact quotation,
not completeness, entailment, business review or authorization.

| RDF element | Who chooses or computes it? |
|---|---|
| Business ontology class/property names and definitions | LLM proposal, subject to validation and review |
| Process rules, conditions and quoted evidence | LLM extraction, followed by deterministic validation |
| `ProcessRule`, `Evidence`, `hasEvidence`, `start_char`, `end_char` | Fixed representation/evidence vocabulary in code |
| Evidence offsets and source hashes | Code, never guessed by the model |
| Turtle/OWL syntax, literal datatypes and instance identifiers | Deterministic serializers and graph projection |

`start_char` is an evidence property, not a business class. It means a zero-based
Unicode codepoint offset; `end_char` is exclusive. The support vocabulary adds
readable labels such as **证据起始位置** and **证据结束位置** and explains the
`[start_char, end_char)` interval. Its original IRIs, types, domains/ranges,
instance values and SHACL targets remain stable. [RDFS labels](https://www.w3.org/TR/rdf-schema/#ch_label)
provide human-readable names without changing resource identity.

The business schema uses a distinct namespace and does not automatically retype
existing rule records as business events or assert equivalence between the two
vocabularies. Review and an explicit mapping are required before using it to
govern instance data. All proposals remain `candidate / unreviewed`. A missing
ontology version stays unknown; a document's V1.3 is not an ontology release.

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

Business navigation and source evidence checks:

```bash
python -m pytest -q \
  tests/ontology/test_evidence_context.py \
  tests/ontology/test_ontology_from_text.py \
  tests/explorer/test_ontology_rule_links.py
cd explorer
npm run test:ontology-evidence
npm run test:ontology-terms
npm run test:graph-workspace
npm run build
```

These regressions cover source and term isolation, changed snapshots, invalid
citations, direct/property links, Unicode ranges, legacy defaults, primary/support
selection, late responses, concept-switch cleanup and literal HTML display.
