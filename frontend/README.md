# Frontend — spread comparison dashboard

Next.js (App Router) + TypeScript + Tailwind UI shell for the
`spread-comparison-tools` backend. Scaffold: **WHI-808**. Section content:
WHI-809 / 810 / 811.

## Local dev

Two processes:

| Process | Port | Command |
| --- | --- | --- |
| Backend (FastAPI) | **8000** | from repo root: `uv run python main.py` |
| Frontend (Next.js) | **3000** | from `frontend/`: `pnpm dev` |

```bash
# terminal 1 — repo root
uv sync
uv run python main.py

# terminal 2 — frontend
cd frontend
pnpm install
cp .env.example .env.local   # optional for pnpm dev only — remove/override before pnpm build
pnpm dev
```

Open http://localhost:3000 — `/` redirects to `/blue-chips` (WHI-809): BTC / ETH /
SOL blocks with live matrices, representation labels, snapshot summary, and
section-level 30s auto-poll. Per-venue failures degrade to `status=error` /
`no_quote` rather than failing the page. Reference mid still needs a working mid
source (Binance index by default); without network, `/quotes` may 503.

UI primitives under `src/components/ui/` follow the shadcn/new-york stack
(Radix + CVA + `cn`). `components.json` is checked in so section agents can run
`pnpm dlx shadcn@latest add <component>` without re-initializing.

### Env / build-time API URL (WHI-857)

| Variable | Dev default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend origin (no trailing slash). **Baked into the client at build time.** |

- **`pnpm dev`**: unset is fine — the client defaults to `http://localhost:8000`. Optional `.env.local` overrides (e.g. an SSH tunnel to the VPS).
- **`.env.local` is development-only.** Next loads it for builds too, so a leftover loopback value will fail `pnpm build` on purpose.
- **`pnpm build` / production**: `NEXT_PUBLIC_API_URL` **must** be set to a **non-loopback** absolute origin. Unset, empty, `localhost`, `127.0.0.1`, and `[::1]` fail the build with a message naming the variable. The `/stream` WebSocket URL is derived from the same value under the same rule.

Correct production example:

```bash
# shell env wins over .env.local for this invocation
NEXT_PUBLIC_API_URL=https://api.example.com pnpm build
```

Wrong (build fails):

```bash
pnpm build                                          # unset → error
NEXT_PUBLIC_API_URL=http://127.0.0.1:8100 pnpm build  # loopback → error
```

Same-origin serving (frontend + API behind one host, relative base URLs) would
remove this class of bug entirely and is strictly safer than any guard — the
client currently requires an **absolute** origin, so that deploy shape is not
supported yet. Until it is, set the public origin explicitly at build time.
`next start` does not re-check the var (it was already baked); only `pnpm build`
fails closed.

The backend enables CORS for local frontend origins (`localhost:3000` / `127.0.0.1:3000`).

## Scripts

| Script | Purpose |
| --- | --- |
| `pnpm dev` | Next dev server (:3000) |
| `pnpm build` | Production build |
| `pnpm start` | Serve production build |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm test` | Vitest unit tests (summary / status / format) |
| `pnpm gen:api` | Regenerate `src/lib/api-types.ts` from `openapi/openapi.json` |
| `pnpm gen:openapi` | Dump backend OpenAPI → `openapi/openapi.json` (needs repo-root venv) |

### Regenerating API types

Types are **generated**, not hand-written:

```bash
# from frontend/
pnpm gen:openapi   # refreshes openapi/openapi.json from FastAPI
pnpm gen:api       # openapi-typescript → src/lib/api-types.ts
```

Commit both `openapi/openapi.json` and `src/lib/api-types.ts` when the backend
contract changes (WHI-807+).

## Layout (parallel-safety for section agents)

```
src/
  app/                 # routes: /, /blue-chips, /stocks, /others, /fees, /simulate, /status-fixtures
  components/          # SpreadMatrix, SizeSelector, TopOfBookRow, StatusCell, SummaryStrip, …
  config/
    notionals.ts       # NOTIONAL_TIERS_USD + DEFAULT_NOTIONAL_USD (WHI-841)
    sections/          # one module per section (blue-chips / stocks / others)
    navigation.ts      # pre-created nav — section PRs must not edit this
  hooks/
    useQuotes.ts       # TanStack Query polling + manual refresh
    useNotionalSize.ts # ?size= URL round-trip for the size selector (WHI-841)
  lib/
    api.ts             # thin fetch client (fetchQuotes + multi-notional helper)
    api-types.ts       # generated
    notionalSize.ts    # pure resolveNotionalSize for ?size=
    matrixDetail.ts    # single-size Effective/Fees cell view-model
    summary.ts         # best-venue-per-tier rule (WHI-799 §5.2)
    status.ts          # status render SSOT
```

Section pages should only edit their own `config/sections/<id>.ts` and page
content for product data — not nav. Shared additive seams used by all sections
live in `config/sections/types.ts`, `config/sections/helpers.ts`,
`lib/summary.ts`, and occasionally `SpreadMatrix` / `SizeSelector` when every
section needs the same UI control (WHI-841 size selector).

## Data fetching

**TanStack Query** (not SWR): explicit query keys and first-class `refetch` for
the manual refresh button. Section matrices fetch **one notional at a time**
via the page-level size selector (`?size=`, WHI-841) — one `GET /quotes` per
asset, not per asset × tier. `fetchQuotesMultiNotional` remains for any caller
that still needs multi-tier fan-out. Default poll: 15s hook default
(`DEFAULT_POLL_MS`); blue-chips / stocks / others override to 30s via
`section.pollIntervalMs`.

## Status rendering

Documented live at `/status-fixtures`. Covers all five `Quote.status` values
plus `gas_unknown` and `mid_stale` (WHI-799 §5.2 / §6.2).
