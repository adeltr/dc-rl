import { useMemo, useState } from "react";

import type { CompareResponse, ScenarioResult, SensitivityResult } from "@/api/types";
import { number, percent, usd, withUnit } from "@/lib/format";

import { axisStyle, BASE_REF, CRITICAL, DIVERGING, EChart, legendStyle, SEQUENTIAL, SERIES, tooltipStyle } from "./echarts";

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export function TableToggle({ table, children }: { table: React.ReactNode; children: React.ReactNode }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <button type="button" onClick={() => setShow(!show)} aria-pressed={show}
              className="absolute -top-0.5 left-0 z-10 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted hover:text-text cursor-pointer">
        {show ? "Graphique" : "Tableau"}
      </button>
      {show ? <div className="max-h-64 overflow-auto pt-6">{table}</div> : children}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="num w-full text-[11px]">
      <thead><tr>{head.map((h) => <th key={h} className="border-b border-border px-2 py-1 text-left font-medium text-muted">{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="border-b border-border/50 px-2 py-1">{c}</td>)}</tr>)}</tbody>
    </table>
  );
}

function workbookSeries(result: ScenarioResult | null) {
  if (!result) return null;
  if (result.workbook) return { years: result.workbook.years, series: result.workbook.series };
  if (result.estimated_series && result.estimated_years) return { years: result.estimated_years, series: result.estimated_series };
  return null;
}

// ------------------------------------------------------------- CFADS vs service de la dette + DSCR

