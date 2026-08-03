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
cp .env.example .env.local   # optional; defaults to http://localhost:8000
pnpm dev
```

Open http://localhost:3000 — `/` redirects to `/blue-chips`, which polls
`GET /quotes` for BTC across **all registered adapters** (empty `venues` filter).
Per-venue failures degrade to `status=error` / `no_quote` rather than failing the
page. Reference mid still needs a working mid source (Binance index by default);
without network, `/quotes` may 503. Section configs (WHI-809+) can pin `venues`
to a subset (e.g. `["mock"]`) when desired.

UI primitives under `src/components/ui/` follow the shadcn/new-york stack
(Radix + CVA + `cn`). `components.json` is checked in so section agents can run
`pnpm dlx shadcn@latest add <component>` without re-initializing.

Env:

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend origin (no trailing slash) |

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
  components/          # SpreadMatrix, TopOfBookRow, StatusCell, SummaryStrip, …
  config/
    sections/          # one module per section (blue-chips / stocks / others)
    navigation.ts      # pre-created nav — section PRs must not edit this
  hooks/useQuotes.ts   # TanStack Query polling + manual refresh
  lib/
    api.ts             # thin fetch client
    api-types.ts       # generated
    summary.ts         # best-venue-per-tier rule (WHI-799 §5.2)
    status.ts          # status render SSOT
```

Section pages (WHI-809/810/811) should only edit their own
`config/sections/<id>.ts` and page content — not `SpreadMatrix` or nav.

## Data fetching

**TanStack Query** (not SWR): explicit query keys, multi-notional fan-out for
the matrix, and first-class `refetch` for the manual refresh button. Default
poll interval: 15s (`DEFAULT_POLL_MS` in `hooks/useQuotes.ts`).

## Status rendering

Documented live at `/status-fixtures`. Covers all five `Quote.status` values
plus `gas_unknown` and `mid_stale` (WHI-799 §5.2 / §6.2).
