/**
 * Suspense fallback for section pages that call useSearchParams (WHI-841).
 * Shared so blue-chips / stocks / others do not each re-copy the shell.
 */

export function SectionShellLoading({ title }: { title: string }) {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-zinc-500">Loading size selector…</p>
      </header>
    </div>
  );
}
