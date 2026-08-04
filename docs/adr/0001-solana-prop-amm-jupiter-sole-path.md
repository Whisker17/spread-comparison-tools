# ADR 0001: Solana prop AMM quotes stay on Jupiter only (explicit degradation)

| Field | Value |
| --- | --- |
| Status | Accepted (amended 2026-08-04 by WHI-839 — **not** superseded) |
| Date | 2026-08-04 |
| Issue | [WHI-837](https://linear.app/whisker-personal/issue/WHI-837); follow-up [WHI-839](https://linear.app/whisker-personal/issue/WHI-839) |
| Research | [WHI-837 research](../research/WHI-837-solana-prop-amm-quote-redundancy.md); [WHI-839 re-run](../research/WHI-839-dflow-okx-redundancy-rerun.md) |

> **Note:** `docs/agents/domain.md` places ADRs after v1 for decisions that do not belong in the PRD. `docs/DESIGN.md` is still the empty stub, so this decision is recorded here. **When DESIGN.md §7 (rejected alternatives / open risks) is written, fold this ADR into that section and mark this file Superseded-by-PRD.**

## Context

HumidiFi, TesseraV, and BisonFi on Solana have no public quote API. Isolated quotes require an aggregator with a **per-DEX include filter**. Production today uses Jupiter Metis `dexes=<Label>` (WHI-797 / WHI-806). That is a single failure domain for the product's headline Solana prop AMM matrix.

WHI-837 surveyed alternative aggregators for a **redundant** path (different vendor) that is both **feasible** (Q1: all three venues + include filter) and **comparable** (Q2: effective-price divergence vs Jupiter in bps). Full candidate cards and evidence: research doc §3–§5.

## Decision

1. **Do not implement a second Solana prop AMM quote adapter** for failover or dual-sourcing at this time.
2. **Treat Jupiter as the sole production quote path** for `humidifi` / `tessera_solana` / `bisonfi`.
3. **On Jupiter outage / hard failure:** mark those venues **unavailable** in the API/UI. Do **not** fill cells from a partial alternative (e.g. Titan DART BisonFi-only) or from realized trade prints.
4. **Track Metis v1 → Swap V2** as a same-vendor migration, not as redundancy (WHI-797 §3.1; WHI-837 samples show V2 still supports `dexes`).

## Alternatives considered

Evidence and per-candidate Q1 reasons live in **[WHI-837 research §3](../research/WHI-837-solana-prop-amm-quote-redundancy.md#3-候选总表q1-裁决)** (single SSOT — do not duplicate long tables here).

Summary (WHI-837 baseline): Titan DART is the only live partial hit (**BisonFi only** among baseline three; ~1 bps Q2); DFlow/OKX/Titan Gateway were document-strong but access-blocked in that run; 0x is exclude-only; 1inch has no Classic Solana swap; Jupiter V2/Ultra share Jupiter's outage domain; on-chain quote reconstruction and swap-event prints are not `Quote` substitutes.

### Amendment — WHI-839 (2026-08-04)

**Verdict (SSOT in research, not restated as a long table here):** DFlow **Q1 PASS** on keyless **dev** Trade API for HumidiFi / `Tessera V` / BisonFi; **Q2 FAIL** the ≲ ~2 bps drop-in bar (same-pass cells about −5.8…+4.3 bps). OKX still **OUT (key)** — credentials not obtained this run. Production DFlow still **403** without `x-api-key`. Full tables/samples: [WHI-839 research](../research/WHI-839-dflow-okx-redundancy-rerun.md), `docs/research/samples/whi-839/`.

**Adopt-redundancy bar from the original follow-up (Q1 all three ∧ Q2 ≲ ~2 bps) is not met.** No implementation issue filed.

## Consequences

- **Positive:** Matrix comparisons stay **single-aggregator**, so observed bps gaps remain venue-driven (within Jupiter's routing/fee semantics).
- **Positive:** Outages fail **honestly** instead of mixing incomparable numbers.
- **Negative:** Solana prop columns go dark if Jupiter is down or drops `dexes` / a venue.
- **Updated knowledge (WHI-839):** A non-Jupiter aggregator (**DFlow**) can now **live-isolate all three** prop venues, so the previous “no full second source exists” statement is obsolete — but **comparability still fails**, so product behavior (sole Jupiter + explicit unavailable) is unchanged.
- **Not in scope of this ADR:** optional future “explicit secondary aggregator” failover UX (must label non-comparable quotes). Requires a new product decision + implementation issue if desired. Throughput remains WHI-836's concern.

## References

- Research evidence and live samples: `docs/research/WHI-837-solana-prop-amm-quote-redundancy.md`, `docs/research/samples/whi-837/`
- WHI-839 re-run: `docs/research/WHI-839-dflow-okx-redundancy-rerun.md`, `docs/research/samples/whi-839/`
- Baseline Jupiter path: `docs/research/WHI-797-prop-amm-jupiter-quote-api.md`
