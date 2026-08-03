/**
 * Static US equity market hours helper (Phase 1 — WHI-810).
 *
 * Regular session: Mon–Fri 09:30–16:00 America/New_York.
 * Holidays: fixed calendar dates (no exchange feed). Good enough for
 * annotating that tokenized stocks trade 24/7 while the underlying may
 * be closed — not for order routing.
 */

/** Regular session open (inclusive), Eastern. */
export const US_EQUITY_OPEN_MINUTES = 9 * 60 + 30;
/** Regular session close (exclusive), Eastern. */
export const US_EQUITY_CLOSE_MINUTES = 16 * 60;

/**
 * Major NYSE full-session holidays 2025–2027 (YYYY-MM-DD in Eastern date).
 * Half-days are treated as open for Phase 1 simplicity.
 *
 * Phase-1 static table — dates after 2027-12-31 are treated as ordinary
 * weekdays (no holiday). Refresh before 2028 if this util is still in use.
 */
export const US_EQUITY_HOLIDAYS_THROUGH = "2027-12-31";

export const US_EQUITY_HOLIDAYS: ReadonlySet<string> = new Set([
  // 2025
  "2025-01-01",
  "2025-01-20",
  "2025-02-17",
  "2025-04-18",
  "2025-05-26",
  "2025-06-19",
  "2025-07-04",
  "2025-09-01",
  "2025-11-27",
  "2025-12-25",
  // 2026
  "2026-01-01",
  "2026-01-19",
  "2026-02-16",
  "2026-04-03",
  "2026-05-25",
  "2026-06-19",
  "2026-07-03", // Independence Day observed
  "2026-09-07",
  "2026-11-26",
  "2026-12-25",
  // 2027
  "2027-01-01",
  "2027-01-18",
  "2027-02-15",
  "2027-03-26",
  "2027-05-31",
  "2027-06-18", // Juneteenth observed
  "2027-07-05", // Independence Day observed
  "2027-09-06",
  "2027-11-25",
  "2027-12-24", // Christmas observed
]);

export type NyCivilParts = {
  /** YYYY-MM-DD in America/New_York. */
  date: string;
  /** 0=Sun … 6=Sat (JS weekday). */
  weekday: number;
  /** Minutes since local midnight. */
  minutes: number;
};

const WEEKDAY_TO_JS: Readonly<Record<string, number>> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

/** Civil date/time parts in America/New_York for a UTC instant. */
export function nyCivilParts(now: Date = new Date()): NyCivilParts {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const bag: Record<string, string> = {};
  for (const part of fmt.formatToParts(now)) {
    if (part.type !== "literal") bag[part.type] = part.value;
  }
  const weekday = WEEKDAY_TO_JS[bag.weekday ?? ""] ?? 0;
  const hour = Number(bag.hour ?? "0");
  const minute = Number(bag.minute ?? "0");
  const date = `${bag.year}-${bag.month}-${bag.day}`;
  return {
    date,
    weekday,
    minutes: hour * 60 + minute,
  };
}

export function isUsEquityHoliday(
  dateYmd: string,
  holidays: ReadonlySet<string> = US_EQUITY_HOLIDAYS,
): boolean {
  return holidays.has(dateYmd);
}

/**
 * True when the US equity cash market is in regular session
 * (weekday, not holiday, 09:30 ≤ t < 16:00 Eastern).
 */
export function isUsEquityMarketOpen(
  now: Date = new Date(),
  holidays: ReadonlySet<string> = US_EQUITY_HOLIDAYS,
): boolean {
  const parts = nyCivilParts(now);
  if (parts.weekday === 0 || parts.weekday === 6) return false;
  if (isUsEquityHoliday(parts.date, holidays)) return false;
  return (
    parts.minutes >= US_EQUITY_OPEN_MINUTES &&
    parts.minutes < US_EQUITY_CLOSE_MINUTES
  );
}

export type UsMarketHoursStatus = {
  open: boolean;
  /** Short UI label, e.g. "US market closed". */
  label: string;
  /** Longer explanation for tooltip / detail. */
  detail: string;
};

export function usMarketHoursStatus(
  now: Date = new Date(),
  holidays: ReadonlySet<string> = US_EQUITY_HOLIDAYS,
): UsMarketHoursStatus {
  const open = isUsEquityMarketOpen(now, holidays);
  if (open) {
    return {
      open: true,
      label: "US market open",
      detail:
        "NYSE regular session (09:30–16:00 ET). Tokenized stocks still trade 24/7 on-chain and on CEX.",
    };
  }
  return {
    open: false,
    label: "US market closed",
    detail:
      "Underlying US equities are outside the regular session. Tokenized stocks trade 24/7 — off-hours spreads can widen versus the cash market.",
  };
}
