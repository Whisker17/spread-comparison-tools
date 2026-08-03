import { PlaceholderCard } from "@/components/PlaceholderCard";
import { SectionPlaceholder } from "@/components/SectionPlaceholder";
import { stocksSection } from "@/config/sections/stocks";

export default function StocksPage() {
  return (
    <SectionPlaceholder section={stocksSection}>
      <PlaceholderCard>
        Section content lands in WHI-810. Routes and navigation are pre-created so
        that PR does not touch shared shell files.
      </PlaceholderCard>
    </SectionPlaceholder>
  );
}
