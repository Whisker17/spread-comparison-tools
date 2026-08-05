/**
 * Pure helpers for the WHI-848 quote WebSocket wire format.
 * No React / browser APIs beyond URL construction.
 */

import type {
  InstrumentType,
  QuotesResponse,
  ReferenceMid,
  SizeQuotePair,
} from "@/lib/api";
import { getApiBaseUrl } from "@/lib/api";

export type StreamConnectionStatus = "connecting" | "live" | "reconnecting";

export type StreamFilter = {
  assets: readonly string[];
  notionals: readonly (string | number)[];
  venues?: readonly string[];
  side?: "buy" | "sell";
  instrument_type?: InstrumentType;
};

export type StreamSubscribeMessage =
  | {
      type: "subscribe";
      assets: string[];
      notionals: string[];
      venues?: string[];
      side?: "buy" | "sell";
      instrument_type?: InstrumentType;
    }
  | {
      type: "subscribe";
      filters: Array<{
        assets: string[];
        notionals: string[];
        venues?: string[];
        side?: "buy" | "sell";
        instrument_type?: InstrumentType;
      }>;
    };

export type AssetQuotesState = {
  asset: string;
  pairs: SizeQuotePair[];
  /** Package-level mid from the latest snapshot/delta (for meta). */
  mid: ReferenceMid | null;
  /** Package-level snapshot id (rows may carry different per-row ids). */
  packageSnapshotId: string | null;
  /** Distinct row snapshot_ids present in pairs (mixed ages are normal). */
  rowSnapshotIds: string[];
};

export type StreamHello = {
  type: "hello";
  coalesce_interval_ms: number;
  heartbeat_interval_sec: number;
  client_liveness_timeout_sec: number;
};

export type StreamServerMessage =
  | StreamHello
  | {
      type: "snapshot";
      asset: string;
      data: QuotesResponse;
    }
  | {
      type: "delta";
      asset: string;
      snapshot_id: string;
      mid: ReferenceMid;
      pairs: SizeQuotePair[];
      removed: string[];
      notionals?: string[];
    }
  | { type: "heartbeat"; ts: number }
  | { type: "pong" }
  | { type: "error"; code: string; message: string; asset?: string }
  | { type: "ping" };

/** Convert HTTP API base URL to a WebSocket URL for `/stream`. */
export function streamUrl(apiBase: string = getApiBaseUrl()): string {
  const base = apiBase.replace(/\/+$/, "");
  const u = new URL(base);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  // Preserve path prefix (e.g. https://host/api → wss://host/api/stream).
  const path = u.pathname.replace(/\/+$/, "");
  u.pathname = `${path}/stream`.replace(/\/{2,}/g, "/");
  return u.toString();
}

export function pairIdentityKey(pair: SizeQuotePair): string {
  return `${pair.venue}|${pair.notional_usd}|${pair.instrument_type}`;
}

export function emptyAssetState(asset: string): AssetQuotesState {
  return {
    asset: asset.toUpperCase(),
    pairs: [],
    mid: null,
    packageSnapshotId: null,
    rowSnapshotIds: [],
  };
}

function collectRowSnapshotIds(pairs: readonly SizeQuotePair[]): string[] {
  const ids = new Set<string>();
  for (const p of pairs) {
    ids.add(p.snapshot_id);
    if (p.buy?.snapshot_id) ids.add(p.buy.snapshot_id);
    if (p.sell?.snapshot_id) ids.add(p.sell.snapshot_id);
  }
  return [...ids];
}

/** Apply a full snapshot for one asset. */
export function applySnapshot(
  prev: Readonly<Record<string, AssetQuotesState>>,
  asset: string,
  data: QuotesResponse,
): Record<string, AssetQuotesState> {
  const key = asset.toUpperCase();
  const pairs = data.pairs ?? [];
  return {
    ...prev,
    [key]: {
      asset: key,
      pairs,
      mid: data.mid ?? null,
      packageSnapshotId: data.snapshot_id ?? null,
      rowSnapshotIds: collectRowSnapshotIds(pairs),
    },
  };
}

