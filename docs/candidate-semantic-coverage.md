# Candidate semantic coverage review

The portable extraction CLI runs staged LLM coverage review after native entity
and relationship extraction, before LLM ontology generation and qualified RDF
export. Predicates, directions, conditions and repair decisions come from the
model. Code validates contracts, applies explicit identity references and
serializes the result; it does not invent business relationships.

The public Python facade retains its previous two-call behavior by default.
Pass `review_coverage=True` to `extract_candidate_facts` to enable staged review.
An extraction with no entities does not invoke a reviewer or invent endpoints.

## Small calls with separate responsibilities

The current prompt version is `candidate-semantic-coverage-staged-v4`.

| Stage | Model output | Maximum completion budget |
| --- | --- | --- |
| Diagnosis | Source-answerable task questions, relevant entity IDs, evidence and coverage gaps | 6,000 tokens |
| Revision | Retained original IDs, replacements, removals and additions | 10,000 tokens |
| Acceptance | Entity and clause audits, answers supported by final relationship endpoints, verdict and findings | 12,000 tokens |

The caller's smaller budget takes precedence. `max_completion_tokens` is also
supported; only one token-limit parameter is sent. These are ceilings, not target
lengths. For reasoning models, the provider may count reasoning against them.

The revision stage does not repeat retained relationship payloads. Explicit
`retained_ids` references preserve those original typed values exactly. Revised
and added relationships contain their full qualifiers and evidence. Every
original relationship must have exactly one disposition. Each revision round is
relative to the original input, including any additions that should survive.

Acceptance receives the final graph, numbered source and questions in a separate
call. The code supplies endpoint-reference indexes, but does not determine their
business meaning. If the model requests revision, its findings are passed to one
further revision and acceptance round. There are at most two semantic rounds.

A technical validation failure can trigger one retry of that stage with its
rejected response and exact validation error. Both attempts remain recorded.
The model must correct the output; code does not repair business content. After
the retry limit, a provider failure, or a second `needs_revision` verdict, no
bundle is published. Increasing the output budget is not a substitute for
separating responsibilities or validating the result.

## Review an existing extraction

```powershell
python examples/extract_candidate_facts.py --config path/to/private-provider.json --review-bundle path/to/original-bundle --output path/to/reviewed-bundle
python examples/complete_candidate_provenance.py --bundle path/to/reviewed-bundle --config path/to/private-provider.json --output path/to/completed-bundle
python -m semantica.explorer --bundle path/to/completed-bundle
```

The input must be an original qualified `candidate-facts-bundle-v2`. Its hashes,
source identity and replayed facts are checked before any model call. Entity
identities, types and citations remain unchanged. Ontology generation uses the
resulting business vocabulary. Provenance completion generates the corresponding
business and evidence relationship declarations through its existing LLM step.

Repeated review of an already reviewed extraction is rejected. Start independent
experiments from the original bundle and use a new output directory. The command
never overwrites a nonempty output directory.

## Semantic boundaries and technical checks

The prompts ask the model to consider actors, categories, scope, alternatives,
compound conditions, participation, negation, modality and timing. They prohibit
guessing links from co-occurrence, shared evidence or the desire to remove isolated
nodes. Several existing relationships with the same condition can already cover
a parallel requirement; they need not generate an extra combination relationship.

- Every entity has an audit disposition: `linked`, `descriptive`, `unsupported`
  or `unresolved`. Linked references must exactly match final incident relations.
  Descriptive entities may remain isolated; unresolved gaps remain visible.
- Diagnosis accounts for every entity, either through task questions or a
  separate `non_question_entities` source-based explanation. This catches skipped
  referents early without requiring that every entity receive a relationship.
- Clause groups cover every nonempty source line exactly once. Valid blank lines
  may accompany a group but are not required. Raw model groups are preserved.
- Every diagnosis question has an acceptance answer with the same ID and text.
  Its referents must remain listed. An `answered` item must cite relationships
  whose endpoints include those entities; names only in conditions or source
  quotations are insufficient. The model evaluates meaning and chooses whether
  a missing association is supported. Code only checks identities and references.
- New relations require existing endpoints, unique IDs, valid fields and aligned
  evidence. Conditions, modalities and evidence survive qualified RDF export.
  A display edge is a projection of an assertion, not an unconditional fact.

Source evidence uses numbered lines; the technical codec copies exact text and
Unicode offsets, including original newlines. This pass cannot add, delete, merge
or reclassify entities. Missing referents need further review. Neither model
acceptance nor SHACL validation promotes candidates to human-approved facts.

## Records, replay and recovery

`extraction.json` retains the initial extraction and adds a `coverage_review`
record with source/input binding, prompt version, provider/model and ordered
stages. Each stage saves its prompt hash, public generation settings, typed
response and any technical rejection feedback. Credentials are never exported.

The bundle includes `coverage-review.json`, `coverage-review-prompt.txt`, and
separate `coverage-<stage>.json` / `coverage-<stage>-prompt.txt` files, including
retry stages. `SUMMARY.json` records audit counts, unresolved dispositions and
artifact hashes. Stage count includes retries and additional semantic rounds;
three responsibilities do not imply exactly three API requests.

```powershell
python examples/extract_candidate_facts.py --replay path/to/reviewed-bundle --output path/to/offline-facts
python examples/complete_candidate_provenance.py --bundle path/to/completed-bundle --output path/to/offline-provenance
```

Replay calls no model. It validates source binding, exact prompts, stage order,
retry feedback, final facts and all exported audit artifacts. Legacy extraction
and coverage prompt versions retain their own schemas and prompt identities;
replay does not add a new diagnosis or evaluation to older recordings.

On rejection, the CLI saves a sibling `<output>.coverage-rejected.json` without
overwriting an existing diagnostic. The staged Python function
`semantica.semantic_extract.candidate_coverage_stages.review_candidate_facts`
also accepts `resume_record=<diagnostic["review"]>`. It revalidates saved stages,
requires the recorded provider/model and source, and calls the model only for
unfinished stages. It does not reset retry limits or bypass a failed final verdict.
There is currently no CLI resume flag.

The private provider configuration may optionally include `reasoning_effort` and
`thinking: {"type": "enabled"}` or `thinking: {"type": "disabled"}` for a gateway
that supports them. These settings are passed through, not selected from business
content. Disabling reasoning reduced response length in local experiments but
also produced semantic errors; small responses still require independent review.

Consult the [Palantir research](research/palantir-isolated-entities-and-semantic-coverage.md)
for official references, local experiments and project-specific adaptations.
These prompts are not Palantir's internal prompts or a reproduction of its pipeline.
