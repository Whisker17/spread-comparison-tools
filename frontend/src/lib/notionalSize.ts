/**
 * Size-selector URL resolution (WHI-841 / WHI-864).
 *
 * Pure helpers so URL round-trip / fallback rules are unit-testable without
 * mounting Next.js navigation hooks.
 *
 * WHI-864: one tier at a time always — no multi-column ``all`` view. Stale
 * ``?size=all`` links fall back to the section default.
 */

/** Query param key for the selected notional tier (USD string, e.g. "1000"). */
export const SIZE_QUERY_PARAM = "size";

/**
 * Resolve the active size view from a URL param against the allowed set.
 *
 * - Valid param that is in `allowed` → that tier
 * - Missing / invalid / legacy ``all`` → `defaultNotional` when allowed
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

/**
 * Matrix columns for the current size view: always a single focus tier.
 * Unknown sizes fall back to the first section tier.
 */
export function notionalsForSizeView(
  size: string,
  sectionNotionals: readonly string[],
): string[] {
  if (sectionNotionals.includes(size)) {
    return [size];
  }
  return sectionNotionals[0] != null ? [sectionNotionals[0]] : [];
}
