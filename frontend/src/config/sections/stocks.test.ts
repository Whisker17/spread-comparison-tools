import { describe, expect, it } from "vitest";

import {
  BSTOCKS_REBASE_FOOTNOTE,
  buildStocksVenueLabels,
  EQUITY_PERP_ASSETS,
  EQUITY_PERP_REPRESENTATIONS,
  EQUITY_PERP_VENUES,
  equityPerpsBoard,
  STOCK_ASSET_TITLES,
  stocksVenueSummaryLabel,
  TOKENIZED_REPRESENTATIONS,
  TOKENIZED_STOCK_ASSETS,
  TOKENIZED_STOCK_VENUES,
  tokenizedStocksBoard,
} from "@/config/sections/stocks";
import {
  hiddenVenuesForAsset,
  isOrderbookVenue,
  venuesForAsset,
} from "@/config/sections/helpers";
import type { SizeQuotePair } from "@/lib/api";
import type { Quote } from "@/lib/api";
import { bestVenuePerTier, formatSnapshotSummary } from "@/lib/summary";
import { decideCellRender } from "@/lib/status";

function quote(
  overrides: Partial<Quote> & Pick<Quote, "venue" | "status">,
): Quote {
  const gasUnknown = overrides.fee_breakdown?.gas_unknown ?? false;
  return {
    snapshot_id: "s1",
    asset: "QQQB",
    instrument_type: "spot",
    side: "buy",
    notional_usd: "10000",
    mid: "500",
    mid_source: "binance_spot_tob",
    mid_timestamp: "2026-08-03T12:00:00Z",
    mid_stale: false, quote_stale: false,
    timestamp: "2026-08-03T12:00:01Z",
    fee_breakdown: {
      embedded_in_price: false,
      platform_fee_bps: "0",
      gas_unknown: gasUnknown,
      explicit_fee_bps: gasUnknown ? null : "10",
      trading_fee_bps: gasUnknown ? null : "10",
      gas_bps: gasUnknown ? null : "0",
    },
    effective_price: overrides.status === "ok" ? "501" : null,
    spread_bps: overrides.status === "ok" ? "10" : null,
    total_cost_bps: overrides.status === "ok" && !gasUnknown ? "20" : null,
    qty_base: overrides.status === "ok" ? "20" : null,
    ...overrides,
  };
}

function pair(
  venue: string,
  notional: string,
  buy: Quote | null,
): SizeQuotePair {
  return {
    snapshot_id: "s1",
    venue,
    asset: "QQQB",
    instrument_type: "spot",
    notional_usd: notional,
    buy,
    sell: null,
  };
}

