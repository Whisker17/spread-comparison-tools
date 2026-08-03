import type { ReactNode } from "react";

/** Shared dashed placeholder used by empty section / fees / simulate routes. */

export function PlaceholderCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
      {children}
    </div>
  );
}
