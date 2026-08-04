"use client";

/**
 * Segmented size control for the single-notional matrix (WHI-841).
 *
 * Options are always passed in (typically `section.notionals` / `NOTIONAL_TIERS_USD`)
 * — never hardcode the tier list here so a sixth tier appears without component edits.
 */

import { formatNotional } from "@/lib/format";
import { cn } from "@/lib/utils";

export type SizeSelectorProps = {
  /** Selectable notional tiers as USD strings (e.g. from `NOTIONAL_TIERS_USD`). */
  tiers: readonly string[];
  /** Currently selected tier (must be one of `tiers` when non-empty). */
  value: string;
  onChange: (notionalUsd: string) => void;
  className?: string;
  /** Accessible name; default "SIZE". */
  label?: string;
};

export function SizeSelector({
  tiers,
  value,
  onChange,
  className,
  label = "SIZE",
}: SizeSelectorProps) {
  return (
    <div
      className={cn("flex flex-col gap-1", className)}
      data-testid="size-selector"
    >
      <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      <div
        className="inline-flex flex-wrap rounded-md border border-zinc-200 p-0.5 dark:border-zinc-700"
        role="group"
        aria-label={label}
      >
        {tiers.map((tier) => {
          const active = tier === value;
          return (
            <button
              key={tier}
              type="button"
              onClick={() => onChange(tier)}
              aria-pressed={active}
              data-testid={`size-option-${tier}`}
              data-size={tier}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors tabular-nums",
                active
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
              )}
            >
              {formatNotional(tier)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
