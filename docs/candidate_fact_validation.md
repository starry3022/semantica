# Candidate facts: extraction, RDF, ontology and Explorer

The primary source-to-graph workflow uses the native LLM entity and relationship
entrypoints with the opt-in `candidate_facts` profile. The LLM proposes domain
types and relationships; code assigns source-scoped IDs and checks references
and citations. Bundle v2 keeps complete candidate records in qualified RDF and
passes those same records to the LLM OntologyGenerator:

```text
UTF-8 source → extract_entities_llm → extract_relations_llm
                              ↓
                    entities / relationships
                      ↙                 ↘
           named RDF statements   LLM ontology (complete context)
             base.ttl              business vocabulary only
                      ↘                 ↙
            preservation check + internal projection SHACL
```

`candidate_facts` is an extension in this branch to the native extraction APIs.
Their existing default mode remains available. The specialized
`semantic_extract/process_graph.py` module is another branch extension for
structured process rules; this primary workflow does not invoke it or use its
fixed business classes. A class named `Role` in this workflow is a model
proposal, not a compulsory type defined by that process-rule module.

## Run from any checkout

Use Python 3.12 and install the project's existing `llm-openai`, `shacl` and
`explorer` extras in your environment. Use the corresponding existing provider
extra for a different provider. No new dependency is introduced by this workflow.
Build the Explorer frontend once from the checkout:

```sh
python -m pip install -e '.[llm-openai,shacl,explorer]'
cd explorer
npm ci
npm run build
cd ..
```

Keep a private provider configuration outside the output directory and Git:

```json
{
  "provider": "openai",
  "model": "YOUR_MODEL",
  "api_key": "YOUR_KEY",
  "max_tokens": 16000,
  "temperature": 0
}
```

An OpenAI-compatible gateway can also specify `base_url`. Provider credentials
are never saved in the artifact bundle. Source text is sent to the configured
model during generation; replay and serving do not call a model.

From the repository root:

```sh
python examples/extract_candidate_facts.py \
  --source /path/to/policy.txt --source-id policy-001 \
  --title '采购管理制度' --version V1.3 \
  --config /private/provider.json --output /path/to/new-bundle

SEMANTICA_ALLOW_ANONYMOUS=true python -m semantica.explorer \
  --bundle /path/to/new-bundle --port 8020 --no-browser
```

The server binds to loopback by default. Open `http://127.0.0.1:8020`. Use a
different free port if that address already hosts another session. A missing
`--version` stays unknown; the CLI does not manufacture version metadata.

In Knowledge Explorer, select a candidate entity, open its declared class in
Ontology Hub, or use **Open source material** to inspect explicit evidence.
The class and property identities use the native exporter's IRI rules. Only one
ontology draft is registered. Evidence and source nodes are a provenance display
overlay, not a second business ontology. In v2 that evidence is also retained in
`base.ttl`. Relations with several evidence items
expose each item through the existing source viewer.

The main graph uses a neutral default node color. Selection, hover, paths and
explicit distance views provide the color emphasis; there is no permanent
per-type color legend above the canvas.

Hub's class property list also shows predicates actually used by the class's
explicit instances, joined to the same full property IRI used in Explorer.
Observed usage is labeled separately from a domain declaration and does not
make a property mandatory or add an ontology constraint. Incoming-only range
references remain collapsed, outside the main property count.

Explorer's single **Properties** section contains both literal values and outgoing
object-property targets. For FinanceHead, **审批（approves）** links to the same
predicate definition shown in Hub; its 采购申请 and 供应商付款申请 values open the
actual relationship details, conditions and source evidence. Parallel relationships
remain individually accessible. Properties come from this instance's recorded
values, not from filling in the class's possible properties.

Candidate/review status recorded only as display metadata appears beside the
node title. The declared class remains the primary type entry; its raw `rdf:type`
assertions are available under **Node identifier**. There is no separate record
details section. Older graphs with explicitly defined status predicates retain
their property links. Missing definitions or relationship data are shown honestly;
neither property matching nor source alignment promotes candidate knowledge to
business-reviewed knowledge.

Copy the **whole bundle directory** to another machine; paths inside it are
relative. Only the code checkout, installed dependencies, built frontend and the
bundle are needed for viewing. Private model configuration is needed only when
generating new content. Replay verifies source, prompts, recorded model responses
and ontology identity, and reruns technical validation without a model call:

