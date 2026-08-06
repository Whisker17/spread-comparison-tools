# AGENTS.md

This file provides guidance to coding agents (Claude Code, Codex, etc.) working in this
repository. `CLAUDE.md` is a symlink to this file — edit here only.

## What this is

Tools and research for comparing execution quality / spreads across venues (CEX, public
DEX, prop AMM) on Solana, Base and BSC.

The full PRD — requirements, architecture, milestones, rejected alternatives, open
risks — lives in `docs/DESIGN.md`. Read it before making any design or architectural
decision; do not re-derive parameters or decisions that are already validated there.
**Caveat: `docs/DESIGN.md` is still the empty template stub** (see §Status) — until it is
written, the M1 research docs under `docs/research/` are the de-facto spec of record.

## Status

<!-- Keep this section current: what has landed, what is architected-for but NOT
implemented yet. Update it the moment reality changes instead of leaving stale
placeholders. Agents must not assume a module exists until its issue lands. -->

**Landed:** template bootstrap is complete (WHI-820 — placeholders filled, test/lint gate
green, GitHub merge policy aligned). M1 research is done and merged under
`docs/research/`: prop AMM quote paths (WHI-797), asset inventory (WHI-798), spread &
fee data model (WHI-799), venue API survey (WHI-800). Solana prop AMM quote redundancy
/ Jupiter SPOF: WHI-837 + ADR 0001; WHI-839 re-ran DFlow/OKX (DFlow Q1 pass on
dev host, Q2 fails the ≲2 bps bar — ADR amended, not superseded). M2 backend scaffold
(WHI-801): `spread_compare` package with models, bookwalk, costs, adapter protocol +
registry, mock adapter, and FastAPI `GET /health`. M2 async adapter protocol (WHI-823):
async `VenueAdapter` + lifecycle hooks, `BaseAdapter` shared `httpx.AsyncClient`, registry
`startup_all`/`aclose_all`, adapter auto-discovery, app lifespan, and `--live` test marker.
M2 CEX adapters (WHI-802): `binance` + `bybit` (spot + perp via `instrument_type`), shared
`cex_symbols` map, fixture + `@pytest.mark.live` smoke tests; discovery test uses
`_test_discovery` slug (not a production venue). M2 perp DEX adapters (WHI-803):
`hyperliquid`, `lighter`, `apex` — orderbook walk → `Quote`/`TopOfBook`, HL 20-level
cap, Lighter per-order aggregation + 60 req/min throttle, ApeX `crossSymbolName`
resolution. M2 AMM DEX adapters (WHI-804): `uniswap_eth`, `aerodrome_base`,
`pancakeswap_bsc` via on-chain Quoter `eth_call` (raw JSON-RPC + eth-abi; no web3);
RPC env `ETH_RPC_URL` / `BASE_RPC_URL` / `BSC_RPC_URL`. M2 prop AMM adapters (WHI-806):
Jupiter `dexes=` for `humidifi` / `tessera_solana` / `bisonfi` (label validation +
keyless ≥2s limiter); KyberSwap `includedSources=tessera` for `tessera_base` /
`tessera_bsc` (gas from route response). M2 aggregation API (WHI-807):
reference-mid service (`mids.py` + `config/mid.yaml`), `QuoteAggregator` fan-out with
per-venue timeout/degradation, short-TTL response cache, `GET /quotes` / `GET /venues`
/ `GET /assets`. M3 frontend scaffold (WHI-808): `frontend/` Next.js App Router +
Tailwind + typed OpenAPI client (`openapi-typescript`), `SpreadMatrix` /
`TopOfBookRow` / status render SSOT / summary best-venue engine, six routes +
`/status-fixtures`, TanStack Query polling; backend CORS for localhost:3000.
M3 blue chips section (WHI-809): `/blue-chips` BTC/ETH/SOL live matrices +
representation labels + snapshot summary (WHI-799 §5.2) + 30s poll; SOL hides
EVM AMM rows. M3 stocks section (WHI-810, rebuilt WHI-882): `/stocks` underlying-first —
one matrix per underlying (NVDA/TSLA/AAPL/MSFT/QQQ/SPCX) with venue × form
rows (perp / bStocks / Ondo …), form badges, form_class §5.2 best, shared mid;
US market-hours badge, mid-source emphasis, bStocks rebase footnote.
M3 others section (WHI-811): `/others` P0 (DOGE/WIF/XRP/SUI/LINK/AVAX/ADA/BNB)
+ P1 scaled memes (PEPE/BONK with `venue_symbol` 1× note) + P2 collapsed
watchlist (JUP/AERO/VIRTUAL/EURC); CEX+perp only (no prop AMM requests).
M4 fee schedules (WHI-812): `config/fees/*.yaml` + `fees.py` loader, adapters'
`get_fees` config-backed, `GET /fees`. M3 asset catalog expansion (WHI-826): Phase 1
stocks / equity perps / others in `assets.py`; instrument-aware `cex_symbols.CexSymbol`
+ contract multipliers; HL HIP-3 `xyz:` meta + `kPEPE`/`kBONK` scaling; PancakeSwap BSC
bStocks tokens; `perp_symbols` shared maps. M4 fees page (WHI-813): `/fees` fee-structure
table + live cost-composition stacked bars (`costComposition` / `feesTable` pure lib +
fixture tests). M5 simulate API (WHI-814): `POST /simulate` pair+amount fan-out
(`TradeSimulator` + `api/simulate.py`), USD-stable pair scope, free-form notional,
expected-output ranking with WHI-799 §5.2 `best` eligibility, per-client rate guard,
`not_supported` rows listed not omitted. M5 simulate pair discovery (WHI-833):
`TRADEABLE_USD_STABLES` (USDC/USDT, no USD) + `GET /simulate/pairs`
`{stables, assets}` for WHI-815 pair selectors; peg set `USD_STABLES` unchanged.
M5 simulate UI (WHI-815): `/simulate` aggregator-style pair+amount form from
`GET /simulate/pairs` (no hardcoded stables), debounced `POST /simulate`, ranked
rows with backend `best` highlight + delta-vs-best, expandable fee breakdowns,
skeleton loading, collapsed `not_supported` section, structured 422 inline errors;
OpenAPI client regenerated for simulate paths.
Core timeout fix (WHI-836): shared `ratelimit.py` token bucket, config-driven
Jupiter budget + header adaptation, concurrent AMM fee-tier probes, per-class
venue timeouts, response-cache TTL. Aggregator load hygiene (WHI-844):
`rate_limited` status + fail-fast when limiter/429 wait exceeds remaining
budget, response-cache single-flight + TTL 35s (above FE 30s poll); pre-existing
Jupiter/CEX rate-limit header logging at info retained.
Core startup resilience (WHI-840): `startup_all` degrades transient
`AdapterFetchError`/`AdapterTimeoutError` (keeps serving), fails fast on config
errors; `config/venues.yaml` disable list + background retry; `/health`
`degraded`/`unavailable_venues`; `not_initialized` quote rows for failed venues.
Frontend size selector (WHI-841): section pages show one notional at a time via
shared `SizeSelector` + `?size=` URL; one `GET /quotes` per asset (not × tiers)
to cut request fan-out 5× and clear TIMEOUT cells.
Orderbook multi-tier (WHI-843): `GET /quotes?notionals=` returns all tiers under
one `snapshot_id`/mid; CEX/perp adapters batch-walk one book fetch; short-TTL
depth-keyed orderbook cache; FE multi-column matrix restored with size selector
as view preference (`all` vs single-size focus).
Core RPC hardening (WHI-842): Multicall3-batched AMM quoter probes, per-endpoint
`TokenBucketRateLimiter` + 429/Retry-After backoff (`config/rpc.yaml`), distinct
`rate_limited` error_code, short-TTL `eth_gasPrice` cache; no RPC URL/key in logs.
Price-impact guard (WHI-845): `price_impact_bps` on Quote + `status=excessive_impact`
when over `config/impact.yaml` threshold (unvalidated); numbers stay readable, never
§5.2 best / heat; Jupiter `priceImpactPct`, AMM/Kyber mid-relative `|spread_bps|`.
Pull-only background poller (WHI-846): in-memory latest-quote store + per-upstream sweep groups for amm_dex/prop_amm; GET /quotes reads store (zero per-request Jupiter/Kyber/RPC); quote_stale age gate for §5.2 best; POST /simulate stays live; WHI-799 §3.1/§6.2 amended.
Infra deploy/CI (WHI-849): `.github/workflows/backend.yml` offline gate (`pytest` +
`ruff` + `mypy`); production-effective config committed (`api.yaml` CORS multi-port,
`venues.yaml` disables `mock`); `scripts/deploy.sh` git-based deploy (secrets + host
overlays + health); systemd unit under `deploy/`; ADR 0002 (systemd+uv, not Docker —
template Dockerfile removed); runbook `docs/DEPLOYMENT.md`.
WS orderbook ingest (WHI-847 / WHI-855): per-venue local books over multiplexed
WebSockets (Binance spot/futures, Bybit spot/linear, HL, Lighter, ApeX) with verified
sequence rules; chunked subscribe (Bybit spot ≤10, ApeX chunk=1), HL app-level ping,
ApeX pong, Lighter gap recovery via channel resubscribe, Binance spot resync weight
budget, catalog/phase-1 subscription scope; `GET /quotes` walks memory (zero REST when
healthy); REST resync on gap + REST fallback when disconnected; fast mid path
(~1 Hz `premiumIndex`) + `mid.max_age_for_ws_quote_sec`; `config/ws.yaml`.
Browser WebSocket push (WHI-848): `WS /stream` on FastAPI (`spread_compare/stream.py`
hub + `api/stream.py`); snapshot-then-delta with coalesce interval, heartbeat, origin
check against `cors_origins`, client/subscription caps + outbound queue backpressure;
`config/stream.yaml`. FE `QuotesStreamProvider` / `useQuotesStream` replaces section
`GET /quotes` polling (one socket per page); `live`/`reconnecting` badge; Resnapshot
button; per-row `snapshot_id` / age / `quote_stale` on the wire. `GET /quotes` kept.
Real-time engine monitoring (WHI-819): `config/monitor.yaml` per-class thresholds
(unvalidated); `/health` embeds `engine` (streams, sweeps, mid age, alerts) and stays
200 when degraded; `GET /health/data` 503 data probe; background evaluator +
`ALERT_WEBHOOK_URL` webhook (ADR 0003); runbook in `docs/DEPLOYMENT.md` § Monitoring.
Stream books-sync alerts (WHI-856): per-stream `books_healthy`/`books_expected`,
`books_unsynced` (critical at zero books: never-synced vs degraded; warning when
partial) past `ws_books_sync_grace_sec`, `subscribe_failed` when `stream_error`
and still zero healthy books, per-stream data-probe floor.
HTTP client construction transport extras (WHI-858): missing optional SOCKS
extra (`ImportError` for `socksio` / `httpx[socks]`) at `BaseAdapter.http`
raises venue-named `AdapterFetchError` (degradable) instead of raw
`ImportError` killing boot; dependency includes `httpx[socks]`.
Jupiter budget + poller sample matrix (WHI-864): Free-plan limiter
(`keyed_capacity=10`, `window_sec=10` → ~1 RPS sustained); per-group
`notionals_usd` (Jupiter 3-tier both sides; Kyber/RPC full §4.1); non-
overlapping sweeps with `skip_count` on `/health`; dashboard one-tier
fetch/subscribe (no SizeSelector `All`).
Unsampled tier status (WHI-865): pull-store misses emit
`status=not_sampled` (not `error`); WHI-799 §6.1/§6.6 + FE StatusCell
muted "not sampled"; Jupiter sample anchors `$100/$1k/$10k` (both sides).
Underlying-first stock model **spec** (WHI-880): WHI-798 §1.2/§4.6/§6.2
+ WHI-799 §3.3/§5.2.1/§6.2/§6.7 amended — one logical asset per equity
underlying, forms as a dimension (`perp`/`bstock`/`ondo`/`xstock`/
`xstock_cex`), shared mid, form_class best.
Underlying-first catalog/API/stream/poller (WHI-881): stock underlyings
with nested forms in `assets.py`; `(asset, form)` CEX/AMM/prop resolution;
`GET /assets` nests forms; `GET /quotes?forms=` + store/stream keys include
form; legacy token ids (NVDAB/QQQB/…) return structured 422.
Underlying-first stocks frontend (WHI-882): `/stocks` one board per
underlying; matrix rows keyed `venue|form`; form badges; form_class best in
summary/matrix; regenerated OpenAPI client; stream `pairIdentityKey` includes
form.
Catalog P0 stock expansion (WHI-884): CRCL/GOOGL/AMD/PLTR/META/AMZN/SPY/MSTR
(+ QQQ perp live); form-aware CEX maps + Bybit `AMDSTOCKUSDT` venue override;
HL exact-only WS (no SPY/QQQ proxy); live bstock@BN + xstock_cex@Bybit; Sol
xStocks stay unverified (zero Jupiter budget).

