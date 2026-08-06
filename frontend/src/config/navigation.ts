/** Top-level nav entries. Routes are pre-created in WHI-808 so section agents
 *  never edit shared navigation. */

export type NavItem = {
  href: string;
  label: string;
  /** Short description for placeholder pages. */
  description: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/blue-chips",
    label: "Blue chips",
    description: "Crypto blue chips — BTC / ETH / SOL (WHI-809).",
  },
  {
    href: "/stocks",
    label: "Stocks",
    description: "Underlying-first stocks: venue × form (WHI-882).",
  },
  {
    href: "/others",
    label: "Others",
    description: "High-volume CEX + perp-DEX assets (WHI-811).",
  },
  {
    href: "/fees",
    label: "Fees",
    description: "Fee schedule comparison (WHI-813).",
  },
  {
    href: "/simulate",
    label: "Simulate",
    description: "Trade simulator (WHI-815).",
  },
] as const;
