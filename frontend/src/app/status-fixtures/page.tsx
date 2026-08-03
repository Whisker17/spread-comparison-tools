"use client";

import { StatusCell } from "@/components/StatusCell";
import { STATUS_FIXTURES } from "@/lib/fixtures/statusQuotes";
import { STATUS_LEGEND } from "@/lib/status";

/**
 * Fixture page documenting every status + gas_unknown + mid_stale rendering.
 * Substitutes for Storybook in the M3 scaffold (WHI-808 AC).
 */
export default function StatusFixturesPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Status render fixtures
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
          Single source of truth for status chrome shared by all section pages.
          Rules live in <code className="text-xs">src/lib/status.ts</code>.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          Legend
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {STATUS_LEGEND.map((row) => (
            <li
              key={row.id}
              className="rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800"
            >
              <div className="font-mono text-xs font-semibold">{row.title}</div>
              <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
                {row.description}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          Live cells
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STATUS_FIXTURES.map((fx) => (
            <div
              key={fx.id}
              className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
              data-fixture={fx.id}
            >
              <div className="mb-2 font-mono text-xs font-semibold">{fx.title}</div>
              <p className="mb-3 text-xs text-zinc-600 dark:text-zinc-400">
                {fx.description}
              </p>
              <div className="rounded border border-zinc-100 bg-zinc-50 p-2 dark:border-zinc-900 dark:bg-zinc-900/40">
                <StatusCell
                  quote={fx.quote}
                  formattedMetric={fx.formattedMetric}
                  metricKey="total_cost_bps"
                  isBest={fx.id === "ok"}
                />
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