**Not implemented:** remaining venue adapters (WHI-805), collector.
Do not assume a module exists until its issue lands.

**Blocking gap:** `docs/DESIGN.md` is still mostly the empty template stub (§4.2 module
layout is filled by WHI-801). Produce the rest via `/grill-me` + `/to-spec` — the PR
checklist's "no new tunables outside DESIGN.md §2" still points at a section that does
not exist yet. Formula SSOT remains `docs/research/WHI-799-spread-fee-data-model.md`.

## Build, test, run

<!-- Replace with the real commands once the stack is confirmed. Default Python/uv
stack: -->

```bash
uv sync                                  # install deps (creates .venv; includes httpx[socks])
uv run pytest                            # unit tests (offline; skips @pytest.mark.live)
uv run pytest --live                     # include live tests (network + credentials)
uv run pytest tests/test_smoke.py        # single test file
uv run ruff check .                      # lint
uv run mypy                              # type check (strict via pyproject)
uv run python main.py                    # backend entrypoint (:8000)
# production deploy (on host): DEPLOY_REF=<tag|sha> scripts/deploy.sh
# see docs/DEPLOYMENT.md

# frontend/ (WHI-808)
cd frontend && pnpm install
pnpm dev                                 # Next.js :3000 (NEXT_PUBLIC_API_URL)
pnpm lint && pnpm typecheck && pnpm test
pnpm gen:openapi && pnpm gen:api         # regenerate OpenAPI types
```

