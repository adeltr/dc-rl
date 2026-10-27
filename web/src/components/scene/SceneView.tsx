import { Flame, Maximize } from "lucide-react";
import { Component, type ReactNode, useMemo } from "react";

import type { Equipment, Meta, ScenarioResult } from "@/api/types";
import { EQUIPMENT_LABELS, Inspector } from "@/components/inspector/Inspector";
import { cn } from "@/lib/cn";
import { number } from "@/lib/format";
import { displayValue } from "@/lib/paths";
import { useTwin } from "@/state/store";

import { CampusScene } from "./Campus";
import { gradient } from "./layout";

const TOOLBAR: Exclude<Equipment, "market">[] = ["substation", "hall", "cooling_plant", "battery", "site"];

class WebGLBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? <div className="flex h-full items-center justify-center p-6 text-center text-xs text-muted">
          Rendu 3D indisponible (WebGL). Les équipements restent éditables avec la barre ci-dessous.
        </div>
      : this.props.children;
  }
}

export function SceneView({ meta, result }: { meta: Meta; result: ScenarioResult | null }) {
  const draft = useTwin((s) => s.draft);
  const effective = useTwin((s) => s.effective);
  const selected = useTwin((s) => s.selected);
  const select = useTwin((s) => s.select);
  const heatmap = useTwin((s) => s.heatmap);
  const toggleHeatmap = useTwin((s) => s.toggleHeatmap);
  const focusOn = useTwin((s) => s.focusOn);

  const value = (path: string) => (draft ? Number(displayValue(draft, effective, path) ?? 0) : 0);
  const kwSpec = meta.parameters.find((p) => p.path === "params.geometry.kw_per_rack");
  const kwBounds: [number, number] = [kwSpec?.min ?? 0, kwSpec?.max ?? 1];
  const thermal = result?.twin?.thermal;
  // échelle thermique : bas de la plage ASHRAE recommandée → sortie la plus chaude (valeurs de l'API)
  const thermalBounds = useMemo<[number, number]>(() => thermal
    ? [thermal.ashrae_recommended_c[0], Math.max(thermal.ashrae_recommended_c[1] + 1, thermal.rack_outlet_max_c)]
    : kwBounds, [thermal]); // sans résultat thermique, la carte thermique n'est pas affichée

  if (!draft) return null;
  return (
    <div className="relative h-full min-h-0 overflow-hidden rounded-lg border border-border bg-bg">
      <WebGLBoundary>
        <CampusScene nHalls={value("params.geometry.n_halls")} rows={value("params.geometry.rows_per_hall")}
                     racksPerRow={value("params.geometry.racks_per_row")} kwPerRack={value("params.geometry.kw_per_rack")}
                     kwBounds={kwBounds} thermalBounds={thermalBounds} batteryMwh={value("params.battery.energy_mwh")}
                     coolingType={String(displayValue(draft, effective, "params.cooling.type"))} result={result} />
      </WebGLBoundary>
      <div className="pointer-events-none absolute inset-0">
        <Inspector meta={meta} />
        <nav aria-label="Équipements" className="pointer-events-auto absolute bottom-3 left-3 flex flex-wrap gap-1">
          {TOOLBAR.map((eq) => (
            <button key={eq} type="button" aria-pressed={selected === eq} onClick={() => { focusOn(eq); select(eq); }}
                    className={cn("rounded-md border px-2 py-1 text-[11px] cursor-pointer",
                                  selected === eq ? "border-accent bg-accent/15 text-text" : "border-border bg-panel/90 text-muted hover:text-text")}>
              {EQUIPMENT_LABELS[eq]}
            </button>
          ))}
          <button type="button" onClick={() => focusOn("campus")} aria-label="Vue d'ensemble"
                  className="rounded-md border border-border bg-panel/90 px-2 py-1 text-muted hover:text-text cursor-pointer"><Maximize size={12} /></button>
          <button type="button" onClick={toggleHeatmap} aria-pressed={heatmap}
                  className={cn("flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] cursor-pointer",
                                heatmap ? "border-provisional bg-provisional/15 text-text" : "border-border bg-panel/90 text-muted hover:text-text")}>
            <Flame size={12} /> Carte thermique
          </button>
        </nav>
        <Legend heatmap={heatmap} kwBounds={kwBounds} thermalBounds={thermalBounds} kw={value("params.geometry.kw_per_rack")} />
      </div>
    </div>
  );
}

function Legend({ heatmap, kwBounds, thermalBounds, kw }: { heatmap: boolean; kwBounds: [number, number]; thermalBounds: [number, number]; kw: number }) {
  const [lo, hi] = heatmap ? thermalBounds : kwBounds;
  return (
    <div className="pointer-events-auto absolute bottom-3 right-3 w-52 rounded-md border border-border bg-panel/90 px-2.5 py-2 text-[10px] text-muted">
      <div className="mb-1 text-text">{heatmap ? "Température d'air des racks (°C)" : `Densité des racks (kW/rack) — ${number(kw, 1)}`}</div>
      <div className="h-2 rounded" style={{ background: gradient(heatmap ? "thermal" : "density") }} />
      <div className="num mt-0.5 flex justify-between"><span>{number(lo, 0)}</span><span>{number(hi, 0)}</span></div>
      <div className="mt-1">Épaisseur des flux ∝ MW moyens</div>
    </div>
  );
}
