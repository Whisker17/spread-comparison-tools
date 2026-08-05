# ADR 0002: Package the backend as systemd + uv venv (not Docker)

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-08-05 |
| Issue | [WHI-849](https://linear.app/whisker-personal/issue/WHI-849) |

> **Note:** `docs/agents/domain.md` places ADRs after v1 for decisions that do not belong in the PRD. `docs/DESIGN.md` is still mostly the empty stub, so this packaging decision is recorded here. Fold into DESIGN.md when that section is written if packaging becomes a PRD concern.

## Context

The backend runs on a single VPS. Early deploys were hand-rolled `rsync` from a laptop working tree into a directory managed by systemd, with a `uv`-created `.venv` (~59 MB). The repo also carried a **template** `Dockerfile` / `docker-compose.yml` that only copied `main.py`, omitted the `spread_compare` package, and used a placeholder entrypoint — usable-looking but broken.

Disk on the host is tight (~2 GB free at the time of this decision). A Docker image plus build cache is several times the size of the production venv. The product is a single-process, read-only quote API (no multi-tenant isolation requirement, no multi-host orchestration).

## Decision

1. **Production packaging is systemd + a project-local `uv` venv**, not containers.
2. **Deploy is git-based** on the host (`git fetch` + detached checkout of a tag/SHA), driven by `scripts/deploy.sh`. Do not rsync a developer working tree.
3. **Delete the template `Dockerfile` and `docker-compose.yml`** rather than finish them. A broken skeleton is worse than none — it invites someone to trust it.
4. **Secrets** live at `/etc/spread-comparison/env` (root-owned `0600`), loaded via systemd `EnvironmentFile=`. Host-only config overlays live under `/etc/spread-comparison/config/` and are re-applied by the deploy script after every checkout.
5. **Committed config is production-effective** for shared tunables (`config/api.yaml`, `config/venues.yaml` including `mock` disabled). `*.local.yaml` is for laptop experiments and deliberate host-only overrides, never for "the real production values nobody committed."

## Alternatives considered

| Option | Why rejected (this time) |
| --- | --- |
| **Finish Docker + compose** | Correct multi-host / CI image story, but image+cache disk cost is a poor fit for a ~2 GB-free single VPS; adds a second packaging path to keep in lockstep with systemd that already works. Revisit if we move to multi-host or need hermetic image provenance. |
| **Keep broken Dockerfile as "optional"** | Invites trust. Explicitly removed. |
| **rsync-from-laptop** | No verifiable revision; untracked `*.local.yaml` and dirty trees silently define production. Replaced by git checkout of tag/SHA. |
| **Bare `pip install` / system Python** | Loses lockfile reproducibility that `uv sync --locked` already gives. |

## Consequences

- **Positive:** Deployed revision is a git object (`/etc/spread-comparison/deployed-revision`); disk stays small; one packaging story.
- **Positive:** Backend CI (`.github/workflows/backend.yml`) can gate merges without needing a container build.
- **Negative:** Host bootstrap (deploy key, systemd unit, `uv` install) is documented in `docs/DEPLOYMENT.md` rather than encoded as an image.
- **Negative:** Reproducing "exactly what ran" requires the host's secrets file + host overlays + the recorded SHA — not a single image digest.
- **Revisit when:** multi-host deploy, stricter supply-chain requirements, or free disk no longer constrains image use.

## References

- Runbook: `docs/DEPLOYMENT.md`
- Deploy script: `scripts/deploy.sh`
- Unit template: `deploy/spread-comparison.service`
- Config convention: `config/README.md`
