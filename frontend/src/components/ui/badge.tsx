import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "border-transparent bg-zinc-800 text-zinc-100",
        secondary: "border-transparent bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100",
        outline: "border-zinc-300 text-zinc-700 dark:border-zinc-600 dark:text-zinc-200",
        warning: "border-transparent bg-amber-500/20 text-amber-800 dark:text-amber-200",
        danger: "border-transparent bg-rose-500/20 text-rose-800 dark:text-rose-200",
        muted: "border-transparent bg-zinc-500/15 text-zinc-600 dark:text-zinc-300",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export type BadgeProps = HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}
