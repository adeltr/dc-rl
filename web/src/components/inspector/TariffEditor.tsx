import { Plus, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { Json, Meta } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { number } from "@/lib/format";
import { displayValue } from "@/lib/paths";
import { useTwin } from "@/state/store";

interface Period { price_usd_per_mwh: number; start_hour: number; end_hour: number; days: string; months: number[] | null }

/** Tarif par plages horaires (liste éditable) ou fichier CSV de 8 760 prix horaires. */
export function TariffEditor({ meta }: { meta: Meta }) {
  const draft = useTwin((s) => s.draft);
  const effective = useTwin((s) => s.effective);
  const setParam = useTwin((s) => s.setParam);
  const [upload, setUpload] = useState<string>("");
  if (!draft) return null;
  const mode = displayValue(draft, effective, "params.price.mode");
  const spec = meta.tou_period;

  if (mode === "csv") {
    const file = displayValue(draft, effective, "params.price.csv_file");
    return (
      <div className="space-y-2 py-2 text-xs">
        <div className="text-text">Fichier de prix horaires (8 760 valeurs, $/MWh)</div>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1 text-muted hover:text-text">
          <Upload size={12} /> Choisir un CSV
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setUpload("envoi…");
            try {
              const r = await api.uploadPrice(f);
              setParam("params.price.csv_file", r.csv_file);
              setUpload(`${number(r.hours, 0)} h · moyenne ${number(r.mean, 1)} $/MWh (min ${number(r.min, 0)}, max ${number(r.max, 0)})`);
            } catch (err) {
              setUpload(`refusé : ${(err as Error).message}`);
            }
          }} />
        </label>
        <p className="break-all text-[10px] text-muted" role="status">{upload || (file ? String(file).split("/").pop() : "aucun fichier")}</p>
      </div>
    );
  }
  if (mode !== "tou") return null;

  const periods = (displayValue(draft, effective, "params.price.tou_periods") as unknown as Period[] | undefined) ?? [];
  const update = (next: Period[]) => setParam("params.price.tou_periods", next as unknown as Json);
  const patch = (i: number, change: Partial<Period>) => update(periods.map((p, j) => (j === i ? { ...p, ...change } : p)));
  const field = "num h-7 rounded border border-border bg-bg px-1.5 text-right text-xs text-text";

  return (
    <div className="space-y-2 py-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-text">Plages horaires</span>
        <Button size="sm" variant="ghost" aria-label="Ajouter une plage"
                onClick={() => update([...periods, { price_usd_per_mwh: spec.price.min, start_hour: spec.hours.min,
                                                     end_hour: spec.hours.max, days: spec.days[0].value, months: null }])}>
          <Plus size={12} /> Plage
        </Button>
      </div>
      {!periods.length && <p className="text-[10px] text-muted">Aucune plage : le prix hors plages s'applique partout.</p>}
      <ol className="space-y-2">
        {periods.map((p, i) => (
          <li key={i} className="space-y-1.5 rounded-md border border-border/70 p-2">
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-1 text-muted">de
                <input type="number" aria-label={`Plage ${i + 1} : heure de début`} min={spec.hours.min} max={spec.hours.max - 1}
                       value={p.start_hour} onChange={(e) => patch(i, { start_hour: Number(e.target.value) })} className={`${field} w-11`} /> h</label>
              <label className="flex items-center gap-1 text-muted">à
                <input type="number" aria-label={`Plage ${i + 1} : heure de fin (exclue)`} min={spec.hours.min + 1} max={spec.hours.max}
                       value={p.end_hour} onChange={(e) => patch(i, { end_hour: Number(e.target.value) })} className={`${field} w-11`} /> h</label>
              <input type="number" aria-label={`Plage ${i + 1} : prix`} min={spec.price.min} max={spec.price.max} step={spec.price.step}
                     value={p.price_usd_per_mwh} onChange={(e) => patch(i, { price_usd_per_mwh: Number(e.target.value) })}
                     className={`${field} w-16`} />
              <span className="text-[10px] text-muted">{spec.price.unit}</span>
              <button type="button" aria-label={`Supprimer la plage ${i + 1}`} onClick={() => update(periods.filter((_, j) => j !== i))}
                      className="ml-auto text-muted hover:text-bad cursor-pointer"><Trash2 size={12} /></button>
            </div>
            <Select label={`Plage ${i + 1} : jours`} value={p.days} options={spec.days} onChange={(v) => patch(i, { days: v })} />
            <div className="flex flex-wrap gap-1" role="group" aria-label={`Plage ${i + 1} : mois (aucun = toute l'année)`}>
              {spec.months.map((m) => {
                const on = p.months?.includes(m.value) ?? false;
                return (
                  <button key={m.value} type="button" aria-pressed={on}
                          onClick={() => {
                            const next = on ? (p.months ?? []).filter((x) => x !== m.value) : [...(p.months ?? []), m.value].sort((a, b) => a - b);
                            patch(i, { months: next.length ? next : null });
                          }}
                          className={`rounded px-1.5 py-0.5 text-[10px] cursor-pointer ${on ? "bg-accent/20 text-text" : "text-muted hover:text-text"}`}>
                    {m.label}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ol>
      <p className="text-[10px] text-muted">La première plage qui correspond l'emporte ; hors plages, le prix hors plages s'applique.</p>
    </div>
  );
}
