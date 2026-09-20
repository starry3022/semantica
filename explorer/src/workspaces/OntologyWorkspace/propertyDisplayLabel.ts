/** Display labels may change; the predicate IRI remains the shared identity. */
export function propertyDisplayLabel(iri: string, label: string): string {
  const key = iri.split(/[/#:]/).pop() || iri;
  const name = label.trim();
  return !name || name === iri || name === key ? key : `${name}（${key}）`;
}