```sh
python examples/extract_candidate_facts.py \
  --replay /path/to/copied-bundle --output /path/to/new-replay
```

Generation publishes a complete bundle atomically and refuses a nonempty output
directory. Explorer checks file hashes and rejects path traversal and symlinks.
The bundle contains `source.txt`, `source-manifest.json`, `facts.json`,
`extraction.json`, `extraction-issues.json`, entity/relationship/ontology prompt
files, `base.ttl`, `ontology.json`, `ontology.ttl`, `shapes.ttl`, `issues.json`,
`candidate-graph.json` and `SUMMARY.json`. `extraction.json` records typed model
JSON, not raw HTTP response bytes. Checksums show consistency, not authenticity.

The code belongs to `feat/opt-0917`, regardless of whether a checkout lives in
`.local/worktrees/opt-0917` or a normal directory. `.local/worktrees` is just a
Git worktree location. Do not copy that directory's `.git` pointer to another
computer. Fetch/checkout the branch after it has been published, or transfer
local commits explicitly with Git's bundle format:

```sh
# On the machine containing the branch; no push is performed:
git bundle create /path/to/opt-0917.bundle feat/opt-0917
# On another machine:
git clone -b feat/opt-0917 /path/to/opt-0917.bundle semantica
```

Runtime artifacts are separate from code and must be copied explicitly or
regenerated with the tracked command above. There is no dependency on a local
startup script, another worktree, or a developer's absolute filesystem path.

## Evidence and semantic limits

The `candidate-facts-extraction-v4` prompt embeds its response schema and supplies
numbered original lines. It also works without the optional instructor package. The
model selects supporting line intervals; code extracts the exact quote and
computes Unicode offsets without asking the model to count characters. Original
line endings are preserved. Explicit quote/character claims remain supported;
conflicting line and character claims are rejected as a location and retained
for review, never silently repaired.

The prompt resolves additions and inherited duties separately from replacements
and exemptions, attaches the current applicability condition to retained duties,
and asks for all supporting clauses. Action timing, working-day deadlines and
source-language modality remain part of the candidate interpretation. These are
instructions to the model, not deterministic business rules. Replay reconstructs
the exact v3 or v4 prompt and checks its hash; a new prompt cannot silently replay
an old extraction under the same identity.

Entity IDs are stable when replaying the same recorded extraction. Model-local
IDs can be reassigned when the same document is extracted again, so a fresh run
is an independent candidate bundle. Do not carry review decisions across runs
or merge entities using these IDs alone.

The profile accepts one document of at most 32,000 Unicode code points and does
not silently chunk, fall back to pattern extraction, fuzzily relink endpoints or
invent missing entities. Unknown endpoints remain in the recorded response and
appear in the extraction issue list, rather than being added as synthetic facts.
Missing evidence and invalid offsets/quotes remain explicit. Citation alignment
does not verify the relation's business meaning or upgrade candidate/unreviewed
status. All source text remains plain text in the source viewer.

The LLM chooses types, labels and definitions; it can still miss entities or
choose a poor abstraction. A role selector is not a named person and a document
requirement is not a concrete existing contract. These are prompt requirements,
not claims of perfect extraction. Review `extraction-issues.json`,
`ontology.json` uncertainties and the technical report.

Bundle v2 represents **every** relationship as a named `rdf:Statement` with
`rdf:subject`, `rdf:predicate` and `rdf:object`. It does not also assert the bare
business triple. For example, an approval duty under one amount condition and
the same duty under another remain distinct assertion resources. Permissions,
negations and conditional requirements therefore do not become unconditional
facts. Entity type/name triples remain ordinary RDF.

The `https://semantica.dev/candidate#` transport vocabulary carries conditions,
modality, negation, confidence and linked evidence. Canonical JSON records retain
the entire input, including unknown metadata and the distinction between an
absent field, null and false. Statement IDs use supplied relationship IDs;
records without IDs receive deterministic content-based IDs. Ontology metadata
binds both complete-facts and authoritative-RDF hashes. Its LLM prompt includes
full records and evidence; the business schema excludes transport vocabulary.
OWL exports retain property comments as `rdfs:comment`.

`preservation.json` compares qualified RDF with the supplied extracted facts. It
detects removed assertions, changed qualifiers and extra bare business triples.
It cannot detect facts missing from extraction itself. `issues.json` runs SHACL
on an internal business projection and labels its scope
`business_projection_schema`; `conforms` refers to that schema check only.
Independent source-based questions are still needed to evaluate business
completeness. Neither report makes this an executable approval/calendar engine.

