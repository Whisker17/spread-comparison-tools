import { describe, expect, it } from "vitest";

import {
  formClassOf,
  makeRowKey,
  pairIdentityKey,
  pairRowKey,
  pairsHaveForms,
  parseRowKey,
} from "@/lib/pairIdentity";

describe("pairIdentity (WHI-882)", () => {
  it("maps form ids to form_class", () => {
    expect(formClassOf("perp")).toBe("perp");
    expect(formClassOf("bstock")).toBe("tokenized");
    expect(formClassOf("ondo")).toBe("tokenized");
    expect(formClassOf("xstock")).toBe("tokenized");
    expect(formClassOf("xstock_cex")).toBe("tokenized");
    expect(formClassOf(null)).toBeNull();
    expect(formClassOf("unknown")).toBeNull();
  });

  it("row keys include form only when set", () => {
    expect(pairRowKey({ venue: "binance" })).toBe("binance");
    expect(pairRowKey({ venue: "binance", form: null })).toBe("binance");
    expect(pairRowKey({ venue: "tessera_bsc", form: "ondo" })).toBe(
      "tessera_bsc|ondo",
    );
    expect(makeRowKey("binance", "perp")).toBe("binance|perp");
    expect(parseRowKey("tessera_bsc|bstock")).toEqual({
      venue: "tessera_bsc",
      form: "bstock",
    });
    expect(parseRowKey("binance")).toEqual({ venue: "binance", form: null });
  });

  it("stream identity matches backend venue|notional|instrument|form", () => {
    expect(
      pairIdentityKey({
        venue: "tessera_bsc",
        notional_usd: "1000",
        instrument_type: "prop_amm",
        form: "ondo",
      }),
    ).toBe("tessera_bsc|1000|prop_amm|ondo");
    expect(
      pairIdentityKey({
        venue: "binance",
        notional_usd: "1000",
        instrument_type: "spot",
      }),
    ).toBe("binance|1000|spot|-");
  });

  it("detects form-aware pair sets", () => {
    expect(pairsHaveForms([{ form: null }])).toBe(false);
    expect(
      pairsHaveForms([{ form: null }, { form: "bstock" }]),
    ).toBe(true);
  });
});
