import type { Json, Scenario } from "@/api/types";

export function getPath(scenario: Scenario, path: string): Json | undefined {
  let node: Json | undefined = scenario as unknown as Json;
  for (const key of path.split(".")) {
    if (node === null || typeof node !== "object" || Array.isArray(node)) return undefined;
    node = (node as Record<string, Json>)[key];
  }
  return node;
}

export function setPath(scenario: Scenario, path: string, value: Json): Scenario {
  const copy = structuredClone(scenario) as unknown as Record<string, Json>;
  const keys = path.split(".");
  let node = copy;
  for (const key of keys.slice(0, -1)) {
    if (node[key] === null || typeof node[key] !== "object") node[key] = {};
    node = node[key] as Record<string, Json>;
  }
  node[keys[keys.length - 1]] = value;
  return copy as unknown as Scenario;
}

/** Valeur affichée : la valeur du scénario, sinon la valeur effective (classeur / défaut). */
export function displayValue(scenario: Scenario, effective: Scenario | null, path: string): Json | undefined {
  const value = getPath(scenario, path);
  if (value !== null && value !== undefined) return value;
  return effective ? getPath(effective, path) : undefined;
}

// ---------------------------------------------------------------- état partageable dans l'URL

/** Différences avec le scénario de base, en liste de [chemin, valeur]. */
export function diff(base: Json, current: Json, prefix = ""): [string, Json][] {
  if (base !== null && current !== null && typeof base === "object" && typeof current === "object"
      && !Array.isArray(base) && !Array.isArray(current)) {
    const out: [string, Json][] = [];
    const keys = new Set([...Object.keys(base), ...Object.keys(current)]);
    for (const key of keys) {
      out.push(...diff((base as Record<string, Json>)[key] ?? null, (current as Record<string, Json>)[key] ?? null,
                       prefix ? `${prefix}.${key}` : key));
    }
    return out;
  }
  return JSON.stringify(base) === JSON.stringify(current) ? [] : [[prefix, current]];
}

const DERIVED = ["params.geometry.n_racks", "params.geometry.it_capacity_mw"];

export function encodeScenario(base: Scenario, current: Scenario): string {
  const changes = diff(base as unknown as Json, current as unknown as Json).filter(([p]) => !DERIVED.includes(p));
  if (!changes.length) return "";
  const json = JSON.stringify(changes);
  return btoa(String.fromCharCode(...new TextEncoder().encode(json)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeScenario(base: Scenario, encoded: string): Scenario | null {
  try {
    const b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const changes = JSON.parse(new TextDecoder().decode(bytes)) as [string, Json][];
    return changes.reduce((s, [path, value]) => setPath(s, path, value), base);
  } catch {
    return null;
  }
}
