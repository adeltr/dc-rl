import { AlertOctagon, AlertTriangle, Info } from "lucide-react";

import type { Alert } from "@/api/types";
import { Panel } from "@/components/ui/panel";
import { cn } from "@/lib/cn";
import { useTwin } from "@/state/store";

const ICONS = { critical: AlertOctagon, warning: AlertTriangle, info: Info };
const TONES = { critical: "text-critical", warning: "text-warning", info: "text-info" };
const ORDER = { critical: 0, warning: 1, info: 2 };

/** Alertes ; un clic déplace la caméra vers l'équipement en cause. */
export function Alerts({ alerts }: { alerts: Alert[] }) {
  const focusOn = useTwin((s) => s.focusOn);
  const sorted = [...alerts].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  return (
    <Panel title={`Alertes${alerts.length ? ` (${alerts.length})` : ""}`}>
      {!sorted.length && <p className="px-3 py-2 text-xs text-muted">Aucune alerte.</p>}
      <ul className="max-h-48 overflow-y-auto">
        {sorted.map((a) => {
          const Icon = ICONS[a.severity];
          return (
            <li key={a.id}>
              <button type="button" onClick={() => focusOn(a.target)}
                      className="flex w-full items-start gap-2 border-b border-border/60 px-3 py-2 text-left text-xs hover:bg-panel-2 cursor-pointer">
                <Icon size={14} className={cn("mt-0.5 shrink-0", TONES[a.severity])} aria-label={a.severity} />
                <span className="leading-snug">{a.message}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
