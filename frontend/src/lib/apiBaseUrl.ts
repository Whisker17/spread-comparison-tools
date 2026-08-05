/**
 * Resolve and validate `NEXT_PUBLIC_API_URL` (WHI-857).
 *
 * Production builds must not bake a loopback origin into the client bundle —
 * every visitor's browser would call their own machine. Development keeps the
 * convenient localhost default.
 */

/** Dev-only fallback when the env var is unset. Never used in production. */
export const DEV_API_BASE_URL = "http://localhost:8000";

/**
 * True for hosts that resolve to the visitor's own machine.
 * Covers the issue's explicit list (localhost / 127.0.0.1 / ::1) plus the rest of
 * 127.0.0.0/8 and `*.localhost` (browsers map those to loopback too).
 */
export function isLoopbackHostname(hostname: string): boolean {
  // URL.hostname is unbracketed for IPv6; accept bracketed form too.
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (h === "localhost" || h.endsWith(".localhost") || h === "::1") {
    return true;
  }
  // 127.0.0.0/8
  const m = /^127\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (!m) return false;
  return m.slice(1).every((octet) => {
    const n = Number(octet);
    return n >= 0 && n <= 255;
  });
}

export type ResolveApiBaseUrlOptions = {
  /**
   * When true, unset and loopback origins throw (named-variable error).
   * Pass `process.env.NODE_ENV === "production"`.
   */
  isProduction: boolean;
};

/**
 * Normalize a backend origin for REST + derived WS URLs.
 *
 * - Non-production: empty/unset → `DEV_API_BASE_URL`.
 * - Production: empty/unset or loopback hostname → Error naming `NEXT_PUBLIC_API_URL`.
 * - Always strips trailing slashes.
 */
export function resolveApiBaseUrl(
  raw: string | undefined | null,
  options: ResolveApiBaseUrlOptions,
): string {
  const trimmed = typeof raw === "string" ? raw.trim() : "";
  if (!trimmed) {
    if (options.isProduction) {
      throw new Error(
        "NEXT_PUBLIC_API_URL must be set for production builds " +
          "(cannot default to localhost — every visitor's browser would call their own machine).",
      );
    }
    return DEV_API_BASE_URL;
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_URL is not a valid absolute URL: ${JSON.stringify(trimmed)}`,
    );
  }

  if (options.isProduction && isLoopbackHostname(parsed.hostname)) {
    throw new Error(
      `NEXT_PUBLIC_API_URL must not be a loopback origin in production builds ` +
        `(got hostname ${JSON.stringify(parsed.hostname)}). ` +
        `Set it to the public API origin at build time, e.g. https://api.example.com.`,
    );
  }

  return trimmed.replace(/\/+$/, "");
}
