import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/cn";

export function Slider({ className, ...props }: SliderPrimitive.SliderProps) {
  return (
    <SliderPrimitive.Root className={cn("relative flex h-5 w-full touch-none select-none items-center", className)} {...props}>
      <SliderPrimitive.Track className="relative h-1 grow overflow-hidden rounded-full bg-border">
        <SliderPrimitive.Range className="absolute h-full bg-accent" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={props["aria-label"]}
        className="block h-3.5 w-3.5 rounded-full border border-accent bg-bg shadow focus-visible:outline-2 focus-visible:outline-accent"
      />
    </SliderPrimitive.Root>
  );
}
