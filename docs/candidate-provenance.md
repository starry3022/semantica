# Candidate provenance in Explorer

The provenance vocabulary and its identity bindings are proposed by an LLM.
Application code validates and loads that response. It does not generate business
rules, define a custom approval-rule class, infer missing evidence, or fall back
to a handwritten ontology when validation fails.

## Complete an existing bundle

When source-supported business links are missing from the extraction, first run
the [independent semantic coverage review](candidate-semantic-coverage.md).
Provenance completion defines the supplied links; it cannot recover omitted facts.

Supply a private provider configuration. A separate configuration may set a
smaller generation budget or different supported reasoning settings for this
schema-declaration step:

```powershell
python examples/complete_candidate_provenance.py --bundle path/to/bundle --config path/to/private-provider.json --output path/to/completed-bundle
```

The input must be a qualified `candidate-facts-bundle-v2`. The command preserves
every original artifact and adds the exact prompt, raw model response, normalized
`provenance-model.json`, `provenance-ontology.ttl`, and `provenance-shapes.ttl`. The manifest records their
hashes. No provider credential is copied into the output.

The validator requires exact coverage of the existing unqualified vocabulary,
preservation of authoritative RDF identities, distinct schema IRIs, and a schema
consistent with observed endpoints. It rejects new classes outside that vocabulary,
unsupported domain/range claims, subclass assertions, and mandatory/cardinality
constraints. Definitions remain model proposals, not independently verified truth.

The v5 prompt retains the v4 `relationship_shapes` contract for business and provenance:
model-selected shape IRIs, subject classes (`target_class`), predicates (`path`),
alternative value types (`value_classes`), `schema_role`, labels and definitions.
Inputs include existing object properties, typed business links and assertion
conditions, modality, negation and evidence references, plus entity and statement
citations. Explicit source-type/path/target-type combinations are indexed into one
row per source-type/path, so the model can list alternative targets in one shape.
Repeated runtime metadata is omitted from the prompt, while original bundle
artifacts remain complete. The index is an input constraint, not a generated schema;
the LLM still supplies every shape IRI, label, definition and declaration. Validation
requires complete source-type/path coverage and exactly the supplied target types.
Roles must agree with explicit vocabulary ownership. Code never creates missing
shapes. Saved v2/v3/v4 models still replay with their original contracts and hashes;
reading an older model does not fabricate business declarations.

Each declaration serializes as a standard SHACL PropertyShape with `sh:targetClass`,
`sh:path` and `sh:class`. Multiple target types use standard `sh:or` alternatives;
separate same-path constraints would incorrectly require every value to have every
type. No minimum/maximum count is added. This preserves the shared
OWL property's global semantics while explicitly describing relationships on each
subject type. It does not imply that every instance has evidence or that a candidate
assertion is true. The raw model response remains available for review and replay.

Replay without a model call by omitting `--config` and using the completed bundle
as input. Start Explorer with `--bundle path/to/completed-bundle`. Bundles without
a provenance model continue to load with their previous representation.

## Display

- Entity sidebars show a separate business-relationships section, followed by
  the source-material count, citation count, and a source-viewer entry. Citation
  details and exact source locations live in that viewer; provenance targets are
  not repeated in Properties. Explicitly related edges remain navigable.
- The graph initially hides provenance instances and links using loaded schema
  roles and exact type declarations. **Graph tools → Show evidence & provenance
  links** restores them in Full, Focus, and Grouped views. This is a reversible
  display projection; it preserves the stored graph, model outputs, and class
  definitions. Selecting a hidden evidence node explicitly also reveals it.
- Each edge's existing qualified assertions display their own qualifiers and
  evidence. Opening a citation limits the source dialog to that assertion's evidence.
- Class views separate **Declared provenance relationships** from **Observed
  provenance usage**. The latter never draws a declared relationship. Declared rows
  show their target type and LLM draft status even when there are no instances.
- Ontology graphs render saved shapes as labelled class-to-class edges. Selecting
  a class opens both its incoming and outgoing declared relationships, including
  business and provenance. Existing OWL object properties with a single named
  domain and range also remain visible; usage alone creates no declaration.
  Anonymous expressions and multiple conjunctive domains are not flattened into
  simple links. Equivalent displayed source/property/target triples are deduplicated.
- Edge labels use the property's label and IRI local name, for example
  `有证据（hasEvidence）`. The shape title and comment belong in the declaration
  details. Multiple target alternatives share one declaration in the class panel.
- **Show entire ontology** restores the overview, with a multi-column layout,
  opaque node cards and thin, muted provenance edges. Edge labels appear on hover
  or selection in the overview and remain visible in the class neighborhood.
  Selecting an edge opens its declaration and property definition. These are
  schema-view projections, never new instance edges.
- The provenance ontology is registered separately as a draft. Its definitions
  come from the saved model response; the business ontology is unchanged.

Business links used to check shape value types exist only in a temporary validation
projection. They are never written back as unconditional triples in `base.ttl`.
The original qualified assertions, conditions and individual evidence remain intact.

## Public Palantir references and project adaptation

Consult the [research index](research/README.md) and the dedicated
[Palantir investigation](research/palantir-provenance-relationships.md) before
repeating research. The latter records confirmed mechanisms, limitations, and
the reason for using class-scoped SHACL in this RDF application.

Foundry defines [link types](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview)
and supports [object-backed links](https://www.palantir.com/docs/foundry/ontology/ontology-structural-guidance)
for relationship metadata. Here, existing qualified RDF statements provide those
relationship records; the UI keeps their distinct evidence associations.

AIP's [prompt guidance](https://www.palantir.com/docs/foundry/aip/best-practices-prompt-engineering)
and [Logic blocks](https://www.palantir.com/docs/foundry/logic/blocks) inform the explicit
task, context, and output contract. [Citations](https://www.palantir.com/docs/foundry/chatbot-studio/citations)
inform navigation to identified source material. These are adaptations of public
mechanisms, not Palantir's internal prompts or a claim that it supplies this schema.
