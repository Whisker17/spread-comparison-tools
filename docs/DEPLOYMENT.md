# Deployment runbook (backend)

How to deploy, roll back, rotate secrets, and verify that a change actually took
effect. Packaging rationale: [ADR 0002](adr/0002-packaging-systemd-uv-venv.md).

**Deploy from a release tag (or SHA), never from a branch tip.** See
`docs/GIT_WORKFLOW.md` § Promotion lanes.

**Frontend builds** (when shipping the Next dashboard) must set
`NEXT_PUBLIC_API_URL` to a public non-loopback origin at `pnpm build` time —
see `frontend/README.md` § Env / build-time API URL (WHI-857). This runbook is
backend-only; that contract lives with the frontend.

## Layout on the host

| Path | Role |
| --- | --- |
| `/opt/spread-comparison-tools` | Git checkout of this repo (deploy key read access) |
| `/opt/spread-comparison-tools/.venv` | `uv sync --locked --no-dev` virtualenv |
| `/etc/spread-comparison/env` | Secrets (`EnvironmentFile=`), **root-owned `0600`** |
| `/etc/spread-comparison/config/*.local.yaml` | Host-only config overlays (optional) |
| `/etc/spread-comparison/deployed-revision` | Last successful deploy record (`sha`, `ref`, `deployed_at`) |
| `spread-comparison.service` | systemd unit (`deploy/spread-comparison.service`) |

## One-time bootstrap

1. Create a **read-only deploy key** for the private repo; install it on the host
   (e.g. `/root/.ssh/spread_deploy`) and configure git SSH for that host.
2. Clone once:

   ```bash
   sudo mkdir -p /opt
   sudo git clone git@github.com:Whisker17/spread-comparison-tools.git \
     /opt/spread-comparison-tools
   sudo useradd --system --home /opt/spread-comparison-tools --shell /usr/sbin/nologin spread
   sudo chown -R spread:spread /opt/spread-comparison-tools
   ```

3. Install `uv` system-wide (or under a path the `spread` user can execute).
4. Create secrets from `.env.example` → `/etc/spread-comparison/env`:

   ```bash
   sudo install -d -m 0750 /etc/spread-comparison
   sudo install -m 0600 -o root -g root /path/to/filled.env /etc/spread-comparison/env
   ```

   Required keys today: `ETH_RPC_URL`, `BASE_RPC_URL`, `BSC_RPC_URL` (keyed
   provider URLs preferred — free public endpoints rate-limit under load).
   Optional: `JUPITER_API_KEY`.

5. Install systemd unit:

   ```bash
   sudo install -m 0644 /opt/spread-comparison-tools/deploy/spread-comparison.service \
     /etc/systemd/system/spread-comparison.service
   sudo systemctl daemon-reload
   sudo systemctl enable spread-comparison
   ```

6. First deploy (see below) with a known tag/SHA.

Host overlays (only if needed beyond committed config): see
`deploy/host/README.md`.

### Config schema notes (breaking overlays)

- **WHI-864 `poller.yaml`**: `notionals_usd` moved from top-level into each
  `groups.<name>` entry (required). A host
  `/etc/spread-comparison/config/poller.local.yaml` that still has top-level
  `notionals_usd` or that replaces `groups:` without the new key will fail
  validation at boot (process-killing config error). Before deploying this
  change, inspect and rewrite any poller overlay to the per-group shape, or
  remove the overlay and rely on the committed defaults.

## Deploy

On the host (or over SSH as root):

```bash
export DEPLOY_REF=v0.1.0   # or a full git SHA
# Optional: push updated secrets this cycle
# export SECRETS_SRC=/root/staging/env

sudo -E /opt/spread-comparison-tools/scripts/deploy.sh
```

The script always performs, in order:

1. **Sync code** — `git fetch` + detached `checkout` of `DEPLOY_REF`
2. **Sync secrets** — install `SECRETS_SRC` → `/etc/spread-comparison/env` when set;
   otherwise keep the existing file (and fail if it is missing)
3. **Re-apply host config** — wipe tree `*.local.yaml`, copy from
   `/etc/spread-comparison/config/`
4. **`uv sync --locked --no-dev`**
5. **`systemctl restart spread-comparison`**
6. **Verify** `GET http://127.0.0.1:8000/health` is **live**: HTTP 200,
   `"status":"ok"`, and not `adapters_initialized=0` when
   `adapters_expected>0`. WHI-840 **degraded** (some venues down, process still
   serving) is allowed — that is not a deploy failure. Then write
   `/etc/spread-comparison/deployed-revision`

Idempotency (end state): running the same `DEPLOY_REF` twice with unchanged
`SECRETS_SRC` / host overlays leaves the git tree and secrets file byte-identical
after the second run. The script still **restarts** the unit and re-checks
`/health` each time (brief downtime is expected; “nothing changed” means no
drift in code/config/secrets, not “zero process churn”). Second run exits 0 only
if health passes.

Dry-run (print planned steps only — no fetch, checkout, secret install, overlay
apply, `uv sync`, restart, or health poll):

