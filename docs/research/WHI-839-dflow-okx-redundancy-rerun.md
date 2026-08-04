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

1. **DFlow Q1 (feasibility): PASS** for all three baseline prop venues (HumidiFi, TesseraV/Tessera V, BisonFi) via the **developer** Trade API host with `dexes=` include filtering. WHI-837 marked DFlow OUT because it only hit **production** `quote-api.dflow.net` (empty 403 without key) and missed the documented keyless dev base URL.
2. **DFlow Q2 (comparability): FAIL** the issue bar of ≲ ~2 bps drop-in. Across 10 successful paired cells on WHI-799 notionals, effective-price divergence vs Jupiter ranged **about −5.8 … +4.3 bps** (mean ≈ −0.6 bps). Sign is not stable; several cells exceed 2 bps absolute. Not safe as a silent dual-source for matrix bps comparisons.
3. **OKX Q1: still OUT (key).** Unauth `get-liquidity` / `quote` → 401 `OK-ACCESS-KEY can not be empty` (same class as WHI-837). No live isolation table without portal credentials.
4. **Recommendation:** **Do not adopt DFlow (or OKX) as production matrix dual-source or silent failover.** Keep ADR 0001 (Jupiter sole path + honest unavailable on outage). **Amend** ADR 0001 with this evidence; **do not** open an adapter implementation issue. Optional later work (separate issue, only if product wants it): explicit “secondary aggregator” failover UX with non-comparable labeling — out of scope here.
5. **Ops note:** DFlow dev endpoint showed multi-minute **503** windows during capture; production remains key-gated. Any future integration must target production + `x-api-key`, not dev.

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
- API keys: https://pond.dflow.net/get-started/api-key — developer endpoints work without a key; production needs form key (2–5 days).  
- Quote `dexes` / `excludeDexes`: https://pond.dflow.net/resources/trading-api/imperative/quote  
- Auth header `x-api-key`: https://pond.dflow.net/resources/recipes/api-keys  

---

## 3. Q1 — Feasibility

### 3.1 DFlow

| Check | Result | Evidence |
| --- | --- | --- |
| Venue list includes baseline three | **Yes** — `HumidiFi`, `Tessera V`, `BisonFi` | `dflow-dev-venues.json` |
| Include filter works | **Yes** — `dexes=<label>` | Q1 JSON samples |
| Label exactness | **Strict** — `Tessera V` works; Jupiter-style `TesseraV` → 400 `Invalid DEX` | `dflow-q1-tesserav_nospace-…` |
| Wrong label | 400 with enumerated valid values (distinct from empty route) | `dflow-q1-notavenue-…` |
| Isolation proof (1 SOL → USDC, `onlyDirectRoutes=true`) | All three **HTTP 200**, `routePlan[].venue` single match | `dflow-q1-{humidifi,tessera_v,bisonfi}-…` |
| Production keyless | Still **403** empty body | `dflow-prod-venues-403.meta.txt` |

**Q1 verdict DFlow: PASS** (on dev host). Same-vendor fault domain as Jupiter? **No** — different operator / API surface. That is necessary but not sufficient for matrix dual-sourcing (Q2).

### 3.2 OKX

| Check | Result | Evidence |
| --- | --- | --- |
| get-liquidity (Solana `chainIndex=501`) unauth | **401** | `okx-get-liquidity-unauth.json` |
| aggregator quote unauth | **401** | `okx-quote-unauth.json` |
| Live `dexIds` for HumidiFi / Tessera / BisonFi | **Not obtained** | blocked on credentials |

**Q1 verdict OKX: OUT (key).** Document surface from WHI-837 still stands (`dexIds` / `forJitoBundle` naming HumidiFi & BisonFi); Tessera still needs auth liquidity scan. Re-open only after portal keys exist.

---

## 4. Q2 — Comparability (DFlow only)

### 4.1 Method

Same structure as WHI-837 §5, three venues × four WHI-799 §4.1 notionals:

