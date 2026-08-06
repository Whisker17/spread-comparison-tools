# WHI-890: Stock DEX / prop AMM coverage survey (BSC + Solana)

| Field | Value |
| --- | --- |
| Issue | [WHI-890](https://linear.app/whisker-personal/issue/WHI-890/m7-docs-survey-dex-prop-amm-coverage-per-stock-token-bsc-addresses) |
| Milestone | M7 stock underlying + form model |
| Blocks | [WHI-891](https://linear.app/whisker-personal/issue/WHI-891) (implementation fan-out widening) |
| Survey date | **2026-08-06** (UTC) |
| Method | Primary sources only: PancakeSwap extended tokenlist, DexScreener token-pairs, BSC `eth_call` (decimals/symbol/name), KyberSwap `includedSources=tessera`, Jupiter Quote `onlyDirectRoutes=true&dexes=` |
| Machine-readable matrix | [`samples/WHI-890-underlying-form-venue-matrix.tsv`](./samples/WHI-890-underlying-form-venue-matrix.tsv) |
| Raw samples | [`samples/whi-890-raw/`](./samples/whi-890-raw/) |

> **Scope:** Evidence for widening stock fan-out beyond the hardcoded 4 BSC tokens (`QQQB` / `SPCXB` / `NVDAB` / `NVDAON`).  
> **Not this ticket:** adapter / catalog / FE code (WHI-891); coverage-honesty UI; new venue adapters (WHI-805).  
> **Project rule:** mark `unverified` when not pinned — never invent addresses or silently drop forms.

---

## 1. TL;DR

1. **PancakeSwap v3 / USDT is the real expansion surface.** Seven *new* bStock tokens clear the WHI-883 §6.4 bar (TVL ≳ $10k) with verified addresses + decimals: **`SPYB`, `AAPLB`, `TSLAB`, `MSFTB`, `GOOGLB`, `METAB`, `AMZNB`** — plus the four already live.
2. **Tessera BSC does *not* expand.** Kyber `includedSources=tessera` stayed green only for the known quartet (`QQQB`, `SPCXB`, `NVDAB`, `NVDAON`). Every other catalogued bStock/Ondo address returned **`route not found`** at $100 / $1k / $10k both sides. **Do not** widen `BSC_STOCK_FORM_TICKER` for Tessera until a re-probe is green.
3. **Solana xStock × all three props = universal `NO_ROUTES_FOUND`.** That includes thick mints **`SPYx` / `QQQx`** and reconfirms **`AMZNx` / `NVDAx`**. Jupiter poller must **not** gain any stock underlying — budget math is moot for addition (see §6).
4. **NVDAB Tessera capacity is asymmetric:** buy routes at **$100 only** in this capture; sell works through **$10k**. Treat as live-with-size-cap, not as a reason to drop the venue.
5. **Phase order for WHI-891 is forced by evidence**, not preference: (A) Pancake address map for the 7 + keep 4, (B) Tessera whitelist unchanged, (C) Solana props stay out, (D) thin/ondo/zero-pool tokens stay catalog-only.

---

## 2. Catalog surface surveyed

All stock underlyings currently in `spread_compare/assets.py`:

`NVDA`, `TSLA`, `AAPL`, `MSFT`, `QQQ`, `SPCX`, `CRCL`, `GOOGL`, `AMD`, `PLTR`, `META`, `AMZN`, `SPY`, `MSTR`.

Forms per issue: **`bstock`**, **`ondo`**, **`xstock`** — even where the catalog form is still `coverage=unverified` or absent as a row today.

Venues in scope:

| Venue | Path |
| --- | --- |
| `pancakeswap_bsc` | On-chain Quoter / pool existence via DexScreener + tokenlist |
| `tessera_bsc` | KyberSwap Aggregator `includedSources=tessera` |
| `humidifi` / `tessera_solana` / `bisonfi` | Jupiter Quote `dexes=HumidiFi\|TesseraV\|BisonFi` |

Status vocabulary (aligned with WHI-883):

| status | Meaning |
| --- | --- |
| `live` | Probe confirmed route/pool usable for fan-out |
| `live_thin` | Exists but fails product bar (TVL ≪ $10k, non-USDT, or empty book) |
| `absent_no_route` | Address/mint known; route or pool explicitly missing |
| `unverified` | Expected form not pinned this round (no trustworthy address) |
| `n/a` | Form/venue combination does not apply (EVM vs Solana) |

---

## 3. BSC token capture

### 3.1 Provenance ladder

1. **Existing `BSC_TOKENS`** in `spread_compare/adapters/_prop_common.py` (already production-live).
2. **PancakeSwap extended tokenlist** — `https://tokens.pancakeswap.finance/pancakeswap-extended.json` (chainId 56). Source for `AMDB` / `PLTRB` / `MSTRB` / `MSFTB` / `METAB` / `GOOGLB` / `QQQB` / `SPYB`.
3. **DexScreener** pair search + `/token-pairs/v1/bsc/{address}` for TVL, 24h volume, fee labels.
4. **BSC public RPC `eth_call`**: `decimals()` / `symbol()` / `name()` for every retained address.
5. Rejected mis-hits recorded, not promoted: `SQQQon` (UltraPro Short QQQ Ondo) searched as QQQon; `Armstrong` / flapsh junk for MSTRon.

GeckoTerminal was used early (then rate-limited) for pool names / fee hints; DexScreener + Pancake list were primary for addresses.

### 3.2 Address + decimals table (transcribable into `BSC_TOKENS`)

All decimals measured **18** via `eth_call`. Listed symbol is on-chain `symbol()`.

| ticker | form | address | decimals | on-chain name | provenance |
| --- | --- | --- | --- | --- | --- |
| NVDAB | bstock | `0x02fca66c1d1afb4e2a7884261eb00f63598a7436` | 18 | NVIDIA Corp | `BSC_TOKENS` + DexScreener |
| NVDAON | ondo | `0xa9ee28c80f960b889dfbd1902055218cba016f75` | 18 | NVIDIA (Ondo Tokenized) | `BSC_TOKENS` + DexScreener |
| QQQB | bstock | `0x205812cdbed920aff76c6580abd681a46d11efc7` | 18 | Invesqo QQQ | `BSC_TOKENS` + Pancake list |
| SPCXB | bstock | `0xbe9d156892e55e7154bcd3cb0fea677f9d3103e1` | 18 | SpaceX | `BSC_TOKENS` + DexScreener |
| SPYB | bstock | `0x7138b48df7d98d7e3cc221bfe7192d0a178182d8` | 18 | SPY | Pancake extended |
| AAPLB | bstock | `0x431a3bee82e2ca41e49895cbece5bb0f76a89b7a` | 18 | Apple | DexScreener + on-chain |
| TSLAB | bstock | `0x5b1910eaad6450e50f816082aa078c41f10c292f` | 18 | Tesla, Inc. | DexScreener + on-chain |
| MSFTB | bstock | `0x80106cb3ead06659a5ad19df39d9b4733863b9b0` | 18 | Microsoft | Pancake extended |
| GOOGLB | bstock | `0x3f53de71c126bdabae20f9cd64848d317f6c3238` | 18 | Alphabet | Pancake extended |
| METAB | bstock | `0x7425889fe94f9d693e8daefe88bcced6acfef4c0` | 18 | Meta Platforms | Pancake extended |
| AMZNB | bstock | `0x1a4b499833a79a09ad7cf1d42d7dacf71e92eb00` | 18 | Amazon | DexScreener + on-chain |
| CRCLB | bstock | `0x80f3d493ebce97e343c53d29a137942416b4ffc0` | 18 | Circle Internet Group Inc. | DexScreener + on-chain |
| AMDB | bstock | `0x75fd4cf6f8392e41e70391d60c90c0d5211603a1` | 18 | Advanced Micro Devices Inc | Pancake extended only |
| PLTRB | bstock | `0x0ca5d51d0277bd006fd9607d3e560785ebad8222` | 18 | Palantir Technologies | Pancake extended only |
| MSTRB | bstock | `0xe87afb3076aeb0f9b14e368de8145ae6a2826a14` | 18 | Strategy Inc. | Pancake extended only |
| TSLAON | ondo | `0x2494b603319d4d9f9715c9f4496d9e0364b59d93` | 18 | Tesla (Ondo Tokenized) | DexScreener base + on-chain |
| AAPLON | ondo | `0x390a684ef9cade28a7ad0dfa61ab1eb3842618c4` | 18 | Apple (Ondo Tokenized) | DexScreener + on-chain |
| MSFTON | ondo | `0x6bfe75d1ad432050ea973c3a3dcd88f02e2444c3` | 18 | Microsoft (Ondo Tokenized) | DexScreener + on-chain |
| GOOGLON | ondo | `0x091fc7778e6932d4009b087b191d1ee3bac5729a` | 18 | Alphabet Class A (Ondo Tokenized) | DexScreener + on-chain |
| AMZNON | ondo | `0x4553cfe1c09f37f38b12dc509f676964e392f8fc` | 18 | Amazon (Ondo Tokenized) | DexScreener + on-chain |
| CRCLON | ondo | `0x992879cd8ce0c312d98648875b5a8d6d042cbf34` | 18 | Circle Internet Group (Ondo Tokenized) | DexScreener + on-chain |
| SPYON | ondo | `0x6a708ead771238919d85930b5a0f10454e1c331a` | 18 | SPDR S&P 500 ETF (Ondo Tokenized) | DexScreener + on-chain |
| SPCXON | ondo | `0xd0a58bc9d88d3ff48c0294cb7e45937d0e41a928` | 18 | SpaceX (Ondo Tokenized) | DexScreener + on-chain |

| QQQon | ondo | `0x0cde6936d305d5b34667fc46425e852efd73559a` | 18 | Invesco QQQ (Ondo Tokenized) | DexScreener exact + on-chain (USDC pool, thin) |

**Still `unverified` (no trustworthy BSC address this round):** `METAon`, `MSTRon`, `AMDon`, `PLTRon` — CoinGecko + DexScreener exact-symbol hunt in `missing_hunt.json` found no clean BSC hit. Earlier false positives (`SQQQon` inverse ETF; flapsh `Armstrong`) were rejected and **must not** appear as pool stats for those rows.

Address SSOT for implementation: [`samples/whi-890-raw/bsc_tokens.json`](./samples/whi-890-raw/bsc_tokens.json).  
Drop-in Python fragment: [`samples/whi-890-raw/bsc_tokens_transcription.py.txt`](./samples/whi-890-raw/bsc_tokens_transcription.py.txt).

---

## 4. PancakeSwap pool check (TVL bar)

Bar (WHI-883 §6.4 phase B, unvalidated product tunable): **TVL ≳ $10 000** on a **v3 + USDT** pool. Measured numbers below are DexScreener `liquidity.usd` / `volume.h24` at survey time — auditable in `bsc_tokens.json`.

Fee tiers below come from GeckoTerminal pool **names** (e.g. `NVDAB / USDT 0.25%`) when DexScreener JSON only exposed `labels: ["v3"]`. Recorded in `bsc_tokens.json` as `fee_tier` + `fee_tier_provenance`. WHI-891 should still treat fee tier as a quoter probe input (adapter already multi-tier probes), not as a single hard-coded tier.

### 4.1 Clears bar → `live` (fan-out candidates)

| ticker | TVL (USD) | 24h vol (USD) | fee (name) | pair (DexScreener) |
| --- | --- | --- | --- | --- |
| SPCXB | **4 197 265** | 20 289 494 | 0.25% | already live |
| QQQB | **2 404 454** | 128 654 761 | 0.25% | already live |
| NVDAB | **1 255 015** | 5 474 809 | 0.25% | already live |
| SPYB | **794 898** | 11 558 443 | **0.01%** | **new** |
| AAPLB | **308 675** | 788 523 | 0.25% | **new** |
| TSLAB | **218 943** | 427 768 | 0.25% | **new** |
| MSFTB | **110 612** | 41 146 | 0.25% | **new** |
| GOOGLB | **105 357** | 75 602 | 0.25% | **new** |
| METAB | **45 772** | 8 380 | 0.25% | **new** |
| AMZNB | **44 735** | 35 789 | 0.25% | **new** |
| NVDAON | **10 526** | 3 531 | 1% | already live (just above bar) |

### 4.2 Below bar / wrong quote → `live_thin` (catalog only)

| ticker | TVL | Note |
| --- | --- | --- |
| GOOGLON | 2 191 | v3/USDT thin |
| QQQon | 1 641 | v3/**USDC** (not USDT) thin — address verified |
| SPYON | 1 061 | v3/USDT thin |
| AMZNON | 5 898 | best pool WBNB, not USDT |
| CRCLON | 2 888 | non-USDT quote |
| TSLAON | 178 | non-USDT quote |
| SPCXON | 485 | non-USDT quote |
| AAPLON | 23 | v3/USDT dust |
| MSFTON | ~0 | listed pool, effectively empty book |
| CRCLB | ~0 | address OK; USDT pool empty at capture |

### 4.3 Address but zero pairs → `absent_no_route`

`AMDB`, `PLTRB`, `MSTRB` — present on Pancake **tokenlist**, on-chain symbol/name OK, DexScreener `/token-pairs/v1/bsc/{addr}` returned **0 pairs**. Binance spot `*BUSDT` can still exist without a usable AMM pool for our quoter path.

---

## 5. Tessera BSC (Kyber) route check

Probe: `GET https://aggregator-api.kyberswap.com/bsc/api/v1/routes` with `includedSources=tessera`, both sides.

- **All tokens with addresses:** WHI-799 §4.1 subset **$100 / $1 000 / $10 000** (survey breadth).
- **Green quartet only:** also **$100 000 / $1 000 000** (full §4.1 depth for production-sized Tessera).

Raw: `kyber_tessera_probes.json` (entries with `tier_extension: whi-890-r1` are the $100k/$1M pass).

### 5.1 Green set (unchanged membership; size matrix expanded)

| ticker | buy $100 | $1k | $10k | $100k | $1M | sell $100 | $1k | $10k | $100k | $1M | gas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QQQB | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | 693831 |
| SPCXB | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | 693831 |
| NVDAON | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | 693831 |
| NVDAB | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | 693831 |

Gas is stable on green routes (`gasUsd` ≈ $0.41). **No green route at $1M either side** in this capture.

**Size-cap notes for WHI-891:** Tessera depth is notional- and side-dependent. NVDAB buy is the most constrained (only $100). Do not assume the production $1k board measurement generalises across all sizes/days — re-measure if product cares about $100k cells.

### 5.2 Everything else → `absent_no_route`

Including thick Pancake names (`SPYB`, `AAPLB`, `TSLAB`, `GOOGLB`, …) and newly verified `QQQon`: Kyber returned **`route not found`** (code 4008) on all probed tiers/sides. That is the “per-token Kyber green” gate from WHI-883 §6.4 — **failed** for expansion.

---

## 6. Solana xStock prop probes

### 6.1 Mints (catalog underlyings)

From Jupiter tokens v2 (WHI-883) + live re-search for `SPCXx`:

| underlying | symbol | mint |
| --- | --- | --- |
| SPY | SPYx | `XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W` |
| QQQ | QQQx | `Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ` |
| NVDA | NVDAx | `Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh` |
| TSLA | TSLAx | `XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB` |
| AAPL | AAPLx | `XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp` |
| MSFT | MSFTx | `XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX` |
| CRCL | CRCLx | `XsueG8BtpquVJX9LVLLEGuViXUungE6WmK5YZ3p3bd1` |
| GOOGL | GOOGLx | `XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN` |
| META | METAx | `Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu` |
| AMZN | AMZNx | `Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg` |
| AMD | AMDx | `XsXcJ6GZ9kVnjqGsjBnktRcuwMBmvKWh8S93RefZ1rF` |
| PLTR | PLTRx | `XsoBhf2ufR8fTyNSjqfU71DYGaE6Z3SUGAidpzriAA4` |
| MSTR | MSTRx | `XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ` |
| SPCX | SPCXx | `Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8` |

Full map: `samples/whi-890-raw/xstock_mints.json`.

### 6.2 Jupiter prop matrix

Probe: `GET …/swap/v1/quote?onlyDirectRoutes=true&dexes=<HumidiFi|TesseraV|BisonFi>`  

| Side | amount | Notes |
| --- | --- | --- |
| Buy | `1_000_000_000` raw USDC | = **$1 000** (USDC 6 decimals) — exact |
| Sell | `5_000_000` raw mint | **assumes 6-decimal mint** (= 5 whole tokens). xStock mint decimals were **not** re-fetched this round; if a mint is 8-decimal this is 0.05 tokens. Verdict still holds: Jupiter returned `NO_ROUTES_FOUND` (errorCode) for a **direct** prop route, independent of size. Re-runs should resolve decimals via mint metadata first. |

Control: SOL → USDC × HumidiFi returned **200 + routePlan label HumidiFi** (path healthy).

**Result: 14 underlyings × 3 props × 2 sides = 84 probes → 84 × `NO_ROUTES_FOUND`.**

That explicitly includes:

- **`SPYx` / `QQQx`** (thick Jupiter liquidity in WHI-883 — still no *prop* direct route)
- **`AMZNx`** reconfirm all three props
- **`NVDAx`** all three props (WHI-883 only checked HumidiFi)

Raw: `samples/whi-890-raw/jup_prop_xstock_probes.json`.

Verdict for every catalogued `xstock` × prop cell: **`absent_no_route`** (not `unverified`).

### 6.3 Jupiter budget arithmetic (why we still write the number)

Current poller sizing (`config/poller.yaml` jupiter group + `config/jupiter.yaml`):

| Quantity | Value |
| --- | --- |
| Prop venues | 3 (`humidifi`, `tessera_solana`, `bisonfi`) |
| Assets sampled today | 3 (blue-chip crypto) |
| Tiers | 3 ($100 / $1k / $10k) |
| Sides | 2 |
| Calls / sweep | \(3 × 3 × 3 × 2 = 54\) |
| Keyed sustained RPS | 1.0 (`keyed_capacity=10`, `window_sec=10`) |
| `budget_share` | 0.6 → **0.6 RPS** effective |
| Sweep wall (start-spacing) | \(54 / 0.6 ≈ 90\) s |
| `interval_sec` | 120 s → **~30 s headroom** |

| If WHI-891 added… | Extra calls | Extra time @ 0.6 RPS | Fits 120 s? |
| --- | --- | --- | --- |
| +1 xStock underlying | +18 | +30 s | exact 120 s, **0 headroom** |
| +2 underlyings | +36 | +60 s | **no** (150 s) without offset |
| + all 14 stocks | +252 | +420 s | absurd on Free plan |

**This survey recommends adding zero xStock underlyings**, so **no budget offset is required**.

If a future re-probe ever goes green on even one mint, WHI-891 (or a follow-up) must pick **one named offset** before shipping:

| Offset | Effect |
| --- | --- |
| Raise `interval_sec` (e.g. 120 → 180 for +1 asset) | Staler prop quotes; raise `max_quote_age_for_best_sec` in lockstep |
| Drop a sample tier (e.g. drop $100 → 2 tiers) | −18 calls / asset-set of 3 venues; loses small-size signal |
| Raise `budget_share` (e.g. 0.6 → 0.8) | Steals RPS from `/simulate` |
| Paid Jupiter plan (higher sustained RPS) | Config-only; keep Free-plan math out of production assumptions |

Do **not** add stock load “and see” — the arithmetic saturates at +1 asset already.

---

## 7. Coverage matrix (summary)

Full TSV: [`samples/WHI-890-underlying-form-venue-matrix.tsv`](./samples/WHI-890-underlying-form-venue-matrix.tsv) (42 rows = 14 underlyings × 3 forms).  

**Cell discipline:** every cell is one of `live` / `live_thin` / `absent_no_route` / `unverified` / `n/a` (or a non-empty address / `unverified` / `n/a` for address columns). Cross-domain blanks (e.g. Solana mint on a Pancake column) are **`n/a`**, never empty. Rejected mis-hit TVL must never appear on `unverified` rows.

### 7.1 bstock × BSC venues

| underlying | ticker | Pancake | Tessera | TVL (USD) |
| --- | --- | --- | --- | --- |
| NVDA | NVDAB | live | live* | 1.26M |
| TSLA | TSLAB | live | absent_no_route | 219k |
| AAPL | AAPLB | live | absent_no_route | 309k |
| MSFT | MSFTB | live | absent_no_route | 111k |
| QQQ | QQQB | live | live | 2.40M |
| SPCX | SPCXB | live | live | 4.20M |
| CRCL | CRCLB | live_thin | absent_no_route | ~0 |
| GOOGL | GOOGLB | live | absent_no_route | 105k |
| AMD | AMDB | absent_no_route | absent_no_route | 0 pairs |
| PLTR | PLTRB | absent_no_route | absent_no_route | 0 pairs |
| META | METAB | live | absent_no_route | 46k |
| AMZN | AMZNB | live | absent_no_route | 45k |
| SPY | SPYB | live | absent_no_route | 795k |
| MSTR | MSTRB | absent_no_route | absent_no_route | 0 pairs |

\*NVDAB Tessera: buy green at $100 only in this capture (see §5.1).

### 7.2 ondo × BSC venues

| underlying | ticker | Pancake | Tessera | Note |
| --- | --- | --- | --- | --- |
| NVDA | NVDAON | live | live | only ondo already in production |
| QQQ | QQQon | live_thin (USDC) | absent_no_route | address verified; thin |
| others with address | *ON | live_thin or dust | absent_no_route | do not fan out |
| META / MSTR / AMD / PLTR | — | unverified | unverified | no trusted address (`missing_hunt.json`) |

### 7.3 xstock × Solana props

| underlying | humidifi | tessera_solana | bisonfi |
| --- | --- | --- | --- |
| **all 14** | absent_no_route | absent_no_route | absent_no_route |

---

## 8. Phase-ordered recommendation for WHI-891

Implement **in order**; do not skip ahead.

### Phase A — PancakeSwap bStock fan-out (zero Jupiter cost)

**Wire into `BSC_TOKENS` + `BSC_STOCK_FORM_TICKER` + `amm_pancakeswap` asset map** (and catalog form venue maps / coverage flags as needed):

| Priority | ticker | underlying | Why |
| --- | --- | --- | --- |
| A1 | SPYB | SPY | Thickest new pool (~$795k TVL, ~$11.6M 24h) |
| A2 | AAPLB | AAPL | ~$309k TVL |
| A3 | TSLAB | TSLA | ~$219k TVL; form already catalogued unverified |
| A4 | MSFTB | MSFT | ~$111k TVL |
| A5 | GOOGLB | GOOGL | ~$105k TVL |
| A6 | METAB | META | ~$46k TVL |
| A7 | AMZNB | AMZN | ~$45k TVL |

Keep existing: NVDAB, QQQB, SPCXB, NVDAON.

**RPC / poller cost (computed, not deferred):**

| Quantity | Today (order of mag.) | After +7 Phase A tokens |
| --- | --- | --- |
| `rpc` group pacing | `max_rps: 5`, `interval_sec: 30` (`config/poller.yaml`) | same |
| Comment in poller | “Full matrix ≈100 calls → ~20 s start-spacing” | — |
| Marginal cost model | per extra token ≈ full §4.1 × both sides through quoter path | **+7 × ~10 ≈ +70 calls** if linear in tokens |
| Start-spacing @ 5 RPS | 100/5 ≈ 20 s | 170/5 ≈ **34 s** |
| vs `interval_sec` 30 | 1.5× headroom | **~0.88× — expected in-flight skip / overlap** |

**Named offset before shipping all 7 (pick one):**

1. **Ship A1–A3 only first** (SPYB, AAPLB, TSLAB) → +~30 calls → ~26 s start-spacing (still fits 30 s with thin headroom), then a follow-up for A4–A7 after measuring production skip counts; or  
2. Raise `rpc.interval_sec` 30 → **45** (and `max_quote_age_for_best_sec` / `max_stale_sec` in proportion); or  
3. Sample fewer notionals on AMM the way Jupiter already does (3 tiers not 5) — product trade-off.

Do not land all seven without one of the above.

**Not in Phase A:** CRCLB (empty pool), AMDB/PLTRB/MSTRB (zero pairs), all thin ondo except keep NVDAON.

### Phase B — Tessera BSC (no expansion)

- **Do not** add SPYB / AAPLB / … to Tessera maps.
- Keep Kyber whitelist = `{QQQB, SPCXB, NVDAB, NVDAON}`.
- Optional hardening: document NVDAB buy size cap; consider surfacing `not_supported` / degraded quote above Tessera depth rather than hard error if product wants it (out of scope for pure address expansion).

### Phase C — Solana props (explicit non-goal until re-probe)

- **Add zero** xStock mints to Jupiter poller assets.
- Leave `xstock` form `coverage=unverified` or add a more honest `absent_no_route`-style catalog note if a later honesty ticket lands — **do not** delete the form.
- Budget impact of following this recommendation: **+0 calls**, **+0 s**, no `interval_sec` / `budget_share` / plan change.

### Phase D — Deferred / catalog-only

| Item | Action |
| --- | --- |
| Ondo tokens other than NVDAON | Keep addresses in research artifact; do not fan out until **USDT** v3 TVL ≥ $10k **and** (if Tessera desired) Kyber green. QQQon is verified but USDC/thin |
| AMDB / PLTRB / MSTRB | Address known; re-check pairs later; no quoter wire |
| METAon / MSTRon / AMDon / PLTRon | Remain `unverified` (`missing_hunt.json`) |
| Solana xStock props | Re-probe (with mint decimals) before any poller discussion; if green, apply §6.3 offset table |

---

## 9. Acceptance checklist (issue)

| Criterion | Status |
| --- | --- |
| Every catalogued stock × {bstock, ondo, xstock} has per-venue verdict with evidence | ✅ TSV + raw samples |
| BSC address + decimals for every token that has a pool, `BSC_TOKENS`-ready | ✅ §3.2 + transcription file |
| SPYx / QQQx × three Solana props, both sides | ✅ all `NO_ROUTES_FOUND` |
| Jupiter budget impact as a number + named offset for any addition | ✅ §6.3 — **addition = 0**; offsets named if future green |
| Phase-ordered recommendation for follow-up | ✅ §8 |

---

## 10. References

- Issue WHI-890; prior survey [WHI-883](./WHI-883-high-volume-stock-underlying-survey.md) §4.4 / §5.2 / §6.4
- Form vocabulary [WHI-798](./WHI-798-asset-category-inventory.md) §4.6
- Code: `spread_compare/adapters/_prop_common.py` (`BSC_TOKENS`, `BSC_STOCK_FORM_TICKER`), `amm_pancakeswap.py`, `prop_kyberswap.py`, `prop_jupiter.py`
- Config: `config/poller.yaml` (jupiter group), `config/jupiter.yaml` (keyed 1 RPS)
- Deferred notes: `docs/DEFERRED_ISSUES.md` (WHI-884 entries — addresses were the gap this ticket fills)