```bash
DRY_RUN=1 DEPLOY_REF=v0.1.0 ./scripts/deploy.sh
```

## Roll back

Deploy the previous known-good tag or SHA the same way:

```bash
export DEPLOY_REF=v0.0.9   # or the SHA from the previous deployed-revision file
sudo -E /opt/spread-comparison-tools/scripts/deploy.sh
```

If the host is hard-down and you only have local state:

```bash
cat /etc/spread-comparison/deployed-revision
# sha=...
# ref=...
```

Do **not** `git checkout` a branch and call it production — always pin a tag or SHA.

## Rotate secrets

1. Prepare a new env file offline (never commit it).
2. Deploy with secret install:

   ```bash
   export DEPLOY_REF="$(sudo awk -F= '/^sha=/{print $2}' /etc/spread-comparison/deployed-revision)"
   export SECRETS_SRC=/root/staging/env.new
   sudo -E /opt/spread-comparison-tools/scripts/deploy.sh
   ```

3. Confirm health and that venues depending on the rotated keys recover (e.g.
   AMM adapters after RPC URL change).
4. Shred the staging file: `shred -u /root/staging/env.new` (or equivalent).

Permissions after install: root-owned `0600`. The deploy script fails if the
mode is not `0600`.

## Verify a deploy took effect

| Check | Command / expectation |
| --- | --- |
| Revision | `cat /etc/spread-comparison/deployed-revision` matches intended tag/SHA |
| Process | `systemctl status spread-comparison` is active |
| Health | `curl -sS http://127.0.0.1:8000/health` → `"status":"ok"` |
| Config (CORS / simulate) | Effective values come from committed `config/api.yaml` (no surprise `api.local.yaml` unless you put one in the host inventory on purpose) |
| Mock disabled | `curl -sS http://127.0.0.1:8000/venues` must **not** list `mock` |
| Secrets | Changing only code does **not** change env; pass `SECRETS_SRC` when secrets must move with the deploy |
| WebSocket stream (WHI-848) | Dashboard uses `WS /stream` (not periodic `GET /quotes`). If a reverse proxy sits in front, forward `Upgrade` + `Connection` and set the idle read timeout **above** `config/stream.yaml` `heartbeat_interval_sec` (15s) so heartbeats keep the connection alive. Origin must be on `cors_origins`. |

### Effective config from a clean checkout

Production-effective API and venue defaults are committed:

- `config/api.yaml` — `cors_origins` (localhost FE ports) + `simulate_min_interval_sec: 2.0`
- `config/venues.yaml` — `disabled: [mock]`

A deploy of a clean tree without any host overlay therefore matches the intended
host behaviour for those keys. Laptop-only `config/*.local.yaml` files are
gitignored and are **deleted** by the deploy script before host overlays are
re-applied — they never ride along from a developer machine.

## Secrets hygiene

- **Never** commit `.env` or paste secrets into issues/PR descriptions.
- **Never** log `ETH_RPC_URL` / `BASE_RPC_URL` / `BSC_RPC_URL` values — they embed
  provider API keys. Prefer logging only the env *name* when an adapter fails.
- Image layers are not in play (no Docker in production); still keep secrets out
  of the git history.
- Journal/`systemctl show` can expose `EnvironmentFile` *path* but not contents;
  do not add `Environment=KEY=secret` lines to the unit.

## Monitoring (WHI-819)

Process liveness is no longer enough: WebSocket books and background sweeps can
fail while systemd and `GET /health` still look fine. Thresholds live in
`config/monitor.yaml` (**unvalidated** defaults). Alert channel: generic HTTPS
webhook — [ADR 0003](adr/0003-alert-channel-webhook.md).

### Endpoints

| Endpoint | HTTP when data is bad | Role |
| --- | --- | --- |
| `GET /health` | **200** (always while serving) | LB / deploy liveness. Body includes adapter degradation **and** `engine` (streams, sweeps, mid age, open alerts). |
| `GET /health/data` | **503** | Data probe: fails when the process is up but serving only stale / missing mid / empty books. Point an external uptime check here. |

Deploy verification still uses `/health` (degraded adapters are allowed). Add
`/health/data` to a secondary probe after the post-boot grace
(`startup_grace_sec`, default 90s).

### Secret

```bash
# /etc/spread-comparison/env  (root 0600)
ALERT_WEBHOOK_URL=https://hooks.example.com/…   # Discord / Slack / Feishu / webhook.site
```

When unset, alerts are still evaluated and listed under `engine.alerts`, and each
fire/resolve is logged at WARNING (`journalctl -u spread-comparison`).

### Alert codes → meaning → first action

