import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ClassPropertiesPanel } from "../src/workspaces/OntologyWorkspace/ClassPropertiesPanel";
import { classPropertyGroups } from "../src/workspaces/OntologyWorkspace/classProperties";
import type { OntologyGraphNode, OntologyGraphEdge } from "../src/workspaces/OntologyWorkspace/api";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

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

const base = "https://example.test/schema/";
const role = `${base}Role`;
const activity = `${base}Activity`;
const parent = `${base}ParentRole`;
const unionNodes: OntologyGraphNode[] = [
  { id: role, type: "owl:Class", content: "角色" },
  { id: activity, type: "owl:Class", content: "活动" },
  { id: parent, type: "owl:Class", content: "父类" },
  { id: "_:union-list", type: "owl:Class", content: "RDF structural node" },
  { id: `${base}name`, type: "owl:DatatypeProperty", content: "名称", properties: { domain_expressions: [{ kind: "unionOf", members: [role, activity] }] } },
  { id: `${base}status`, type: "owl:DatatypeProperty", content: "状态", properties: { domain_expressions: [{ kind: "unionOf", members: [parent, activity] }] } },
  { id: `${base}approver`, type: "owl:ObjectProperty", content: "审批人", properties: { range_expressions: [{ kind: "unionOf", members: [role, activity] }] } },
  { id: `${base}opaque`, type: "owl:ObjectProperty", content: "不支持的表达式", properties: { domain_expressions: [{ kind: "unsupported", members: [role], rdf: "opaque" }] } },
];
const unionEdges: OntologyGraphEdge[] = [{ source: role, target: parent, type: "rdfs:subClassOf" }];

test("union membership exposes declared, inherited and incoming properties without flattening the expression", () => {
  const before = JSON.stringify({ unionNodes, unionEdges });
  const groups = classPropertyGroups(role, unionNodes, unionEdges);
  assert.deepEqual(groups.declared.map((row) => row.node.id), [`${base}name`]);
  assert.deepEqual(groups.declared[0].domain, []);
  assert.deepEqual(groups.declared[0].domainExpressions, [{ kind: "unionOf", members: [role, activity] }]);
  assert.deepEqual(groups.inherited.map((row) => row.node.id), [`${base}status`]);
  assert.deepEqual(groups.inherited[0].inheritedFrom, [parent]);
  assert.deepEqual(groups.incoming.map((row) => row.node.id), [`${base}approver`]);
  assert.deepEqual(groups.incoming[0].rangeExpressions, [{ kind: "unionOf", members: [role, activity] }]);
  assert.equal(JSON.stringify({ unionNodes, unionEdges }), before);
});

test("RDF structural blank nodes are not class entries and unsupported expressions do not invent memberships", () => {
  const structuralEdge = { source: `${base}name`, target: "_:union-list", type: "rdfs:domain" };
  assert.deepEqual(classPropertyGroups("_:union-list", unionNodes, [structuralEdge]), { declared: [], inherited: [], incoming: [] });
  assert.equal(classPropertyGroups(role, unionNodes, unionEdges).declared.some((row) => row.node.id === `${base}opaque`), false);
});

test("property rows distinguish union OR from independent domain statements AND", () => {
  const mixed = [...unionEdges, { source: `${base}name`, target: parent, type: "rdfs:domain" }];
  const html = renderToStaticMarkup(<ClassPropertiesPanel classUri={role} nodes={unionNodes} edges={mixed} onSelectTerm={() => undefined} />);
  assert.match(html, /Declared properties · 1/);
  assert.match(html, /Domain: 父类 AND \(角色 OR 活动\)/);
  assert.match(html, /Range: \(角色 OR 活动\)/);
  const simple = renderToStaticMarkup(<ClassPropertiesPanel classUri="child" nodes={nodes} edges={[...edges, { source: "owner", target: "other", type: "rdfs:domain" }]} onSelectTerm={() => undefined} />);
  assert.match(simple, /Domain: 采购申请 AND 岗位/);
});
