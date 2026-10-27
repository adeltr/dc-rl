import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, Lock, Pencil, Redo2, RotateCcw, Save, Trash2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { SavedScenario } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { scenarioKey, useTwin } from "@/state/store";

export function ScenarioBar() {
  const queryClient = useQueryClient();
  const { data: saved = [] } = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const { draft, past, future, undo, redo, resetToBase, loadScenario, activeSavedId, setActiveSaved,
          confirmed, confirmedKey, compareIds, toggleCompare, setDrawer } = useTwin();
  const [naming, setNaming] = useState<null | { id?: string; name: string }>(null);
  const [copied, setCopied] = useState(false);
  const confirmedForDraft = confirmed && confirmedKey === scenarioKey(draft) && confirmed.status === "confirmed"
    ? confirmed : null;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["scenarios"] });
  const save = useMutation({
    mutationFn: ({ id, name }: { id?: string; name: string }) =>
      id ? api.patchScenario(id, { name }) : api.saveScenario(name, draft!, confirmedForDraft?.id ?? null),
    onSuccess: (s, variables) => {
      refresh();
      if (!variables.id) {
        setActiveSaved(s.id);
        if (!s.result_id) setPendingLink({ id: s.id, key: scenarioKey(draft) });
      }
      setNaming(null);
    },
  });
  const remove = useMutation({ mutationFn: api.deleteScenario, onSuccess: refresh });

  // un scénario sauvegardé avant la fin du calcul reçoit son résultat confirmé dès qu'il arrive
  const [pendingLink, setPendingLink] = useState<{ id: string; key: string } | null>(null);
  useEffect(() => {
    if (pendingLink && confirmed && confirmedKey === pendingLink.key && confirmed.status === "confirmed") {
      api.patchScenario(pendingLink.id, { result_id: confirmed.id }).then(refresh);
      setPendingLink(null);
    }
  }, [pendingLink, confirmed, confirmedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      if ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  const open = (s: SavedScenario) => loadScenario(s.scenario, s.id);
  const share = async () => {
    await navigator.clipboard?.writeText(window.location.href).catch(() => undefined);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <div className="flex items-center gap-1" role="group" aria-label="Historique">
        <Button size="icon" variant="ghost" onClick={undo} disabled={!past.length} aria-label="Annuler (Ctrl+Z)" title="Annuler (Ctrl+Z)"><Undo2 size={14} /></Button>
        <Button size="icon" variant="ghost" onClick={redo} disabled={!future.length} aria-label="Rétablir (Ctrl+Maj+Z)" title="Rétablir (Ctrl+Maj+Z)"><Redo2 size={14} /></Button>
        <Button size="icon" variant="ghost" onClick={resetToBase} aria-label="Revenir au cas de base" title="Revenir au cas de base"><RotateCcw size={14} /></Button>
      </div>

      <ul className="flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="Scénarios sauvegardés">
        {saved.map((s) => {
          const active = s.id === activeSavedId;
          const comparing = s.result_id ? compareIds.includes(s.result_id) : false;
          return (
            <li key={s.id} className={cn("flex shrink-0 items-center rounded-md border text-xs",
                                         active ? "border-accent/60 bg-accent/10" : "border-border")}>
              {naming?.id === s.id ? (
                <NameInput initial={s.name} onDone={(name) => (name ? save.mutate({ id: s.id, name }) : setNaming(null))} />
              ) : (
                <button type="button" onClick={() => open(s)} className="flex items-center gap-1 px-2 py-1 cursor-pointer"
                        aria-current={active ? "true" : undefined}>
                  {s.locked && <Lock size={11} className="text-muted" aria-label="verrouillé" />}
                  {s.name}
                </button>
              )}
              {s.result_id && (
                <label className="flex items-center gap-1 border-l border-border px-1.5 py-1 text-[10px] text-muted cursor-pointer" title="Comparer (3 au plus)">
                  <input type="checkbox" checked={comparing}
                         onChange={() => { toggleCompare(s.result_id!); setDrawer(true, "compare"); }}
                         aria-label={`Comparer ${s.name}`} className="accent-[var(--color-accent)]" />
                  comparer
                </label>
              )}
              {!s.locked && naming?.id !== s.id && (
                <>
                  <button type="button" aria-label={`Renommer ${s.name}`} onClick={() => setNaming({ id: s.id, name: s.name })}
                          className="px-1 text-muted hover:text-text cursor-pointer"><Pencil size={11} /></button>
                  <button type="button" aria-label={`Supprimer ${s.name}`} onClick={() => remove.mutate(s.id)}
                          className="px-1 pr-1.5 text-muted hover:text-bad cursor-pointer"><Trash2 size={11} /></button>
                </>
              )}
            </li>
          );
        })}
      </ul>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {naming && !naming.id ? (
          <NameInput initial={naming.name} onDone={(name) => (name ? save.mutate({ name }) : setNaming(null))} />
        ) : (
          <Button size="sm" onClick={() => setNaming({ name: `Scénario ${saved.length}` })} disabled={!draft}
                  title={confirmedForDraft ? "Sauvegarder le scénario" : "Sauvegarder (le résultat confirmé sera associé à la prochaine sauvegarde)"}>
            <Save size={13} /> Sauvegarder
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={share} aria-label="Copier le lien du scénario">
          {copied ? <Check size={13} /> : <Copy size={13} />} Lien
        </Button>
        <a href={confirmedForDraft ? api.exportUrl(confirmedForDraft.id) : undefined}
           aria-disabled={!confirmedForDraft}
           className={cn("inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs",
                         confirmedForDraft ? "text-muted hover:bg-panel-2 hover:text-text" : "pointer-events-none text-muted/40")}>
          <Download size={13} /> Excel
        </a>
      </div>
    </div>
  );
}

function NameInput({ initial, onDone }: { initial: string; onDone: (name: string | null) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <input autoFocus value={value} aria-label="Nom du scénario" onChange={(e) => setValue(e.target.value)}
           onBlur={() => onDone(value.trim() || null)}
           onKeyDown={(e) => { if (e.key === "Enter") onDone(value.trim() || null); if (e.key === "Escape") onDone(null); }}
           className="h-7 w-40 rounded-md border border-accent bg-bg px-2 text-xs text-text outline-none" />
  );
}
