# Candidate bundle fixtures

`candidate_bundle_v1/` was produced with the native extraction-v3 and
ontology-v2 pipeline at commit `9d823815`, using a small Chinese policy sentence
and deterministic mock provider responses. It contains no provider credentials.
Its OWL serialization also uses that commit's generator.

The OWL fixture deliberately retains the serializer's extra newline at EOF;
do not normalize golden output whitespace independently of its manifest hash.

Replay tests use the saved source, prompts, model records and exact output
identities to protect the pre-v2 format. They prohibit provider calls. Property
comments were absent from old OWL output; the corrected serializer retains them
when the old JSON ontology is exported again.
