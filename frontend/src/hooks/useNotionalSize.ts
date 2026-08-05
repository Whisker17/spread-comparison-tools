"use client";

/**
 * Persist the selected notional tier in `?size=` (WHI-841 / WHI-864).
 *
 * Shared by every section page so a refresh or shared link restores the view.
 * Resolution rules live in `lib/notionalSize.ts` (pure / unit-tested).
 * One tier at a time — legacy ``all`` is not a valid selection.
 */

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  resolveNotionalSize,
  SIZE_QUERY_PARAM,
} from "@/lib/notionalSize";

export type UseNotionalSizeOptions = {
  /** Selectable tiers for this section (usually `section.notionals`). */
  allowed: readonly string[];
  /**
   * Config default when the URL param is missing or invalid.
   * Must be a tier USD string (not ``all``).
   */
  defaultNotional: string;
};

export type UseNotionalSizeResult = {
  /** Resolved size view: a tier USD string. */
  notional: string;
  /** Update selection and write `?size=` (scroll preserved). */
  setNotional: (next: string) => void;
};

export function useNotionalSize(
  options: UseNotionalSizeOptions,
): UseNotionalSizeResult {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const notional = useMemo(
    () =>
      resolveNotionalSize(
        searchParams.get(SIZE_QUERY_PARAM),
        options.allowed,
        options.defaultNotional,
      ),
    [searchParams, options.allowed, options.defaultNotional],
  );

  const setNotional = useCallback(
    (next: string) => {
      if (!options.allowed.includes(next)) {
        return;
      }
      const params = new URLSearchParams(searchParams.toString());
      params.set(SIZE_QUERY_PARAM, next);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [options.allowed, searchParams, router, pathname],
  );

  return { notional, setNotional };
}
