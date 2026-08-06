/**
 * Pair / row identity helpers for form-aware matrices (WHI-881 / WHI-882).
 *
 * Backend stream identity is `venue|notional|instrument|form` (WHI-881).
 * Matrix row identity collapses notional and is `venue` (crypto) or
 * `venue|form` (stocks).
 */

export type FormClass = "perp" | "tokenized";

const TOKENIZED_FORMS = new Set([
  "bstock",
  "ondo",
  "xstock",
  "xstock_cex",
]);

/** Map stock form id → form_class (WHI-798 §4.6 / WHI-799 §5.2). */
export function formClassOf(
  form: string | null | undefined,
): FormClass | null {
  if (form == null || form === "") return null;
  const key = form.toLowerCase();
  if (key === "perp") return "perp";
  if (TOKENIZED_FORMS.has(key)) return "tokenized";
  return null;
}

/** Build a row key from venue + optional form. */
export function makeRowKey(venue: string, form?: string | null): string {
  if (form != null && form !== "") {
    return `${venue}|${form}`;
  }
  return venue;
}

/**
 * Matrix / TOB row key for a quote pair.
 * Non-stocks (form null) stay venue-only so existing boards are unchanged.
 */
export function pairRowKey(pair: {
  venue: string;
  form?: string | null;
}): string {
  return makeRowKey(pair.venue, pair.form);
}

/** Parse a row key back into venue + form (form null when absent). */
export function parseRowKey(rowKey: string): {
  venue: string;
  form: string | null;
} {
  const sep = rowKey.indexOf("|");
  if (sep < 0) {
    return { venue: rowKey, form: null };
  }
  return {
    venue: rowKey.slice(0, sep),
    form: rowKey.slice(sep + 1) || null,
  };
}

/**
 * Stream / delta merge identity — must match backend
 * `spread_compare.stream.pair_identity_key`.
 */
export function pairIdentityKey(pair: {
  venue: string;
  notional_usd: string | number;
  instrument_type: string;
  form?: string | null;
}): string {
  return `${pair.venue}|${pair.notional_usd}|${pair.instrument_type}|${pair.form ?? "-"}`;
}

/** True when any pair carries a stock form (trigger form_class best grouping). */
export function pairsHaveForms(
  pairs: readonly { form?: string | null }[],
): boolean {
  return pairs.some((p) => p.form != null && p.form !== "");
}
