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
      quote_stale: false,
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
      quote_stale: false,
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
      quote_stale: false,
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
      quote_stale: false,
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
      quote_stale: false,
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
    id: "not_sampled",
    title: "not_sampled",
    description:
      "Pull poller did not sample this size (sparse matrix) → muted 'not sampled', not error (WHI-865).",
    quote: {
      ...base,
      venue: "humidifi",
      instrument_type: "prop_amm",
      notional_usd: "100000",
      mid_stale: false,
      quote_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "not_sampled",
      qty_base: null,
      error_code: "not_sampled",
      error_message:
        "humidifi: notional 100000 is outside this group's sample matrix (group=jupiter)",
    },
  },
  {
    id: "rate_limited",
    title: "rate_limited",
    description:
      "Rate-limit wait would exceed budget → RATE LIMITED (WHI-844), not timeout.",
    quote: {
      ...base,
      venue: "humidifi",
      instrument_type: "prop_amm",
        mid_stale: false,
      quote_stale: false,
      effective_price: null,
      spread_bps: null,
      total_cost_bps: null,
      fee_breakdown: emptyFees,
      status: "rate_limited",
      qty_base: null,
      error_code: "rate_limited",
      error_message: "Jupiter rate limited; retry_after=8.00s exceeds remaining budget",
    },
  },
  {
    id: "excessive_impact",
    title: "excessive_impact",
    description:
      "Price impact over threshold → number stays visible, never best/heat (WHI-845).",
    formattedMetric: "38283.00",
    quote: {
      ...base,
      venue: "tessera_solana",
      instrument_type: "prop_amm",
        mid_stale: false,
      quote_stale: false,
      effective_price: "344641.67",
      spread_bps: "44011.1805",
      total_cost_bps: "38283",
      price_impact_bps: "8100",
      fee_breakdown: {
        embedded_in_price: true,
        fee_tier: "TesseraV",
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_unknown: false,
        gas_bps: "0",
        explicit_fee_bps: "0",
      },
      status: "excessive_impact",
      qty_base: "2.9016",
      error_code: "excessive_impact",
      error_message: "price impact 8100 bps exceeds max_price_impact_bps=500",
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
      quote_stale: false,
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
      quote_stale: false,
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
  {
    id: "gas_dominated_100",
    title: "gas_dominated ($100)",
    description:
      "WHI-838: $100 L1 AMM — $3 gas → 300 gas_bps. Number stays fully legible; " +
      "matrix heat is per-column so this cell does not flatten larger tiers.",
    formattedMetric: "304.40",
    quote: {
      ...base,
      venue: "uniswap_eth",
      instrument_type: "amm_pool",
      notional_usd: "100",
        mid_stale: false,
      quote_stale: false,
      effective_price: "100044",
      spread_bps: "4.4000",
      // spread 4.4 + gas 300 = 304.4 total (embedded trading fee in price)
      total_cost_bps: "304.4000",
      fee_breakdown: {
        embedded_in_price: true,
        fee_tier: null,
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_unknown: false,
        gas_bps: "300.0000",
        gas_usd: "3",
        explicit_fee_bps: null,
      },
      status: "ok",
      qty_base: "0.001",
      qty_method: "base_from_mid",
    },
  },
];
