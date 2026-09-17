# Instance and ontology class navigation

Work on `feat/opt-0917`, based on the consolidated local improvements and current upstream main (`6fc2facf`). Preserve the prior service worktrees and original extraction artifacts.

## Behavior

- Resolve instance classes only from explicit RDF type declarations, absolute type IRIs, or the source graph's declared base namespace. Keep multiple classes and report unloaded class definitions. Never infer a class from a label, IRI suffix or arbitrary neighboring node.
- Preserve source graph metadata through JSON serialization, loading and clearing so namespace identity follows the actual graph lifecycle.
- Show declared classes in the selected instance inspector, with class labels, URIs, declaration basis and navigation to Ontology Hub. Show validated source-citation associations to business classes separately; these are candidate associations, not type assertions or business approval.
- Offer an optional display of the selected instance's type links. Add only its class references to the display projection after aggregation and neighborhood limiting. Do not mutate graph storage or RDF, and do not treat display-only links as evidence-bearing relationships.
- List instances of a selected class in Ontology Hub using the same backend resolver, with navigation back to the knowledge graph.
- Clear stale selection data, type links and responses when the node or graph changes. Keep older graphs usable with explicit unmapped states.

## Implementation and ownership

1. Lock metadata lifecycle and read-only API behavior with regression tests; implement the shared type resolver and authenticated routes.
2. Build tested instance/class panels and workspace navigation using existing URL ownership and draft protection.
3. Add tested type-link display projection and coordinate a single selected-node request in GraphWorkspace.
4. Run relevant Python and frontend regressions, build/type checks and static comparisons. Validate the real procurement artifacts in a browser on a new service port, including class navigation, evidence-only business associations, type links, node switching and legacy/unmapped data.
5. Update final usage documentation and the existing issue ledger with evidence and remaining scope. Commit with a summary and consecutive list items; do not push.

## Boundaries

No LLM calls, new dependencies, changes to extraction artifacts, RDF semantics, review status or global model settings. Editing ontology definitions remains session-only. This work makes existing declarations and validated evidence associations visible; it does not automatically assign business ontology types to normative rules.
