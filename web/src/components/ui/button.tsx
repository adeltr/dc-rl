import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const variants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md text-xs font-medium transition-colors disabled:pointer-events-none disabled:opacity-40 cursor-pointer",
  {
    variants: {
      variant: {
        default: "bg-accent/15 text-accent hover:bg-accent/25 border border-accent/40",
        ghost: "text-muted hover:text-text hover:bg-panel-2",
        outline: "border border-border text-text hover:bg-panel-2",
      },
      size: { sm: "h-7 px-2", md: "h-8 px-3", icon: "h-7 w-7" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);

export function Button({ className, variant, size, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof variants>) {
  return <button type="button" className={cn(variants({ variant, size }), className)} {...props} />;
}
