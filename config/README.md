# config/

Non-secret runtime parameters — thresholds, feature flags, tunables — live here as YAML,
loaded into a typed, validated model at startup.

## The convention

- **Secrets** go in `.env` locally, or `/etc/spread-comparison/env` on the host
  (never committed; `.env.example` is the template). They are credentials — API
  keys, private keys, webhook URLs. RPC URLs that embed provider keys are secrets.
- **Parameters** go here, in YAML, checked in. They are decisions — every value should
  trace to `docs/DESIGN.md` §2 or be flagged as unvalidated.
- Loading is **typed and fail-fast**: define a pydantic model per config file, parse at
  startup, and include cross-field validation (e.g. `min_x < max_x`). A bad config must
  kill the process with a clear error before any real work starts.
- **Production-effective values are committed** (WHI-849). A deploy from a clean
  checkout must reproduce production behaviour for shared tunables without any
  untracked file. Do not put the "real" `cors_origins` or `simulate_min_interval_sec`
  only in `api.local.yaml`.
- **`*.local.yaml` is optional overlay**, gitignored:
  - **Laptop:** personal experiments (extra CORS ports, temporary timeouts).
  - **Host:** files under `/etc/spread-comparison/config/` re-applied by
    `scripts/deploy.sh` after every checkout (geo-block venue disables, emergencies).
  - Overlay merge is shallow key replace (`settings._merge_local`) — a local
    `cors_origins` list replaces the whole committed list, it does not append.

Loaders:
- `spread_compare/settings.py` — `load_mid_settings`, `load_aggregator_settings`,
  `load_jupiter_settings`, `load_api_settings`, `load_venue_settings`,
  `load_rpc_settings`, `load_impact_settings`, `load_orderbook_cache_settings`,
  `load_poller_settings`, `load_stream_settings`, `load_ws_settings`,
  `load_monitor_settings`
- `spread_compare/fees.py` — `get_fee_catalog` / `get_fee_schedule` (one YAML per venue)

Checked-in files:
- `mid.yaml`, `aggregator.yaml`, `jupiter.yaml`, `api.yaml` (defaults flagged
  unvalidated pending DESIGN.md §2). `api.yaml` includes multi-port localhost
  CORS used by local Next.js and `simulate_min_interval_sec: 2.0`.
- `impact.yaml` — price-impact guard threshold in bps (WHI-845). Quotes above
  `max_price_impact_bps` become `status=excessive_impact` (shown, never best /
  heat). Unvalidated pending DESIGN.md §2; override with `impact.local.yaml`.
- `rpc.yaml` — EVM JSON-RPC client budget (WHI-842): per-endpoint token-bucket RPS,
  429 retry/backoff, `eth_gasPrice` cache TTL. Shared across AMM adapters on the
  same RPC URL. Override with `rpc.local.yaml` for keyed provider tiers.
- `orderbook_cache.yaml` — short-TTL orderbook snapshot reuse (WHI-843). Depth is
  part of the cache key so a shallow $100 book is never walked for $1M. Unvalidated
  pending DESIGN.md §2; override with `orderbook_cache.local.yaml`.
- `poller.yaml` — pull-only background poller (WHI-846): served venue classes,
  per-upstream sweep groups (interval, budget_share / max_rps, max ages).
  AMM DEX + prop AMM quotes are written to an in-memory store; `GET /quotes`
  reads them (zero per-request upstream). Unvalidated pending DESIGN.md §2;
  override with `poller.local.yaml`.
- `stream.yaml` — browser WebSocket push stream (WHI-848): coalesce interval,
  heartbeat / client liveness, max clients, subscription breadth caps, outbound
  queue depth. Origin allowlist reuses `api.yaml` `cors_origins`. Unvalidated
  pending DESIGN.md §2; override with `stream.local.yaml`.
- `ws.yaml` — WebSocket orderbook ingest (WHI-847): enable flag, max book age,
  reconnect backoff, Lighter resync floor, fast-mid poll interval, per-stream
  flags. When healthy, CEX/perp quotes walk in-memory books (zero REST).
  Unvalidated pending DESIGN.md §2; override with `ws.local.yaml`.
  Pair with `mid.yaml` → `max_age_for_ws_quote_sec` for the tighter mid gate.
- `monitor.yaml` — real-time engine monitoring (WHI-819): per-class staleness
  thresholds (WS disconnect / book age / resync, sweep multiplier, mid age,
  sustained 429s), data-probe asset, eval interval, startup grace, alert
  cooldown. Webhook URL is a secret (`ALERT_WEBHOOK_URL`), not YAML.
  Unvalidated pending DESIGN.md §2; override with `monitor.local.yaml`.
- `venues.yaml` — per-host venue disable list + startup-retry backoff (WHI-840).
  Committed default disables `mock` (fixture adapter; WHI-849). Disabled slugs are
  omitted from `GET /venues` and never started; unknown slugs fail fast at load.
  Use a host `venues.local.yaml` for geo-blocked hosts (e.g. Binance/Bybit 451
  from US IPs) — deploy re-applies it.
- `fees/<venue>.yaml` — verified venue fee schedules (WHI-812); every number cites
  `source_urls` and carries `updated_at`. Filename stem must equal `venue:`.
  Adding a slug to `venues.py` requires a matching fee file (fail-fast at startup).
  `*.local.yaml` files under `fees/` are ignored by the loader (fee data is
  checked-in, not a per-deploy overlay).

Deploy / host layout: `docs/DEPLOYMENT.md`.
