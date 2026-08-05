"use client";

/**
 * Page-level quote WebSocket (WHI-848).
 *
 * One connection per provider; section pages wrap their asset blocks so the
 * dashboard issues zero periodic GET /quotes. Manual resnapshot re-requests
 * a full snapshot over the same socket (no upstream fan-out force).
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { QuotesMatrixData } from "@/hooks/useQuotes";
import {
  applyServerMessage,
  buildSubscribeMessage,
  reconnectDelayMs,
  streamUrl,
  toQuotesMatrixData,
  type AssetQuotesState,
  type StreamConnectionStatus,
  type StreamFilter,
} from "@/lib/streamQuotes";

/** Default client liveness window — must exceed server heartbeat (15s). */
export const DEFAULT_LIVENESS_TIMEOUT_MS = 45_000;
export const DEFAULT_RECONNECT_BASE_MS = 1_000;

export type QuotesStreamValue = {
  status: StreamConnectionStatus;
  byAsset: Readonly<Record<string, AssetQuotesState>>;
  /** Matrix-shaped data for one asset (undefined until first snapshot). */
  matrixFor: (asset: string) => QuotesMatrixData | undefined;
  /** Request full snapshots (Refresh button). */
  resnapshot: (assets?: readonly string[]) => void;
  lastError: string | null;
  /** True once at least one snapshot has arrived for `asset`. */
  hasAsset: (asset: string) => boolean;
};

const QuotesStreamContext = createContext<QuotesStreamValue | null>(null);

export type QuotesStreamProviderProps = {
  filters: readonly StreamFilter[];
  children: ReactNode;
  /** Override stream URL (tests). */
  url?: string;
  livenessTimeoutMs?: number;
  reconnectBaseMs?: number;
  /** Disable auto-connect (tests). */
  enabled?: boolean;
};

type SocketHandle = {
  send: (payload: string) => void;
  ready: boolean;
};

