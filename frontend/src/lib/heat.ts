/**
 * Heat coloring for bps cells: lower total cost = cooler (green), higher = warmer (red).
 * Pure function of the value and the min/max among comparable cells in the same matrix.
 */

import { parseDecimal } from "@/lib/format";

export type HeatRange = { min: number; max: number };

/** Build min/max over finite numbers (nulls ignored). */
export function heatRange(values: readonly (number | null | undefined)[]): HeatRange | null {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const v of values) {
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  return { min, max };
}

/**
 * Return a Tailwind-ish background class for a bps value.
 * Null range or null value → neutral.
 */
export function heatClass(
  value: number | string | null | undefined,
  range: HeatRange | null,
): string {
  const n = typeof value === "string" ? parseDecimal(value) : value ?? null;
  if (n === null || range === null) {
    return "bg-transparent";
  }
  const span = range.max - range.min;
  if (span <= 0) {
    return "bg-emerald-500/15";
  }
  // 0 = best (green), 1 = worst (red)
  const t = Math.min(1, Math.max(0, (n - range.min) / span));
  if (t < 0.25) return "bg-emerald-500/25";
  if (t < 0.5) return "bg-emerald-500/10";
  if (t < 0.75) return "bg-amber-500/15";
  return "bg-rose-500/20";
}
