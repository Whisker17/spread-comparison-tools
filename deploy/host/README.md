# Host config inventory

Files in this directory are **examples** of what lives on the production host at
`/etc/spread-comparison/config/`. They are **not** copied by git checkout.

`scripts/deploy.sh` re-applies every `*.local.yaml` from
`/etc/spread-comparison/config/` into the app's `config/` after each checkout so
host-only settings survive deploys.

## Production defaults that are already committed

| Setting | Where |
| --- | --- |
| `cors_origins`, `simulate_min_interval_sec` | `config/api.yaml` (committed) |
| `mock` disabled | `config/venues.yaml` (committed) |

Do **not** put those in a host overlay unless you are intentionally overriding
them. Host overlays replace whole YAML keys (`settings._merge_local`).

## When to use a host overlay

- Geo-blocked venues on this host only (e.g. Binance/Bybit 451 from a US VPS)
- Temporary disable of a flaky venue without a code change
- Emergency CORS origin that must land before the next release tag

Example install on the host:

```bash
sudo install -d -m 0755 /etc/spread-comparison/config
sudo install -m 0644 deploy/host/venues.local.yaml.example \
  /etc/spread-comparison/config/venues.local.yaml
# edit, then re-run deploy (or restart the service)
```
