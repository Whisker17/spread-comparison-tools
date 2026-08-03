import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type { SectionConfig } from "@/config/sections/types";

/** Others section config — content in WHI-811. */
export const othersSection: SectionConfig = {
  id: "others",
  title: "Others",
  description:
    "High-volume CEX + perp-DEX assets. Section content lands in WHI-811.",
  assets: [],
  venues: [],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
};
