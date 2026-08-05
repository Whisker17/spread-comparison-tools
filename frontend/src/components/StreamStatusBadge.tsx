"use client";

/**
 * Explicit live / reconnecting indicator for the WHI-848 push stream.
 * Mirror of the mpamm.wtf status pill — product surface, not a debug badge.
 */

import type { StreamConnectionStatus } from "@/lib/streamQuotes";
import { cn } from "@/lib/utils";

export type StreamStatusBadgeProps = {
  status: StreamConnectionStatus;
  className?: string;
};

const LABEL: Record<StreamConnectionStatus, string> = {
  connecting: "connecting",
  live: "live",
  reconnecting: "reconnecting",
};

export function StreamStatusBadge({ status, className }: StreamStatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        status === "live" &&
          "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200",
        status === "reconnecting" &&
          "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
        status === "connecting" &&
          "border-zinc-300 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
        className,
      )}
      data-testid="stream-status"
      data-status={status}
      role="status"
      aria-live="polite"
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "live" && "bg-emerald-500",
          status === "reconnecting" && "animate-pulse bg-amber-500",
          status === "connecting" && "animate-pulse bg-zinc-400",
        )}
        aria-hidden
      />
      {LABEL[status]}
    </span>
  );
}
