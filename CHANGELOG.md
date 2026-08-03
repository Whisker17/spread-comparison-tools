# Template Changelog

Improvements to the template layer, newest first. When a downstream project ports a
change back (see "Template feedback loop" in `AGENTS.md`), record it here so other
projects can pick it up deliberately.

Format: date — what changed and why — which project surfaced it (if any).

---

## 2026-07-28 — Runtime-neutral agent roles

The template pinned its reviewer to `model: "opus"` inside `code-review/SKILL.md` and
narrated the `/implement` escalation pass as "Opus 5". Both are Claude-Code-only
encodings, so the review path silently had no meaning under Codex, Grok, or any other
runtime — and since `/implement`'s self-merge authorization is *derived from* the review
loop having run, a portability gap could turn into an unreviewed self-merge.

**The invariant, stated once:** review happens in a **different context** than
implementation, on a model **at least as capable**, **preferably cross-vendor**. A model
name is one encoding of that; the invariant is what the workflow rests on.

- **New adapter layer.** `docs/agents/runtime.md` defines four roles — `IMPLEMENTER`,
  `REVIEWER`, `ESCALATOR`, `EXPLORER`. `config/agent-roles.conf` maps roles → commands
  (checked in, non-secret). `scripts/agent-dispatch.sh` dispatches and probes them.
  A model generation turnover is now a one-line edit in the conf, not a skill edit.
- **Subprocess dispatch is canonical; native sub-agents are an optimization.** A
  non-interactive CLI call (`claude -p`, `codex exec`, …) works in every runtime including
  ones with no sub-agent primitive, and gives every runtime an identical prompt/output
  contract. Claude Code's `Agent` tool is a faster path to the same contract, not a
  different design. Skills must not branch three ways on runtime.
- **Cross-vendor review is preferred, not a fallback.** Sonnet→Opus is stronger but shares
  the implementer's blind spots; Codex→Opus has independent failure modes. `--probe` warns
  when both sides of the review are the same vendor.
- **Degraded mode is a hard stop.** If `REVIEWER` probes unusable, the loop did not run:
  finish the work, open the PR, stop at `In Review`, name the missing role. Self-review in
  the implementing context never authorizes a self-merge. Wired into
  `docs/GIT_WORKFLOW.md` § Agent / automation constraints #4.
- **Parallelism was never the point.** Skills that fan out (`/code-review` 2,
  design-it-twice 3+, `/wayfinder` research N) need *context isolation*, not concurrency —
  serial dispatch is an explicit, documented fallback. Reducing the agent count is not.
- **Other runtime assumptions generalized:** `EnterWorktree` demoted to a labelled aside
  behind the universal `merge-base`/`rev-parse` check; Linear access became a fallback
  ladder (MCP → GraphQL + `LINEAR_API_KEY` → stop and say so, never a silent local
  tracker); `/compact` reworded as "your runtime's compaction, if it has one"; bootstrap
  entry no longer says "open in Claude Code"; `AGENTS.md` now lists skills **by file path**
  so a runtime with no skill loader can still be pointed at one.

**Two template bugs found while auditing** (unrelated to portability, both live):

