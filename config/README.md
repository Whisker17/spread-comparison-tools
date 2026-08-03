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

Loader: `spread_compare/settings.py` (`load_mid_settings`, `load_aggregator_settings`).
Checked-in files: `mid.yaml`, `aggregator.yaml` (defaults flagged unvalidated pending
DESIGN.md §2).
