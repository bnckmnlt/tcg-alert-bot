from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models.listing import Listing
from .prices import discount_percent, score_price

@dataclass(frozen=True)
class DealScore:
    listing: Listing
    score: float
    price_score: float
    shipping_score: float
    seller_score: float
    quantity_score: float
    discount_percent: float
    reason: str

def _seller_score(listing: Listing) -> float:
    rating = listing.seller.rating_percent
    if rating is None:
        return 0.0
    return max(0.0, min(100.0, (rating - 95.0) * 10.0 + 50.0))

def _seller_confidence(listing: Listing) -> float:
    count = listing.seller.rating_count
    if count is None:
        return 0.5
    return min(1.0, max(0.0, count / 500.0))

def _shipping_score(listing: Listing) -> float:
    return max(0.0, min(100.0, 100.0 - listing.shipping * 20.0))

def _quantity_score(listing: Listing, preferred_quantity: int) -> float:
    needed = max(preferred_quantity, 1)
    coverage = min(1.0, listing.quantity / needed)
    surplus = min(1.0, listing.quantity / (needed * 5.0))
    return coverage * 70.0 + surplus * 30.0

def score_deal(listing: Listing, baseline: Optional[float], preferred_quantity: int = 1, market_price: Optional[float] = None) -> DealScore:
    recent_score = score_price(listing, baseline)
    market_score = score_price(listing, market_price)
    price_score = recent_score if not market_price or market_price <= 0 else recent_score * 0.4 + market_score * 0.6
    shipping_score = _shipping_score(listing)
    raw_seller = _seller_score(listing)
    seller_score = raw_seller * (0.65 + 0.35 * _seller_confidence(listing))
    quantity_score = _quantity_score(listing, preferred_quantity)
    score = price_score * 0.55 + shipping_score * 0.20 + seller_score * 0.15 + quantity_score * 0.10
    reference = market_price if market_price and market_price > 0 else baseline
    discount = discount_percent(listing.landed_unit_price, reference)
    reason = "landed ${:.2f}; {:.1f}% below {} reference".format(
        listing.landed_unit_price, discount, "market" if market_price and market_price > 0 else "recent"
    )
    return DealScore(listing, round(score, 1), round(price_score, 1), round(shipping_score, 1),
                     round(seller_score, 1), round(quantity_score, 1), round(discount, 1), reason)
