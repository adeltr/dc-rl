import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import type { Meta } from "@/api/types";
import { ParamField } from "@/components/inspector/ParamField";
import { Panel } from "@/components/ui/panel";

/** Panneau global « Hypothèses marché » (revenu, montée en occupation, prix carbone et eau, indexations…). */
export function MarketPanel({ meta }: { meta: Meta }) {
  const [open, setOpen] = useState(false);
  const params = meta.parameters.filter((p) => p.equipment === "market");
  return (
    <Panel
      title={
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                className="flex items-center gap-1 uppercase cursor-pointer">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Hypothèses marché
        </button>
      }
    >
      {open && <div className="divide-y divide-border/60 px-3 pb-2">{params.map((p) => <ParamField key={p.path} spec={p} />)}</div>}
    </Panel>
  );
}
