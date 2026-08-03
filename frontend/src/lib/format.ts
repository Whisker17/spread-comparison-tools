/**
 * Display formatters. API bps keep 4 decimal places; UI shows 2 (WHI-799 §9).
 */

/** Format a bps value for display (2 decimal places). Null/undefined → "—". */
export function formatBps(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) {
    return "—";
  }
  return n.toFixed(2);
}

/** Parse API decimal string/number to finite number, or null. */
export function parseDecimal(
  value: string | number | null | undefined,
): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Sort notional tier strings ascending by numeric value. */
export function sortNotionals(notionals: readonly string[]): string[] {
  return [...notionals].sort(
    (a, b) => (parseDecimal(a) ?? 0) - (parseDecimal(b) ?? 0),
  );
}

/** Lexicographic slug / id comparator (matches summary.ts venue tiebreak). */
export function compareSlug(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Compact USD notional labels ($1k / $10k / $100k / $1M). */
export function formatNotional(usd: string | number): string {
  const n = typeof usd === "number" ? usd : Number(usd);
  if (!Number.isFinite(n)) {
    return String(usd);
  }
  if (n >= 1_000_000) {
    return `$${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (n >= 1_000) {
    return `$${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}k`;
  }
  return `$${n}`;
}

/** Format an ISO timestamp for compact UI. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleString(undefined, {
    hour12: false,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Format a mid/effective price with sensible precision. */
export function formatPrice(value: string | number | null | undefined): string {
  const n = parseDecimal(value);
  if (n === null) {
    return "—";
  }
  if (n >= 1000) {
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  if (n >= 1) {
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });
}
