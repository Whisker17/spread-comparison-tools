# Deferred issues registry

A living log of issues that were **surfaced during review but consciously not fixed**
in the PR that found them. This is not a bug tracker for open work — it is the record of
*known, accepted debt*: things we decided to defer, so a future change touching the same
area starts from knowledge instead of rediscovery.

## How to use this file

- **Add an entry** whenever a review turns up a real issue that a PR deliberately leaves
  unfixed (scope, risk, or priority). Record it here in the same PR that defers it.
- **Reference it** before working on the affected area — check whether the thing you are
  about to "discover" is already logged, and whether a listed fix is now in scope.
- **Close an entry** by moving it to *Resolved* (bottom) with the PR/commit that fixed
  it, rather than deleting — the history is useful.
- Keep entries short. Link the originating tracker issue / PR and the code symbol so the
  entry stays findable as the code moves.

Severity is the reviewer's judgement at defer time: **High** (correctness/safety, fix
soon — anything touching a high-risk path defaults to at least High, though this project
defines none: `docs/GIT_WORKFLOW.md` § High-risk paths), **Medium**
(operational/perf, fix when convenient), **Low** (nit/consistency).

## Entry format

```markdown
- **<one-line description of the defect>** (<Severity>, <issue-id>).
  `<file>::<symbol>` — what's wrong, why it was deferred, and what the fix would be.
```

---

## Open

- **`mid_stale` is never computed by adapters** (Low, WHI-801).
  `spread_compare/models.py::Quote.mid_stale` — WHI-799 §3.2 defines
  `mid_stale = abs(quote.timestamp - mid_timestamp) > mid.stale_threshold_sec`, but
  computing it needs `config/mid.yaml` (still unvalidated / WHI-807). Mock leaves the
  default `False`. Fix in WHI-807 (or a shared helper once the threshold lives in
  typed config).

- **Shared Quote assembly helper not extracted** (Low, WHI-801).
  `spread_compare/adapters/mock.py::_quote_shell` — mapping `ReferenceMid` + status
  into a §6.2-valid `Quote` is private to the mock. Real adapters (WHI-802…806) risk
  copy-paste drift. Promote a `build_quote(...)` (and optional mid/asset guard) into
  `adapters/base.py` with the first real adapter PR if duplication appears.

- **Default HTTP timeout hardcoded on BaseAdapter** (Low, WHI-823).
  `spread_compare/adapters/base.py::_DEFAULT_HTTP_TIMEOUT` — AGENTS.md requires
  non-secret tunables in `config/` traced to DESIGN.md §2, but neither the config
  loader nor DESIGN §2 exists yet. Subclasses can override via
  `super().__init__(timeout=…)`. Move to typed YAML when the first real adapter
  lands a shared HTTP config (or when DESIGN §2 is written).

- **Adapter init state is process-global** (Low, WHI-823).
  `spread_compare/adapters/registry.py::_INITIALIZED` — `/health`'s
  `adapters_initialized` count is shared across all `create_app()` instances in a
  process. Fine for the single-process CLI/server; wrong if multi-app TestClient
  suites run concurrent lifespans. Stash on `app.state` if that ever lands. Also:
  if a slug is started then removed from `_REGISTRY` without `aclose_all`, the
  count can go stale — clear both sets together when unregister is added.

- **AMM fee-tier / tick-spacing probe lists are module constants** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::UNISWAP_FEE_TIERS` (and
  `PANCAKE_FEE_TIERS`, `AERO_TICK_SPACINGS`) — AGENTS.md wants non-secret tunables
  in `config/` traced to DESIGN.md §2, but DESIGN §2 is still empty and WHI-812
  owns fee numbers. Constants are cited to WHI-800 (2026-08-03). Move to typed
  YAML when DESIGN §2 / WHI-812 lands.

- **Native gas USD uses Binance spot bookTicker inside AMM helpers** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::fetch_binance_mid` — WHI-804 requires
  `gasEstimate × gasPrice × native USD` via Binance ETHUSDT/BNBUSDT; not the
  reference-mid path (WHI-807). Acceptable coupling for Phase 1; extract a shared
  CEX mid helper when WHI-802/807 land to avoid shotgun edits on URL/field renames.

- **AMM ExactOut / deep-size reverts map to `no_quote`, not `insufficient_liquidity`**
  (Medium, WHI-804).
  `spread_compare/adapters/_amm_common.py::probe_quoter_v2` — WHI-799 §4.2/§6.6
  distinguish thin depth from missing routes, but a QuoterV2 eth_call revert does
  not tell them apart without an extra small-size probe RPC. Left as `no_quote` for
  reverts; upgrade when a cheap pool-existence probe is worth the RTT.

- **AMM Quote builders not yet unified with mock `_quote_shell`** (Low, WHI-804).
  `spread_compare/adapters/_amm_common.py::build_ok_quote` / `build_non_ok_quote` —
  same shape as mock's helper (WHI-801 deferred entry). Promote one shared builder
  when a third adapter family duplicates the pattern again.

---

## Resolved

_(none yet)_
