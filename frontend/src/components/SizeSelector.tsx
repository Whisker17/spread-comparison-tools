"use client";

/**
 * Segmented size control (WHI-841 / WHI-864).
 *
 * One tier at a time — no ``All`` multi-column chip. Tier lists are always
 * passed in — never hardcode so a sixth tier appears without edits.
 */

import { formatNotional } from "@/lib/format";
import { cn } from "@/lib/utils";

export type SizeSelectorProps = {
  /** Selectable notional tiers as USD strings (e.g. from `NOTIONAL_TIERS_USD`). */
  tiers: readonly string[];
  /** Current view: a tier USD string. */
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
  const options = tiers.map((tier) => ({
    id: tier,
    label: formatNotional(tier),
  }));

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
        {options.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onChange(opt.id)}
              aria-pressed={active}
              data-testid={`size-option-${opt.id}`}
              data-size={opt.id}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors tabular-nums",
                active
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
