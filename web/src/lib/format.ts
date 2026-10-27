// Formatage français : espace fine insécable pour les milliers, virgule décimale, unité après
// une espace insécable (« 1 234,5 $ »).

const NBSP = " ";
const cache = new Map<number, Intl.NumberFormat>();

function nf(digits: number): Intl.NumberFormat {
  let f = cache.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    cache.set(digits, f);
  }
  return f;
}

export function number(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return nf(digits).format(value).replace(/-/, "−");
}

/** Montant en dollars, abrégé (k$, M$, Md$) au-delà de 10 000. */
export function usd(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${number(value / 1e9, digits)}${NBSP}Md$`;
  if (abs >= 1e6) return `${number(value / 1e6, digits)}${NBSP}M$`;
  if (abs >= 1e4) return `${number(value / 1e3, digits)}${NBSP}k$`;
  return `${number(value, 0)}${NBSP}$`;
}

export function percent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${number(value * 100, digits)}${NBSP}%`;
}

/** Valeur d'un KPI ou d'un paramètre selon son unité déclarée par l'API. */
export function withUnit(value: number | null | undefined, unit: string, digits?: number): string {
  if (unit === "%") return percent(value, digits ?? 2);
  if (unit === "$") return usd(value, digits ?? 1);
  if (unit === "x") return value === null || value === undefined ? "—" : `${number(value, digits ?? 2)}${NBSP}x`;
  if (unit === "") return number(value, digits ?? 3);
  return `${number(value, digits ?? 1)}${NBSP}${unit}`;
}

/** Écart signé : points de pourcentage pour les %, sinon unité de la grandeur. */
export function delta(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  if (unit === "%") return `${sign}${number(value * 100, 2)}${NBSP}pt`;
  return `${sign}${withUnit(value, unit)}`;
}

export function deltaPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return `${value > 0 ? "+" : ""}${number(value * 100, 1)}${NBSP}%`;
}

/** Nombre de décimales cohérent avec le pas d'un paramètre. */
export function digitsForStep(step: number | null): number {
  if (!step || step >= 1) return 0;
  return Math.min(4, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)));
}
