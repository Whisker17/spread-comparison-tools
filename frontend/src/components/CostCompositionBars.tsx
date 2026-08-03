import type { CostBarRow, CostSegmentId } from "@/lib/costComposition";
import { COST_SEGMENT_ORDER } from "@/lib/costComposition";
import { formatBps } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const SEGMENT_COLORS: Record<CostSegmentId, string> = {
  spread_bps: "bg-sky-500",
  trading_component_bps: "bg-violet-500",
  platform_fee_bps: "bg-amber-500",
  gas_bps: "bg-rose-400",
};

/** Negative segment (better than mid) — still drawn at |bps| width. */
const SEGMENT_COLORS_NEG: Record<CostSegmentId, string> = {
  spread_bps: "bg-sky-500/40 ring-1 ring-inset ring-sky-600",
  trading_component_bps: "bg-violet-500/40 ring-1 ring-inset ring-violet-600",
  platform_fee_bps: "bg-amber-500/40 ring-1 ring-inset ring-amber-600",
  gas_bps: "bg-rose-400/40 ring-1 ring-inset ring-rose-600",
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
  other?: readonly CostBarRow[];
};

/**
 * Stacked horizontal bars for complete costs; open-ended incomplete rows so
 * gas_unknown is never drawn as cheaper-than-zero (WHI-799 §5.2).
 * Negative segment bps are preserved (drawn at |bps|, ringed style).
 */
export function CostCompositionBars({
  ranked,
  incomplete,
  other = [],
}: Props) {
  // Scale from rankable totals + known segment magnitudes (including incomplete
  // known pieces). Null gas never contributes, so unknown is not treated as 0.
  const maxTotal = Math.max(
    0,
    ...ranked.map((r) => Math.abs(r.totalCostBps ?? 0)),
    ...ranked.flatMap((r) =>
      r.segments.map((s) => (s.bps == null ? 0 : Math.abs(s.bps))),
    ),
    ...incomplete.flatMap((r) =>
      r.segments.map((s) => (s.bps == null ? 0 : Math.abs(s.bps))),
    ),
  );
  const scale = maxTotal > 0 ? maxTotal : 1;

  if (ranked.length === 0 && incomplete.length === 0 && other.length === 0) {
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
            Open-ended bars; gas is not treated as zero.
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

      {other.length > 0 && (
        <div className="space-y-2 border-t border-dashed border-zinc-200 pt-4 dark:border-zinc-800">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            No quote / error
          </h3>
          <ul className="space-y-1">
            {other.map((row) => (
              <li
                key={row.venue}
                className="flex items-center justify-between gap-3 text-sm text-zinc-600 dark:text-zinc-400"
              >
                <span className="font-medium text-zinc-800 dark:text-zinc-200">
                  {row.label}
                </span>
                <Badge variant="muted" className="normal-case tracking-normal">
                  {row.quoteStatus}
                </Badge>
              </li>
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
      {COST_SEGMENT_ORDER.map((id) => (
        <span key={id} className="inline-flex items-center gap-1.5">
          <span
            className={cn(
              "inline-block h-2.5 w-2.5 rounded-sm",
              SEGMENT_COLORS[id],
            )}
            aria-hidden
          />
          {SEGMENT_LABELS[id]}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-4 rounded-sm bg-[repeating-linear-gradient(135deg,#a1a1aa_0_2px,transparent_2px_4px)] dark:bg-[repeating-linear-gradient(135deg,#52525b_0_2px,transparent_2px_4px)]"
          aria-hidden
        />
        Unknown gas
      </span>
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
          <Badge
            variant="secondary"
            className="mt-0.5 normal-case tracking-normal"
          >
            fee in price
          </Badge>
        ) : null}
      </div>

      <div
        className={cn(
          "relative flex h-6 w-full overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-900",
          mode === "incomplete" && "border border-dashed border-amber-400/60",
        )}
        role="img"
        aria-label={`${row.label}: ${totalLabel}`}
      >
        {row.segments.map((seg) => {
          if (seg.bps === null) {
            // Unknown segment (gas_unknown): hatched open-ended tail, not zero width.
            if (mode !== "incomplete" || seg.id !== "gas_bps") return null;
            return (
              <div
                key={seg.id}
                className="h-full min-w-[1.5rem] flex-1 bg-[repeating-linear-gradient(135deg,#fbbf24_0_3px,transparent_3px_6px)] opacity-70 dark:bg-[repeating-linear-gradient(135deg,#b45309_0_3px,transparent_3px_6px)]"
                title="Gas unknown — not ranked"
              />
            );
          }
          // Skip exact zero only — negatives are preserved (drawn at |bps|).
          if (seg.bps === 0) return null;
          const pct = (Math.abs(seg.bps) / scale) * 100;
          const neg = seg.bps < 0;
          return (
            <div
              key={seg.id}
              className={cn(
                "h-full min-w-[2px]",
                neg ? SEGMENT_COLORS_NEG[seg.id] : SEGMENT_COLORS[seg.id],
              )}
              style={{ width: `${pct}%` }}
              title={`${SEGMENT_LABELS[seg.id]}: ${formatBps(seg.bps)} bps${neg ? " (better than mid)" : ""}`}
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
