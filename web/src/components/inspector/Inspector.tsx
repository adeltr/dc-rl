import { X } from "lucide-react";

import type { Equipment, Meta } from "@/api/types";
import { Panel } from "@/components/ui/panel";
import { useTwin } from "@/state/store";

import { ParamField } from "./ParamField";
import { SiteData } from "./SiteData";
import { TariffEditor } from "./TariffEditor";

export const EQUIPMENT_LABELS: Record<Equipment, string> = {
  substation: "Poste électrique",
  hall: "Halls informatiques",
  cooling_plant: "Centrale de refroidissement",
  battery: "Parc batterie",
  site: "Site",
  market: "Hypothèses marché",
};

/** Paramètres portés par l'équipement sélectionné (catalogue /meta). */
export function Inspector({ meta }: { meta: Meta }) {
  const selected = useTwin((s) => s.selected);
  const select = useTwin((s) => s.select);
  if (!selected || selected === "market") return null;
  const params = meta.parameters.filter((p) => p.equipment === selected);
  return (
    <Panel
      className="pointer-events-auto absolute left-3 top-3 z-10 max-h-[calc(100%-1.5rem)] w-80 overflow-y-auto shadow-xl"
      title={EQUIPMENT_LABELS[selected]}
      actions={
        <button type="button" aria-label="Fermer l'inspecteur" onClick={() => select(null)}
                className="text-muted hover:text-text cursor-pointer"><X size={14} /></button>
      }
    >
      <div className="divide-y divide-border/60 px-3 pb-2">
        {params.map((p) => <ParamField key={p.path} spec={p} />)}
        {selected === "substation" && <TariffEditor meta={meta} />}
        {selected === "site" && <SiteData />}
      </div>
    </Panel>
  );
}
