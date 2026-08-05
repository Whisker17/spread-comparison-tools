import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEV_API_BASE_URL,
  isLoopbackHostname,
  resolveApiBaseUrl,
} from "@/lib/apiBaseUrl";
import { getApiBaseUrl } from "@/lib/api";
import { streamUrl } from "@/lib/streamQuotes";

describe("isLoopbackHostname", () => {
  it("recognizes localhost, 127.0.0.1, and IPv6 loopback", () => {
    expect(isLoopbackHostname("localhost")).toBe(true);
    expect(isLoopbackHostname("LOCALHOST")).toBe(true);
    expect(isLoopbackHostname("127.0.0.1")).toBe(true);
    expect(isLoopbackHostname("::1")).toBe(true);
    expect(isLoopbackHostname("[::1]")).toBe(true);
  });

  it("rejects public and private non-loopback hosts", () => {
    expect(isLoopbackHostname("api.example.com")).toBe(false);
    expect(isLoopbackHostname("10.0.0.1")).toBe(false);
    expect(isLoopbackHostname("0.0.0.0")).toBe(false);
  });
});

describe("resolveApiBaseUrl (development)", () => {
  it("defaults to localhost when unset", () => {
    expect(resolveApiBaseUrl(undefined, { isProduction: false })).toBe(
      DEV_API_BASE_URL,
    );
    expect(resolveApiBaseUrl("", { isProduction: false })).toBe(
      DEV_API_BASE_URL,
    );
    expect(resolveApiBaseUrl("   ", { isProduction: false })).toBe(
      DEV_API_BASE_URL,
    );
  });

  it("allows explicit loopback and strips trailing slashes", () => {
    expect(
      resolveApiBaseUrl("http://127.0.0.1:8100/", { isProduction: false }),
    ).toBe("http://127.0.0.1:8100");
    expect(
      resolveApiBaseUrl("http://localhost:8000", { isProduction: false }),
    ).toBe("http://localhost:8000");
  });
});

describe("resolveApiBaseUrl (production)", () => {
  it("throws a named-variable error when unset", () => {
    expect(() =>
      resolveApiBaseUrl(undefined, { isProduction: true }),
    ).toThrowError(/NEXT_PUBLIC_API_URL/);
    expect(() => resolveApiBaseUrl("", { isProduction: true })).toThrowError(
      /NEXT_PUBLIC_API_URL must be set/,
    );
  });

  it.each([
    "http://localhost:8000",
    "http://127.0.0.1:8100",
    "http://[::1]:8000",
    "https://localhost",
  ])("rejects loopback origin %s", (raw) => {
    expect(() =>
      resolveApiBaseUrl(raw, { isProduction: true }),
    ).toThrowError(/NEXT_PUBLIC_API_URL.*loopback/i);
  });

  it("accepts a public origin and strips trailing slashes", () => {
    expect(
      resolveApiBaseUrl("https://api.example.com/v1/", {
        isProduction: true,
      }),
    ).toBe("https://api.example.com/v1");
  });

  it("rejects non-absolute values", () => {
    expect(() =>
      resolveApiBaseUrl("/relative", { isProduction: true }),
    ).toThrowError(/NEXT_PUBLIC_API_URL/);
  });
});

describe("getApiBaseUrl / streamUrl production guard", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("in production, refuses unset env so streamUrl cannot fall back to loopback", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");

    expect(() => getApiBaseUrl()).toThrowError(/NEXT_PUBLIC_API_URL/);
    expect(() => streamUrl()).toThrowError(/NEXT_PUBLIC_API_URL/);
  });

  it("in production, refuses loopback so derived WS URL cannot be ws://localhost", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");

    expect(() => getApiBaseUrl()).toThrowError(/loopback/i);
    expect(() => streamUrl()).toThrowError(/loopback/i);
  });

  it("in production, public origin yields a matching wss stream URL", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");

    expect(getApiBaseUrl()).toBe("https://api.example.com");
    expect(streamUrl()).toBe("wss://api.example.com/stream");
  });

  it("in non-production, defaults remain available for pnpm dev", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");

    expect(getApiBaseUrl()).toBe(DEV_API_BASE_URL);
    expect(streamUrl()).toBe("ws://localhost:8000/stream");
  });
});
