# Deferred issues registry

A living log of issues that were **surfaced during review but consciously not fixed**
in the PR that found them. This is not a bug tracker for open work — it is the record of
*known, accepted debt*: things we decided to defer, so a future change touching the same
area starts from knowledge instead of rediscovery.

## How to use this file

- **Add an entry** whenever a review turns up a real issue that a PR deliberately leaves
  unfixed (scope, risk, or priority). Record it here in the same PR that defers it.
- **Reference it** before working on the affected area — check whether the thing you are
  about to "discover" is already logged, and whether a listed fix is now in scope.
- **Close an entry** by moving it to *Resolved* (bottom) with the PR/commit that fixed
  it, rather than deleting — the history is useful.
- Keep entries short. Link the originating tracker issue / PR and the code symbol so the
  entry stays findable as the code moves.

Severity is the reviewer's judgement at defer time: **High** (correctness/safety, fix
soon — anything touching a high-risk path defaults to at least High, though this project
defines none: `docs/GIT_WORKFLOW.md` § High-risk paths), **Medium**
(operational/perf, fix when convenient), **Low** (nit/consistency).

## Entry format

```markdown
- **<one-line description of the defect>** (<Severity>, <issue-id>).
  `<file>::<symbol>` — what's wrong, why it was deferred, and what the fix would be.
```

---

## Open

- **Frontend requires an absolute API origin (no same-origin relative base)** (Medium, WHI-857).
  `frontend/src/lib/apiBaseUrl.ts::resolveApiBaseUrl` only accepts absolute
  `http(s)` origins so production builds cannot bake loopback. Same-origin
  serving (empty/relative base, FE+API one host) would remove the class of bug
  entirely but needs client URL construction changes plus a deploy shape.
  Fix: support relative base when the product is served behind one host.

- **Sustained-429 alerts cover Jupiter / Kyber / RPC only** (Low, WHI-819).
  `upstream_events.RATE_LIMIT_SOURCES` matches the poller-fed sources the issue
  called out; CEX/perp REST resync 429s are not counted. Fix: record from
  `_cex_common` / `_perp_common` with a `cex`/`perp` source key if those
  backoffs return under the WS path.

- **Webhook e2e is MockTransport + documented host procedure** (Low, WHI-819).
  ADR 0003 § Verification records the real-receiver check as an operator step
  (`ALERT_WEBHOOK_URL` → Discord/webhook.site + journal). Offline suite cannot
  ship a live sink. Fix: optional `@pytest.mark.live` against a capture URL when
  CI secrets allow.

- **Stream hub still uses aggregator response cache for live packages** (Low, WHI-848).
  `QuoteStreamHub.publish_once` → `aggregator.collect(use_cache=True)`. WHI-847
  serves orderbooks from memory (zero REST when healthy), so cache hits are
  cheap; residual is only stale packaging when a stream is disconnected and REST
  fallback is cached. Fix: hub-side shorter TTL or `use_cache=False` with shared
  single-flight if sub-second push for REST-fallback paths is required.

- **Stream delta fingerprint excludes `age_sec` alone** (Low, WHI-848).
  `pair_fingerprint` drops `age_sec` so poller rows do not re-send every coalesce
  tick. `quote_stale` still pushes; FE shows age from `timestamp` /
  `StatusCell.ageFromTimestamp` when `age_sec` is not re-stamped. Acceptable
  mixed-age contract; revisit if product wants second-granularity age on every
  cell without other field changes.

- **Live blue-chips poll under five tiers not re-measured in a clean network** (Medium, WHI-838).
  Agent-env load runs hit SOCKS-proxy latency (Binance/mid timeouts) so the AC
  "no `error_code=timeout` rows" could not be validated live. Capacity prior:
  3 assets × 5 tiers × 3 Solana props × 2 sides ≈ 90 Jupiter acquires on a cold
  page; keyed bucket 10/s + `prop_amm` timeout raised to 12s in this PR. Re-run
  a clean-network blue-chips cycle after deploy and record wall-clock + timeout
  count in a follow-up comment if any residual timeouts remain.

- **Solana prop `gas_bps=0` remains best-eligible at $100 while EVM gas dominates**
  (Low, WHI-838). Documented in WHI-799 §6.6.1 / §8: base fee is still ≪ L1 gas,
  but priority fees can be tens of bps at $100. Convention kept so Solana props
  stay §5.2 eligible; EVM AMM carries the gas signal. Fix: account priority fee
  or mark `gas_unknown` at the retail tier when funding that work.

- **`AssetResponse.category` is plain `str` in OpenAPI — no category enum for FE** (Low, WHI-827).
  `spread_compare/api/quotes.py::AssetResponse.category` is `str`, so
  `pnpm gen:openapi` / `gen:api` cannot emit `tokenized_stock` /
  `equity_perp` / `other` as a typed union (WHI-827 AC partial). Domain
  values live in `assets.py::AssetCategory`. Fix: type the API field as
  `AssetCategory` (or a `Literal` re-export) in a small backend follow-up,
  then re-run WHI-827-style regenerate; section configs can then re-export
  the union from `frontend/src/config/sections/types.ts`.

