# ADR 0001: Solana prop AMM quotes stay on Jupiter only (explicit degradation)

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-08-04 |
| Issue | [WHI-837](https://linear.app/whisker-personal/issue/WHI-837) |
| Research | [WHI-837 research](../research/WHI-837-solana-prop-amm-quote-redundancy.md) |

## Context

HumidiFi, TesseraV, and BisonFi on Solana have no public quote API. Isolated quotes require an aggregator with a **per-DEX include filter**. Production today uses Jupiter Metis `dexes=<Label>` (WHI-797 / WHI-806). That is a single failure domain for the product's headline Solana prop AMM matrix.

WHI-837 surveyed alternative aggregators for a **redundant** path (different vendor) that is both **feasible** (Q1: all three venues + include filter) and **comparable** (Q2: effective-price divergence vs Jupiter in bps).

## Decision

1. **Do not implement a second Solana prop AMM quote adapter** for failover or dual-sourcing at this time.
2. **Treat Jupiter as the sole production quote path** for `humidifi` / `tessera_solana` / `bisonfi`.
3. **On Jupiter outage / hard failure:** mark those venues **unavailable** in the API/UI. Do **not** fill cells from a partial alternative (e.g. Titan DART BisonFi-only) or from realized trade prints.
4. **Track Metis v1 → Swap V2** as a same-vendor migration, not as redundancy (WHI-797 §3.1; WHI-837 samples show V2 still supports `dexes`).

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| **Titan DART** (`includeDexes`, keyless) | Live: **BisonFi only** among the baseline three; HumidiFi/TesseraV → no routes. Q2 on BisonFi is ~1 bps (usable alone) but **incomplete coverage** would bias the matrix. 1 rps free tier is too tight for matrix fan-out. |
| **Titan Gateway** | Has `dexes` in docs; **API token required** (401 unauth). Not verified for all three prop labels. |
| **DFlow** | Best *documented* Jupiter-like surface (`dexes` + prop AMMs), but live **403 empty** without a working keyless path; production keys are form-gated (days). |
| **OKX DEX** | `dexIds` include + docs name HumidiFi/BisonFi; **full auth suite required**; Tessera membership unproven without `get-liquidity`. |
| **0x Solana Swap** | Only **`disabled_sources`** (exclude) — cannot isolate one venue. |
| **1inch** | No Classic swap on Solana (Intent / cross-chain only). |
| **Jupiter Ultra / V2 as "backup"** | Same operator and outage domain. |
| **On-chain quote reconstruction** | Closed-source prop curves + private oracles — infeasible for `Quote` at request size. |
| **Swap-event realized prices as quote substitute** | Useful as health/staleness signal only; cannot satisfy WHI-799 notional `Quote`. |

## Consequences

- **Positive:** Matrix comparisons stay **single-aggregator**, so observed bps gaps remain venue-driven (within Jupiter's routing/fee semantics).
- **Positive:** Outages fail **honestly** instead of mixing incomparable numbers.
- **Negative:** Solana prop columns go dark if Jupiter is down or drops `dexes` / a venue.
- **Follow-up:** If DFlow or OKX keys later prove Q1 for all three **and** Q2 divergence stays ≲ ~2 bps, supersede this ADR with an adopt-redundancy decision and a separate implementation issue. Throughput remains WHI-836's concern, not this ADR's.

## References

- Research evidence and live samples: `docs/research/WHI-837-solana-prop-amm-quote-redundancy.md`, `docs/research/samples/whi-837/`
- Baseline Jupiter path: `docs/research/WHI-797-prop-amm-jupiter-quote-api.md`
