"use client";

import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { Quote } from "@/lib/api";
import {
  formatBps,
  formatPrice,
  formatTimestamp,
} from "@/lib/format";
import {
  decideCellRender,
  type CellRenderKind,
  type MetricKey,
} from "@/lib/status";
import { cn } from "@/lib/utils";

export type StatusCellProps = {
  quote: Quote | null | undefined;
  /** Pre-formatted metric when status is ok (caller owns metric choice). */
  formattedMetric?: string | null;
  metricKey?: MetricKey;
  /** Highlight as best venue for this tier. */
  isBest?: boolean;
  /** Heat background class from heat.ts. */
  heatClassName?: string;
  className?: string;
  /** Extra tooltip lines (effective price, fees, etc.). */
  tooltipExtra?: ReactNode;
  /** Optional retry handler for error cells (wired by LiveSpreadDemo / section pages). */
  onRetry?: () => void;
};

/** Shared status rendering for matrix cells and fixture demos. */
export function StatusCell({
  quote,
  formattedMetric,
  metricKey = "total_cost_bps",
  isBest = false,
  heatClassName,
  className,
  tooltipExtra,
  onRetry,
}: StatusCellProps) {
  const decision = decideCellRender(quote, { formattedMetric, metricKey });

  const body = (
    <div
      className={cn(
        "relative flex min-h-10 flex-col items-center justify-center gap-0.5 rounded px-1 py-1 text-center text-sm tabular-nums",
        heatClassName,
        isBest && "ring-2 ring-emerald-500/70",
        className,
      )}
      data-kind={decision.kind}
      data-best={isBest ? "true" : "false"}
      data-mid-stale={decision.midStale ? "true" : "false"}
    >
      {decision.kind === "value" || decision.kind === "cost_incomplete" ? (
        <span className="font-medium">{decision.label}</span>
      ) : decision.kind === "dash" ? (
        <span className="text-zinc-400">—</span>
      ) : null}

      {decision.kind === "insufficient_liquidity" && (
        <Badge variant="warning">{decision.badge}</Badge>
      )}
      {decision.kind === "error" && (
        <div className="flex flex-col items-center gap-0.5">
          <Badge variant="danger">{decision.badge ?? "error"}</Badge>
          {onRetry ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-auto px-1 py-0 text-[10px] text-zinc-500"
              onClick={(e) => {
                e.stopPropagation();
                onRetry();
              }}
            >
              Retry
            </Button>
          ) : (
            decision.hint && (
              <span className="text-[10px] text-zinc-500">{decision.hint}</span>
            )
          )}
        </div>
      )}
      {decision.kind === "cost_incomplete" && decision.badge && (
        <Badge variant="muted">{decision.badge}</Badge>
      )}

      {decision.midStale && (
        <span
          className="absolute right-0.5 top-0.5 text-amber-500"
          aria-label={
            decision.midTimestamp
              ? `mid stale · mid ${formatTimestamp(decision.midTimestamp)}`
              : "mid stale"
          }
          title={
            decision.midTimestamp
              ? `mid stale · mid ${formatTimestamp(decision.midTimestamp)}`
              : "mid stale"
          }
        >
          <AlertTriangle className="h-3 w-3" />
        </span>
      )}
    </div>
  );

  const tip = buildTooltip(quote, decision.kind, decision.midStale, tooltipExtra);
  return <Tooltip content={tip}>{body}</Tooltip>;
}

function buildTooltip(
  quote: Quote | null | undefined,
  kind: CellRenderKind,
  midStale: boolean,
  extra?: ReactNode,
): ReactNode {
  if (!quote) {
    return "No quote";
  }
  return (
    <div className="space-y-1">
      <div className="font-medium">
        {quote.venue} · {quote.side} · {quote.status}
      </div>
      {midStale && (
        <p className="text-amber-700 dark:text-amber-300">
          mid stale
          {quote.mid_timestamp
            ? ` · mid ${formatTimestamp(quote.mid_timestamp)}`
            : ""}
        </p>
      )}
      {kind === "value" || kind === "cost_incomplete" ? (
        <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-300">
          <li>effective: {formatPrice(quote.effective_price)}</li>
          <li>spread: {formatBps(quote.spread_bps)} bps</li>
          <li>total cost: {formatBps(quote.total_cost_bps)} bps</li>
          <li>
            trading fee: {formatBps(quote.fee_breakdown.trading_fee_bps)} bps
            {quote.fee_breakdown.embedded_in_price ? " (embedded)" : ""}
          </li>
          <li>
            gas:{" "}
            {quote.fee_breakdown.gas_unknown
              ? "unknown"
              : `${formatBps(quote.fee_breakdown.gas_bps)} bps`}
          </li>
          <li>quote ts: {formatTimestamp(quote.timestamp)}</li>
          <li>mid ts: {formatTimestamp(quote.mid_timestamp)}</li>
        </ul>
      ) : (
        <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-300">
          {quote.error_message && <li>{quote.error_message}</li>}
          {quote.error_code && <li>code: {quote.error_code}</li>}
          <li>quote ts: {formatTimestamp(quote.timestamp)}</li>
        </ul>
      )}
      {extra}
    </div>
  );
}
