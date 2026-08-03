import { PlaceholderCard } from "@/components/PlaceholderCard";
import { SectionPlaceholder } from "@/components/SectionPlaceholder";
import { othersSection } from "@/config/sections/others";

export default function OthersPage() {
  return (
    <SectionPlaceholder section={othersSection}>
      <PlaceholderCard>
        Section content lands in WHI-811. Routes and navigation are pre-created so
        that PR does not touch shared shell files.
      </PlaceholderCard>
    </SectionPlaceholder>
  );
}