Local SOCKS/HTTP proxy env (`ALL_PROXY` / `HTTPS_PROXY` / …): the project depends on
`httpx[socks]`, so a SOCKS proxy does not require an extra install. Prefer direct
upstream for lower latency when dogfooding venues (agent shells often set a system
proxy):

```bash
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy \
  uv run python main.py
```

If the SOCKS transport extra is still missing (``ImportError`` on adapter
client construction), WHI-858 remaps that to a per-venue degradable
`AdapterFetchError` (not a process-killing config error); `GET /health` lists
those venues under `unavailable_venues`. Other non-adapter `httpx.AsyncClient`
call sites are not remapped — see `docs/DEFERRED_ISSUES.md`.

## Runtime configuration

Secrets live in `.env` at the repo root (`.env.example` is the checked-in
template), loaded at startup — a missing required var must fail fast with a clear
error. **Never commit `.env`.** Non-secret runtime parameters (thresholds, feature
flags, tunables) live in `config/` as validated, typed config — not hardcoded, not in
`.env`. See `config/README.md` for the convention.

## Architecture

Module layout is fixed by `docs/DESIGN.md` §4.2. Keep this section a short mirror of
that section — one bullet per top-level module, its single responsibility, and the
load-bearing interfaces other modules may depend on.

- **`spread_compare/models.py`** — WHI-799 pydantic models + Quote §6.2 invariants (incl. `form` for stocks, WHI-881).
- **`spread_compare/venues.py`** — static venue slug registry (WHI-799 §6.5) + chain for FE.
- **`spread_compare/assets.py`** — logical asset catalog + nested stock forms (WHI-798 §3.3 / WHI-881); `USD_STABLES` / `is_usd_stable` peg predicate + `TRADEABLE_USD_STABLES` for simulate pair pickers (WHI-833).
- **`spread_compare/cex_symbols.py`** — logical asset → CEX spot/perp USDT symbols + multipliers; stock resolution is `(asset, form)`-aware (WHI-798 §3.3 / WHI-826 / WHI-881).
- **`spread_compare/perp_symbols.py`** — perp-DEX logical → venue coin/base + multipliers (HL HIP-3, k-prefix, 1000×).
- **`spread_compare/bookwalk.py`** — sole walk-the-book VWAP; CEX/perp adapters import only this.
- **`spread_compare/costs.py`** — sole `spread_bps` / `total_cost_bps` / `basis_bps`; aggregator never recomputes.
- **`spread_compare/impact.py`** — AMM/prop price-impact bps conversion + threshold reclassification to `excessive_impact` (WHI-845; not CEX/perp).
- **`spread_compare/settings.py`** — typed YAML config loader (`config/mid.yaml`, `config/aggregator.yaml`, `config/jupiter.yaml`, `config/api.yaml`, `config/venues.yaml`, `config/rpc.yaml`, `config/impact.yaml`, `config/orderbook_cache.yaml`, `config/poller.yaml`, `config/stream.yaml`, `config/ws.yaml`, `config/monitor.yaml`).
- **`spread_compare/ratelimit.py`** — shared `AsyncRateLimiter` / `TokenBucketRateLimiter` / `RollingWindowRateLimiter` with `max_wait_s` / `expected_wait_s` (WHI-836 / WHI-844); adapters must not define their own.
- **`spread_compare/budget.py`** — per-call quote deadline + `acquire_within_budget` / `sleep_within_budget` (WHI-844).
- **`spread_compare/fees.py`** — typed `config/fees/*.yaml` → `FeeSchedule` catalog; adapters + `GET /fees`.
- **`spread_compare/mids.py`** — reference-mid service (WHI-799 §3 priority chain + cache).
- **`spread_compare/upstream_events.py`** — rolling counters for upstream rate-limit hits (WHI-819).
- **`spread_compare/monitor.py`** — engine health snapshot + alert evaluation + webhook delivery (WHI-819); never recomputes bps.
- **`spread_compare/aggregator.py`** — concurrent adapter fan-out, multi-notional packages (WHI-843), per-class timeout, SizeQuotePair assembly, response cache (multi-tier + single-tier subset hits); partitions poller-served classes to the in-memory store (WHI-846); also hosts shared fan-out helpers (`quote_with_timeout`, `resolve_mid_with_budget`, `effective_instrument_type`) used by the simulator; never recomputes bps.
- **`spread_compare/simulator.py`** — `POST /simulate` fan-out (WHI-814): pair validation, free-form notional, expected_output derivation, §5.2 best ranking; no response cache; never recomputes bps.
- **`spread_compare/adapters/`** — async `VenueAdapter` + `BaseAdapter`, auto-discovery, `@register_adapter` registry with `startup_all`/`aclose_all` (WHI-840: degrade transient startup failures, disabled venues, background retry), `mock` + CEX (`binance`/`bybit`) + perp DEX (`perp_hyperliquid`/`perp_lighter`/`perp_apex`) + AMM DEX (`amm_uniswap`/`amm_aerodrome`/`amm_pancakeswap`) + prop AMM (`prop_jupiter`/`prop_kyberswap`), shared `_cex_common` / `_perp_common` / `_amm_common` / `_prop_common`; one module per real venue (no hand-import list).
- **`spread_compare/api/`** — FastAPI app factory with lifespan; `/health` (degradation + engine fields), `/health/data` (data probe), `/quotes`, `/venues` (omits config-disabled), `/assets`, `/fees`, `POST /simulate`, `GET /simulate/pairs`; CORS for local FE.
- **`spread_compare/orderbook_cache.py`** — short-TTL single-flight orderbook snapshot cache (WHI-843); depth is part of the key.
- **`spread_compare/quote_store.py`** — in-memory latest-quote store for pull-only venues (WHI-846); no persistence.
- **`spread_compare/poller.py`** — background sweep groups (Jupiter / Kyber / RPC); writes store; never recomputes bps.
- **`spread_compare/stream.py`** — browser push hub (WHI-848): client registry, coalesce publish, shared collect per filter key, delta diff; never recomputes bps.
- **`spread_compare/api/stream.py`** — `WS /stream` endpoint (origin validation, subscribe / resnapshot / ping).
- **`spread_compare/local_book.py`** / **`ws_registry.py`** / **`ws_protocols.py`** / **`ws_connection.py`** / **`ws_feeds.py`** / **`ws_serve.py`** / **`ws_mid.py`** / **`ws_bootstrap.py`** — WS orderbook ingest (WHI-847 / WHI-855): local books, per-venue sequence rules, reconnecting multiplexed feeds (chunked subscribe, app heartbeats, throttled resync), serve-from-memory + REST fallback, phase-1 subscription scope, fast mid poller.
- **`frontend/`** — Next.js dashboard (WHI-808): typed API client, SpreadMatrix, section config modules, route shell; `/simulate` UI (WHI-815) via `SimulateSection` + `simulatePairs`/`simulateView` pure libs; multi-tier matrix + size view preference (WHI-843 / WHI-841); page-level quote WebSocket (WHI-848) via `QuotesStreamProvider`.
- **`main.py`** — CLI: `--dry-run` validates; live serves uvicorn.

