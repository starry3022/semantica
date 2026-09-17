import assert from "node:assert/strict";
import test from "node:test";
import { resolveEditorOntology, initialOntologyTab, partitionOntologyRegistry } from "../src/workspaces/OntologyWorkspace/ontologyEditorModel.ts";

const entries = [
  { uri: "https://example.test/support/", name: "Technical vocabulary" },
  { uri: "https://example.test/business/", name: "Business ontology" },
];
const context = {
  configured: true,
  business_ontologies: [entries[1].uri],
  support_ontologies: [entries[0].uri],
};

test("a configured business ontology is the landing graph regardless of registry order", () => {
  for (const registry of [entries, [...entries].reverse()]) {
    assert.deepEqual(resolveEditorOntology(registry, "", undefined, context), {
      status: "resolved", uri: "https://example.test/business/",
    });
  }
});

test("explicit technical ownership and authoritative no-owner verdicts survive business defaults", () => {
  assert.deepEqual(resolveEditorOntology(entries, "https://example.test/support/Evidence", entries[0].uri, context), {
    status: "resolved", uri: entries[0].uri,
  });
  assert.deepEqual(resolveEditorOntology(entries, "https://example.test/business/Unknown", null, context), {
    status: "unowned", entityUri: "https://example.test/business/Unknown",
  });
});

test("legacy and unloaded business registries do not fabricate a business selection", () => {
  assert.deepEqual(resolveEditorOntology(entries, "", undefined), { status: "unresolved" });
  assert.deepEqual(resolveEditorOntology([entries[0]], "", undefined, context), { status: "unresolved" });
});

test("configured landing uses the business graph while explicit tabs and legacy navigation remain stable", () => {
  assert.equal(initialOntologyTab({}, true), "editor");
  assert.equal(initialOntologyTab({}, false), "registry");
  assert.equal(initialOntologyTab({ tab: "registry" }, true), "registry");
  assert.equal(initialOntologyTab({ tab: "health", entityUri: "https://example.test/support/Evidence" }, true), "health");
  assert.equal(initialOntologyTab({ entityUri: "https://example.test/support/Evidence" }, true), "editor");
  assert.equal(initialOntologyTab({ tab: "unrecognized" }, true), "editor");
});

test("technical and unclassified resources stay out of the primary business selector", () => {
  const extra = { uri: "https://other.test/", name: "Other ontology" };
  const partition = partitionOntologyRegistry([...entries, extra], context);
  assert.deepEqual(partition.primary.map((entry) => entry.uri), ["https://example.test/business/"]);
  assert.deepEqual(partition.auxiliary.map((entry) => entry.uri), ["https://example.test/support/", "https://other.test/"]);
  assert.deepEqual(partitionOntologyRegistry(entries).primary, entries);
  assert.deepEqual(partitionOntologyRegistry(entries).auxiliary, []);
});
