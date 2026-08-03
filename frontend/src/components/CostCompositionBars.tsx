import type { CostBarRow, CostSegmentId } from "@/lib/costComposition";
import { costSegmentOrder } from "@/lib/costComposition";
import { formatBps } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const SEGMENT_COLORS: Record<CostSegmentId, string> = {
  spread_bps: "bg-sky-500",
  trading_component_bps: "bg-violet-500",
  platform_fee_bps: "bg-amber-500",
  gas_bps: "bg-rose-400",
};

const SEGMENT_LABELS: Record<CostSegmentId, string> = {
  spread_bps: "Spread",
  trading_component_bps: "Trading fee",
  platform_fee_bps: "Platform fee",
  gas_bps: "Gas",
};

type Props = {
  ranked: readonly CostBarRow[];
  incomplete: readonly CostBarRow[];
};

/**
 * Stacked horizontal bars: spread + trading + platform + gas = total_cost_bps.
 * Ranked group first (ascending); gas_unknown / incomplete sit below.
 */
export function CostCompositionBars({ ranked, incomplete }: Props) {
  const maxTotal = Math.max(
    0,
    ...ranked.map((r) => r.totalCostBps ?? 0),
    // Incomplete may still show spread width relative scale from ranked max.
    ...incomplete.map((r) =>
      r.segments.reduce((s, seg) => s + Math.max(0, seg.bps), 0),
    ),
  );
  const scale = maxTotal > 0 ? maxTotal : 1;

  if (ranked.length === 0 && incomplete.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No quote cost data for this asset and size yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Legend />

      {ranked.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Ranked by total cost
          </h3>
          <ul className="space-y-2">
            {ranked.map((row, i) => (
              <BarRow
                key={row.venue}
                row={row}
                scale={scale}
                rank={i + 1}
                mode="complete"
              />
            ))}
          </ul>
        </div>
      )}

      {incomplete.length > 0 && (
        <div className="space-y-2 border-t border-dashed border-zinc-200 pt-4 dark:border-zinc-800">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
            Cost incomplete
          </h3>
          <p className="text-xs text-zinc-500">
            gas_unknown or missing total — excluded from ranking (WHI-799 §5.2).
            Not treated as zero.
          </p>
          <ul className="space-y-2">
            {incomplete.map((row) => (
              <BarRow
                key={row.venue}
                row={row}
                scale={scale}
                mode="incomplete"
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-600 dark:text-zinc-400">
      {costSegmentOrder().map((id) => (
        <span key={id} className="inline-flex items-center gap-1.5">
          <span
            className={cn("inline-block h-2.5 w-2.5 rounded-sm", SEGMENT_COLORS[id])}
            aria-hidden
          />
          {SEGMENT_LABELS[id]}
        </span>
      ))}
    </div>
  );
}

function BarRow({
  row,
  scale,
  rank,
  mode,
}: {
  row: CostBarRow;
  scale: number;
  rank?: number;
  mode: "complete" | "incomplete";
}) {
  const totalLabel =
    mode === "complete" && row.totalCostBps != null
      ? `${formatBps(row.totalCostBps)} bps`
      : "incomplete";

  return (
    <li className="grid grid-cols-[minmax(7rem,10rem)_1fr_auto] items-center gap-3">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
          {rank != null ? (
            <span className="mr-1.5 tabular-nums text-zinc-400">{rank}.</span>
          ) : null}
          {row.label}
        </div>
        {row.feeEmbeddedInPrice ? (
          <Badge variant="secondary" className="mt-0.5 normal-case tracking-normal">
            fee in price
          </Badge>
        ) : null}
      </div>

      <div
        className="relative flex h-6 w-full overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-900"
        role="img"
        aria-label={`${row.label}: ${totalLabel}`}
      >
        {row.segments.map((seg) => {
          if (seg.bps <= 0) return null;
          const pct = Math.max(0.5, (seg.bps / scale) * 100);
          return (
            <div
              key={seg.id}
              className={cn(
                "h-full min-w-[2px]",
                SEGMENT_COLORS[seg.id],
                mode === "incomplete" && "opacity-50",
              )}
              style={{ width: `${pct}%` }}
              title={`${SEGMENT_LABELS[seg.id]}: ${formatBps(seg.bps)} bps`}
            />
          );
        })}
      </div>

      <div className="w-20 text-right text-sm tabular-nums text-zinc-700 dark:text-zinc-300">
        {totalLabel}
      </div>
    </li>
  );
}