## Git workflow (mandatory)

**One issue = one git worktree off latest `origin/dev` = one PR into `dev`.**
Do **not** implement issues in the primary clone working tree.

1. `git fetch` + create worktree/branch from `origin/dev`
   (`fix/whi-NNN-topic` or `feat/whi-NNN-topic`).
   **Check the issue's labels first** — an issue labelled `hotfix` branches off
   `origin/main` instead and targets `main` (see **Promotion lanes** below). Verify the
   base right after creating the worktree — `git merge-base HEAD origin/dev` must equal
   `git rev-parse origin/dev` — whatever tooling created it. *(Runtime aside: Claude
   Code's `EnterWorktree` defaults to `origin/main`, wrong for this lane. Any wrapper may
   have its own default; the check above is what settles it.)*
2. Implement only that issue; tracker state → **`In Progress`**.
3. `gh pr create --base dev` (title/body include `WHI-NNN`); tracker →
   **`In Review`**. Any review finding you intentionally leave unfixed goes in
   `docs/DEFERRED_ISSUES.md` as part of this PR — see that file for the format.
4. A PR whose implementation went through `/implement`'s full three-round review loop
   (plus the escalation pass, when round 3 left findings open) is **pre-authorized to
   self-squash-merge** once it reads MERGEABLE/CLEAN and tests + lint pass — no separate
   human approval. **Exceptions that stop at `In Review` for a human:** `release/*` →
   `main` promotions, and PRs that skipped the review loop. **This project defines no
   high-risk paths** — it is read-only (no order placement, no transaction signing, no
   custody), so the template's high-risk-path gate is inactive; revisit the moment
   execution, key custody, or destructive DB migrations land
   (`docs/GIT_WORKFLOW.md` § High-risk paths). After merging, run the **post-merge
   cleanup** below.

