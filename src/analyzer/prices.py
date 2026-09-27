from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Optional

from ..models.listing import Listing


@dataclass(frozen=True)
class PriceSignal:
    listing: Listing
    baseline: float
    discount_percent: float
    reason: str


def robust_baseline(listings: Iterable[Listing]) -> Optional[float]:
    """Use the median landed unit price, ignoring obviously invalid prices."""
    prices = sorted(x.landed_unit_price for x in listings if x.landed_unit_price > 0)
    return round(median(prices), 2) if prices else None


def score_price(listing: Listing, baseline: Optional[float]) -> float:
    if not baseline or baseline <= 0 or listing.landed_unit_price <= 0:
        return 0.0
    discount = (1 - listing.landed_unit_price / baseline) * 100
    # A listing near the reference can still be attractive when shipping,
    # seller reputation, and quantity are strong.
    return max(0.0, min(100.0, 40.0 + discount * 2.5))


def discount_percent(price: float, reference: Optional[float]) -> float:
    if not reference or reference <= 0:
        return 0.0
    return (1 - price / reference) * 100


def price_signal(
    listing: Listing,
    baseline: Optional[float],
    threshold: float = 10.0,
) -> Optional[PriceSignal]:
    discount = discount_percent(listing.landed_unit_price, baseline)
    if discount < threshold:
        return None
    return PriceSignal(
        listing,
        float(baseline),
        round(discount, 1),
        "{:.1f}% below the recent observed landed price".format(discount),
    )
