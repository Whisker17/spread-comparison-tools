import { PlaceholderCard } from "@/components/PlaceholderCard";

export default function SimulatePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Simulate</h1>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Aggregator-style trade simulator. Content lands in WHI-815.
      </p>
      <PlaceholderCard>
        Placeholder route (WHI-808). No edits to navigation required in WHI-815.
      </PlaceholderCard>
    </div>
  );
}