### Post-merge cleanup (mandatory, in order)

Drive these from the **primary clone**; never commit to `dev` directly.

0. **If the PR is CONFLICTING** (`dev` advanced since you branched): inside the feature
   worktree, `git merge origin/dev`, resolve, rerun the affected tests, and `git push`.
   The PR must read **MERGEABLE / CLEAN** before you merge.
1. **Squash-merge + drop the remote branch:** `gh pr merge <N> --squash --delete-branch`.
2. **Remove the worktree:** `git worktree remove <worktree-path>` then
   `git worktree prune`.
3. **Delete the local branch:** `git branch -D fix/whi-NNN-topic`
   (this fails while the worktree still holds the branch — do step 2 first).
4. **Fast-forward local `dev`:** `git fetch origin --prune` then
   `git merge --ff-only origin/dev` (must fast-forward — do not create commits on
   `dev`).
5. **Tracker → `Done`.**

### Promotion lanes (`→ main`)

`main` **equals production** — always the last deployed tag. Never open a PR with `dev` as
head into `main` (the branch would be auto-deleted by `delete_branch_on_merge`). Two lanes
reach `main`, and picking the wrong one ships unreviewed work:

- **Release** — everything on `dev` is shippable. Cut a temporary `release/vX.Y.Z` from
  `dev`, PR → `main`. **Always a human gate.**
