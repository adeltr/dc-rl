// Miroir des modèles pydantic de l'API (api/*.py, twin/results.py, bridge/bridge.py).

export type Equipment = "substation" | "hall" | "cooling_plant" | "battery" | "site" | "market";
export type AlertTarget = "campus" | "substation" | "hall" | "cooling_plant" | "battery" | "site";

export interface Option { value: string | boolean; label: string }

export interface ParameterSpec {
  path: string;
  label: string;
  unit: string;
  equipment: Equipment;
  kind: "number" | "integer" | "select" | "toggle" | "percent";
  min: number | null;
  max: number | null;
  step: number | null;
  options: Option[] | null;
  help: string;
  sensitivity: boolean;
}

export interface KpiDefinition {
  id: string;
  label: string;
  unit: string;
  better: "higher" | "lower";
  source: "workbook" | "twin";
  field: string;
  drivers: string[];
  cockpit: boolean;
}

export interface Site { id: string; label: string; country: string; latitude: number; longitude: number }

export interface Meta {
  parameters: ParameterSpec[];
  kpis: KpiDefinition[];
  sites: Site[];
  workload_traces: string[];
  defaults: Record<string, unknown>;
  engine: string | null;
  surrogate_ready: boolean;
}

// Scénario : on manipule le JSON tel que l'API le renvoie (TwinParams + MarketAssumptions).
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Scenario { params: Record<string, Json>; market: Record<string, Json> }

export interface Provenance { status: string; source: string; detail: string; url: string | null; retrieved_at: string | null }

export interface TwinResults {
  it_capacity_mw: number;
  n_racks: number;
  servers_per_rack: number;
  energy: Record<string, number>;
  pue_annual: number;
  pue_monthly: number[];
  peak_facility_mw: number;
  peak_grid_mw: number;
  grid_capacity_mw: number;
  grid_overload_hours: number;
  water_m3: number;
  co2_t: number;
  energy_cost_usd: number;
  effective_price_usd_per_mwh: number;
  battery_cycles: number;
  monthly_it_mwh: number[];
  monthly_facility_mwh: number[];
  monthly_grid_mwh: number[];
  monthly_energy_cost_usd: number[];
  hourly_grid_mw: number[];
  hourly_price_usd_per_mwh: number[];
  thermal: {
    rack_inlet_c: Record<string, number>;
    rack_outlet_mean_c: number;
    rack_outlet_max_c: number;
    ashrae_recommended_c: [number, number];
    inlet_within_ashrae: boolean;
    rack_delta_floor_share: number;
    chiller_rated_cooling_mw: number;
    chiller_load_factor_mean: number;
    chiller_load_factor_monthly: number[];
    sizing_ambient_c: number;
  };
  flows_mw: { mean: Record<string, number>; peak: Record<string, number> };
  capex: { total_usd: number; by_component: Record<string, number> };
  provenance: Record<string, Provenance>;
  warnings: string[];
}

export interface WorkbookResults {
  engine: string;
  duration_s: number;
  solver_iterations: number;
  recalc_ok: boolean;
  outputs: Record<string, number | null>;
  years: number[];
  series: Record<string, (number | null)[]>;
}

export interface KpiValue {
  id: string;
  label: string;
  unit: string;
  better: "higher" | "lower";
  cockpit: boolean;
  value: number | null;
  base: number | null;
  delta: number | null;
  delta_pct: number | null;
  favorable: boolean | null;
  drivers: { path: string; label: string }[];
}

export interface Alert {
  id: string;
  severity: "critical" | "warning" | "info";
  message: string;
  target: AlertTarget;
  value: number | null;
  threshold: number | null;
}

export interface ScenarioResult {
  id: string;
  kind: "scenario";
  status: "provisional" | "confirmed" | "error";
  scenario: Scenario;
  twin: TwinResults | null;
  workbook: WorkbookResults | null;
  estimated_outputs: Record<string, number | null> | null;
  estimated_series: Record<string, (number | null)[]> | null;
  estimated_years: number[] | null;
  kpis: KpiValue[];
  alerts: Alert[];
  error: string | null;
  durations_s: Record<string, number>;
}

export interface TornadoItem {
  path: string;
  label: string;
  unit: string;
  base: number;
  low: number;
  high: number;
  kpis: Record<string, { base: number | null; low: number | null; high: number | null }>;
}

export interface SensitivityResult {
  id: string;
  kind: "sensitivity";
  method: string;
  tornado: TornadoItem[] | null;
  grid: { prices: number[]; utilizations: number[]; kpis: Record<string, (number | null)[][]> } | null;
  errors: string[];
}

export interface SavedScenario {
  id: string;
  name: string;
  locked: boolean;
  scenario: Scenario;
  result_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface JobEvent {
  job_id: string;
  seq: number;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  stage: string;
  progress: number;
  message: string;
  result_id: string | null;
}

export interface CompareResponse {
  kpis: KpiDefinition[];
  scenarios: {
    id: string;
    name: string;
    status: string;
    kpis: Record<string, number | null>;
    years: number[] | null;
    series: Record<string, (number | null)[]> | null;
    pue_monthly: number[] | null;
    monthly_grid_mwh: number[] | null;
  }[];
}

export interface BaseResponse {
  scenario: Scenario;
  effective: Scenario | null;
  result: ScenarioResult | null;
  base_twin_error: string | null;
  bridge_error: string | null;
}
