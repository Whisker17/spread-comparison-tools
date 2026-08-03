/**
 * Thin typed fetch client for the spread-comparison-tools backend (WHI-807).
 *
 * Types come from `api-types.ts` (openapi-typescript). Do not hand-write
 * parallel response shapes — regenerate with `pnpm gen:api`.
 *
 * `/simulate` remains a stub until M5 (WHI-814 / WHI-815).
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

export type QuotesQuery = NonNullable<
  paths["/quotes"]["get"]["parameters"]["query"]
>;

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

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const detail =
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      (body as { detail: unknown }).detail !== undefined
        ? String((body as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(
      `GET ${url.pathname} failed: ${res.status} ${detail}`,
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
    instrument_type?: "spot" | "perp" | "amm_pool" | "prop_amm";
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
 * Fan out `/quotes` across notional tiers (matrix needs all four).
 * Failures on individual tiers surface as rejected Promise (caller handles).
 */
export async function fetchQuotesMultiNotional(
  params: {
    asset: string;
    notionals: readonly (string | number)[];
    venues?: readonly string[] | string;
    side?: "buy" | "sell";
    instrument_type?: "spot" | "perp" | "amm_pool" | "prop_amm";
  },
  options?: FetchOptions,
): Promise<{
  asset: string;
  pairs: SizeQuotePair[];
  mids: ReferenceMid[];
  snapshotIds: string[];
}> {
  const settled = await Promise.allSettled(
    params.notionals.map((notional) =>
      fetchQuotes(
        {
          asset: params.asset,
          notional,
          venues: params.venues,
          side: params.side,
          instrument_type: params.instrument_type,
        },
        options,
      ),
    ),
  );

  const ok = settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  if (ok.length === 0) {
    const first = settled.find((r) => r.status === "rejected");
    const reason =
      first && first.status === "rejected" ? first.reason : undefined;
    throw reason instanceof Error
      ? reason
      : new ApiError("all notional tiers failed", 502, reason);
  }

  return {
    asset: params.asset,
    pairs: ok.flatMap((r) => r.pairs),
    mids: ok.map((r) => r.mid),
    snapshotIds: ok.map((r) => r.snapshot_id),
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

/** M5 stub shape — WHI-815 will fill the real `/simulate` contract. */
export type SimulateRequest = {
  asset: string;
  notional_usd: string | number;
  side: "buy" | "sell";
  venues?: readonly string[];
};

/** Placeholder until WHI-815 ships `POST /simulate`. */
export async function postSimulate(
  ..._args: [SimulateRequest, FetchOptions?]
): Promise<never> {
  void _args;
  throw new ApiError(
    "POST /simulate not implemented yet (WHI-815). Stub keeps the client seam ready.",
    501,
    null,
  );
}
