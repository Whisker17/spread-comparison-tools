/**
 * Single-notional matrix detail columns (WHI-841).
 *
 * Pure view-model helpers for effective price + fee-breakdown summary that
 * previously lived only in StatusCell tooltips. Kept out of SpreadMatrix.tsx
 * so they are unit-testable (same seam as costComposition / simulateView).
 */

import type { Quote, SizeQuotePair } from "@/lib/api";
import { formatBps, formatPrice } from "@/lib/format";
import type { SideView } from "@/lib/summary";

export type MatrixDetailModel = {
  effective: string;
  fees: string;
  feesTitle: string | undefined;
};

/** Inline Effective / Fees cells for the selected size. */
export function detailFromPair(
  pair: SizeQuotePair | undefined,
  sideView: SideView,
): MatrixDetailModel {
  if (!pair) {
    return { effective: "—", fees: "—", feesTitle: undefined };
  }
  if (sideView === "round_trip") {
    // Round-trip has no single effective price; surface leg fees if both ok.
    const buy = pair.buy;
    const sell = pair.sell;
    if (!buy || !sell || buy.status !== "ok" || sell.status !== "ok") {
      return { effective: "—", fees: "—", feesTitle: undefined };
    }
    const buyFee = feeSummary(buy);
    const sellFee = feeSummary(sell);
    return {
      effective: "—",
      fees: `B ${buyFee.short} / S ${sellFee.short}`,
      feesTitle: `buy: ${buyFee.title}; sell: ${sellFee.title}`,
    };
  }
  const quote = sideView === "buy" ? pair.buy : pair.sell;
  if (!quote || quote.status !== "ok") {
    return { effective: "—", fees: "—", feesTitle: undefined };
  }
  const fee = feeSummary(quote);
  return {
    effective: formatPrice(quote.effective_price),
    fees: fee.short,
    feesTitle: fee.title,
  };
}

/** Compact fee line for matrix cells + full title for hover. */
export function feeSummary(quote: Quote): { short: string; title: string } {
  const fb = quote.fee_breakdown;
  const tradingLabel =
    fb.trading_fee_bps == null || fb.trading_fee_bps === ""
      ? null
      : `${formatBps(fb.trading_fee_bps)}f`;
  const gasLabel = fb.gas_unknown
    ? "gas?"
    : fb.gas_bps == null || fb.gas_bps === ""
      ? null
      : `${formatBps(fb.gas_bps)}g`;
  const parts = [tradingLabel, gasLabel].filter(Boolean);
  if (fb.embedded_in_price) parts.push("in price");
  const short = parts.length > 0 ? parts.join(" · ") : "—";
  const title = [
    fb.trading_fee_bps != null && fb.trading_fee_bps !== ""
      ? `trading fee ${formatBps(fb.trading_fee_bps)} bps`
      : null,
    fb.embedded_in_price ? "embedded in price" : null,
    fb.gas_unknown
      ? "gas unknown"
      : fb.gas_bps != null && fb.gas_bps !== ""
        ? `gas ${formatBps(fb.gas_bps)} bps`
        : null,
    fb.platform_fee_bps != null && fb.platform_fee_bps !== "0"
      ? `platform ${formatBps(fb.platform_fee_bps)} bps`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { short, title: title || "—" };
}
