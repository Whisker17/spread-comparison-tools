/**
 * Size-selector URL resolution (WHI-841 / WHI-843).
 *
 * Pure helpers so URL round-trip / fallback rules are unit-testable without
 * mounting Next.js navigation hooks.
 *
 * WHI-843: ``all`` is a valid view preference — show every tier column from
 * one multi-tier `/quotes` response. A concrete tier narrows the matrix to
 * single-size focus (detail columns).
 */

/** Query param key for the selected notional tier (USD string, e.g. "1000"). */
export const SIZE_QUERY_PARAM = "size";

/** Sentinel for multi-column matrix view (all §4.1 tiers). */
export const SIZE_ALL = "all";

/**
 * Resolve the active size view from a URL param against the allowed set.
 *
 * - ``all`` → multi-column view
 * - Valid param that is in `allowed` → single-size focus
 * - Missing / invalid → `defaultNotional` when allowed (or ``all`` if default is all)
 */
export function resolveNotionalSize(
  param: string | null | undefined,
  allowed: readonly string[],
  defaultNotional: string,
): string {
  if (param === SIZE_ALL) {
    return SIZE_ALL;
  }
  if (param != null && param !== "" && allowed.includes(param)) {
    return param;
  }
  if (defaultNotional === SIZE_ALL) {
    return SIZE_ALL;
  }
  if (allowed.includes(defaultNotional)) {
    return defaultNotional;
  }
  return allowed[0] ?? defaultNotional;
}

/** Whether the size view is multi-column (all tiers). */
export function isSizeAll(size: string): boolean {
  return size === SIZE_ALL;
}

/**
 * Matrix columns for the current size view: all section tiers, or one focus.
 */
export function notionalsForSizeView(
  size: string,
  sectionNotionals: readonly string[],
): string[] {
  if (isSizeAll(size)) {
    return [...sectionNotionals];
  }
  return sectionNotionals.includes(size) ? [size] : [...sectionNotionals];
}