/**
 * Merge a delta into existing asset state.
 * `removed` entries are identity keys (`venue|notional|instrument`).
 */
export function applyDelta(
  prev: Readonly<Record<string, AssetQuotesState>>,
  msg: Extract<StreamServerMessage, { type: "delta" }>,
): Record<string, AssetQuotesState> {
  const key = msg.asset.toUpperCase();
  const current = prev[key] ?? emptyAssetState(key);
  const map = new Map(
    current.pairs.map((p) => [pairIdentityKey(p), p] as const),
  );
  for (const id of msg.removed ?? []) {
    map.delete(id);
  }
  for (const pair of msg.pairs ?? []) {
    map.set(pairIdentityKey(pair), pair);
  }
  const pairs = [...map.values()];
  return {
    ...prev,
    [key]: {
      asset: key,
      pairs,
      mid: msg.mid ?? current.mid,
      packageSnapshotId: msg.snapshot_id ?? current.packageSnapshotId,
      rowSnapshotIds: collectRowSnapshotIds(pairs),
    },
  };
}

/** Apply any server message that mutates asset state; ignore control frames. */
export function applyServerMessage(
  prev: Readonly<Record<string, AssetQuotesState>>,
  raw: unknown,
): {
  next: Record<string, AssetQuotesState>;
  kind: StreamServerMessage["type"] | "unknown";
  error?: { code: string; message: string };
} {
  if (typeof raw !== "object" || raw === null || !("type" in raw)) {
    return { next: { ...prev }, kind: "unknown" };
  }
  const msg = raw as StreamServerMessage;
  switch (msg.type) {
    case "snapshot":
      return {
        next: applySnapshot(prev, msg.asset, msg.data),
        kind: "snapshot",
      };
    case "delta":
      return { next: applyDelta(prev, msg), kind: "delta" };
    case "error":
      return {
        next: { ...prev },
        kind: "error",
        error: { code: msg.code, message: msg.message },
      };
    case "hello":
    case "heartbeat":
    case "pong":
    case "ping":
      return { next: { ...prev }, kind: msg.type };
    default:
      return { next: { ...prev }, kind: "unknown" };
  }
}

/** Build the outbound subscribe payload from one or more filters. */
export function buildSubscribeMessage(
  filters: readonly StreamFilter[],
): StreamSubscribeMessage {
  if (filters.length === 0) {
    throw new Error("at least one stream filter is required");
  }
  if (filters.length === 1) {
    const f = filters[0]!;
    return {
      type: "subscribe",
      assets: f.assets.map((a) => a.toUpperCase()),
      notionals: f.notionals.map(String),
      venues: f.venues ? [...f.venues] : undefined,
      side: f.side,
      instrument_type: f.instrument_type,
    };
  }
  return {
    type: "subscribe",
    filters: filters.map((f) => ({
      assets: f.assets.map((a) => a.toUpperCase()),
      notionals: f.notionals.map(String),
      venues: f.venues ? [...f.venues] : undefined,
      side: f.side,
      instrument_type: f.instrument_type,
    })),
  };
}

/**
 * Reconnect delay with linear backoff capped at maxMs.
 * attempt 0 → baseMs, 1 → 2*baseMs, …
 */
export function reconnectDelayMs(
  attempt: number,
  baseMs = 1000,
  maxMs = 10_000,
): number {
  const n = Math.max(0, attempt);
  return Math.min(maxMs, baseMs * (n + 1));
}

/** Shape used by AssetSpreadBlock / useQuotesMatrix consumers. */
export function toQuotesMatrixData(state: AssetQuotesState | undefined): {
  asset: string;
  pairs: SizeQuotePair[];
  mids: ReferenceMid[];
  snapshotIds: string[];
} | undefined {
  if (!state) return undefined;
  return {
    asset: state.asset,
    pairs: state.pairs,
    mids: state.mid ? [state.mid] : [],
    // Prefer distinct row ids so mixed-age packages are visible; fall back
    // to package id when pairs are empty.
    snapshotIds:
      state.rowSnapshotIds.length > 0
        ? state.rowSnapshotIds
        : state.packageSnapshotId
          ? [state.packageSnapshotId]
          : [],
  };
}
