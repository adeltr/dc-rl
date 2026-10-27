import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2, Play } from "lucide-react";
import { useRef, useState } from "react";

import { api, followJob } from "@/api/client";
import type { Meta, ScenarioResult, SensitivityResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CLIENT_ID } from "@/hooks/useSimulationLoop";
import { number } from "@/lib/format";
import { type DrawerTab, useTwin } from "@/state/store";

import { CfadsChart, CompareView, HourlyHeatmap, PueChart, SensitivityGrid, TornadoChart } from "./Charts";

const TABS: { id: DrawerTab; label: string }[] = [
  { id: "cfads", label: "CFADS et DSCR" },
  { id: "heatmap", label: "Heatmap 24 h × 365 j" },
  { id: "pue", label: "PUE mensuel" },
  { id: "tornado", label: "Tornado" },
  { id: "grid", label: "Grille prix × utilisation" },
  { id: "compare", label: "Comparaison" },
];

export function ChartsDrawer({ meta, result }: { meta: Meta; result: ScenarioResult | null }) {
  const { drawerOpen, drawerTab, setDrawer, baseResult, draft, compareIds } = useTwin();
  const covenant = Number(draft?.market.dscr_covenant ?? 0);
  const compare = useQuery({ queryKey: ["compare", compareIds], queryFn: () => api.compare(compareIds),
                             enabled: compareIds.length > 0 });
  const sens = useSensitivity();
  const kpiOptions = meta.kpis.filter((k) => k.cockpit && k.source === "workbook").map((k) => ({ value: k.id, label: k.label }));
  const [kpiId, setKpiId] = useState("irr_equity");
  const kpi = meta.kpis.find((k) => k.id === kpiId)!;

  return (
    <section aria-label="Graphiques" className="rounded-lg border border-border bg-panel">
      <Tabs value={drawerTab} onValueChange={(v) => setDrawer(true, v as DrawerTab)}>
        <header className="flex items-center gap-2 px-2 py-1.5">
          <button type="button" onClick={() => setDrawer(!drawerOpen)} aria-expanded={drawerOpen}
                  aria-label={drawerOpen ? "Replier les graphiques" : "Déplier les graphiques"}
                  className="text-muted hover:text-text cursor-pointer">
            {drawerOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
          <TabsList>{TABS.map((t) => <TabsTrigger key={t.id} value={t.id} onClick={() => setDrawer(true, t.id)}>{t.label}</TabsTrigger>)}</TabsList>
          {(drawerTab === "tornado" || drawerTab === "grid") && drawerOpen && (
            <div className="ml-auto flex items-center gap-2 text-[11px]">
              <div className="w-40"><Select label="KPI analysé" value={kpiId} options={kpiOptions} onChange={setKpiId} /></div>
              <label className="flex items-center gap-1 text-muted">±
                <input type="number" min={1} max={50} value={sens.pct} onChange={(e) => sens.setPct(Number(e.target.value))}
                       aria-label="Variation du tornado en pourcentage" className="num h-7 w-12 rounded border border-border bg-bg px-1 text-right text-text" /> %
              </label>
              <Button size="sm" onClick={() => draft && sens.run(draft, "surrogate")} disabled={sens.running}>
                <Play size={12} /> Rapide (surrogate)
              </Button>
              <Button size="sm" variant="ghost" onClick={() => draft && sens.run(draft, "exact")} disabled={sens.running}>
                Exact (classeur)
              </Button>
              {sens.running && <span className="flex items-center gap-1 text-provisional"><Loader2 size={12} className="animate-spin" />{sens.progress}</span>}
              {sens.result && !sens.running && <span className="text-muted">méthode : {sens.result.method === "exact" ? "exacte" : "surrogate"}</span>}
            </div>
          )}
        </header>
        {drawerOpen && (
          <div className="border-t border-border px-3 pb-2 pt-3">
            <TabsContent value="cfads"><CfadsChart result={result} base={baseResult} covenant={covenant} /></TabsContent>
            <TabsContent value="heatmap"><HourlyHeatmap result={result} /></TabsContent>
            <TabsContent value="pue"><PueChart result={result} base={baseResult} /></TabsContent>
            <TabsContent value="tornado"><TornadoChart sensitivity={sens.result} kpiId={kpiId} kpiLabel={kpi.label} unit={kpi.unit} pct={sens.pct / 100} /></TabsContent>
            <TabsContent value="grid"><SensitivityGrid sensitivity={sens.result} kpiId={kpiId} kpiLabel={kpi.label} unit={kpi.unit} /></TabsContent>
            <TabsContent value="compare"><CompareView data={compareIds.length ? compare.data : undefined} /></TabsContent>
          </div>
        )}
      </Tabs>
    </section>
  );
}

function useSensitivity() {
  const [pct, setPct] = useState(10);
  const [result, setResult] = useState<SensitivityResult | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const stop = useRef<() => void>(() => {});
  const run = async (scenario: NonNullable<ReturnType<typeof useTwin.getState>["draft"]>, method: "exact" | "surrogate") => {
    stop.current();
    setRunning(true);
    setProgress("");
    try {
      const job = await api.sensitivity({ scenario, method, pct: pct / 100, client_id: `${CLIENT_ID}-sens` });
      stop.current = followJob(job.job_id, async (event) => {
        setProgress(event.message || `${number(event.progress * 100, 0)} %`);
        if (event.status === "done") setResult(await api.result<SensitivityResult>(job.result_id));
        if (event.status !== "running" && event.status !== "queued") setRunning(false);
      });
    } catch (error) {
      setProgress(String((error as Error).message));
      setRunning(false);
    }
  };
  return { pct, setPct, result, running, progress, run };
}
