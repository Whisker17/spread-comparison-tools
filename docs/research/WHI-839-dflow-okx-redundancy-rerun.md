# WHI-839: DFlow + OKX Solana prop AMM redundancy re-run (Q1/Q2)

| Field | Value |
| --- | --- |
| Issue | [WHI-839](https://linear.app/whisker-personal/issue/WHI-839) |
| Parent research | [WHI-837](./WHI-837-solana-prop-amm-quote-redundancy.md) / [ADR 0001](../adr/0001-solana-prop-amm-jupiter-sole-path.md) |
| Related | WHI-799 §4.1 notional tiers; WHI-836 throughput (orthogonal) |
| Date | 2026-08-04 (UTC) |
| Environment | Jupiter (`JUPITER_API_KEY`); DFlow **dev** keyless `https://dev-quote-api.dflow.net`; OKX unauth negatives; DFlow production still 403 keyless |
| Samples | [`samples/whi-839/`](./samples/whi-839/) |

---

## 1. TL;DR

1. **DFlow Q1 (feasibility): PASS** for all three baseline prop venues (HumidiFi, Tessera V / product slug `tessera_solana`, BisonFi) via the **developer** Trade API host with `dexes=` include filtering. WHI-837 marked DFlow OUT because it only hit **production** `quote-api.dflow.net` (empty 403 without key) and missed the documented keyless dev base URL.
2. **DFlow Q2 (comparability): FAIL** the issue bar of ≲ ~2 bps drop-in. Across **9** successful same-pass paired cells on WHI-799 notionals, effective-price divergence vs Jupiter ranged **about −5.8 … +4.3 bps**. Sign is not stable; several cells exceed 2 bps absolute. One additional cell (BisonFi $100k, **+2.61 bps**) is a **retry-pair** only (first pass: Jupiter 200 / DFlow `route_not_found`) and is reported separately. Not safe as a silent dual-source for matrix bps comparisons.
3. **OKX Q1: still OUT (key).** Spec step 1 (“obtain OKX credentials”) was **not completed** in this environment — no portal keys were available. Unauth `get-liquidity` / `quote` → 401. **Acceptance criterion “live Q1 for OKX on all three venues” is unmet** (blocked), not PASS. Re-open when keys exist.
4. **DFlow credentials:** Spec step 1 also asked for a DFlow production `x-api-key`. This re-run used the documented **keyless dev** host instead (valid for research Q1/Q2; **not** the production surface an adapter would use — prod remains 403 without key). Partial against step 1; Q1 still live-proven on dev.
5. **Recommendation:** **Do not adopt DFlow (or OKX) as production matrix dual-source or silent failover.** Keep ADR 0001 (Jupiter sole path + honest unavailable on outage). **Amend** ADR 0001 with this evidence; **do not** open an adapter implementation issue.
6. **Ops note:** DFlow dev endpoint showed multi-minute **503** windows during capture; production remains key-gated.

---

## 2. What changed vs WHI-837

| Item | WHI-837 | WHI-839 |
| --- | --- | --- |
| DFlow host tested | `quote-api.dflow.net` only | + `dev-quote-api.dflow.net` (docs: keyless, rate-limited) |
| DFlow `/venues` | empty 403 | **200** venue list including all three props |
| DFlow isolation | untested | **200** single-leg for HumidiFi / Tessera V / BisonFi |
| DFlow Q2 | n/a | table below; fails ≲2 bps bar |
| OKX | 401 unauth | **reconfirmed** 401 unauth |
| Titan DART | partial (BisonFi only) | not re-run (unchanged) |

Docs (primary):

- Dev vs prod endpoints: https://pond.dflow.net/get-started/endpoints  
- API keys: https://pond.dflow.net/get-started/api-key  
- Quote `dexes` / `excludeDexes`: https://pond.dflow.net/resources/trading-api/imperative/quote  
- Auth header `x-api-key`: https://pond.dflow.net/resources/recipes/api-keys  

---

## 3. Q1 — Feasibility

### 3.1 DFlow

| Check | Result | Evidence |
| --- | --- | --- |
| Venue list includes baseline three | **Yes** — `HumidiFi`, `Tessera V`, `BisonFi` | `dflow-dev-venues.json` |
| Include filter works | **Yes** — `dexes=<label>` | Q1 JSON samples |
| Label exactness | **Strict** — `Tessera V` works; Jupiter-style `TesseraV` → 400 `invalid_dex` | `dflow-q1-tesserav_nospace-…` |
| Wrong label (invalid id) | 400 `invalid_dex` with enumerated valid values | `dflow-q1-notavenue-…` |
| No-route (valid label, no SOL/USDC route) | 400 `route_not_found` | `dflow-q1-noroute-bisonfi_predictions-…` (`dexes=BisonFi Predictions`) |
| Isolation proof (1 SOL → USDC, `onlyDirectRoutes=true`) | All three **HTTP 200**, `routePlan[].venue` single match | `dflow-q1-{humidifi,tessera_v,bisonfi}-…` |
| Production keyless | Still **403** empty body | `dflow-prod-venues-403.meta.txt` |

**Naming note:** DFlow’s venue string is `Tessera V` (space). Product venue slug remains `tessera_solana` (`spread_compare/venues.py`). Sample `research_key` `tesserav` is filename-stable only, not a product slug.

**Q1 verdict DFlow: PASS** (on **dev** host). Different operator from Jupiter — necessary for redundancy, not sufficient for matrix dual-sourcing (Q2).

### 3.2 OKX

| Check | Result | Evidence |
| --- | --- | --- |
| Credentials obtained | **No** (not in env / not provisioned for this run) | — |
| get-liquidity (Solana `chainIndex=501`) unauth | **401** | `okx-get-liquidity-unauth.json` |
| aggregator quote unauth | **401** | `okx-quote-unauth.json` |
| Live `dexIds` for HumidiFi / Tessera / BisonFi | **Not obtained** | blocked on credentials |

**Q1 verdict OKX: OUT (key) — AC not met.** Document surface from WHI-837 still stands; re-open after portal keys.

---

## 4. Q2 — Comparability (DFlow only)

### 4.1 Method

Same structure as WHI-837 §5, three venues × four WHI-799 §4.1 notionals:

1. Mid for size conversion only: Jupiter `dexes=HumidiFi` 1 SOL → USDC (`mid ≈ 73.37 USDC/SOL` this run). **Caveat (WHI-799 §4.2):** production uses reference mid; here mid only aligns `amount` so both legs share the same input size.
2. `amount = round(N / mid * 1e9)` lamports for `N ∈ {1000, 10_000, 100_000, 1_000_000}` USD.
3. Per cell: Jupiter then DFlow (`onlyDirectRoutes=true`, matching labels). **Intended** inter-leg sleep ~2 s; **observed** `gap_j_to_d_s` on first-pass cells is typically **~8–12 s** (one cell ~46 s) because DFlow transport/5xx retries elongated the wall clock (see summary JSON). Do **not** read “~2 s” as the measured separation.
4. Effective price `P = (out/1e6) / (amount/1e9)` (USDC per SOL).
5. `div_bps = (P_dflow - P_jup) / P_jup * 10_000`.

Controls:

- Jupiter twice, HumidiFi, N=$10k, **~2 s** sleep → **−0.90 bps**. This control is **not** matched to the 8–12 s first-pass cell gaps; it is only an indicative same-source floor at short separation.
- Reverse order (DFlow then Jupiter), BisonFi, N=$10k → **−0.65 bps** (also short intended sleep).

### 4.2 Results (2026-08-04)

Source: `samples/whi-839/q2-dflow-divergence.json`.

| venue (product slug) | N=$1k | N=$10k | N=$100k | N=$1M |
| --- | ---: | ---: | ---: | ---: |
| HumidiFi (`humidifi`) | **+4.28** | −0.79 | **−4.79** | *both sides 400 / no route* |
| Tessera (`tessera_solana`) | **+2.14** | +1.48 | **−2.18** | −1.51 |
| BisonFi (`bisonfi`) | **−5.76** | *no paired success*† | *retry only*‡ | −1.44 |

† BisonFi $10k: pass 1 = Jupiter **400** / DFlow 200; pass 2 = Jupiter 200 / DFlow **400** (`route_not_found`). No simultaneous success pair.  
‡ BisonFi $100k: first pass = Jupiter 200 / DFlow `route_not_found`; **retry pair** both 200 → **+2.61 bps** (retry gap not instrumented). Counted separately from same-pass successes.

- Same-pass successful cells: **9 / 12**.
- Range on same-pass successes: **min −5.76 / max +4.28 bps**.
- **Drop-in bar (≲ ~2 bps absolute): not met.**

### 4.3 Interpretation

- Short-interval same-source control is ~1 bps; several same-pass |div| values are **~4–6 bps**. That is suggestive of aggregator / path differences **beyond** a 2 s clock skew, but **not** a rigorous attribution against an 8–12 s mid move (control was not re-run at matched gaps). The FAIL decision does **not** require proving fee attribution — it only requires that observed divergence is **not reliably inside** the ≲2 bps product bar.
- DFlow does **not** present a stable small bias we can treat as a constant fee offset.
- Therefore DFlow cannot fill matrix cells interchangeably with Jupiter without redefining the comparison (aggregator-dependent quotes).

---

## 5. Recommendation

| Option | Decision |
| --- | --- |
| Adopt DFlow as silent dual-source / matrix failover | **No** (Q2 fails ≲2 bps) |
| Adopt OKX | **No** (credentials not obtained; Q1 incomplete) |
| Keep Jupiter sole path + explicit unavailable on outage | **Yes** (reaffirm ADR 0001) |
| Open adapter implementation issue now | **No** |
| Production DFlow key / OKX keys for a future re-run | Optional follow-up if product wants another attempt |

**One-line:** DFlow is the first **non-Jupiter** aggregator with live **full three-venue include isolation** on Solana prop AMMs, but effective prices are **not drop-in comparable** at the product’s few-bps resolution — so the correct product behavior remains honest degradation, not second-source fill.

---

## 6. ADR / doc updates in this PR

- Amend [ADR 0001](../adr/0001-solana-prop-amm-jupiter-sole-path.md) with WHI-839 evidence (Q1 pass on dev / Q2 fail; no supersede-to-adopt).
- Cross-link from WHI-837 §8 follow-up; one-line risk table touch on WHI-797.
- No DESIGN.md change (`DESIGN.md` still stub; ADR remains the decision record).

---

## 7. Risks / acceptance gaps

| Risk / gap | Note |
| --- | --- |
| Spec step 1 credentials | DFlow **prod** key and OKX keys **not** obtained; DFlow research used **dev** host |
| OKX AC | Unmet until keys exist |
| Dev endpoint reliability | Multi-minute 503 observed mid-session |
| Label mismatch | `Tessera V` vs Jupiter `TesseraV` footgun |
| Large-notional / intermittent routes | HumidiFi $1M both fail; BisonFi mid tiers intermittent |
| Q2 timing control mismatch | Control ~2 s; many cells ~8–12 s gaps |

---

## 8. Artifact checklist

| Path | Role |
| --- | --- |
| `docs/research/WHI-839-dflow-okx-redundancy-rerun.md` | This report |
| `docs/research/samples/whi-839/` | Live captures |
| `docs/adr/0001-solana-prop-amm-jupiter-sole-path.md` | Amended consequences / follow-up |
