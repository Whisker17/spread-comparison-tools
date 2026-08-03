"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function TooltipProvider({
  delayDuration = 200,
  ...props
}: ComponentPropsWithoutRef<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider delayDuration={delayDuration} {...props} />;
}

export function Tooltip({
  children,
  content,
  className,
  side = "top",
}: {
  children: ReactNode;
  content: ReactNode;
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}) {
  if (content === null || content === undefined || content === false) {
    return <>{children}</>;
  }
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-xs rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-800 shadow-md dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100",
            className,
          )}
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-white dark:fill-zinc-900" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
