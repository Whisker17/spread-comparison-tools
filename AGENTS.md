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
green, GitHub merge policy aligned). M1 research is done and merged: prop AMM quote paths
across Solana/Base/BSC (WHI-797), asset inventory (WHI-798), spread & fee data model
(WHI-799), venue API survey (WHI-800) — all under `docs/research/`. M2 backend scaffold
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
/ `GET /assets`.

**Not implemented:** remaining venue adapters (WHI-805), fee config numbers
(WHI-812), collector, frontend. Do not assume a module exists until its issue lands.

**Blocking gap:** `docs/DESIGN.md` is still mostly the empty template stub (§4.2 module
layout is filled by WHI-801). Produce the rest via `/grill-me` + `/to-spec` — the PR
checklist's "no new tunables outside DESIGN.md §2" still points at a section that does
not exist yet. Formula SSOT remains `docs/research/WHI-799-spread-fee-data-model.md`.

## Build, test, run

<!-- Replace with the real commands once the stack is confirmed. Default Python/uv
stack: -->

```bash
uv sync                                  # install deps (creates .venv)
uv run pytest                            # unit tests (offline; skips @pytest.mark.live)
uv run pytest --live                     # include live tests (network + credentials)
uv run pytest tests/test_smoke.py        # single test file
uv run ruff check .                      # lint
uv run mypy                              # type check
uv run python main.py                    # entrypoint
```

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

- **`spread_compare/models.py`** — WHI-799 pydantic models + Quote §6.2 invariants.
- **`spread_compare/venues.py`** — static venue slug registry (WHI-799 §6.5) + chain for FE.
- **`spread_compare/assets.py`** — logical asset catalog + representation labels (WHI-798 §3.3).
- **`spread_compare/cex_symbols.py`** — logical asset → CEX USDT symbol map (WHI-798 §3.3).
- **`spread_compare/bookwalk.py`** — sole walk-the-book VWAP; CEX/perp adapters import only this.
- **`spread_compare/costs.py`** — sole `spread_bps` / `total_cost_bps` / `basis_bps`; aggregator never recomputes.
- **`spread_compare/settings.py`** — typed YAML config loader (`config/mid.yaml`, `config/aggregator.yaml`).
- **`spread_compare/mids.py`** — reference-mid service (WHI-799 §3 priority chain + cache).
- **`spread_compare/aggregator.py`** — concurrent adapter fan-out, per-venue timeout, SizeQuotePair assembly, response cache; never recomputes bps.
- **`spread_compare/adapters/`** — async `VenueAdapter` + `BaseAdapter`, auto-discovery, `@register_adapter` registry with `startup_all`/`aclose_all`, `mock` + CEX (`binance`/`bybit`) + perp DEX (`perp_hyperliquid`/`perp_lighter`/`perp_apex`) + AMM DEX (`amm_uniswap`/`amm_aerodrome`/`amm_pancakeswap`) + prop AMM (`prop_jupiter`/`prop_kyberswap`), shared `_cex_common` / `_perp_common` / `_amm_common` / `_prop_common`; one module per real venue (no hand-import list).
- **`spread_compare/api/`** — FastAPI app factory with lifespan; `/health`, `/quotes`, `/venues`, `/assets`.
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
