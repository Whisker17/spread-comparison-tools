import type { FeeTableGroup, FeeTableRow } from "@/lib/feesTable";
import {
  fundingModelLabel,
  instrumentTypeLabel,
} from "@/lib/feesTable";
import { formatBps, formatTimestamp } from "@/lib/format";
import { Badge } from "@/components/ui/badge";

type Props = {
  groups: readonly FeeTableGroup[];
};

/** Static fee-structure comparison from GET /fees (WHI-813). */
export function FeeStructureTable({ groups }: Props) {
  if (groups.length === 0) {
    return (
      <p className="text-sm text-zinc-500">No fee schedules available.</p>
    );
  }

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.venueClass} className="space-y-2">
          <h3 className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-300">
            {group.label}
          </h3>
          <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead className="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900/60">
                <tr>
                  <th className="px-3 py-2 font-medium">Venue</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Maker</th>
                  <th className="px-3 py-2 font-medium">Taker</th>
                  <th className="px-3 py-2 font-medium">LP tiers</th>
                  <th className="px-3 py-2 font-medium">Gas est.</th>
                  <th className="px-3 py-2 font-medium">Funding</th>
                  <th className="px-3 py-2 font-medium">Fee model</th>
                  <th className="px-3 py-2 font-medium">Sources</th>
                  <th className="px-3 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {group.rows.map((row) => (
                  <FeeRow key={`${row.venue}:${row.instrumentType}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function FeeRow({ row }: { row: FeeTableRow }) {
  return (
    <tr className="bg-white dark:bg-zinc-950">
      <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">
        {row.displayName}
        <div className="text-[11px] font-normal text-zinc-400">{row.venue}</div>
      </td>
      <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
        {instrumentTypeLabel(row.instrumentType)}
      </td>
      <td className="px-3 py-2 tabular-nums">
        {row.makerBps == null ? "—" : `${formatBps(row.makerBps)} bps`}
      </td>
      <td className="px-3 py-2 tabular-nums">
        {row.takerBps == null ? "—" : `${formatBps(row.takerBps)} bps`}
      </td>
      <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
        {row.lpFeeTiersBps && row.lpFeeTiersBps.length > 0
          ? row.lpFeeTiersBps.map((b) => `${formatBps(b)}`).join(" / ") + " bps"
          : "—"}
      </td>
      <td className="px-3 py-2 tabular-nums text-zinc-600 dark:text-zinc-400">
        {row.gasEstimateUsd == null ? "—" : `$${row.gasEstimateUsd}`}
      </td>
      <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
        {fundingModelLabel(row.fundingModel)}
      </td>
      <td className="px-3 py-2">
        {row.feeEmbeddedInQuote ? (
          <Badge variant="secondary">fee in price</Badge>
        ) : (
          <Badge variant="outline">explicit</Badge>
        )}
      </td>
      <td className="px-3 py-2">
        <SourceLinks urls={row.sourceUrls} />
      </td>
      <td className="px-3 py-2 whitespace-nowrap text-xs text-zinc-500">
        {formatTimestamp(row.updatedAt)}
      </td>
    </tr>
  );
}

function SourceLinks({ urls }: { urls: readonly string[] }) {
  if (urls.length === 0) {
    return <span className="text-zinc-400">—</span>;
  }
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-1">
      {urls.map((url, i) => (
        <a
          key={url}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-sky-700 underline-offset-2 hover:underline dark:text-sky-400"
          title={url}
        >
          [{i + 1}]
        </a>
      ))}
    </span>
  );
}
