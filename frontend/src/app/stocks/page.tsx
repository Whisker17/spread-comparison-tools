import { SectionPlaceholder } from "@/components/SectionPlaceholder";
import { stocksSection } from "@/config/sections/stocks";

export default function StocksPage() {
  return (
    <SectionPlaceholder section={stocksSection}>
      <PlaceholderCard issue="WHI-810" />
    </SectionPlaceholder>
  );
}

function PlaceholderCard({ issue }: { issue: string }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
      Section content lands in {issue}. Routes and navigation are pre-created so
      that PR does not touch shared shell files.
    </div>
  );
}