export function CfadsChart({ result, base, covenant }: { result: ScenarioResult | null; base: ScenarioResult | null; covenant: number }) {
  const data = workbookSeries(result);
  const baseData = workbookSeries(base);
  const outputs = result?.workbook?.outputs ?? result?.estimated_outputs ?? null;
  // résultats enregistrés avant l'ajout du service de la dette total : dette permanente seule
  const debtService = data ? (data.series.out_debt_service_total ?? data.series.out_debt_service ?? []) : [];
  const permDebt = Boolean(outputs?.out_perm_debt_active);
  // seuil tracé : covenant de la dette permanente, sinon couverture des intérêts du prêt de construction
  const threshold = permDebt ? covenant : 1;
  const ratio = permDebt ? "DSCR" : "ICR";
  // années d'exploitation avec service de la dette mais hors ratio (montée en occupation)
  const excluded = data ? data.years.filter((_, i) => (data.series.out_egr?.[i] ?? 0) > 0
                                           && data.series.out_dscr[i] === null && (debtService[i] ?? 0) > 0) : [];
  const excludedArea = excluded.length
    ? { silent: true, itemStyle: { color: "rgba(139,148,158,0.12)" },
        label: { color: "#8b949e", fontSize: 10, position: "insideTop", formatter: "montée en occupation : hors ratio" },
        data: [[{ xAxis: `A${excluded[0]}` }, { xAxis: `A${excluded[excluded.length - 1]}` }]] }
    : undefined;
  const option = useMemo(() => {
    if (!data) return null;
    const years = data.years.map((y) => `A${y}`);
    return {
      grid: { left: 64, right: 12, top: 24, bottom: 22 },
      legend: { ...legendStyle, data: ["CFADS", "Service de la dette", "CFADS (base)"] },
      tooltip: { ...tooltipStyle, trigger: "axis", valueFormatter: (v: number) => usd(v) },
      xAxis: { type: "category", data: years, ...axisStyle },
      yAxis: { type: "value", ...axisStyle, axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => usd(v, 0) } },
      series: [
        { name: "CFADS", type: "bar", data: data.series.out_cfads, itemStyle: { color: SERIES[0], borderRadius: [4, 4, 0, 0] }, barGap: "8%", barMaxWidth: 26,
          ...(excludedArea ? { markArea: excludedArea } : {}) },
        { name: "Service de la dette", type: "bar", data: debtService, itemStyle: { color: SERIES[1], borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
        ...(baseData ? [{ name: "CFADS (base)", type: "line", data: baseData.series.out_cfads, symbol: "none",
                         lineStyle: { color: BASE_REF, width: 2, type: "dashed" }, itemStyle: { color: BASE_REF } }] : []),
      ],
    };
  }, [data, baseData, debtService, excludedArea]);
  const dscrOption = useMemo(() => {
    if (!data) return null;
    const years = data.years.map((y) => `A${y}`);
    return {
      grid: { left: 64, right: 96, top: 18, bottom: 22 },
      tooltip: { ...tooltipStyle, trigger: "axis", valueFormatter: (v: number | null) => (v === null ? "hors ratio" : `${number(v, 2)} x`) },
      xAxis: { type: "category", data: years, ...axisStyle },
      yAxis: { type: "value", name: ratio, splitNumber: 3, ...axisStyle,
               axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => `${number(v, 1)} x` } },
      series: [{
        name: ratio, type: "line", data: data.series.out_dscr, connectNulls: false, symbolSize: 8,
        lineStyle: { color: SERIES[0], width: 2 }, itemStyle: { color: SERIES[0] },
        markLine: { symbol: "none", silent: true, lineStyle: { color: CRITICAL, type: "dashed", width: 1.5 },
                    label: { color: "#e6edf3", fontSize: 10, position: "end",
                             formatter: `${permDebt ? "covenant" : "couverture"} ${number(threshold, 2)} x` },
                    data: [{ yAxis: threshold }] },
      }],
    };
  }, [data, threshold, permDebt, ratio]);
  if (!data || !option || !dscrOption) return <Empty />;
  const hasDebt = data.series.out_dscr.some((v) => v !== null);
  return (
    <TableToggle table={<Table head={["Année", "CFADS", "Service de la dette", "DSCR"]}
                               rows={data.years.map((y, i) => [`A${y}`, usd(data.series.out_cfads[i]), usd(debtService[i]),
                                                               data.series.out_dscr[i] === null ? "—" : `${number(data.series.out_dscr[i], 2)} x`])} />}>
      <EChart option={option} height={150} label="CFADS et service de la dette par année" />
      {hasDebt ? <EChart option={dscrOption} height={120} label="DSCR par année et covenant" />
               : <p className="px-16 text-[11px] text-muted">DSCR sans objet : aucun service de la dette pendant l'exploitation.</p>}
      {outputs && typeof outputs.out_sale_net === "number" ? (
        <p className="num px-16 pt-1 text-[11px] text-muted">
          Cession au mois {number(outputs.out_sale_month ?? 0, 0)} : {usd(outputs.out_sale_net)} nets
          (taux de sortie {percent(outputs.out_exit_cap ?? 0)}), hors graphique et incluse dans les TRI et la VAN.
          {!permDebt ? " Service de la dette : intérêts du prêt de construction, remboursé à la vente." : ""}
        </p>
      ) : null}
    </TableToggle>
  );
}

// ------------------------------------------------------------- heatmap 24 h × 365 j

export function HourlyHeatmap({ result }: { result: ScenarioResult | null }) {
  const [metric, setMetric] = useState<"grid" | "price">("grid");
  const values = metric === "grid" ? result?.twin?.hourly_grid_mw : result?.twin?.hourly_price_usd_per_mwh;
  const option = useMemo(() => {
    if (!values) return null;
    const data: [number, number, number][] = values.map((v, i) => [Math.floor(i / 24), i % 24, v]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const unit = metric === "grid" ? "MW" : "$/MWh";
    return {
      grid: { left: 40, right: 70, top: 8, bottom: 22 },
      tooltip: { ...tooltipStyle, formatter: (p: { value: [number, number, number] }) =>
        `jour ${p.value[0] + 1}, ${p.value[1]} h : ${withUnit(p.value[2], unit, metric === "grid" ? 2 : 1)}` },
      xAxis: { type: "category", data: Array.from({ length: 365 }, (_, i) => i + 1), ...axisStyle,
               axisLabel: { ...axisStyle.axisLabel, interval: 30 }, splitLine: { show: false } },
      yAxis: { type: "category", data: Array.from({ length: 24 }, (_, i) => `${i} h`), ...axisStyle,
               axisLabel: { ...axisStyle.axisLabel, interval: 5 }, splitLine: { show: false } },
      visualMap: { min, max: max > min ? max : min + 1, calculable: false, orient: "vertical", right: 0, top: "middle",
                   text: [number(max, metric === "grid" ? 1 : 0), number(min, metric === "grid" ? 1 : 0)],
                   itemHeight: 110, itemWidth: 10, inRange: { color: SEQUENTIAL },
                   textStyle: { color: "#9aa7b4", fontSize: 10 }, formatter: (v: number) => number(v, metric === "grid" ? 1 : 0) },
      series: [{ type: "heatmap", data, progressive: 0 }],
    };
  }, [values, metric]);
  if (!option) return <Empty />;
  return (
    <div>
      <div className="mb-1 flex gap-1" role="group" aria-label="Grandeur affichée">
        {(["grid", "price"] as const).map((m) => (
          <button key={m} type="button" aria-pressed={metric === m} onClick={() => setMetric(m)}
                  className={`rounded px-2 py-0.5 text-[10px] cursor-pointer ${metric === m ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>
            {m === "grid" ? "Consommation réseau (MW)" : "Prix de l'électricité ($/MWh)"}
          </button>
        ))}
      </div>
      <EChart option={option} height={225} label="Carte horaire 24 heures par 365 jours" />
    </div>
  );
}

// ------------------------------------------------------------- PUE mensuel

export function PueChart({ result, base }: { result: ScenarioResult | null; base: ScenarioResult | null }) {
  const pue = result?.twin?.pue_monthly;
  const basePue = base?.twin?.pue_monthly;
  const option = useMemo(() => pue && {
    grid: { left: 48, right: 12, top: 24, bottom: 22 },
    legend: { ...legendStyle, data: ["Scénario", "Base"] },
    tooltip: { ...tooltipStyle, trigger: "axis", valueFormatter: (v: number) => number(v, 3) },
    xAxis: { type: "category", data: MONTHS, ...axisStyle },
    yAxis: { type: "value", scale: true, ...axisStyle, axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => number(v, 2) } },
    series: [
      { name: "Scénario", type: "line", data: pue, symbolSize: 8, lineStyle: { color: SERIES[0], width: 2 }, itemStyle: { color: SERIES[0] } },
      ...(basePue ? [{ name: "Base", type: "line", data: basePue, symbol: "none", lineStyle: { color: BASE_REF, width: 2, type: "dashed" }, itemStyle: { color: BASE_REF } }] : []),
    ],
  }, [pue, basePue]);
  if (!option || !pue) return <Empty />;
  return (
    <TableToggle table={<Table head={["Mois", "PUE scénario", "PUE base"]}
                               rows={MONTHS.map((m, i) => [m, number(pue[i], 3), basePue ? number(basePue[i], 3) : "—"])} />}>
      <EChart option={option} height={250} label="PUE mensuel, scénario et base" />
    </TableToggle>
  );
}

// ------------------------------------------------------------- tornado

export function TornadoChart({ sensitivity, kpiId, kpiLabel, unit, pct }: { sensitivity: SensitivityResult | null; kpiId: string; kpiLabel: string; unit: string; pct: number }) {
  const items = sensitivity?.tornado;
  const option = useMemo(() => {
    if (!items) return null;
    const rows = items.filter((t) => t.kpis[kpiId]?.base !== null).slice().reverse();
    const base = rows[0]?.kpis[kpiId]?.base ?? 0;
    const fmt = (v: number) => withUnit(v, unit);
    return {
      grid: { left: 190, right: 24, top: 24, bottom: 22 },
      legend: { ...legendStyle, data: [`−${number(pct * 100, 0)} %`, `+${number(pct * 100, 0)} %`] },
      tooltip: { ...tooltipStyle, trigger: "axis", axisPointer: { type: "shadow" },
                 formatter: (p: { seriesName: string; name: string; value: number }[]) =>
                   `${p[0].name}<br/>${p.map((x) => `${x.seriesName} : ${fmt(base + x.value)}`).join("<br/>")}<br/>base : ${fmt(base)}` },
      xAxis: { type: "value", ...axisStyle, axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => fmt(base + v) } },
      yAxis: { type: "category", data: rows.map((t) => t.label), ...axisStyle, axisLabel: { ...axisStyle.axisLabel, color: "#e6edf3" } },
      series: [
        { name: `−${number(pct * 100, 0)} %`, type: "bar", stack: "t", barWidth: 12,
          data: rows.map((t) => (t.kpis[kpiId].low ?? base) - base), itemStyle: { color: SERIES[0], borderRadius: 4 } },
        { name: `+${number(pct * 100, 0)} %`, type: "bar", stack: "t2", barWidth: 12, barGap: "-100%",
          data: rows.map((t) => (t.kpis[kpiId].high ?? base) - base), itemStyle: { color: SERIES[1], borderRadius: 4 } },
      ],
    };
  }, [items, kpiId, unit, pct]);
  if (!option || !items) return <Empty text="Lancer l'analyse de sensibilité." />;
  return (
    <TableToggle table={<Table head={["Paramètre", "Valeur −", "Valeur +", `${kpiLabel} −`, `${kpiLabel} +`]}
                               rows={items.map((t) => [t.label, withUnit(t.low, t.unit, 2), withUnit(t.high, t.unit, 2),
                                                       withUnit(t.kpis[kpiId]?.low, unit), withUnit(t.kpis[kpiId]?.high, unit)])} />}>
      <EChart option={option} height={250} label={`Tornado ±${number(pct * 100, 0)} % sur ${kpiLabel}`} />
    </TableToggle>
  );
}

// ------------------------------------------------------------- grille 2D prix × utilisation

export function SensitivityGrid({ sensitivity, kpiId, kpiLabel, unit }: { sensitivity: SensitivityResult | null; kpiId: string; kpiLabel: string; unit: string }) {
  const grid = sensitivity?.grid;
  const option = useMemo(() => {
    if (!grid) return null;
    const values = grid.kpis[kpiId];
    const data: [number, number, number | null][] = [];
    values.forEach((row, i) => row.forEach((v, j) => data.push([i, j, v])));
    const finite = data.map((d) => d[2]).filter((v): v is number => v !== null);
    const mid = values[Math.floor(values.length / 2)]?.[values[0].length - 1] ?? finite[0];
    const span = Math.max(...finite.map((v) => Math.abs(v - mid))) || 1;
    return {
      grid: { left: 64, right: 80, top: 8, bottom: 34 },
      tooltip: { ...tooltipStyle, formatter: (p: { value: [number, number, number] }) =>
        `${number(grid.prices[p.value[0]], 0)} $/MWh · ${percent(grid.utilizations[p.value[1]], 0)} : ${withUnit(p.value[2], unit)}` },
      xAxis: { type: "category", name: "Prix ($/MWh)", nameLocation: "middle", nameGap: 22, data: grid.prices.map((v) => number(v, 0)), ...axisStyle, splitLine: { show: false } },
      yAxis: { type: "category", name: "Utilisation CPU", data: grid.utilizations.map((v) => percent(v, 0)), ...axisStyle, splitLine: { show: false } },
      visualMap: { min: mid - span, max: mid + span, orient: "vertical", right: 0, top: "middle", itemHeight: 110, itemWidth: 10,
                   text: [withUnit(mid + span, unit), withUnit(mid - span, unit)],
                   inRange: { color: DIVERGING.slice().reverse() }, textStyle: { color: "#9aa7b4", fontSize: 10 },
                   formatter: (v: number) => withUnit(v, unit) },
      series: [{ type: "heatmap", data, label: { show: true, color: "#e6edf3", fontSize: 10, formatter: (p: { value: [number, number, number] }) => withUnit(p.value[2], unit, 1) },
                 itemStyle: { borderColor: "#121821", borderWidth: 2 } }],
    };
  }, [grid, kpiId, unit]);
  if (!option || !grid) return <Empty text="Lancer l'analyse de sensibilité." />;
  return <EChart option={option} height={250} label={`Grille prix de l'électricité par taux d'utilisation : ${kpiLabel}`} />;
}

// ------------------------------------------------------------- comparaison

export function CompareView({ data }: { data: CompareResponse | undefined }) {
  const option = useMemo(() => {
    if (!data) return null;
    const years = data.scenarios.find((s) => s.years)?.years ?? [];
    return {
      grid: { left: 64, right: 12, top: 24, bottom: 22 },
      legend: { ...legendStyle, data: data.scenarios.map((s) => s.name) },
      tooltip: { ...tooltipStyle, trigger: "axis", valueFormatter: (v: number) => usd(v) },
      xAxis: { type: "category", data: years.map((y) => `A${y}`), ...axisStyle },
      yAxis: { type: "value", name: "CFADS", ...axisStyle, axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => usd(v, 0) } },
      series: data.scenarios.map((s, i) => ({ name: s.name, type: "line", data: s.series?.out_cfads ?? [], symbolSize: 8,
                                              lineStyle: { color: SERIES[i], width: 2 }, itemStyle: { color: SERIES[i] } })),
    };
  }, [data]);
  if (!data || !option) return <Empty text="Cocher « comparer » sur 1 à 3 scénarios sauvegardés." />;
  const kpis = data.kpis.filter((k) => k.cockpit);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4">
      <table className="num w-full text-[11px]">
        <thead>
          <tr><th className="border-b border-border px-2 py-1 text-left text-muted">KPI</th>
            {data.scenarios.map((s, i) => (
              <th key={s.id} className="border-b border-border px-2 py-1 text-right font-medium">
                <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: SERIES[i] }} />{s.name}
              </th>))}
          </tr>
        </thead>
        <tbody>
          {kpis.map((k) => (
            <tr key={k.id}>
              <td className="border-b border-border/50 px-2 py-1 text-muted">{k.label}</td>
              {data.scenarios.map((s) => <td key={s.id} className="border-b border-border/50 px-2 py-1 text-right">{withUnit(s.kpis[k.id], k.unit, k.unit === "" ? 3 : undefined)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <EChart option={option} height={260} label="CFADS par année, scénarios comparés" />
    </div>
  );
}

function Empty({ text = "En attente du résultat…" }: { text?: string }) {
  return <p className="flex h-40 items-center justify-center text-xs text-muted">{text}</p>;
}
