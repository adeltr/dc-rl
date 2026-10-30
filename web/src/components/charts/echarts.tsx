import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  GridComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, TooltipComponent, VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent,
             VisualMapComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer]);

// Palette catégorielle (pas sombre) validée sur la surface #121821 : ordre fixe, jamais cyclé.
export const SERIES = ["#3987e5", "#d95926", "#199e70"];
export const BASE_REF = "#9aa7b4"; // référence « cas de base » : encre secondaire, en pointillé
export const CRITICAL = "#d03b3b";
// Rampe séquentielle bleue (sombre : valeurs faibles proches de la surface)
export const SEQUENTIAL = ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"];
// Divergente bleu ↔ rouge, milieu gris neutre
export const DIVERGING = ["#2a78d6", "#5598e7", "#9ec5f4", "#383835", "#f0a3a3", "#e66767", "#d03b3b"];

const TEXT = { primary: "#e6edf3", secondary: "#9aa7b4", grid: "#263241" };

export const axisStyle = {
  axisLine: { lineStyle: { color: TEXT.grid } },
  axisTick: { show: false },
  axisLabel: { color: TEXT.secondary, fontSize: 10 },
  splitLine: { lineStyle: { color: TEXT.grid, opacity: 0.6 } },
  nameTextStyle: { color: TEXT.secondary, fontSize: 10 },
};

export const tooltipStyle = {
  backgroundColor: "#18202b",
  borderColor: "#263241",
  textStyle: { color: TEXT.primary, fontSize: 11 },
  extraCssText: "font-variant-numeric: tabular-nums;",
};

export const legendStyle = { textStyle: { color: TEXT.secondary, fontSize: 10 }, itemWidth: 12, itemHeight: 8, top: 0, right: 0 };

export function EChart({ option, height, label }: { option: echarts.EChartsCoreOption; height: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.current?.dispose(); chart.current = null; };
  }, []);
  useEffect(() => { chart.current?.setOption(option, { notMerge: true }); }, [option]);
  return <div ref={ref} role="img" aria-label={label} style={{ height, width: "100%" }} />;
}
