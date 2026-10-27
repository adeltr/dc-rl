import { Check, Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";
import { useTwin } from "@/state/store";

const STEPS = ["simulation physique", "recalcul Excel", "terminé"];

/** Étape en cours de la simulation (SSE). L'interface reste utilisable pendant le calcul. */
export function StageIndicator() {
  const stage = useTwin((s) => s.stage);
  const index = stage.status === "done" ? 2 : STEPS.indexOf(stage.stage);
  return (
    <div className="flex items-center gap-3 text-[11px]" role="status" aria-live="polite">
      {STEPS.map((step, i) => {
        const done = stage.status === "done" || i < index;
        const active = i === index && stage.status !== "done" && stage.status !== "error";
        return (
          <span key={step} className={cn("flex items-center gap-1",
                done ? "text-good" : active ? "text-provisional" : "text-muted")}>
            {done ? <Check size={12} /> : active ? <Loader2 size={12} className="animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-border" />}
            {step}
          </span>
        );
      })}
      {(stage.status === "queued" && stage.stage !== "en attente") && <span className="text-provisional">aperçu provisoire…</span>}
      {stage.status === "error" && <span className="max-w-96 truncate text-bad" title={stage.message}>erreur : {stage.message}</span>}
    </div>
  );
}
