/**
 * Thin typed fetch client for the spread-comparison-tools backend (WHI-807).
 *
 * Types come from `api-types.ts` (openapi-typescript). Do not hand-write
 * parallel response shapes — regenerate with `pnpm gen:api`.
 */

import type { components, paths } from "@/lib/api-types";

export type QuotesResponse = components["schemas"]["QuotesResponse"];
export type VenueResponse = components["schemas"]["VenueResponse"];
export type AssetResponse = components["schemas"]["AssetResponse"];
export type FeeSchedule = components["schemas"]["FeeSchedule"];
export type FeeTier = components["schemas"]["FeeTier"];
export type SizeQuotePair = components["schemas"]["SizeQuotePair"];
export type Quote = components["schemas"]["Quote"];
export type TopOfBook = components["schemas"]["TopOfBook"];
export type ReferenceMid = components["schemas"]["ReferenceMid"];
export type SimulateRequest = components["schemas"]["SimulateRequest"];
export type SimulateResponse = components["schemas"]["SimulateResponse"];
export type SimulateRowResponse = components["schemas"]["SimulateRowResponse"];
export type SimulatePairsResponse = components["schemas"]["SimulatePairsResponse"];
export type SimulatePairErrorDetail =
  components["schemas"]["SimulatePairErrorDetail"];
export type FeeBreakdown = components["schemas"]["FeeBreakdown"];

export type QuotesQuery = NonNullable<
  paths["/quotes"]["get"]["parameters"]["query"]
>;

/**
 * Instrument type accepted by `GET /quotes`, derived from the generated
 * OpenAPI types — never hand-written, so a backend enum change surfaces as a
 * type error here instead of a silently stale union.
 */
export type InstrumentType = NonNullable<QuotesQuery["instrument_type"]>;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Backend base URL (no trailing slash). Browser default: localhost:8000. */
export function getApiBaseUrl(): string {
  const raw =
    process.env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";
  return raw.replace(/\/+$/, "");
}

type FetchOptions = {
  signal?: AbortSignal;
};