export function QuotesStreamProvider({
  filters,
  children,
  url,
  livenessTimeoutMs = DEFAULT_LIVENESS_TIMEOUT_MS,
  reconnectBaseMs = DEFAULT_RECONNECT_BASE_MS,
  enabled = true,
}: QuotesStreamProviderProps) {
  const [status, setStatus] = useState<StreamConnectionStatus>(
    enabled ? "connecting" : "reconnecting",
  );
  const [byAsset, setByAsset] = useState<Record<string, AssetQuotesState>>({});
  const [lastError, setLastError] = useState<string | null>(null);
  // Socket handle is state so senders re-bind without reading refs during render.
  const [socket, setSocket] = useState<SocketHandle | null>(null);
  // Server-driven via hello; ref so updates do not re-run the connect effect.
  const livenessMsRef = useRef(livenessTimeoutMs);
  const byAssetRef = useRef(byAsset);
  useEffect(() => {
    byAssetRef.current = byAsset;
  }, [byAsset]);

  const subscribePayload = useMemo(
    () => JSON.stringify(buildSubscribeMessage(filters)),
    [filters],
  );
  // Keep latest payload in a ref so the connect effect does not re-open the
  // socket when only the size filter changes (WHI-864).
  const subscribePayloadRef = useRef(subscribePayload);
  useEffect(() => {
    subscribePayloadRef.current = subscribePayload;
  }, [subscribePayload]);

  const resnapshot = useCallback(
    (assets?: readonly string[]) => {
      if (!socket?.ready) return;
      const body =
        assets && assets.length > 0
          ? {
              type: "resnapshot",
              assets: assets.map((a) => a.toUpperCase()),
            }
          : { type: "resnapshot" };
      socket.send(JSON.stringify(body));
    },
    [socket],
  );

  // Re-subscribe on the live socket when filters change (size switch).
  useEffect(() => {
    if (!socket?.ready) return;
    socket.send(subscribePayload);
  }, [socket, subscribePayload]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let stopped = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let lastMsgAt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let livenessTimer: ReturnType<typeof setInterval> | null = null;

    const clearTimers = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (livenessTimer) {
        clearInterval(livenessTimer);
        livenessTimer = null;
      }
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      setStatus("reconnecting");
      setSocket(null);
      const delay = reconnectDelayMs(attempt, reconnectBaseMs);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      if (stopped) return;
      clearTimers();
      if (ws) {
        try {
          ws.onopen = null;
          ws.onmessage = null;
          ws.onclose = null;
          ws.onerror = null;
          ws.close();
        } catch {
          /* ignore */
        }
        ws = null;
      }

      setStatus((s) => (s === "live" ? "reconnecting" : "connecting"));
      const target = url ?? streamUrl();
      try {
        ws = new WebSocket(target);
      } catch (err) {
        setLastError(err instanceof Error ? err.message : String(err));
        scheduleReconnect();
        return;
      }

      const active = ws;
      active.onopen = () => {
        lastMsgAt = Date.now();
        attempt = 0;
        // Subscribe is owned by the filter-change effect (fires when socket
        // becomes ready) so we never double-send on open (WHI-864).
        setSocket({
          ready: true,
          send: (payload: string) => {
            if (active.readyState === WebSocket.OPEN) {
              active.send(payload);
            }
          },
        });
        livenessTimer = setInterval(() => {
          const silent = Date.now() - lastMsgAt;
          const timeout = livenessMsRef.current || livenessTimeoutMs;
          if (silent > timeout) {
            setStatus("reconnecting");
            try {
              active.close();
            } catch {
              /* ignore */
            }
          }
        }, Math.min(5_000, livenessTimeoutMs / 3));
      };

      active.onmessage = (ev) => {
        lastMsgAt = Date.now();
        let parsed: unknown;
        try {
          parsed = JSON.parse(String(ev.data)) as unknown;
        } catch {
          return;
        }
        if (typeof parsed === "object" && parsed !== null && "type" in parsed) {
          const t = (parsed as { type: string }).type;
          if (t === "ping") {
            if (active.readyState === WebSocket.OPEN) {
              active.send(JSON.stringify({ type: "pong" }));
            }
            return;
          }
          if (t === "hello") {
            const sec = (parsed as { client_liveness_timeout_sec?: number })
              .client_liveness_timeout_sec;
            if (typeof sec === "number" && sec > 0) {
              livenessMsRef.current = sec * 1000;
            }
            return;
          }
        }
        const applied = applyServerMessage(byAssetRef.current, parsed);
        byAssetRef.current = applied.next;
        setByAsset(applied.next);
        if (applied.error) {
          setLastError(`${applied.error.code}: ${applied.error.message}`);
        }
        if (applied.kind === "snapshot" || applied.kind === "delta") {
          setStatus("live");
        } else if (applied.kind === "heartbeat") {
          setStatus((s) => (s === "connecting" ? "connecting" : "live"));
        }
      };

      active.onerror = () => {
        setLastError("WebSocket error");
      };

      active.onclose = () => {
        setSocket(null);
        clearTimers();
        if (!stopped) {
          // Full resnapshot on reconnect: clear state so stale rows cannot linger.
          setByAsset({});
          scheduleReconnect();
        }
      };
    };

    connect();

    return () => {
      stopped = true;
      clearTimers();
      setSocket(null);
      if (ws) {
        try {
          ws.onclose = null;
          ws.close();
        } catch {
          /* ignore */
        }
      }
    };
  }, [enabled, url, livenessTimeoutMs, reconnectBaseMs]);

  const matrixFor = useCallback(
    (asset: string): QuotesMatrixData | undefined =>
      toQuotesMatrixData(byAsset[asset.toUpperCase()]),
    [byAsset],
  );

  const hasAsset = useCallback(
    (asset: string) => Boolean(byAsset[asset.toUpperCase()]?.pairs.length),
    [byAsset],
  );

  const value = useMemo<QuotesStreamValue>(
    () => ({
      status,
      byAsset,
      matrixFor,
      resnapshot,
      lastError,
      hasAsset,
    }),
    [status, byAsset, matrixFor, resnapshot, lastError, hasAsset],
  );

  return createElement(
    QuotesStreamContext.Provider,
    { value },
    children,
  );
}

export function useQuotesStream(): QuotesStreamValue {
  const ctx = useContext(QuotesStreamContext);
  if (!ctx) {
    throw new Error("useQuotesStream requires QuotesStreamProvider");
  }
  return ctx;
}

export function useQuotesStreamOptional(): QuotesStreamValue | null {
  return useContext(QuotesStreamContext);
}

/**
 * Asset-level view of the page stream, shaped like the former poll hook so
 * AssetSpreadBlock can swap transport without rewriting render logic.
 */
export function useStreamAssetQuotes(asset: string): {
  data: QuotesMatrixData | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  error: Error | null;
  status: StreamConnectionStatus;
  refetch: () => void;
  dataUpdatedAt: number;
} {
  const stream = useQuotesStream();
  const data = stream.matrixFor(asset);
  const isLoading =
    (stream.status === "connecting" || stream.status === "reconnecting") &&
    !data;
  const isError =
    stream.status === "reconnecting" && !data && Boolean(stream.lastError);
  return {
    data,
    isLoading,
    isFetching: stream.status === "connecting",
    isError,
    error: stream.lastError ? new Error(stream.lastError) : null,
    status: stream.status,
    refetch: () => stream.resnapshot([asset]),
    dataUpdatedAt: data ? 1 : 0,
  };
}
