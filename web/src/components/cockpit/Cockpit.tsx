import type { KpiValue, ScenarioResult } from "@/api/types";
import { Panel } from "@/components/ui/panel";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { delta, deltaPct, withUnit } from "@/lib/format";

const DIGITS: Record<string, number> = { pue: 3, energy_cost_effective: 1, dscr_min: 2, dscr_avg: 2, llcr: 2 };

export function Cockpit({ result, provisional }: { result: ScenarioResult | null; provisional: boolean }) {
  const kpis = (result?.kpis ?? []).filter((k) => k.cockpit);
  return (
    <Panel title="Cockpit financier"
           actions={provisional && result ? <span className="rounded bg-provisional/15 px-1.5 py-0.5 text-[10px] font-medium text-provisional">provisoire</span> : null}>
      {!result && <p className="p-3 text-xs text-muted">Calcul du cas de base…</p>}
      {result?.status === "error" && (
        <p role="alert" className="border-b border-border p-3 text-xs text-bad">{result.error}</p>
      )}
      <ul className="grid grid-cols-2 gap-px bg-border">
        {kpis.map((k) => <KpiCard key={k.id} kpi={k} provisional={provisional} />)}
      </ul>
    </Panel>
  );
}

function KpiCard({ kpi, provisional }: { kpi: KpiValue; provisional: boolean }) {
  const digits = DIGITS[kpi.id];
  const tone = kpi.favorable === null ? "text-muted" : kpi.favorable ? "text-good" : "text-bad";
  const missing = kpi.value === null;
  return (
    <li className="bg-panel">
      <Tooltip side="left" content={
        <div className="space-y-1">
          <p className="font-medium">{kpi.label} — paramètres pilotes</p>
          <ul className="space-y-0.5 text-muted">
            {kpi.drivers.slice(0, 12).map((d) => <li key={d.path}>• {d.label}</li>)}
          </ul>
          {kpi.note ? <p className="max-w-72 pt-1 text-muted">{kpi.note}</p> : null}
        </div>
      }>
        <button type="button"
                aria-label={`${kpi.label} : ${withUnit(kpi.value, kpi.unit, digits)}, base ${withUnit(kpi.base, kpi.unit, digits)}, écart ${delta(kpi.delta, kpi.unit)}`}
                className="block w-full px-3 py-2.5 text-left hover:bg-panel-2 focus-visible:bg-panel-2 cursor-default">
          <div className="text-[11px] text-muted">{kpi.label}</div>
          <div className={cn("num mt-0.5 text-lg font-semibold leading-tight", provisional ? "text-provisional" : "text-text",
                             missing && "text-muted")}>
            {missing ? "N/A" : withUnit(kpi.value, kpi.unit, digits)}
            {missing && kpi.na_reason ? <span className="ml-1.5 text-[11px] font-normal">{kpi.na_reason}</span> : null}
          </div>
          <div className="num mt-1 flex items-baseline justify-between gap-2 text-[11px]">
            <span className="text-muted">base {kpi.base === null ? "N/A" : withUnit(kpi.base, kpi.unit, digits)}</span>
            <span className={tone}>
              {kpi.delta === null || kpi.favorable === null ? "=" : `${delta(kpi.delta, kpi.unit)} ${kpi.unit === "%" ? "" : deltaPct(kpi.delta_pct)}`}
            </span>
          </div>
        </button>
      </Tooltip>
    </li>
  );
}
