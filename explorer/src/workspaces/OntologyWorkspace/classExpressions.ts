export type ClassExpression =
  | { kind: "unionOf"; members: string[] }
  | { kind: "unsupported" };

export function isClassExpression(value: unknown): value is ClassExpression {
  if (!value || typeof value !== "object") return false;
  const expression = value as Record<string, unknown>;
  if (expression.kind === "unsupported") return true;
  return expression.kind === "unionOf" && Array.isArray(expression.members)
    && expression.members.length > 0
    && expression.members.every((member) => typeof member === "string" && member.trim().length > 0);
}

export function readClassExpressions(value: unknown): ClassExpression[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return [{ kind: "unsupported" }];
  return value.map((expression) => isClassExpression(expression) ? expression : { kind: "unsupported" });
}

export function formatClassConstraint(
  named: string[], expressions: ClassExpression[], name: (uri: string) => string = (uri) => uri,
): string {
  const parts = named.map(name);
  for (const expression of expressions) {
    parts.push(expression.kind === "unionOf"
      ? `(${expression.members.map(name).join(" OR ")})`
      : "Unsupported OWL expression");
  }
  return parts.join(" AND ") || "Not declared";
}
