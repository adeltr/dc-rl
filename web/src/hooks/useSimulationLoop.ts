import { useEffect, useRef } from "react";

import { api, followJob } from "@/api/client";
import { encodeScenario } from "@/lib/paths";
import { scenarioKey, useTwin } from "@/state/store";

const DEBOUNCE_MS = 400;
const CLIENT_ID = `ui-${Math.random().toString(36).slice(2, 10)}`;

/**
 * Boucle de retour : 400 ms après la dernière modification, aperçu immédiat (surrogate,
 * valeurs provisoires) puis simulation complète suivie en SSE. Une réponse qui ne
 * correspond plus au brouillon courant est ignorée ; l'interface ne se bloque jamais.
 */
export function useSimulationLoop() {
  const draft = useTwin((s) => s.draft);
  const base = useTwin((s) => s.base);
  const stopRef = useRef<() => void>(() => {});

  // état partageable dans l'URL
  useEffect(() => {
    if (!draft || !base) return;
    const encoded = encodeScenario(base, draft);
    const url = new URL(window.location.href);
    if (encoded) url.searchParams.set("s", encoded);
    else url.searchParams.delete("s");
    window.history.replaceState(null, "", url);
  }, [draft, base]);

  useEffect(() => {
    if (!draft) return;
    const key = scenarioKey(draft);
    const state = useTwin.getState();
    if (state.confirmedKey === key) {
      state.setStage({ status: "done", stage: "terminé", progress: 1, message: "" });
      return;
    }
    const timer = window.setTimeout(async () => {
      const current = () => scenarioKey(useTwin.getState().draft) === key;
      stopRef.current();
      useTwin.getState().setStage({ status: "queued", stage: "aperçu", progress: 0, message: "" });

      api.preview(draft)
        .then((preview) => current() && useTwin.getState().setPreview(key, preview))
        .catch((error) => current() && useTwin.getState().setStage({
          status: "error", stage: "erreur", progress: 0, message: String(error.message ?? error) }));

      try {
        const job = await api.simulate(draft, CLIENT_ID);
        stopRef.current = followJob(job.job_id, async (event) => {
          if (!current()) return;
          useTwin.getState().setStage({ status: event.status, stage: event.stage, progress: event.progress,
                                        message: event.message });
          if ((event.status === "done" || event.status === "error") && event.result_id) {
            const result = await api.result(event.result_id);
            if (current()) useTwin.getState().setConfirmed(key, result);
          }
        });
      } catch (error) {
        if (current()) useTwin.getState().setStage({ status: "error", stage: "erreur", progress: 0,
                                                      message: String((error as Error).message ?? error) });
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [draft]);

  useEffect(() => () => stopRef.current(), []);
}

export { CLIENT_ID };
