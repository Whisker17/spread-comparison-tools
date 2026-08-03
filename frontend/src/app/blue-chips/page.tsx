import { LiveSpreadDemo } from "@/components/LiveSpreadDemo";
import { SectionPlaceholder } from "@/components/SectionPlaceholder";
import { blueChipsSection } from "@/config/sections/blue-chips";

export default function BlueChipsPage() {
  const demoAsset = blueChipsSection.assets[0] ?? "BTC";

  return (
    <SectionPlaceholder section={blueChipsSection}>
      <p className="rounded-md border border-dashed border-zinc-300 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
        Scaffold demo (WHI-808): live <strong>{demoAsset}</strong> matrix via
        mock/live adapters. Full section content arrives in WHI-809.
      </p>
      <LiveSpreadDemo section={blueChipsSection} asset={demoAsset} />
    </SectionPlaceholder>
  );
}
