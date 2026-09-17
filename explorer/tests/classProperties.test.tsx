import assert from "node:assert/strict";
import test from "node:test";
import { classPropertyGroups } from "../src/workspaces/OntologyWorkspace/classProperties";
import type { OntologyGraphNode, OntologyGraphEdge } from "../src/workspaces/OntologyWorkspace/api";

const nodes: OntologyGraphNode[] = [
  { id: "child", type: "owl:Class", content: "采购申请" },
  { id: "parent", type: "owl:Class", content: "申请" },
  { id: "other", type: "owl:Class", content: "岗位" },
  { id: "owner", type: "owl:ObjectProperty", content: "申请人" },
  { id: "amount", type: "http://www.w3.org/2002/07/owl#DatatypeProperty", content: "金额" },
  { id: "inbound", type: "owl:ObjectProperty", content: "引用申请" },
  { id: "unrelated", type: "owl:ObjectProperty", content: "无关属性" },
  { id: "instance", type: "ProcessRule", content: "规则" },
];
const edges: OntologyGraphEdge[] = [
  { source: "child", target: "parent", type: "rdfs:subClassOf" },
  { source: "owner", target: "child", type: "rdfs:domain" },
  { source: "owner", target: "other", type: "rdfs:range" },
  { source: "amount", target: "parent", type: "http://www.w3.org/2000/01/rdf-schema#domain" },
  { source: "amount", target: "http://www.w3.org/2001/XMLSchema#decimal", type: "rdfs:range" },
  { source: "inbound", target: "child", type: "rdfs:range" },
  { source: "unrelated", target: "child", type: "hasEvidence" },
  { source: "instance", target: "child", type: "rdfs:domain" },
];

test("a class separates declared, inherited and incoming properties with their complete domain/range", () => {
  const result = classPropertyGroups("child", nodes, edges);
  assert.deepEqual(result.declared.map((row) => row.node.id), ["owner"]);
  assert.deepEqual(result.declared[0].domain, ["child"]);
  assert.deepEqual(result.declared[0].range, ["other"]);
  assert.deepEqual(result.inherited.map((row) => row.node.id), ["amount"]);
  assert.deepEqual(result.inherited[0].inheritedFrom, ["parent"]);
  assert.deepEqual(result.inherited[0].range, ["http://www.w3.org/2001/XMLSchema#decimal"]);
  assert.deepEqual(result.incoming.map((row) => row.node.id), ["inbound"]);
});

test("cycles, duplicate declarations and multiple domains cannot duplicate rows or hide constraints", () => {
  const result = classPropertyGroups("child", nodes, [...edges,
    { source: "parent", target: "child", type: "rdfs:subClassOf" },
    { source: "owner", target: "parent", type: "rdfs:domain" },
    { source: "owner", target: "child", type: "rdfs:domain" },
  ]);
  assert.equal(result.declared.length, 1);
  assert.deepEqual(result.declared[0].domain, ["child", "parent"]);
  assert.deepEqual(result.inherited.map((row) => row.node.id), ["amount"]);
});

test("a class with no declarations is empty and input graph data is unchanged", () => {
  const before = JSON.stringify({ nodes, edges });
  assert.deepEqual(classPropertyGroups("unknown", nodes, edges), { declared: [], inherited: [], incoming: [] });
  classPropertyGroups("child", nodes, edges);
  assert.equal(JSON.stringify({ nodes, edges }), before);
});
