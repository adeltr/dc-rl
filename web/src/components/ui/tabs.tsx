import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/cn";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return <TabsPrimitive.List className={cn("flex gap-1", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn("rounded px-2.5 py-1 text-xs text-muted hover:text-text data-[state=active]:bg-panel-2 data-[state=active]:text-text cursor-pointer", className)}
      {...props}
    />
  );
}
