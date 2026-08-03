/**
 * Synthetic Quote fixtures demonstrating every status + gas_unknown + mid_stale.
 * Used by /status-fixtures (no Storybook dependency for M3 scaffold).
 */

import type { Quote } from "@/lib/api";

const base = {
  snapshot_id: "fixture-snap",
  asset: "BTC",
  venue_symbol: "BTCUSDT",
  instrument_type: "spot" as const,
  side: "buy" as const,
  notional_usd: "10000",
  mid: "100000",
  mid_source: "binance_usdm_index" as const,
  mid_timestamp: "2026-08-03T12:00:00Z",
  timestamp: "2026-08-03T12:00:01Z",
};

const okFees = {
  embedded_in_price: false,
  fee_tier: "default_taker",
  trading_fee_bps: "10",
  platform_fee_bps: "0",
  gas_unknown: false,
  gas_bps: "0",
  explicit_fee_bps: "10",
};

const emptyFees = {
  embedded_in_price: false,
  fee_tier: "default_taker",
  trading_fee_bps: null,
  platform_fee_bps: "0",
  gas_unknown: false,
  explicit_fee_bps: null,
};

export type FixtureCase = {
  id: string;
  title: string;
  description: string;
  quote: Quote;
  /** Metric to display when kind is value / cost_incomplete. */
  formattedMetric?: string;
};

export const STATUS_FIXTURES: FixtureCase[] = [
  {
    id: "ok",
    title: "ok",
    description: "Numeric bps cell; eligible for best-venue highlight.",
    formattedMetric: "14.40",
    quote: {
      ...base,
      venue: "binance",
      mid_stale: false,
      effective_price: "100144",
      spread_bps: "14.4000",
      total_cost_bps: "24.4000",
      fee_breakdown: okFees,
      status: "ok",
      qty_base: "0.1",
      qty_method: "base_from_mid",
    },
  },
  {
    id: "no_quote",
    title: "no_quote",
    description: 'No market / no route → "—".',
    quote: {
      ...base,
      venue: "humidifi",
      mid_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "no_quote",
      qty_base: null,
    },
  },
  {
    id: "unsupported_asset",
    title: "unsupported_asset",
    description: 'Asset not listed → "—".',
    quote: {
      ...base,
      venue: "apex",
      mid_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "unsupported_asset",
      qty_base: null,
    },
  },
  {
    id: "insufficient_liquidity",
    title: "insufficient_liquidity",
    description: "Depth below target size → badge.",
    quote: {
      ...base,
      venue: "lighter",
      mid_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "insufficient_liquidity",
      qty_base: null,
    },
  },
  {
    id: "error",
    title: "error",
    description: "Adapter failure → badge + retry hint.",
    quote: {
      ...base,
      venue: "bybit",
      mid_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "error",
      qty_base: null,
      error_code: "timeout",
      error_message: "upstream timeout after 2s",
    },
  },
  {
    id: "gas_unknown",
    title: "gas_unknown",
    description:
      "status=ok but gas unknown → cost incomplete; excluded from best (WHI-799 §5.2).",
    formattedMetric: "4.40",
    quote: {
      ...base,
      venue: "uniswap_eth",
      instrument_type: "amm_pool",
      mid_stale: false,
      effective_price: "100044",
      spread_bps: "4.4000",
      total_cost_bps: null,
      fee_breakdown: {
        embedded_in_price: true,
        fee_tier: null,
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_unknown: true,
        gas_bps: null,
        gas_usd: null,
        explicit_fee_bps: null,
      },
      status: "ok",
      qty_base: "0.1",
      qty_method: "quote_exact_in_approx",
    },
  },
  {
    id: "mid_stale",
    title: "mid_stale",
    description:
      "Orthogonal flag: warning icon + mid timestamp; bps unchanged.",
    formattedMetric: "12.00",
    quote: {
      ...base,
      venue: "hyperliquid",
      instrument_type: "perp",
      mid_stale: true,
      mid_timestamp: "2026-08-03T11:59:50Z",
      timestamp: "2026-08-03T12:00:10Z",
      effective_price: "100120",
      spread_bps: "12.0000",
      total_cost_bps: "22.0000",
      fee_breakdown: okFees,
      status: "ok",
      qty_base: "0.1",
      qty_method: "base_from_mid",
    },
  },
];
