import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "@/api/client";
import { ChartsDrawer } from "@/components/charts/ChartsDrawer";
import { Alerts } from "@/components/cockpit/Alerts";
import { Cockpit } from "@/components/cockpit/Cockpit";
import { StageIndicator } from "@/components/cockpit/StageIndicator";
import { MarketPanel } from "@/components/market/MarketPanel";
import { SceneView } from "@/components/scene/SceneView";
import { ScenarioBar } from "@/components/scenarios/ScenarioBar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useSimulationLoop } from "@/hooks/useSimulationLoop";
import { decodeScenario } from "@/lib/paths";
import { useDisplayed, useTwin } from "@/state/store";

export default function App() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity, retry: 30, retryDelay: 2000 });
  const base = useQuery({ queryKey: ["base"], queryFn: api.base, staleTime: Infinity, retry: 30, retryDelay: 2000 });
  const initialized = useTwin((s) => s.draft !== null);
  const { result, provisional } = useDisplayed();
  useSimulationLoop();

  useEffect(() => {
    if (!base.data || initialized) return;
    const encoded = new URLSearchParams(window.location.search).get("s");
    const fromUrl = encoded ? decodeScenario(base.data.scenario, encoded) : null;
    useTwin.getState().init(base.data.scenario, base.data.effective, base.data.result, fromUrl ?? undefined);
  }, [base.data, initialized]);

  const error = meta.error ?? base.error;
  if (error) return <Splash text={`API indisponible : ${(error as Error).message}`} />;
  if (!meta.data || !base.data || !initialized) return <Splash text="Chargement du jumeau et du cas de base…" />;
  const baseIssue = base.data.base_twin_error ?? base.data.bridge_error;

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col gap-2 p-2">
        <header className="flex items-center gap-4 rounded-lg border border-border bg-panel px-3 py-2">
          <h1 className="shrink-0 text-sm font-semibold">Jumeau numérique · data center</h1>
          <ScenarioBar />
        </header>
        {baseIssue && (
          <p role="alert" className="rounded-md border border-bad/50 bg-bad/10 px-3 py-2 text-xs text-text">
            Cas de base incomplet : {baseIssue}
          </p>
        )}
        <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,3fr)_minmax(340px,2fr)] gap-2">
          <div className="flex min-h-0 flex-col gap-2">
            <div className="flex items-center justify-between px-1"><StageIndicator />
              {result?.twin && (
                <span className="num text-[11px] text-muted">
                  {result.twin.n_racks.toLocaleString("fr-FR")} racks · {result.twin.it_capacity_mw.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} MW IT
                </span>
              )}
            </div>
            <div className="min-h-0 flex-1"><SceneView meta={meta.data} result={result} /></div>
          </div>
          <aside className="flex min-h-0 flex-col gap-2" aria-label="Cockpit">
            <Cockpit result={result} provisional={provisional} />
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
              <Alerts alerts={result?.alerts ?? []} />
              <MarketPanel meta={meta.data} />
            </div>
          </aside>
        </main>
        <ChartsDrawer meta={meta.data} result={result} />
      </div>
    </TooltipProvider>
  );
}

function Splash({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center text-sm text-muted" role="status">{text}</div>;
}
