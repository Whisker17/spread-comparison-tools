# config/

Non-secret runtime parameters — thresholds, feature flags, tunables — live here as YAML,
loaded into a typed, validated model at startup.

## The convention

- **Secrets** go in `.env` (never committed; `.env.example` is the template). They are
  credentials — API keys, private keys, webhook URLs.
- **Parameters** go here, in YAML, checked in. They are decisions — every value should
  trace to `docs/DESIGN.md` §2 or be flagged as unvalidated.
- Loading is **typed and fail-fast**: define a pydantic model per config file, parse at
  startup, and include cross-field validation (e.g. `min_x < max_x`). A bad config must
  kill the process with a clear error before any real work starts.
- Per-deployment overrides use an untracked `<name>.local.yaml` copy (gitignored), so
  checking out a release tag never conflicts with live settings.

Loaders:
- `spread_compare/settings.py` — `load_mid_settings`, `load_aggregator_settings`,
  `load_jupiter_settings`, `load_api_settings`, `load_venue_settings`
- `spread_compare/fees.py` — `get_fee_catalog` / `get_fee_schedule` (one YAML per venue)

Checked-in files:
- `mid.yaml`, `aggregator.yaml`, `jupiter.yaml`, `api.yaml`, `venues.yaml` (defaults
  flagged unvalidated pending DESIGN.md §2)
- `venues.yaml` — per-host venue disable list + startup-retry backoff (WHI-840).
  Disabled slugs are omitted from `GET /venues` and never started; use this for
  geo-blocked hosts (e.g. Binance/Bybit 451 from US IPs). Override with
  `venues.local.yaml`.
- `fees/<venue>.yaml` — verified venue fee schedules (WHI-812); every number cites
  `source_urls` and carries `updated_at`. Filename stem must equal `venue:`.
  Adding a slug to `venues.py` requires a matching fee file (fail-fast at startup).
  `*.local.yaml` files under `fees/` are ignored by the loader (fee data is
  checked-in, not a per-deploy overlay).