| Code | Meaning | First action |
| --- | --- | --- |
| `ws_disconnected` | One multiplexed orderbook WS has been down longer than `ws_disconnected_alert_sec` | `curl -sS localhost:8000/health \| jq .engine.streams`; check venue status / geo blocks; journal for reconnect loops; REST fallback should still serve until books age out |
| `books_unsynced` | Connected stream with `books_healthy < books_expected` past `ws_books_sync_grace_sec` (WHI-856). Message says *never synced since connect* vs *was healthy, now degraded* | `jq '.engine.streams[] \| {stream_id, connected, books_healthy, books_expected, stream_error}'`; never-synced → subscribe/protocol; degraded → upstream/network. REST fallback still serves |
| `subscribe_failed` | Stream reported a subscribe/stream error **and still has zero healthy books** — immediate (no books-sync grace). Cleared once any book becomes HEALTHY; residual shortfall is `books_unsynced` warning | Journal for that stream's ack failure; fix chunk size / topic format; books for failed symbols stay non-servable |
| `book_stale` | Connected stream but max book age &gt; `ws_max_book_age_sec` | Confirm diffs are flowing; forced resync may be stuck — see `resync_*_window` on the stream |
| `book_desync` | Too many REST resyncs in `ws_resync_window_sec` (sequence gaps) | Inspect that venue's protocol; rate-limit on REST resync path; temporary disable stream in `config/ws.yaml` if poisoning the matrix |
| `book_resync_failed` | Repeated failed REST resync (distinct from desync count) | Auth / REST endpoint / network to that venue; books will stay non-servable → REST path or empty |
| `sweep_stale` | Pull-only group (`jupiter` / `kyber` / `rpc`) has not completed within `interval × sweep_stale_multiplier` | `jq .engine.sweeps` on `/health`; check 429s (`engine.rate_limits`); poller task alive? |
| `mid_stale` | Reference mid cache older than `mid_max_age_sec` (or missing) | Fast mid poller / Binance premiumIndex path; all bps drift if mid is wrong |
| `rate_limited` | Sustained upstream 429s on Jupiter / Kyber / RPC in the rolling window | Raise keyed budgets, slow sweep groups, or rotate RPC provider |
| `data_stale` | Data probe failed (aggregate of mid / store / books / per-stream floors) | Same as 503 on `/health/data` — treat as "serving garbage", not "process down" |

### Interpreting `/health` fields

- **`degraded` / `unavailable_venues`** (WHI-840): adapter `startup()` failed or not
  yet retried. Process still serves other venues; **not** a deploy failure.
- **`engine.streams[]`**: per multiplexed WS (`binance_spot`, `bybit_linear`, …) —
  `connected`, `healthy` (operator-facing: not zero-book past grace / no blocking
  subscribe error), `books_healthy` / `books_expected`, `peak_healthy_since_connect`,
  book counts by health, max age, resync window counts, `stream_error`,
  `connected_age_sec`.
- **`engine.sweeps[]`**: per poller group — `age_sec` since last completed sweep,
  `stale` vs `interval_sec × sweep_stale_multiplier`, `sweep_count`, and
  `skip_count` (WHI-864 ticks skipped while a sweep was still in flight or
  overran the interval).
- **`engine.mid_age_sec`**: age of the probe asset mid (default BTC).
- **`engine.alerts`**: currently open conditions (same codes as webhook).
- **`engine.in_startup_grace`**: true during `startup_grace_sec` — data probe and
  sweep/mid alerts are suppressed so cold start does not page. Stream
  `books_unsynced` still uses the shorter per-stream books-sync grace after connect.

### Stated SLOs (defaults — unvalidated)

| Condition | Default threshold |
| --- | --- |
| WS disconnect alert | 30s disconnected |
| Books unsynced (connected, short of expected) | 60s after connect (`ws_books_sync_grace_sec`; optional per-stream map) |
| Subscribe / stream error at zero books | Immediate (`subscribe_failed`); clears when any book is healthy |
| Per-stream data-probe floor | ≥1 healthy book per connected stream past grace |
| Sweep stale | 2.5 × group `interval_sec` (e.g. Jupiter 15s → 37.5s) |
| Book desync | ≥5 resyncs / 60s |
| Failed resync | ≥2 failures / 60s |
| Sustained 429 | ≥10 events / 60s per source |
| Alert re-page cooldown | 300s |

### Manual checks

```bash
# Liveness (deploy / LB)
curl -sS http://127.0.0.1:8000/health | jq '{status, degraded, unavailable_venues, data_ok: .engine.data_ok, alerts: .engine.alerts}'

# Data freshness (uptime robot — expect 200 after grace when healthy)
curl -sS -o /tmp/health-data.json -w '%{http_code}\n' http://127.0.0.1:8000/health/data

# Webhook smoke (requires ALERT_WEBHOOK_URL): stop is not required — force a
# disconnect by disabling a stream in ws.local.yaml host overlay, restart, wait
# ws_disconnected_alert_sec, confirm delivery in the sink + journal.
journalctl -u spread-comparison -n 100 --no-pager | grep -iE 'alert|webhook|ws stream'
```

## Related

- Backend CI: `.github/workflows/backend.yml` (`pytest`, `ruff`, `mypy` on backend paths)
- Config convention: `config/README.md`
- Alert channel ADR: [ADR 0003](adr/0003-alert-channel-webhook.md)
