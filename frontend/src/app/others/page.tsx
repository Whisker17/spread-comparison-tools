import { SectionPlaceholder } from "@/components/SectionPlaceholder";
import { othersSection } from "@/config/sections/others";

export default function OthersPage() {
  return (
    <SectionPlaceholder section={othersSection}>
      <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
        Section content lands in WHI-811. Routes and navigation are pre-created so
        that PR does not touch shared shell files.
      </div>
    </SectionPlaceholder>
  );
}
