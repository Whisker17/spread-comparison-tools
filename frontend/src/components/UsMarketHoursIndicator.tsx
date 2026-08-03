"use client";

/**
 * Static NYSE-session badge for the stocks page (WHI-810).
 * Tokenized equities trade 24/7; this only annotates the underlying cash market.
 */

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { usMarketHoursStatus } from "@/lib/usMarketHours";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;

export function UsMarketHoursIndicator({
  className,
  now,
}: {
  className?: string;
  /** Injected clock for tests; live UI uses an interval on Date.now(). */
  now?: Date;
}) {
  // Live clock only — when `now` is injected, status is pure from props.
  const [liveNow, setLiveNow] = useState(() => new Date());

  useEffect(() => {
    if (now) return;
    const id = window.setInterval(() => setLiveNow(new Date()), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [now]);

  const status = usMarketHoursStatus(now ?? liveNow);

  return (
    <Badge
      variant={status.open ? "secondary" : "warning"}
      className={cn("normal-case tracking-normal", className)}
      data-testid="us-market-hours"
      data-open={status.open ? "true" : "false"}
      title={status.detail}
    >
      {status.label}
    </Badge>
  );
}
