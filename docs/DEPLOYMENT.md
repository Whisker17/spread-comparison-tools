# Deployment runbook (backend)

How to deploy, roll back, rotate secrets, and verify that a change actually took
effect. Packaging rationale: [ADR 0002](adr/0002-packaging-systemd-uv-venv.md).

**Deploy from a release tag (or SHA), never from a branch tip.** See
`docs/GIT_WORKFLOW.md` § Promotion lanes.

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

## Related

- Backend CI: `.github/workflows/backend.yml` (`pytest`, `ruff`, `mypy` on backend paths)
- Config convention: `config/README.md`
- Monitoring / freshness alerts: WHI-819 (out of scope here)
