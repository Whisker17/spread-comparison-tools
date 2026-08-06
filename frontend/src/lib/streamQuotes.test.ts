import { describe, expect, it } from "vitest";

import type { QuotesResponse, SizeQuotePair } from "@/lib/api";
import {
  applyDelta,
  applyServerMessage,
  applySnapshot,
  buildSubscribeMessage,
  emptyAssetState,
  pairIdentityKey,
  reconnectDelayMs,
  streamUrl,
  toQuotesMatrixData,
} from "@/lib/streamQuotes";

function pair(
  venue: string,
  snap: string,
  cost: string,
  age: number | null = 2,
  stale = false,
): SizeQuotePair {
  return {
    snapshot_id: snap,
    venue,
    asset: "BTC",
    instrument_type: "spot",
    notional_usd: "1000",
    buy: {
      snapshot_id: snap,
      venue,
      asset: "BTC",
      instrument_type: "spot",
      side: "buy",
      notional_usd: "1000",
      mid: "100000",
      mid_source: "binance_usdm_index",
      mid_timestamp: "2026-08-05T12:00:00Z",
      mid_stale: false,
      quote_stale: stale,
      age_sec: age,
      effective_price: "100100",
      spread_bps: "10",
      total_cost_bps: cost,
      fee_breakdown: {
        embedded_in_price: false,
        platform_fee_bps: "0",
        gas_unknown: false,
        explicit_fee_bps: "10",
        trading_fee_bps: "10",
        gas_bps: "0",
      },
      timestamp: "2026-08-05T12:00:01Z",
      status: "ok",
      qty_base: "0.01",
    },
    sell: null,
  };
}

const mid = {
  snapshot_id: "pkg-1",
  asset: "BTC",
  mid: "100000",
  mid_source: "binance_usdm_index" as const,
  timestamp: "2026-08-05T12:00:00Z",
};

describe("streamUrl", () => {
  it("maps http → ws and appends /stream", () => {
    expect(streamUrl("http://localhost:8000")).toBe(
      "ws://localhost:8000/stream",
    );
  });
  it("maps https → wss", () => {
    expect(streamUrl("https://api.example.com")).toBe(
      "wss://api.example.com/stream",
    );
  });
});

describe("applySnapshot / applyDelta", () => {
  it("stores mixed per-row snapshot_ids without collapsing to one", () => {
    const data: QuotesResponse = {
      snapshot_id: "pkg-live",
      asset: "BTC",
      notional_usd: "1000",
      mid,
      pairs: [pair("binance", "live-1", "10"), pair("humidifi", "sweep-9", "5", 12)],
      notionals: ["1000"],
    };
    const next = applySnapshot({}, "BTC", data);
    const matrix = toQuotesMatrixData(next.BTC)!;
    expect(matrix.snapshotIds.sort()).toEqual(
      ["live-1", "pkg-live", "sweep-9"].sort().filter((id) =>
        matrix.snapshotIds.includes(id),
      ),
    );
    // Both row ids present.
    expect(matrix.snapshotIds).toEqual(
      expect.arrayContaining(["live-1", "sweep-9"]),
    );
    expect(matrix.pairs).toHaveLength(2);
  });

  it("merges delta pairs and removals", () => {
    const snap = applySnapshot(
      {},
      "BTC",
      {
        snapshot_id: "p1",
        asset: "BTC",
        notional_usd: "1000",
        mid,
        pairs: [pair("binance", "s1", "10"), pair("mock", "s1", "20")],
        notionals: ["1000"],
      },
    );
    const after = applyDelta(snap, {
      type: "delta",
      asset: "BTC",
      snapshot_id: "p2",
      mid: { ...mid, snapshot_id: "p2" },
      pairs: [pair("binance", "s2", "11", 40, true)],
      removed: [pairIdentityKey(pair("mock", "s1", "20"))],
    });
    const state = after.BTC!;
    expect(state.pairs).toHaveLength(1);
    expect(state.pairs[0]!.venue).toBe("binance");
    expect(state.pairs[0]!.buy?.quote_stale).toBe(true);
    expect(state.pairs[0]!.buy?.age_sec).toBe(40);
    expect(state.packageSnapshotId).toBe("p2");
  });
});

describe("applyServerMessage", () => {
  it("ignores heartbeats for state", () => {
    const base = { BTC: emptyAssetState("BTC") };
    const { next, kind } = applyServerMessage(base, {
      type: "heartbeat",
      ts: 1,
    });
    expect(kind).toBe("heartbeat");
    expect(next).toEqual(base);
  });
});

describe("buildSubscribeMessage", () => {
  it("emits flat form for one filter", () => {
    expect(
      buildSubscribeMessage([
        { assets: ["btc"], notionals: [1000], venues: ["mock"] },
      ]),
    ).toEqual({
      type: "subscribe",
      assets: ["BTC"],
      notionals: ["1000"],
      venues: ["mock"],
      side: undefined,
      instrument_type: undefined,
      forms: undefined,
    });
  });

  it("emits filters form for multi-board pages", () => {
    const msg = buildSubscribeMessage([
      { assets: ["NVDA"], notionals: ["1000"] },
      {
        assets: ["TSLA"],
        notionals: ["1000"],
        forms: ["perp"],
      },
    ]);
    expect(msg).toMatchObject({
      type: "subscribe",
      filters: [
        { assets: ["NVDA"], notionals: ["1000"] },
        { assets: ["TSLA"], notionals: ["1000"], forms: ["perp"] },
      ],
    });
  });

  it("includes form in pair identity keys", () => {
    const a = pair("tessera_bsc", "s1", "10");
    a.form = "bstock";
    a.instrument_type = "prop_amm";
    const b = pair("tessera_bsc", "s1", "12");
    b.form = "ondo";
    b.instrument_type = "prop_amm";
    expect(pairIdentityKey(a)).toBe("tessera_bsc|1000|prop_amm|bstock");
    expect(pairIdentityKey(b)).toBe("tessera_bsc|1000|prop_amm|ondo");
    expect(pairIdentityKey(a)).not.toBe(pairIdentityKey(b));
  });
});

describe("reconnectDelayMs", () => {
  it("grows then caps", () => {
    expect(reconnectDelayMs(0, 1000, 5000)).toBe(1000);
    expect(reconnectDelayMs(1, 1000, 5000)).toBe(2000);
    expect(reconnectDelayMs(10, 1000, 5000)).toBe(5000);
  });
});
