import type { ReactNode } from "react";

import type { SectionConfig } from "@/config/sections/types";

export function SectionPlaceholder({
  section,
  children,
}: {
  section: SectionConfig;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{section.title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
          {section.description}
        </p>
      </div>
      {children}
    </div>
  );
}