- **Prop AMM asset surface beyond BTC/ETH/SOL has no mid path** (Medium, WHI-806).
  `spread_compare/adapters/prop_kyberswap.py` advertises Base AERO/VIRTUAL/EURC and
  BSC QQQB/SPCXB/NVDAB/NVDAON, but `assets.py` / `config/mid.yaml` only seed blue
  chips — so `/quotes` cannot resolve a reference mid for those pairs yet. Expand
  mid + catalog with WHI-810 (stocks) / a follow-up mid config ticket; adapters keep
  the mint/address map so live smoke can still probe QQQB once mid exists.

- **Jupiter header adaptation does not retune `window_sec` from `x-ratelimit-reset`**
  (Low, WHI-836). Capacity adapts from remaining+current; window stays config-fixed
  at the measured ~1s. If a plan's reset interval diverges, add reset-based window
  adaptation.

- **AdapterConfigError collapses to generic adapter_error in aggregator** (Low, WHI-806).
  `AdapterConfigError` subclasses `AdapterError`; the aggregator maps both to
  `error_code=adapter_error`. Config drift (40011 / dexes+exclude) is therefore
  hard to alert on separately. Promote a distinct error_code when the aggregator
  error taxonomy is next touched.

- **Prop pair lists are a static snapshot** (Low, WHI-806).
  `SOL_MINTS` / `BASE_TOKENS` / `BSC_TOKENS` — WHI-797 §7.4 warns pool sets drift;
  "no route is a normal business state". Phase 1 uses a researched initial map;
  dynamic discovery is out of scope for WHI-806.

- **Prop rate/slippage tunables partially still in source** (Low, WHI-806 / WHI-836).
  Jupiter window capacities moved to `config/jupiter.yaml` (WHI-836). Remaining:
  `prop_kyberswap.py` min interval, Jupiter `slippageBps=50`, retry counts. Same
  pattern as WHI-803; finish the migration once DESIGN.md §2 exists.

- **`GET /assets` lists blue chips only** (Low, WHI-807).
  `spread_compare/assets.py::list_assets` — WHI-798 stocks/equity catalogs are
  mid-routing seeds (`TOKENIZED_*`, `EQUITY_PERP_ASSETS`) but not returned by
  `/assets`. Expand with WHI-810.

- **Perp adapter rate/depth constants live in source, not `config/`** (Low, WHI-803).
  `spread_compare/adapters/_perp_common.py`, `perp_*.py` — min intervals and depth
  limits still cite WHI-800 until `docs/DESIGN.md` §2 exists. Taker bps moved to
  `config/fees/` in WHI-812; rate/depth still deferred.

- **Perp `venue_mark` / funding cached at startup, not per-quote** (Medium, WHI-803).
  HL/Lighter marks (and ApeX mark via blue-chip ticker warm-up) are populated in
  `startup()` only. Fine for short-lived smoke processes; a long-running collector
  (WHI-816) should refresh mark/funding on a timer or alongside each book fetch so
  `basis_bps` stays same-snapshot (WHI-799 §3.4).

- **Perp adapters do not apply lot/tick rounding** (Low, WHI-803).
  WHI-799 §8 mentions lot/tick for perp DEX; Phase 1 walks `q_star = N/mid` raw.
  Fix when fee/size config lands (WHI-812) or when a size-precision matrix is added.

- **ApeX `funding_rate_8h` left null on quote path** (Low, WHI-803 / WHI-812).
  `config/fees/apex.yaml` now records `funding_model: perp_continuous` (hourly on
  the hour, cited). Quote path still does not join the ticker funding field into
  `FeeBreakdown.funding_rate_8h` (would need hourly→8h normalization for the
  WHI-799 field name). Wire when funding display is needed.

- **Shared Quote assembly helper not extracted** (Low, WHI-801).
  `spread_compare/adapters/mock.py::_quote_shell` — mapping `ReferenceMid` + status
  into a §6.2-valid `Quote` is private to the mock. Real adapters (WHI-802…806) risk
  copy-paste drift. Promote a `build_quote(...)` (and optional mid/asset guard) into
  `adapters/base.py` with the first real adapter PR if duplication appears.

- **SizeQuotePair has no first-class TOB-error field** (Low, WHI-807).
  `spread_compare/aggregator.py::_collect_venue` — WHI-799 §6.3 says orderbook
  TOB fetch failure must not look like AMM `None`, but §6.4's `SizeQuotePair`
  has no `tob_error` channel. WHI-807 stamps `raw_ref=tob_error:…` on ok legs
  instead so spread bps stay authoritative. Promote a dedicated field if the FE
  needs structured handling.

- **`cex_tradfi_index` is best-effort via Binance premiumIndex only** (Low, WHI-807).
  `spread_compare/mids.py::_try_cex_tradfi_index` — WHI-799 §3.3 prefers a CEX
  TradFi index; we reuse USDT-M `premiumIndex` when the equity symbol is listed,
  else fall through to mark median. A dedicated TradFi feed (when productized)
  should replace this probe.


