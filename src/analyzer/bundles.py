from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from ..models.listing import Listing


@dataclass(frozen=True)
class BundleLine:
    card_name: str
    listing: Listing
    quantity: int
    unit_landed: float


@dataclass(frozen=True)
class Bundle:
    seller_name: str
    lines: tuple[BundleLine, ...]
    total: float
    separate_shipping: float
    shipping_saving: float
    market_total: float
    purchase_saving: float
    score: float


def _reference(target_cards: dict[str, float], listing: Listing) -> float:
    return float(
        target_cards.get(listing.card_key)
        or target_cards.get(listing.card_name)
        or 0.0
    )


def best_watchlist_bundle(
    listings: Iterable[Listing],
    target_cards: dict[str, float],
    max_cards: int = 8,
) -> Bundle | None:
    grouped: dict[str, list[Listing]] = {}
    for listing in listings:
        if _reference(target_cards, listing) > 0:
            grouped.setdefault(listing.seller.name, []).append(listing)

    candidates: list[Bundle] = []
    for seller, seller_listings in grouped.items():
        best_by_card: dict[str, Listing] = {}
        for listing in seller_listings:
            key = listing.card_key
            current = best_by_card.get(key)
            if current is None or listing.landed_unit_price < current.landed_unit_price:
                best_by_card[key] = listing

        cards = sorted(best_by_card, key=lambda c: best_by_card[c].landed_unit_price)[:12]
        for size in range(2, min(max_cards, len(cards)) + 1):
            for combo in combinations(cards, size):
                lines = tuple(
                    BundleLine(
                        best_by_card[c].card_name,
                        best_by_card[c],
                        1,
                        best_by_card[c].landed_unit_price,
                    )
                    for c in combo
                )
                product_total = sum(x.unit_landed for x in lines)
                separate_shipping = sum(x.listing.shipping for x in lines)
                # TCGPlayer charges one seller-level shipping amount for an order,
                # so using the largest displayed per-line shipping is a conservative
                # estimate until the cart itself is queried.
                bundle_shipping = max((x.listing.shipping for x in lines), default=0.0)
                shipping_saving = max(0.0, separate_shipping - bundle_shipping)
                market_total = sum(_reference(target_cards, x.listing) for x in lines)
                purchase_saving = max(0.0, market_total - product_total)
                total = product_total
                score = purchase_saving + shipping_saving * 1.5 + size * 2
                candidates.append(
                    Bundle(
                        seller,
                        lines,
                        round(total, 2),
                        round(separate_shipping, 2),
                        round(shipping_saving, 2),
                        round(market_total, 2),
                        round(purchase_saving, 2),
                        round(score, 2),
                    )
                )
    return max(candidates, key=lambda x: x.score, default=None)