- **Hotfix** — production is broken *and* `dev` holds work that must not ship. Branch off
  `origin/main`, PR → `main`, then **merge `main` back into `dev`** or the next release
  re-ships the bug.

The decision rule: run `git log --oneline origin/main..origin/dev`. **If that list holds a
single commit you would not ship right now, you must use the hotfix lane.**

Merge strategy is per-lane: **squash** into `dev`, but **merge commit** into `main` —
squashing a release/hotfix disconnects the tag from `dev`'s history and silently breaks
`git log <tag>..origin/dev`. Bump the project version before tagging, **deploy from the
tag and never from a branch**, and keep the tracker Release ↔ git tag ↔ GitHub Release
triple in agreement (backfill the Release's `commitSha`).

Enable the local push guard once per clone **and per worktree**:
`git config core.hooksPath .githooks`.

Full rules: `docs/GIT_WORKFLOW.md`.

## Agent runtime (any agent, any vendor)

This repo is runtime-neutral: Claude Code, Codex, or anything else. Nothing in the
workflow names a model. Instead, skills name a **role** — `REVIEWER`, `ESCALATOR`,
`EXPLORER` — mapped to real commands in `config/agent-roles.conf` and dispatched through
`scripts/agent-dispatch.sh`. Full contract: **`docs/agents/runtime.md`**.

Two rules matter more than the mechanism:

- **Review happens in a different context than implementation**, with a model at least as
  capable (cross-vendor preferred). Check the path before relying on it:
  `scripts/agent-dispatch.sh --probe`.
- **If the reviewer is unavailable, the review loop did not run** — finish the work, open
  the PR, and stop at `In Review` for a human. Self-review in the implementing context
  never authorizes a self-merge.

When a model generation turns over, edit `config/agent-roles.conf` and nothing else.

## Agent skills

Skills live in `.claude/skills/<name>/SKILL.md`. Runtimes that auto-discover them expose
each as `/<name>`; **in a runtime with no skill loader, read the file directly** — a skill
is just markdown. The load-bearing ones:

| Skill | Path |
|-------|------|
| `/implement` | `.claude/skills/implement/SKILL.md` |
| `/code-review` | `.claude/skills/code-review/SKILL.md` |
| `/grill-me` → `/to-spec` → `/to-tickets` | `.claude/skills/{grill-me,to-spec,to-tickets}/SKILL.md` |
| `/tdd`, `/diagnosing-bugs`, `/handoff`, `/triage` | `.claude/skills/<name>/SKILL.md` |
| `/ask-matt` (which skill do I want?) | `.claude/skills/ask-matt/SKILL.md` |

### Issue tracker

Issues and PRDs live in **Linear** (project `spread-comparison-tools`, team
`Whisker-Personal`). Access is a fallback ladder — MCP tools, else the GraphQL API with
`LINEAR_API_KEY` — and reaching the tracker is mandatory, not optional: workflow state
moves in lockstep with the PR. External PRs are not a triage surface. See
`docs/agents/issue-tracker.md`.

### Triage labels

Canonical role names (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`) used verbatim as Linear labels. See
`docs/agents/triage-labels.md`.

### Domain docs

This repo's spec of record is `docs/DESIGN.md` (PRD: requirements, architecture,
milestones, rejected alternatives, open risks) plus `docs/adr/` for narrower decisions
made after v1 ships. See `docs/agents/domain.md`.