describe("stocks section config (WHI-810)", () => {
  it("P0-A covers QQQB/SPCXB/NVDAB/NVDAON across three BSC venues", () => {
    expect(tokenizedStocksBoard.assets).toEqual([...TOKENIZED_STOCK_ASSETS]);
    expect(tokenizedStocksBoard.venues).toEqual([...TOKENIZED_STOCK_VENUES]);
    expect(venuesForAsset(tokenizedStocksBoard, "QQQB")).toEqual([
      "binance",
      "pancakeswap_bsc",
      "tessera_bsc",
    ]);
  });

  it("hides Binance for NVDAON (no CEX spot) and labels Ondo", () => {
    expect(hiddenVenuesForAsset(tokenizedStocksBoard, "NVDAON")).toEqual([
      "binance",
    ]);
    expect(venuesForAsset(tokenizedStocksBoard, "NVDAON")).toEqual([
      "pancakeswap_bsc",
      "tessera_bsc",
    ]);
    expect(STOCK_ASSET_TITLES.NVDAON).toMatch(/Ondo/i);
  });

  it("P0-B is four equities × five venues with no SPY/QQQ", () => {
    expect(equityPerpsBoard.assets).toEqual([...EQUITY_PERP_ASSETS]);
    expect(equityPerpsBoard.venues).toEqual([...EQUITY_PERP_VENUES]);
    expect(equityPerpsBoard.assets).not.toContain("SPY");
    expect(equityPerpsBoard.assets).not.toContain("QQQ");
    for (const asset of EQUITY_PERP_ASSETS) {
      expect(venuesForAsset(equityPerpsBoard, asset)).toEqual([
        ...EQUITY_PERP_VENUES,
      ]);
    }
  });

  it("surfaces Hyperliquid xyz: representation on equity-perp labels", () => {
    const labels = buildStocksVenueLabels([...EQUITY_PERP_VENUES], {
      board: "equity_perp",
      asset: "TSLA",
      instrumentType: equityPerpsBoard.instrumentType,
    });
    expect(labels.hyperliquid).toContain("xyz:TSLA");
    expect(labels.hyperliquid).toMatch(/perp/i);
    expect(labels.binance).toMatch(/perp/i);
    expect(labels.binance).toContain("TSLAUSDT");
    expect(labels.hyperliquid).toMatch(/USDC/);
    expect(EQUITY_PERP_REPRESENTATIONS.TSLA.hyperliquid).toBe("xyz:TSLA");
  });

  it("drops the quote-currency part when the symbol already ends in it", () => {
    const labels = buildStocksVenueLabels([...EQUITY_PERP_VENUES], {
      board: "equity_perp",
      asset: "TSLA",
      instrumentType: equityPerpsBoard.instrumentType,
    });
    // No "TSLAUSDT · USDT" / "TSLA-USDT · USDT" tail.
    expect(labels.binance).toBe("Binance · perp · TSLAUSDT");
    expect(labels.apex).toBe("ApeX · perp · TSLA-USDT");
    // Still annotated where the symbol does not imply the quote leg.
    expect(labels.hyperliquid).toBe("Hyperliquid · perp · xyz:TSLA · USDC");
    expect(labels.lighter).toBe("Lighter · perp · TSLA · USDC");
  });

  it("labels tokenized CEX as spot with venue symbol and on-chain tokens", () => {
    const labels = buildStocksVenueLabels([...TOKENIZED_STOCK_VENUES], {
      board: "tokenized",
      asset: "NVDAB",
    });
    expect(labels.binance).toMatch(/spot/i);
    expect(labels.binance).toContain("NVDABUSDT");
    expect(labels.binance).toMatch(/USDT/);
    expect(labels.pancakeswap_bsc).toBe("PancakeSwap (BSC) · NVDAB · USDT");
    expect(labels.tessera_bsc).toBe("Tessera (BSC) · NVDAB · USDT");
    expect(TOKENIZED_REPRESENTATIONS.NVDAON.pancakeswap_bsc).toBe("NVDAon");
  });

  it("marks only orderbook classes for TOB rows", () => {
    expect(isOrderbookVenue("binance")).toBe(true);
    expect(isOrderbookVenue("hyperliquid")).toBe(true);
    expect(isOrderbookVenue("pancakeswap_bsc")).toBe(false);
    expect(isOrderbookVenue("tessera_bsc")).toBe(false);
  });

  it("includes wrapper/symbol in on-chain and CEX summary labels", () => {
    expect(
      stocksVenueSummaryLabel("tessera_bsc", {
        board: "tokenized",
        asset: "QQQB",
      }),
    ).toBe("Tessera (BSC) (QQQB)");
    expect(
      stocksVenueSummaryLabel("binance", {
        board: "tokenized",
        asset: "QQQB",
      }),
    ).toBe("Binance spot (QQQBUSDT)");
    expect(
      stocksVenueSummaryLabel("binance", {
        board: "equity_perp",
        asset: "TSLA",
        instrumentType: "perp",
      }),
    ).toBe("Binance perp (TSLAUSDT)");
    expect(
      stocksVenueSummaryLabel("hyperliquid", {
        board: "equity_perp",
        asset: "AAPL",
      }),
    ).toBe("Hyperliquid perp (xyz:AAPL)");
  });

  it("ships a persistent bStocks rebase footnote for P0-A", () => {
    expect(BSTOCKS_REBASE_FOOTNOTE.toLowerCase()).toMatch(/rebase/);
  });

  it("defaults poll interval to 30s on both boards", () => {
    expect(tokenizedStocksBoard.pollIntervalMs).toBe(30_000);
    expect(equityPerpsBoard.pollIntervalMs).toBe(30_000);
  });

  it("requests instrument_type=perp on equity-perp board so CEX resolves TradFi", () => {
    // Without this, aggregator defaults CEX to spot and TSLA/NVDA/… are
    // unsupported_asset on Binance/Bybit (WHI-826 _perp_only).
    expect(equityPerpsBoard.instrumentType).toBe("perp");
    expect(tokenizedStocksBoard.instrumentType).toBeUndefined();
  });
});

describe("stocks snapshot summary fixtures (WHI-799 §5.2 / WHI-810)", () => {
  it("Tessera no_quote never wins; dash render stays non-fatal", () => {
    const pairs = [
      pair(
        "binance",
        "10000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "25" }),
      ),
      pair(
        "pancakeswap_bsc",
        "10000",
        quote({
          venue: "pancakeswap_bsc",
          status: "ok",
          total_cost_bps: "40",
        }),
      ),
      pair(
        "tessera_bsc",
        "10000",
        quote({ venue: "tessera_bsc", status: "no_quote", total_cost_bps: null }),
      ),
    ];

    const picks = bestVenuePerTier(pairs, {
      side: "buy",
      venues: [...TOKENIZED_STOCK_VENUES],
    });
    expect(picks).toHaveLength(1);
    expect(picks[0]?.venue).toBe("binance");
    expect(picks[0]?.empty).toBe(false);

    const tesseraCell = decideCellRender(
      quote({ venue: "tessera_bsc", status: "no_quote" }),
    );
    expect(tesseraCell.kind).toBe("dash");
    expect(tesseraCell.label).toBe("—");
    expect(tesseraCell.eligibleForBest).toBe(false);
  });

  it("gas_unknown on-chain row is excluded from best ranking", () => {
    const pairs = [
      pair(
        "tessera_bsc",
        "1000",
        quote({
          venue: "tessera_bsc",
          status: "ok",
          total_cost_bps: null,
          spread_bps: "2",
          fee_breakdown: {
            embedded_in_price: true,
            platform_fee_bps: "0",
            gas_unknown: true,
            explicit_fee_bps: null,
            gas_bps: null,
          },
        }),
      ),
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "18" }),
      ),
    ];
    const picks = bestVenuePerTier(pairs, {
      venues: [...TOKENIZED_STOCK_VENUES],
    });
    expect(picks[0]?.venue).toBe("binance");

    const prose = formatSnapshotSummary(pairs, {
      asset: "QQQB",
      venues: [...TOKENIZED_STOCK_VENUES],
      venueLabels: {
        binance: "Binance spot",
        pancakeswap_bsc: "PancakeSwap (BSC)",
        tessera_bsc: "Tessera (BSC)",
      },
    });
    expect(prose).toMatch(/Binance spot/);
    expect(prose).not.toMatch(/Tessera/);
  });
});
