import { Upload, X } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { getPath } from "@/lib/paths";
import { useDisplayed, useTwin } from "@/state/store";

const KEYS: Record<string, string> = {
  weather: "Météo", carbon_intensity: "Intensité carbone", load: "Charge", price: "Prix de l'électricité",
};
const STATUS: Record<string, string> = {
  vendor: "SustainDC", api: "API publique", cache: "API publique (cache)", manual: "saisie manuelle",
  workbook: "classeur", default: "valeur par défaut",
};

/** Provenance des données du site et remplacement manuel de la météo (EPW ou CSV). */
export function SiteData() {
  const draft = useTwin((s) => s.draft);
  const setParam = useTwin((s) => s.setParam);
  const { result } = useDisplayed();
  const [message, setMessage] = useState("");
  if (!draft) return null;
  const manual = getPath(draft, "params.data.weather_file");
  const provenance = result?.twin?.provenance ?? {};
  return (
    <div className="space-y-2 py-2 text-xs">
      <div className="text-text">Provenance des données</div>
      <ul className="space-y-1 text-[11px]">
        {Object.entries(provenance).map(([key, p]) => (
          <li key={key}>
            <span className="text-muted">{KEYS[key] ?? key} : </span>{p.source}
            <span className="text-muted"> — {STATUS[p.status] ?? p.status}{p.detail ? `, ${p.detail}` : ""}</span>
          </li>
        ))}
      </ul>
      {result?.error && <p role="alert" className="text-[11px] text-bad">{result.error}</p>}
      <div className="flex items-center gap-2">
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1 text-muted hover:text-text">
          <Upload size={12} /> Météo manuelle (EPW / CSV)
          <input type="file" accept=".epw,.csv" className="sr-only" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setMessage("envoi…");
            try {
              const r = await api.uploadWeather(f);
              setParam("params.data.weather_file", r.weather_file);
              setMessage(`${f.name} utilisé pour ce scénario`);
            } catch (err) {
              setMessage(`refusé : ${(err as Error).message}`);
            }
          }} />
        </label>
        {manual ? (
          <button type="button" onClick={() => { setParam("params.data.weather_file", null); setMessage(""); }}
                  className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-text cursor-pointer"
                  aria-label="Revenir à la météo automatique"><X size={12} /> source automatique</button>
        ) : null}
      </div>
      {message && <p className="text-[10px] text-muted" role="status">{message}</p>}
      <p className="text-[10px] leading-snug text-muted">
        CSV : colonnes temp_c, rh_pct, pressure_pa sur 8 760 heures. Sans fichier, la météo vient de SustainDC (sites US)
        ou d'Open-Meteo / NASA POWER (autres sites).
      </p>
    </div>
  );
}
