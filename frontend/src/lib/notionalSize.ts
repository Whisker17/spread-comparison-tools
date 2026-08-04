/**
 * Size-selector URL resolution (WHI-841).
 *
 * Pure helpers so URL round-trip / fallback rules are unit-testable without
 * mounting Next.js navigation hooks.
 */

/** Query param key for the selected notional tier (USD string, e.g. "1000"). */
export const SIZE_QUERY_PARAM = "size";

/**
 * Resolve the active notional from a URL param against the allowed set.
 *
 * - Valid param that is in `allowed` → that value
 * - Missing / invalid / not allowed → `defaultNotional` when allowed, else first allowed
 */
export function resolveNotionalSize(
  param: string | null | undefined,
  allowed: readonly string[],
  defaultNotional: string,
): string {
  if (param != null && param !== "" && allowed.includes(param)) {
    return param;
  }
  if (allowed.includes(defaultNotional)) {
    return defaultNotional;
  }
  return allowed[0] ?? defaultNotional;
}
