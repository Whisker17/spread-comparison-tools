"""Cross-language NOTIONAL_TIERS_USD parity (WHI-838 / WHI-799 §4.1).

Backend ``models.NOTIONAL_TIERS_USD`` is the runtime SSOT; the frontend keeps a
string mirror in ``frontend/src/config/notionals.ts``. This contract test fails
if either side drifts without the other.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from spread_compare.models import NOTIONAL_TIERS_USD

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NOTIONALS_TS = _REPO_ROOT / "frontend" / "src" / "config" / "notionals.ts"


def test_notional_tiers_match_frontend_mirror() -> None:
    text = _NOTIONALS_TS.read_text(encoding="utf-8")
    m = re.search(
        r"export const NOTIONAL_TIERS_USD\s*=\s*\[([\s\S]*?)\]\s*as const",
        text,
    )
    assert m is not None, "could not parse frontend NOTIONAL_TIERS_USD"
    frontend = tuple(Decimal(s) for s in re.findall(r'"(\d+)"', m.group(1)))
    assert frontend == NOTIONAL_TIERS_USD
