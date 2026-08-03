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

- **Default HTTP timeout hardcoded on BaseAdapter** (Low, WHI-823).
  `spread_compare/adapters/base.py::_DEFAULT_HTTP_TIMEOUT` — AGENTS.md requires
  non-secret tunables in `config/` traced to DESIGN.md §2, but neither the config
  loader nor DESIGN §2 exists yet. Subclasses can override via
  `super().__init__(timeout=…)`. Move to typed YAML when DESIGN §2 is written.

- **CEX rate-limit / depth / fee placeholder tunables hardcoded** (Low, WHI-802).
  `spread_compare/adapters/cex_binance.py::_DEPTH_LIMITS` and
  `BinanceAdapter._min_interval_s`;
  `cex_bybit.py::_ORDERBOOK_LIMIT` and `BybitAdapter._min_interval_s`;
  `CexBaseAdapter._max_retries` / `_backoff_start_s` /
  `_cex_common.PLACEHOLDER_TAKER_BPS` — config/README.md wants YAML, but
  DESIGN.md §2 and the typed loader still do not exist. Defer until DESIGN §2 +
  config loader land (or WHI-812 for fees). Fix: `config/cex.yaml` + pydantic
  model, loaded at adapter startup.

- **`funding_rate_8h` not fetched on CEX quote path** (Low, WHI-802).
  Spec allows null "when not cheaply available". Depth endpoints do not carry
  funding; piggybacking `premiumIndex` / Bybit tickers adds weight and latency
  per quote. Leave null for Phase 1; optional cheap join once the aggregator
  batches mid+funding (WHI-807) or WHI-812 fee work.

- **Adapter init state is process-global** (Low, WHI-823).
  `spread_compare/adapters/registry.py::_INITIALIZED` — `/health`'s
  `adapters_initialized` count is shared across all `create_app()` instances in a
  process. Fine for the single-process CLI/server; wrong if multi-app TestClient
  suites run concurrent lifespans. Stash on `app.state` if that ever lands. Also:
  if a slug is started then removed from `_REGISTRY` without `aclose_all`, the
  count can go stale — clear both sets together when unregister is added.

---

## Resolved

- **Shared Quote assembly helper not extracted** (Low, WHI-801 → WHI-802).
  CEX path extracted into `spread_compare/adapters/_cex_common.py`
  (`CexBaseAdapter`, `build_quote_from_book`). Mock still has its own shell;
  promote further only if AMM/perp adapters re-copy.
