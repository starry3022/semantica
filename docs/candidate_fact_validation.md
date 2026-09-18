# Candidate facts: native technical validation

The same `entities` / `relationships` dictionary feeds two native components:

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