- `implement/SKILL.md` still carried `pm-arbitrage-bot`'s values — a hardcoded `WHI-NNN`
  issue prefix and its trading-specific gated paths ("order-placement, stop-loss,
  circuit-breaker, private-key … once real funds are live") instead of `{{ISSUE_PREFIX}}`
  and `{{HIGH_RISK_PATHS}}`. Its gate also cited a `docs/GIT_WORKFLOW.md` section
  ("Agent 约束 #6") that does not exist in the template, so the high-risk-path gate pointed
  at a dead reference.
- **Root cause:** `SETUP.md`'s placeholder-verification grep passed
  `--exclude-dir=.claude`, so no placeholder inside a vendored skill was ever checked.
  That exclusion is why the values above survived bootstrap. `.claude/` is now in scope,
  with one narrow exception for `HTML-REPORT.md`'s report template marker.

## 2026-07-28 — Release/hotfix lanes + full skill parity

Ported back from `pm-arbitrage-bot`, which hardened its workflow after shipping five
releases and discovering the template's promotion rules were underspecified.

**Git workflow (`docs/GIT_WORKFLOW.md`)** — the substantive change:

- **`main` ≡ production**, defined as always equal to the last deployed tag. The two
  promotion lanes are only distinguishable once that holds.
- **Release-vs-hotfix decision rule**, mechanical: if
  `git log origin/main..origin/dev` holds a single commit you would not ship right now,
  the hotfix lane is mandatory. Cutting a release to rush one fix drags everything on
  `dev` into production.
- **Per-lane merge strategy** — squash into `dev`, **merge commit** into `main`.
  Squashing a release/hotfix creates a commit absent from `dev`'s history, so the tag
  lands on a disconnected branch and `git log <tag>..origin/dev` silently returns
  garbage. `pm-arbitrage-bot` squashed v0.1.1–v0.1.5 before catching this and left five
  orphaned commits on `main`. **This reverses the template's previous squash-only
  policy** — `SETUP.md` no longer passes `--enable-merge-commit=false`.
- **Version axis** — tracker Release ↔ annotated git tag ↔ GitHub Release must agree;
  backfill the Release's `commitSha` as the authoritative version↔code binding.
  Milestones and Releases are orthogonal axes. Hotfixes take a fourth version segment
  (`0.1.5.1`) rather than stealing the next minor.
- **Deploy from tags only, never branches** — a branch deploy leaves nobody able to say
  which tree production is running.
- **Base verification after every worktree creation** (`merge-base` vs `rev-parse`).
  Claude Code's `EnterWorktree` branches from `origin/<default-branch>` = `main`, which
  is wrong for the issue lane and coincidentally right for hotfixes.
- Hotfix lane now requires a patch version bump before tagging and a `main` → `dev`
  merge-back, or the next release re-ships the fixed bug.
- Expanded **Forbidden** list; new **Agent / automation constraints** section (the
  high-risk-path gate explicitly overrides the self-merge pre-authorization).
- New **Branch protection** section: private repos on the Free plan get
  `403 Upgrade to GitHub Pro` for both classic protection and rulesets, so
  `.githooks/pre-push` is the stand-in.

**New: `.githooks/pre-push`** — refuses direct pushes to `main`/`dev`, `ALLOW_DIRECT_PUSH=1`
to override. Must be enabled per clone *and per worktree* (`git config core.hooksPath
.githooks`); `SETUP.md` now does this at bootstrap.

**Skills: 15 → 22 (full parity with `pm-arbitrage-bot`)** — added `diagnosing-bugs`,
`wayfinder`, `prototype`, `grill-with-docs`, `teach`, `writing-great-skills`, `ask-matt`.
Reverses the "trimmed from 22" decision below. Two caveats recorded in `README.md`:
`ask-matt` routes to five skills neither repo vendors, and `skills-lock.json` stores
upstream hashes so it cannot detect the local customizations in `implement`/`code-review`.

**`docs/agents/issue-tracker.md`** — new **Wayfinding operations** section (Linear map
issue, `parent` sub-issues, native blocking, frontier query). Without it `/wayfinder`
silently falls back to a local-markdown tracker; `pm-arbitrage-bot` has this gap too.

**`docs/agents/triage-labels.md`** — documents `hotfix` as the one type label that changes
git behaviour, so agents read labels before choosing a base branch.

## 2026-07-25 — Initial extraction

Extracted and generalized from `pm-arbitrage-bot` (dev branch):

- AGENTS.md as canonical agent guidance, CLAUDE.md symlinked.
- 15 vendored skills (trimmed from 22) + trimmed `skills-lock.json`.
- Docs system: DESIGN.md PRD skeleton as spec of record, GIT_WORKFLOW.md,
  DEFERRED_ISSUES.md, adr/, agents/ four-pack.
- Linear as default tracker; ticket-set publishing rules (native blocked-by relations)
  added to `docs/agents/issue-tracker.md` so `/to-tickets` output lands Linear-native.
- Worktree-per-issue git flow with agent self-squash-merge + high-risk-path
  human-review exceptions (paths defined per-project at setup).
- Minimal Python/uv stack layer (no CI, no shared core/ helpers — deliberate).
- SETUP.md self-destructing bootstrap runbook.