Existing v1 bundles remain readable and replayable with their original prompts,
facts and graph projection. Their `base.ttl` contains bare relationships, with
qualifiers only in sidecar JSON and the viewer. Replay keeps that v1 contract;
it does not silently reinterpret the old graph as qualified RDF. OWL serialization
now retains property comments when regenerating an old draft.

## Existing candidate-fact input

The same `entities` / `relationships` dictionary feeds two native components:

The source extraction CLI enables qualified statements automatically. Direct
callers can select the same representation explicitly:

```python
from semantica.ontology import OntologyGenerator
from semantica.ontology.candidate_statements import (
    prepare_candidate_statements,
    validate_candidate_statements,
)

statements = prepare_candidate_statements(candidate_facts)
draft = OntologyGenerator(**private_provider_config).generate_ontology(
    candidate_facts, method="llm", qualified_statements=True
)
preservation = validate_candidate_statements(statements.rdf, candidate_facts)
```

The existing default API and `validate_candidate_facts.py` keep their original
bare-RDF contract for compatibility:

```text
candidate facts ── OntologyGenerator(method="llm") ── ontology draft ──┐
                └─ RDFExporter ───────────────────── base RDF ──────┤
                                      OntologyEngine.validate_graph ─┘
                                                   ↓
                                       technical issues + coverage
```

```python
from semantica.export.rdf_exporter import RDFExporter
from semantica.ontology import OntologyGenerator
from semantica.ontology.engine import OntologyEngine

draft = OntologyGenerator(**private_provider_config).generate_ontology(
    candidate_facts, method="llm"
)
base_rdf = RDFExporter().export_to_rdf(candidate_facts, format="turtle")
report = OntologyEngine(provider=None).validate_graph(base_rdf, ontology=draft)
issues = report.to_dict()
```

`OntologyEngine.from_data(candidate_facts, method="llm")` is the equivalent
facade. An explicit LLM request never silently falls back to heuristics.
Omitting the method keeps the existing heuristic behavior for compatibility;
that older path does not provide this shared vocabulary identity contract.

The exporter defines the actual class and predicate IRIs. The model gives those
terms readable names, labels and definitions, retaining their exact IRIs.
Domain and range proposals must agree with observed types. This input contract
does not supply independently authored required fields, cardinalities or business
rules, so generation does not invent such constraints from sample frequency.
Callers can validate with separately authored ontology constraints or SHACL via
the existing `validate_graph` API when those constraints are available.

`conforms` retains the standard SHACL meaning. Read `coverage` and
`technical_issues` alongside `violations`, `warnings` and `infos`: no matching
targets or no effective constraints does not demonstrate useful validation.
Full-IRI domains, ranges and parent references work with generated shapes.

Generate an artifact bundle or replay one without another model request:

```sh
python examples/validate_candidate_facts.py \
  --facts /path/to/candidate-facts.json --config /private/provider.json \
  --output /path/to/new-validation
python examples/validate_candidate_facts.py \
  --facts /path/to/candidate-facts.json \
  --replay /path/to/new-validation/ontology.json \
  --output /path/to/new-replay
```

The bundle contains unchanged `facts.json`, `base.ttl`, `ontology.json`,
`ontology.ttl`, `shapes.ttl`, `prompt.txt`, `issues.json`, and a hash manifest in
`SUMMARY.json`. Generation errors do not publish a partial bundle. Replay checks
the RDF and prompt hashes and validates the draft again.
The private JSON accepts provider and generation settings only. Set the ontology
title and base URI with `--name` and `--base-uri`, retaining the same values during
replay. Other schema options, including `review_feedback` and `version`, are
rejected in this CLI instead of producing a bundle that cannot be replayed.

This is an internal technical path. A draft and constraints derived from the same
facts check self-consistency; they cannot independently establish completeness,
truth, or correct business meaning. The model's labels and definitions remain
unreviewed. An input `RequiredDocument` remains a material requirement and is not
retagged as an actual `Contract`. Ambiguous or mistaken input types require
correction in the candidate facts. No approval, publication, or automatic change
to the facts is performed. Existing RDF-to-business-concept navigation is a
separate interface; its JSON `references_concept` records are not RDF type
assertions and are not used by this validator.
