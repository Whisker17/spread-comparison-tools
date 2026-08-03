import { describe, expect, it } from "vitest";

import {
  ApiError,
  type SimulateRowResponse,
  type VenueResponse,
} from "@/lib/api";
import {
  bestSimulateRow,
  buildVenueMetaMap,
  deltaVsBest,
  feeBreakdownLines,
  parseSimulateError,
  partitionSimulateRows,
} from "@/lib/simulateView";

function row(
  partial: Partial<SimulateRowResponse> &
    Pick<SimulateRowResponse, "venue" | "status">,
): SimulateRowResponse {
  return {
    instrument_type: "spot",
    expected_output: null,
    effective_price: null,
    spread_bps: null,
    fee_breakdown: {
      embedded_in_price: false,
      platform_fee_bps: "0",
      gas_unknown: false,
    },
    total_cost_bps: null,
    timestamp: "2026-08-03T12:00:00Z",
    best: false,
    error_code: null,
    error_message: null,
    mid_stale: false,
    venue_symbol: null,
    ...partial,
  };
}

describe("partitionSimulateRows", () => {
  it("keeps backend order for ranked rows and isolates not_supported", () => {
    const rows = [
      row({
        venue: "humidifi",
        status: "ok",
        expected_output: "150",
        best: true,
      }),
      row({ venue: "binance", status: "ok", expected_output: "149" }),
      row({ venue: "error_v", status: "error", error_code: "timeout" }),
      row({ venue: "apex", status: "not_supported" }),
      row({ venue: "lighter", status: "not_supported" }),
    ];
    const { ranked, notSupported } = partitionSimulateRows(rows);
    expect(ranked.map((r) => r.venue)).toEqual([
      "humidifi",
      "binance",
      "error_v",
    ]);
    // Error rows stay in the ranked list (in place), not dropped.
    expect(ranked.some((r) => r.status === "error")).toBe(true);
    expect(notSupported.map((r) => r.venue)).toEqual(["apex", "lighter"]);
  });
});

describe("bestSimulateRow / deltaVsBest", () => {
  it("uses the backend best flag only — never re-derives from output", () => {
    const rows = [
      // Higher output but not best (e.g. gas_unknown incomplete cost).
      row({
        venue: "gas_unknown_venue",
        status: "ok",
        expected_output: "200",
        best: false,
        total_cost_bps: null,
        fee_breakdown: {
          embedded_in_price: true,
          platform_fee_bps: "0",
          gas_unknown: true,
        },
      }),
      row({
        venue: "humidifi",
        status: "ok",
        expected_output: "150",
        best: true,
        total_cost_bps: "3.5",
      }),
    ];
    const best = bestSimulateRow(rows);
    expect(best?.venue).toBe("humidifi");
    expect(best?.expected_output).not.toBe("200");
  });

  it("computes absolute and bps delta vs the flagged best", () => {
    const best = row({
      venue: "best",
      status: "ok",
      expected_output: "100",
      best: true,
    });
    const other = row({
      venue: "other",
      status: "ok",
      expected_output: "99",
    });
    expect(deltaVsBest(best, best)).toEqual({ absolute: 0, bps: 0 });
    const d = deltaVsBest(other, best);
    expect(d.absolute).toBeCloseTo(1, 8);
    expect(d.bps).toBeCloseTo(100, 4); // 1/100 * 10_000
  });

  it("returns null deltas when output is missing", () => {
    const best = row({
      venue: "best",
      status: "ok",
      expected_output: "100",
      best: true,
    });
    const err = row({ venue: "err", status: "error" });
    expect(deltaVsBest(err, best)).toEqual({ absolute: null, bps: null });
  });
});

describe("parseSimulateError", () => {
  it("surfaces unknown_asset and cross_pair as distinct kinds", () => {
    const unknown = parseSimulateError(
      new ApiError("fail", 422, {
        detail: { message: "unknown asset: FOO", reason: "unknown_asset" },
      }),
    );
    expect(unknown.kind).toBe("unknown_asset");
    expect(unknown.message.toLowerCase()).toContain("unknown");

    const cross = parseSimulateError(
      new ApiError("fail", 422, {
        detail: {
          message: "cross pair: both non-stable",
          reason: "cross_pair",
        },
      }),
    );
    expect(cross.kind).toBe("cross_pair");
    expect(cross.message.toLowerCase()).toMatch(/cross|stable/);
  });

  it("maps 429 and 503 to dedicated messages", () => {
    expect(parseSimulateError(new ApiError("rl", 429, null)).kind).toBe(
      "rate_limit",
    );
    expect(parseSimulateError(new ApiError("mid", 503, null)).kind).toBe(
      "mid_unavailable",
    );
  });
});

describe("feeBreakdownLines", () => {
  it("marks embedded trading fee and unknown gas", () => {
    const lines = feeBreakdownLines(
      row({
        venue: "humidifi",
        status: "ok",
        spread_bps: "2.5",
        total_cost_bps: null,
        fee_breakdown: {
          embedded_in_price: true,
          trading_fee_bps: "0",
          platform_fee_bps: "0",
          gas_unknown: true,
          gas_bps: null,
        },
      }),
    );
    const trading = lines.find((l) => l.id === "trading");
    const gas = lines.find((l) => l.id === "gas");
    const total = lines.find((l) => l.id === "total");
    expect(trading?.note).toMatch(/embedded/i);
    expect(gas?.unknown).toBe(true);
    expect(total?.note).toMatch(/incomplete/i);
  });

  it("does not stringify pydantic 422 lists as [object Object]", () => {
    const err = parseSimulateError(
      new ApiError("POST /simulate failed: 422 [object Object]", 422, {
        detail: [{ loc: ["body", "amount"], msg: "value is not a valid decimal", type: "type_error.decimal" }],
      }),
    );
    expect(err.kind).toBe("validation");
    expect(err.message.toLowerCase()).toContain("decimal");
    expect(err.message).not.toMatch(/\[object Object\]/i);
  });

  it("maps non-mid 503s to generic instead of always mid_unavailable", () => {
    const err = parseSimulateError(
      new ApiError("fail", 503, { detail: "simulator not initialized" }),
    );
    expect(err.kind).toBe("generic");
    expect(err.message).toMatch(/simulator/i);
  });
});

describe("buildVenueMetaMap", () => {
  it("prefers VENUE_META display names and flags on-chain representation", () => {
    const venues: VenueResponse[] = [
      {
        slug: "humidifi",
        display_name: "API HumidiFi",
        venue_class: "prop_amm",
        chain: "solana",
        adapter_registered: true,
      },
      {
        slug: "binance",
        display_name: "API Binance",
        venue_class: "cex",
        chain: null,
        adapter_registered: true,
      },
    ];
    const map = buildVenueMetaMap(venues);
    expect(map.humidifi?.displayName).toBe("HumidiFi"); // static SSOT
    expect(map.humidifi?.chain).toBe("solana");
    expect(map.humidifi?.showRepresentation).toBe(true);
    expect(map.binance?.showRepresentation).toBe(false);
    expect(map.binance?.classLabel).toBe("CEX");
  });
});
