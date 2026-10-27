import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

import type { Option } from "@/api/types";

export function Select({ value, options, onChange, label }: { value: string; options: Option[]; onChange: (v: string) => void; label: string }) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onChange}>
      <SelectPrimitive.Trigger aria-label={label}
        className="flex h-7 w-full items-center justify-between gap-2 rounded-md border border-border bg-bg px-2 text-xs text-text cursor-pointer">
        <SelectPrimitive.Value />
        <SelectPrimitive.Icon><ChevronDown size={14} className="text-muted" /></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={4}
          className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-auto rounded-md border border-border bg-panel-2 p-1 shadow-lg">
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item key={String(o.value)} value={String(o.value)}
                className="flex cursor-pointer items-center justify-between gap-3 rounded px-2 py-1.5 text-xs text-text outline-none data-[highlighted]:bg-accent/20">
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator><Check size={12} /></SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
