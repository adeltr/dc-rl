import { create } from "zustand";

import type { AlertTarget, Equipment, Json, Scenario, ScenarioResult } from "@/api/types";
import { setPath } from "@/lib/paths";

const COALESCE_MS = 800; // modifications successives d'un même paramètre = une seule étape d'historique
const HISTORY_LIMIT = 100;

export interface Stage {
  status: "idle" | "queued" | "running" | "done" | "error" | "cancelled";
  stage: string;
  progress: number;
  message: string;
}

export type DrawerTab = "cfads" | "heatmap" | "pue" | "tornado" | "grid" | "compare";

interface TwinState {
  base: Scenario | null;
  effective: Scenario | null;
  baseResult: ScenarioResult | null;
  draft: Scenario | null;
  past: Scenario[];
  future: Scenario[];
  lastEdit: { path: string; at: number } | null;
  selected: Equipment | null;
  focus: { target: AlertTarget; nonce: number } | null;
  heatmap: boolean;
  preview: ScenarioResult | null;
  confirmed: ScenarioResult | null;
  confirmedKey: string | null;
  previewKey: string | null;
  stage: Stage;
  activeSavedId: string | null;
  compareIds: string[];
  drawerOpen: boolean;
  drawerTab: DrawerTab;

  init: (base: Scenario, effective: Scenario | null, baseResult: ScenarioResult | null, draft?: Scenario) => void;
  setParam: (path: string, value: Json) => void;
  loadScenario: (scenario: Scenario, savedId: string | null) => void;
  undo: () => void;
  redo: () => void;
  resetToBase: () => void;
  select: (equipment: Equipment | null) => void;
  focusOn: (target: AlertTarget) => void;
  toggleHeatmap: () => void;
  setPreview: (key: string, result: ScenarioResult | null) => void;
  setConfirmed: (key: string, result: ScenarioResult | null) => void;
  setStage: (stage: Stage) => void;
  toggleCompare: (resultId: string) => void;
  setDrawer: (open: boolean, tab?: DrawerTab) => void;
  setActiveSaved: (id: string | null) => void;
}

export const scenarioKey = (s: Scenario | null) => (s ? JSON.stringify(s) : "");

export const useTwin = create<TwinState>((set, get) => ({
  base: null,
  effective: null,
  baseResult: null,
  draft: null,
  past: [],
  future: [],
  lastEdit: null,
  selected: null,
  focus: null,
  heatmap: false,
  preview: null,
  confirmed: null,
  confirmedKey: null,
  previewKey: null,
  stage: { status: "idle", stage: "", progress: 0, message: "" },
  activeSavedId: "base",
  compareIds: [],
  drawerOpen: true,
  drawerTab: "cfads",

  init: (base, effective, baseResult, draft) =>
    set({ base, effective, baseResult, draft: draft ?? base, past: [], future: [],
          confirmed: baseResult, confirmedKey: scenarioKey(base), activeSavedId: draft ? null : "base" }),

  setParam: (path, value) => {
    const { draft, past, lastEdit } = get();
    if (!draft) return;
    const now = Date.now();
    const coalesce = lastEdit && lastEdit.path === path && now - lastEdit.at < COALESCE_MS;
    set({
      draft: setPath(draft, path, value),
      past: coalesce ? past : [...past, draft].slice(-HISTORY_LIMIT),
      future: [],
      lastEdit: { path, at: now },
      activeSavedId: null,
    });
  },

  loadScenario: (scenario, savedId) => {
    const { draft, past } = get();
    set({ draft: scenario, past: draft ? [...past, draft].slice(-HISTORY_LIMIT) : past, future: [],
          lastEdit: null, activeSavedId: savedId });
  },

  undo: () => {
    const { past, draft, future } = get();
    if (!past.length || !draft) return;
    set({ draft: past[past.length - 1], past: past.slice(0, -1), future: [draft, ...future], lastEdit: null,
          activeSavedId: null });
  },

  redo: () => {
    const { past, draft, future } = get();
    if (!future.length || !draft) return;
    set({ draft: future[0], past: [...past, draft], future: future.slice(1), lastEdit: null, activeSavedId: null });
  },

  resetToBase: () => {
    const { base } = get();
    if (base) get().loadScenario(base, "base");
  },

  select: (selected) => set({ selected }),
  focusOn: (target) => set({ focus: { target, nonce: Date.now() },
                             selected: target === "campus" ? null : (target as Equipment) }),
  toggleHeatmap: () => set((s) => ({ heatmap: !s.heatmap })),
  setPreview: (previewKey, preview) => set({ preview, previewKey }),
  setConfirmed: (confirmedKey, confirmed) => set({ confirmed, confirmedKey }),
  setStage: (stage) => set({ stage }),
  toggleCompare: (id) =>
    set((s) => ({ compareIds: s.compareIds.includes(id) ? s.compareIds.filter((x) => x !== id)
                                                         : [...s.compareIds, id].slice(-3) })),
  setDrawer: (drawerOpen, tab) => set((s) => ({ drawerOpen, drawerTab: tab ?? s.drawerTab })),
  setActiveSaved: (activeSavedId) => set({ activeSavedId }),
}));

/** Résultat à afficher : confirmé s'il correspond au brouillon, sinon l'aperçu provisoire. */
export function useDisplayed(): { result: ScenarioResult | null; provisional: boolean } {
  const { draft, confirmed, confirmedKey, preview, previewKey } = useTwin();
  const key = scenarioKey(draft);
  if (confirmed && confirmedKey === key) return { result: confirmed, provisional: false };
  if (preview && previewKey === key) return { result: preview, provisional: true };
  return { result: confirmed ?? preview, provisional: true };
}
