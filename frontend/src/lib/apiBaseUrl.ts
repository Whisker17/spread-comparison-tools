/**
 * Resolve and validate `NEXT_PUBLIC_API_URL` (WHI-857).
 *
 * Production builds must not bake a loopback origin into the client bundle —
 * every visitor's browser would call their own machine. Development keeps the
 * convenient localhost default.
 */

/** Dev-only fallback when the env var is unset. Never used in production. */
export const DEV_API_BASE_URL = "http://localhost:8000";

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * True for hosts that resolve to the visitor's own machine.
 * Covers the issue's explicit list (localhost / 127.0.0.1 / ::1) plus the rest of
 * 127.0.0.0/8, wildcards `0.0.0.0` / `::`, IPv4-mapped IPv6 127/8, and `*.localhost`.
 *
 * Note: WHATWG serializes `[::ffff:127.0.0.1]` as hostname `[::ffff:7f00:1]` —
 * match that hex form, not the dotted form.
 */
export function isLoopbackHostname(hostname: string): boolean {
  // Accept bracketed IPv6 (URL.hostname often keeps brackets).
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (
    h === "localhost" ||
    h.endsWith(".localhost") ||
    h === "::1" ||
    h === "::" ||
    h === "0.0.0.0"
  ) {
    return true;
  }
  // 127.0.0.0/8 (dotted)
  if (/^127(?:\.\d{1,3}){3}$/.test(h)) {
    return true;
  }
  // IPv4-mapped IPv6 for 127.0.0.0/8 as WHATWG serializes it (::ffff:7f00:1, …)
  if (/^::ffff:7f[0-9a-f]{2}:[0-9a-f]{1,4}$/.test(h)) {
    return true;
  }
  // Dotted IPv4-mapped form if a caller passes it raw (::ffff:127.0.0.1)
  if (h.startsWith("::ffff:")) {
    return isLoopbackHostname(h.slice("::ffff:".length));
  }
  return false;
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
 * - Always requires an absolute http(s) URL when set; strips trailing slashes.
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

  // Reject scheme-less typos like `localhost:8000` (WHATWG parses those as
  // protocol="localhost:" with an empty hostname, which would bypass loopback).
  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
    throw new Error(
      `NEXT_PUBLIC_API_URL must be an http(s) origin (got protocol ${JSON.stringify(parsed.protocol)}). ` +
        `Example: https://api.example.com`,
    );
  }

  if (!parsed.hostname) {
    throw new Error(
      `NEXT_PUBLIC_API_URL must include a hostname: ${JSON.stringify(trimmed)}`,
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