- **Default HTTP timeout hardcoded on BaseAdapter** (Low, WHI-823).
  `spread_compare/adapters/base.py::_DEFAULT_HTTP_TIMEOUT` — AGENTS.md requires
  non-secret tunables in `config/` traced to DESIGN.md §2, but neither the config
  loader nor DESIGN §2 exists yet. Subclasses can override via
  `super().__init__(timeout=…)`. Move to typed YAML when DESIGN §2 is written.

- **CEX rate-limit / depth tunables hardcoded** (Low, WHI-802).
  `spread_compare/adapters/cex_binance.py::_DEPTH_LIMITS` and
  `BinanceAdapter._min_interval_s`;
  `cex_bybit.py::_ORDERBOOK_LIMIT` and `BybitAdapter._min_interval_s`;
  `CexBaseAdapter._max_retries` / `_backoff_start_s` — fee placeholders moved to
  `config/fees/` (WHI-812); rate/depth still need DESIGN.md §2 + `config/cex.yaml`.

- **`funding_rate_8h` not fetched on CEX quote path** (Low, WHI-802).
  Spec allows null "when not cheaply available". Depth endpoints do not carry
  funding; piggybacking `premiumIndex` / Bybit tickers adds weight and latency
  per quote. Leave null for Phase 1; optional cheap join once the aggregator
  batches mid+funding (WHI-807) or WHI-812 fee work.

- **Adapter init state is process-global** (Low, WHI-823).
  `spread_compare/adapters/registry.py::_INITIALIZED` — `/health`'s
  `adapters_initialized` count is shared across all `create_app()` instances in a
  process. Fine for the single-process CLI/server; wrong if multi-app TestClient
  suites run concurrent lifespans. Stash on `app.state` if that ever lands. Also:
  if a slug is started then removed from `_REGISTRY` without `aclose_all`, the
  count can go stale — clear both sets together when unregister is added.

- **AMM fee-tier / tick-spacing probe lists are module constants** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::UNISWAP_FEE_TIERS` (and
  `PANCAKE_FEE_TIERS`, `AERO_TICK_SPACINGS`) — these drive which pools the quoter
  probes at runtime. WHI-812 put the display `lp_fee_tiers_bps` into
  `config/fees/`; probe lists remain source constants until DESIGN.md §2.

- **Native gas USD uses Binance spot bookTicker inside AMM helpers** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::fetch_binance_mid` — WHI-804 requires
  `gasEstimate × gasPrice × native USD` via Binance ETHUSDT/BNBUSDT; not the
  reference-mid path (WHI-807). Acceptable coupling for Phase 1; extract a shared
  CEX mid helper when WHI-802/807 land to avoid shotgun edits on URL/field renames.

- **AMM ExactOut / deep-size reverts map to `no_quote`, not `insufficient_liquidity`**
  (Medium, WHI-804).
  `spread_compare/adapters/_amm_common.py::probe_quoter_v2` — WHI-799 §4.2/§6.6
  distinguish thin depth from missing routes, but a QuoterV2 eth_call revert does
  not tell them apart without an extra small-size probe RPC. Left as `no_quote` for
  reverts; upgrade when a cheap pool-existence probe is worth the RTT.

- **AMM Quote builders not yet unified with mock `_quote_shell`** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::build_ok_quote` / `build_non_ok_quote` —
  same shape as mock's helper (WHI-801 deferred entry). Promote one shared builder
  when a third adapter family duplicates the pattern again.

---

## Resolved

- **`probe_min_healthy_books` is a process-level floor, not per-stream**
  (Low, WHI-819 → fixed in WHI-856). `probe_min_healthy_books_per_stream` plus
  `books_unsynced` / `subscribe_failed` assert per connected stream after
  `ws_books_sync_grace_sec`; process-wide floor retained as a secondary gate.

- **CEX / perp `PLACEHOLDER_TAKER_BPS` + empty `source_urls`** (Low, WHI-802/803 →
  fixed in WHI-812). Venue default_taker schedules live in `config/fees/*.yaml`,
  loaded by `spread_compare/fees.py`; adapters' `get_fees` and quote paths use
  config-backed taker bps. `TODO(WHI-812)` markers removed.

- **`mid_stale` is never computed by adapters** (Low, WHI-801 → fixed in WHI-807).
  Aggregator stamps `mid_stale` via `spread_compare.mids.is_mid_stale` /
  `apply_mid_stale` using `config/mid.yaml` `stale_threshold_sec` after each
  adapter quote is collected. Adapters may still leave the default `False`; the
  aggregator is the SSOT for the flag on the assembled package.

- **Shared Quote assembly helper not extracted** (Low, WHI-801 → WHI-802).
  CEX path extracted into `spread_compare/adapters/_cex_common.py`
  (`CexBaseAdapter`, `build_quote_from_book`). Mock still has its own shell;
  promote further only if AMM/perp adapters re-copy.

