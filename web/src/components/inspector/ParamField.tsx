import { RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

import type { Json, ParameterSpec } from "@/api/types";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { digitsForStep, number } from "@/lib/format";
import { displayValue, getPath } from "@/lib/paths";
import { useTwin } from "@/state/store";

/** Un paramètre éditable : curseur + saisie numérique + unité + bornes, tout vient de /meta. */
export function ParamField({ spec }: { spec: ParameterSpec }) {
  const draft = useTwin((s) => s.draft);
  const effective = useTwin((s) => s.effective);
  const base = useTwin((s) => s.base);
  const setParam = useTwin((s) => s.setParam);
  if (!draft) return null;
  const raw = getPath(draft, spec.path);
  const value = displayValue(draft, effective, spec.path);
  const baseValue = base ? displayValue(base, effective, spec.path) : undefined;
  const changed = JSON.stringify(value) !== JSON.stringify(baseValue);
  const id = `param-${spec.path.replace(/\./g, "-")}`;

  return (
    <div className="space-y-1.5 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-xs text-text">
          {spec.label}
          {changed && <span className="ml-1.5 text-[10px] text-accent" aria-label="modifié">●</span>}
        </label>
        {raw === null && spec.kind !== "toggle" && spec.kind !== "select" && (
          <span className="text-[10px] text-muted">valeur par défaut</span>
        )}
      </div>
      {spec.kind === "select" && spec.options && (
        <Select label={spec.label} value={String(value ?? "")} options={spec.options}
                onChange={(v) => setParam(spec.path, v)} />
      )}
      {spec.kind === "toggle" && (
        <Switch label={spec.label} checked={Boolean(value)} onChange={(v) => setParam(spec.path, v)} />
      )}
      {(spec.kind === "number" || spec.kind === "integer" || spec.kind === "percent") && (
        <NumericField id={id} spec={spec} value={typeof value === "number" ? value : null}
                      baseValue={typeof baseValue === "number" ? baseValue : null}
                      onChange={(v) => setParam(spec.path, v)} />
      )}
      {spec.help && <p className="text-[10px] leading-snug text-muted">{spec.help}</p>}
    </div>
  );
}

function NumericField({ id, spec, value, baseValue, onChange }: {
  id: string; spec: ParameterSpec; value: number | null; baseValue: number | null; onChange: (v: Json) => void;
}) {
  const scale = spec.kind === "percent" ? 100 : 1;
  const unit = spec.kind === "percent" ? "%" : spec.unit;
  const step = (spec.step ?? (spec.kind === "integer" ? 1 : 0.1)) * scale;
  const digits = spec.kind === "integer" ? 0 : digitsForStep(step);
  const min = (spec.min ?? 0) * scale;
  const max = (spec.max ?? 100) * scale;
  const shown = value === null ? null : value * scale;
  const [text, setText] = useState(shown === null ? "" : number(shown, digits));
  useEffect(() => setText(shown === null ? "" : number(shown, digits)), [shown, digits]);

  const commit = (v: number) => {
    const clamped = Math.min(max, Math.max(min, v));
    const rounded = spec.kind === "integer" ? Math.round(clamped) : Math.round(clamped / step) * step;
    onChange(Number((rounded / scale).toPrecision(12)));
  };

  return (
    <div className="flex items-center gap-2">
      <Slider aria-label={spec.label} min={min} max={max} step={step} value={[shown ?? min]}
              onValueChange={([v]) => commit(v)} className="flex-1" />
      <div className="flex items-center rounded-md border border-border bg-bg focus-within:border-accent">
        <input id={id} inputMode="decimal" value={text}
          aria-describedby={`${id}-bounds`}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            const parsed = Number(text.replace(/\s/g, "").replace(" ", "").replace(",", "."));
            if (Number.isFinite(parsed) && text.trim() !== "") commit(parsed);
            else setText(shown === null ? "" : number(shown, digits));
          }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
          className="num h-7 w-20 bg-transparent px-2 text-right text-xs text-text outline-none" />
        {unit && <span className="pr-2 text-[11px] text-muted">{unit}</span>}
      </div>
      {baseValue !== null && value !== null && Math.abs(baseValue - value) > 1e-12 && (
        <button type="button" title="Revenir à la valeur de base" aria-label={`${spec.label} : revenir à la base`}
                onClick={() => onChange(baseValue)} className="text-muted hover:text-text cursor-pointer">
          <RotateCcw size={12} />
        </button>
      )}
      <span id={`${id}-bounds`} className="sr-only">
        bornes {number(min, digits)} à {number(max, digits)} {unit}
      </span>
    </div>
  );
}
