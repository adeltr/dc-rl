import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Panel({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-border bg-panel", className)}>
      {title && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}