1. Mid for size conversion only: Jupiter `dexes=HumidiFi` 1 SOL → USDC (`mid ≈ 73.37 USDC/SOL` this run). **Caveat (WHI-799 §4.2):** production uses reference mid; here mid only aligns `amount` so both legs share the same input size. Divergence is relative effective price and does not depend on which mid chose the size.
2. `amount = round(N / mid * 1e9)` lamports for `N ∈ {1000, 10_000, 100_000, 1_000_000}` USD.
3. Per cell: Jupiter then DFlow (`onlyDirectRoutes=true`, matching labels). Nominal sleep ~2 s between legs; some cells had longer gaps when DFlow retried 5xx (see `gap_j_to_d_s` in summary JSON).
4. Effective price `P = (out/1e6) / (amount/1e9)` (USDC per SOL).
5. `div_bps = (P_dflow - P_jup) / P_jup * 10_000`.

Controls:

- Jupiter twice, HumidiFi, N=$10k → **−0.90 bps** (timing floor indicative).
- Reverse order (DFlow then Jupiter), BisonFi, N=$10k → **−0.65 bps**.

### 4.2 Results (2026-08-04)

Source: `samples/whi-839/q2-dflow-divergence.json`.

| venue | N=$1k | N=$10k | N=$100k | N=$1M |
| --- | ---: | ---: | ---: | ---: |
| HumidiFi | **+4.28** | −0.79 | **−4.79** | *no route both sides* |
| Tessera V / TesseraV | **+2.14** | +1.48 | **−2.18** | −1.51 |
| BisonFi | **−5.76** | *mixed failures* | **+2.61** | −1.44 |

- Successful cells: **10 / 12**. Failures: HumidiFi $1M both aggregators `route_not_found` / Jupiter 400; BisonFi $10k intermittent DFlow `route_not_found` (Jupiter 200 on retry path).
- Range on successes: **min −5.76 / max +4.28 bps**; mean ≈ **−0.6 bps**.
- **Drop-in bar (≲ ~2 bps absolute on the cells we care about): not met.** Multiple cells exceed 2 bps; sign flips by venue and size.

### 4.3 Interpretation

- Q2 noise floor from same-source control is ~1 bps; observed |div| up to ~5–6 bps is **larger than timing alone** on several cells, so aggregator / fee / inventory path differences are plausible — not pure clock skew.
- Unlike Titan DART’s ~1 bps one-sided BisonFi bias (WHI-837), DFlow does **not** present a stable small bias we can treat as a constant fee offset.
- Therefore DFlow cannot fill matrix cells interchangeably with Jupiter without **redefining the comparison** (aggregator-dependent quotes). That reopens the spoofed venue-spread risk WHI-837 / ADR 0001 rejected.

---

## 5. Recommendation

| Option | Decision |
| --- | --- |
| Adopt DFlow as silent dual-source / matrix failover | **No** (Q2 fails ≲2 bps) |
| Adopt OKX | **No** (still key-blocked; Q1 incomplete) |
| Keep Jupiter sole path + explicit unavailable on outage | **Yes** (reaffirm ADR 0001) |
| Open adapter implementation issue now | **No** |
| Production DFlow key for ops hardening (if product later wants secondary path) | Optional, non-blocking |
| Re-run OKX after portal keys | Separate follow-up if keys appear |

**One-line:** DFlow is the first **non-Jupiter** aggregator with live **full three-venue include isolation** on Solana prop AMMs, but effective prices are **not drop-in comparable** at the product’s few-bps resolution — so the correct product behavior remains honest degradation, not second-source fill.

---

## 6. ADR / doc updates in this PR

- Amend [ADR 0001](../adr/0001-solana-prop-amm-jupiter-sole-path.md) with WHI-839 evidence (Q1 pass / Q2 fail; no supersede-to-adopt).
- Cross-link from WHI-837 §8 follow-up.
- No DESIGN.md change (`DESIGN.md` still stub; ADR remains the decision record).

---

## 7. Risks

| Risk | Note |
| --- | --- |
| Dev endpoint reliability | Multi-minute 503 observed mid-session; not production-grade |
| Label mismatch | `Tessera V` vs Jupiter `TesseraV` is a footgun for any future adapter |
| Large-notional thin liquidity | $1M HumidiFi failed both sources; Q2 incomplete at top tier for that venue |
| OKX still unknown | Key may unlock Q1; do not assume Tessera coverage |

---

## 8. Artifact checklist

| Path | Role |
| --- | --- |
| `docs/research/WHI-839-dflow-okx-redundancy-rerun.md` | This report |
| `docs/research/samples/whi-839/` | Live captures |
| `docs/adr/0001-solana-prop-amm-jupiter-sole-path.md` | Amended consequences / follow-up |
