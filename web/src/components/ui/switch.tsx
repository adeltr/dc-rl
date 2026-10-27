import * as SwitchPrimitive from "@radix-ui/react-switch";

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <SwitchPrimitive.Root checked={checked} onCheckedChange={onChange} aria-label={label}
      className="relative h-4 w-7 rounded-full bg-border data-[state=checked]:bg-accent cursor-pointer">
      <SwitchPrimitive.Thumb className="block h-3 w-3 translate-x-0.5 rounded-full bg-text transition-transform data-[state=checked]:translate-x-3.5" />
    </SwitchPrimitive.Root>
  );
}
