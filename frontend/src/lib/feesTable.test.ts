import { describe, expect, it } from "vitest";

import type { FeeSchedule, VenueResponse } from "@/lib/api";
import { buildFeeTableGroups, fundingModelLabel } from "@/lib/feesTable";

const venues: VenueResponse[] = [
  {
    slug: "binance",
    display_name: "Binance",
    venue_class: "cex",
    adapter_registered: true,
  },
  {
    slug: "humidifi",
    display_name: "HumidiFi",
    venue_class: "prop_amm",
    adapter_registered: true,
  },
  {
    slug: "uniswap_eth",
    display_name: "Uniswap (Ethereum)",
    venue_class: "amm_dex",
    adapter_registered: true,
  },
];

function schedule(
  partial: Partial<FeeSchedule> &
    Pick<FeeSchedule, "venue" | "instrument_type">,
): FeeSchedule {
  return {
    default_tier: "default_taker",
    funding_model: "none",
    fee_embedded_in_quote: false,
    source_urls: ["https://example.com/fees"],
    updated_at: "2026-08-03T00:00:00Z",
    ...partial,
  };
}

describe("buildFeeTableGroups", () => {
  it("groups by venue class in CEX → perp → AMM → prop order", () => {
    const schedules = [
      schedule({
        venue: "humidifi",
        instrument_type: "prop_amm",
        fee_embedded_in_quote: true,
      }),
      schedule({
        venue: "binance",
        instrument_type: "perp",
        maker_bps: "2",
        taker_bps: "5",
        funding_model: "perp_8h",
      }),
      schedule({
        venue: "binance",
        instrument_type: "spot",
        maker_bps: "10",
        taker_bps: "10",
      }),
      schedule({
        venue: "uniswap_eth",
        instrument_type: "amm_pool",
        fee_embedded_in_quote: true,
        lp_fee_tiers_bps: ["5", "30"],
        gas_estimate_usd: "8",
      }),
    ];

    const groups = buildFeeTableGroups(schedules, venues);
    expect(groups.map((g) => g.venueClass)).toEqual([
      "cex",
      "amm_dex",
      "prop_amm",
    ]);
    expect(groups[0]?.rows.map((r) => r.instrumentType)).toEqual([
      "spot",
      "perp",
    ]);
    expect(groups[0]?.rows[0]?.displayName).toBe("Binance");
    expect(groups[0]?.rows[0]?.sourceUrls).toEqual([
      "https://example.com/fees",
    ]);
    expect(groups[0]?.rows[0]?.updatedAt).toBe("2026-08-03T00:00:00Z");
    expect(groups[1]?.rows[0]?.lpFeeTiersBps).toEqual(["5", "30"]);
    expect(groups[2]?.rows[0]?.feeEmbeddedInQuote).toBe(true);
  });

  it("keeps unknown venues in an Other group", () => {
    const groups = buildFeeTableGroups(
      [
        schedule({
          venue: "future_venue",
          instrument_type: "spot",
          maker_bps: "1",
          taker_bps: "2",
        }),
      ],
      venues,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0]?.venueClass).toBe("unknown");
    expect(groups[0]?.rows[0]?.displayName).toBe("future_venue");
  });
});

describe("fundingModelLabel", () => {
  it("maps known models", () => {
    expect(fundingModelLabel("none")).toBe("—");
    expect(fundingModelLabel("perp_8h")).toBe("8h funding");
    expect(fundingModelLabel("perp_continuous")).toBe("continuous funding");
  });
});
