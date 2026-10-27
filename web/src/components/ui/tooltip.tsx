import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({ content, children, side = "left" }: { content: ReactNode; children: ReactNode; side?: "left" | "right" | "top" | "bottom" }) {
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6}
          className="z-50 max-w-72 rounded-md border border-border bg-panel-2 px-3 py-2 text-xs text-text shadow-lg">
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