function buildUrl(
  path: string,
  query?: Record<string, string | undefined | null>,
): URL {
  // Preserve any path prefix on the base (e.g. https://host/api + /quotes).
  const base = getApiBaseUrl();
  const joined = `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
  const url = new URL(joined);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, v);
      }
    }
  }
  return url;
}

function parseResponseBody(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * Unwrap FastAPI error bodies: `{detail: string | {message} | ValidationError[]}`.
 * Exported so simulateView (and callers) share one walk instead of re-deriving.
 */
export function unwrapApiDetail(body: unknown): {
  message: string | null;
  detail: unknown;
} {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return { message: null, detail: null };
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return { message: detail, detail };
  }
  if (Array.isArray(detail)) {
    // Pydantic / HTTPValidationError: list of {loc, msg, type}.
    const first = detail[0] as { msg?: unknown } | undefined;
    if (first && typeof first.msg === "string") {
      return { message: first.msg, detail };
    }
    return { message: "Request validation failed", detail };
  }
  if (
    typeof detail === "object" &&
    detail !== null &&
    "message" in detail &&
    typeof (detail as { message: unknown }).message === "string"
  ) {
    return { message: (detail as { message: string }).message, detail };
  }
  return { message: null, detail };
}

function errorDetailMessage(body: unknown, fallback: string): string {
  const { message } = unwrapApiDetail(body);
  return message ?? fallback;
}

async function apiGet<T>(
  path: string,
  query?: Record<string, string | undefined | null>,
  options: FetchOptions = {},
): Promise<T> {
  const url = buildUrl(path, query);

  const res = await fetch(url.toString(), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
    cache: "no-store",
  });

  const body = parseResponseBody(await res.text());

  if (!res.ok) {
    throw new ApiError(
      `GET ${url.pathname} failed: ${res.status} ${errorDetailMessage(body, res.statusText)}`,
      res.status,
      body,
    );
  }

  return body as T;
}

async function apiPost<T>(
  path: string,
  payload: unknown,
  options: FetchOptions = {},
): Promise<T> {
  const url = buildUrl(path);

  const res = await fetch(url.toString(), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: options.signal,
    cache: "no-store",
  });

  const body = parseResponseBody(await res.text());

  if (!res.ok) {
    throw new ApiError(
      `POST ${url.pathname} failed: ${res.status} ${errorDetailMessage(body, res.statusText)}`,
      res.status,
      body,
    );
  }

  return body as T;
}

/** `GET /quotes` — one asset × one notional, optional venue/side filters. */
export async function fetchQuotes(
  params: {
    asset: string;
    notional: string | number;
    venues?: readonly string[] | string;
    side?: "buy" | "sell";
    instrument_type?: InstrumentType;
  },
  options?: FetchOptions,
): Promise<QuotesResponse> {
  const venues =
    params.venues === undefined
      ? undefined
      : Array.isArray(params.venues)
        ? params.venues.join(",")
        : params.venues;

  const query: Record<string, string | undefined | null> = {
    asset: params.asset,
    notional: String(params.notional),
    venues: typeof venues === "string" ? venues : undefined,
    side: params.side,
    instrument_type: params.instrument_type,
  };

  return apiGet<QuotesResponse>("/quotes", query, options);
}

/**
 * `GET /quotes` multi-tier package (WHI-843) — one request, shared snapshot/mid.
 * Prefer this over N single-notional calls so orderbook venues fetch once.
 */
export async function fetchQuotesMultiTier(
  params: {
    asset: string;
    notionals: readonly (string | number)[];
    venues?: readonly string[] | string;
    side?: "buy" | "sell";
    instrument_type?: InstrumentType;
  },
  options?: FetchOptions,
): Promise<QuotesResponse> {
  if (params.notionals.length === 0) {
    throw new ApiError("notionals must be non-empty", 422, null);
  }
  // Single tier: keep the legacy `notional` param for back-compat clients.
  if (params.notionals.length === 1) {
    return fetchQuotes(
      {
        asset: params.asset,
        notional: params.notionals[0]!,
        venues: params.venues,
        side: params.side,
        instrument_type: params.instrument_type,
      },
      options,
    );
  }

  const venues =
    params.venues === undefined
      ? undefined
      : Array.isArray(params.venues)
        ? params.venues.join(",")
        : params.venues;

  const query: Record<string, string | undefined | null> = {
    asset: params.asset,
    notionals: params.notionals.map(String).join(","),
    venues: typeof venues === "string" ? venues : undefined,
    side: params.side,
    instrument_type: params.instrument_type,
  };

  return apiGet<QuotesResponse>("/quotes", query, options);
}

/**
 * Quotes across notional tiers for the matrix.
 *
 * WHI-843: one multi-tier request (shared snapshot). Falls back to the
 * response shape expected by `useQuotesMatrix`.
 */
export async function fetchQuotesMultiNotional(
  params: {
    asset: string;
    notionals: readonly (string | number)[];
    venues?: readonly string[] | string;
    side?: "buy" | "sell";
    instrument_type?: InstrumentType;
  },
  options?: FetchOptions,
): Promise<{
  asset: string;
  pairs: SizeQuotePair[];
  mids: ReferenceMid[];
  snapshotIds: string[];
}> {
  const body = await fetchQuotesMultiTier(params, options);
  return {
    asset: params.asset,
    pairs: body.pairs,
    mids: [body.mid],
    snapshotIds: [body.snapshot_id],
  };
}

/** `GET /venues` */
export async function fetchVenues(
  options?: FetchOptions,
): Promise<VenueResponse[]> {
  return apiGet<VenueResponse[]>("/venues", undefined, options);
}

/** `GET /assets` */
export async function fetchAssets(
  options?: FetchOptions,
): Promise<AssetResponse[]> {
  return apiGet<AssetResponse[]>("/assets", undefined, options);
}

/** `GET /fees` — all validated venue fee schedules (WHI-812; UI in WHI-813). */
export async function fetchFees(
  options?: FetchOptions,
): Promise<FeeSchedule[]> {
  return apiGet<FeeSchedule[]>("/fees", undefined, options);
}

/**
 * `GET /simulate/pairs` — tradeable stables × catalog assets for pair pickers
 * (WHI-833). Do not hardcode USDC/USDT; this list is the SSOT.
 */
export async function fetchSimulatePairs(
  options?: FetchOptions,
): Promise<SimulatePairsResponse> {
  return apiGet<SimulatePairsResponse>("/simulate/pairs", undefined, options);
}

/**
 * `POST /simulate` — free-form pair trade fan-out ranked by expected output
 * (WHI-814; UI in WHI-815). Amount is in sell-asset units.
 */
export async function postSimulate(
  body: SimulateRequest,
  options?: FetchOptions,
): Promise<SimulateResponse> {
  return apiPost<SimulateResponse>("/simulate", body, options);
}
