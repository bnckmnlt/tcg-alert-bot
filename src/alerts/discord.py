from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Iterable
import time

import requests
from ..analyzer.bundles import Bundle
from ..analyzer.deals import DealScore
from ..analyzer.prices import PriceSignal
from ..models.listing import Listing

COLORS = {
    "PRICE_DROP": 0x57F287,
    "DEAL": 0xFF6B35,
    "BUNDLE": 0x5865F2,
    "STOCK_CHANGE": 0xED4245,
    "HEALTH": 0xED4245,
}

def _money(value: float) -> str:
    return "$" + "{:,.2f}".format(value)

def _seller(listing: Listing) -> str:
    rating = "{:.1f}%".format(listing.seller.rating_percent) if listing.seller.rating_percent is not None else "n/a"
    count = "" if listing.seller.rating_count is None else " • {:,} sales".format(listing.seller.rating_count)
    return "{} ({}{})".format(listing.seller.name, rating, count)

def _display_name(listing: Listing) -> str:
    """Return a human-friendly card name that distinguishes watchlist variants."""
    parts = [listing.card_name]
    if listing.set_name:
        parts.append(listing.set_name)
    if listing.condition:
        parts.append(listing.condition)
    if listing.printing:
        parts.append(listing.printing)
    return " — ".join(parts)


def _embed(title: str, description: str, kind: str, fields: list[dict], url: str | None = None) -> dict:
    embed = {
        "title": "{}  •  {}".format(kind.replace("_", " "), title),
        "description": description,
        "color": COLORS[kind],
        "fields": fields,
        "footer": {"text": "Meowth's Market • price + shipping + quantity + seller weighted"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if url:
        embed["url"] = url
    return embed

def price_drop(signal: PriceSignal) -> dict:
    l = signal.listing
    return _embed(_display_name(l), "**{:.1f}% below** the recent observed landed price.".format(signal.discount_percent), "PRICE_DROP", [
        {"name": "💵 Price", "value": _money(l.price), "inline": True},
        {"name": "🚚 Shipping", "value": _money(l.shipping), "inline": True},
        {"name": "🧮 Landed", "value": _money(l.landed_unit_price), "inline": True},
        {"name": "📦 Quantity", "value": str(l.quantity), "inline": True},
        {"name": "⭐ Seller", "value": _seller(l), "inline": True},
        {"name": "📉 Baseline", "value": _money(signal.baseline), "inline": True},
    ], l.url)

def deal(score: DealScore) -> dict:
    l = score.listing
    return _embed(_display_name(l), "**Deal score {:.0f}/100** • {:.1f}% below baseline.".format(score.score, score.discount_percent), "DEAL", [
        {"name": "💵 Landed price", "value": _money(l.landed_unit_price), "inline": True},
        {"name": "🚚 Shipping", "value": _money(l.shipping), "inline": True},
        {"name": "📦 Quantity", "value": str(l.quantity), "inline": True},
        {"name": "⭐ Seller", "value": _seller(l), "inline": True},
        {"name": "🎯 Price score", "value": "{:.0f}/100".format(score.price_score), "inline": True},
        {"name": "🚚 Shipping score", "value": "{:.0f}/100".format(score.shipping_score), "inline": True},
        {"name": "⭐ Seller score", "value": "{:.0f}/100".format(score.seller_score), "inline": True},
        {"name": "📦 Quantity score", "value": "{:.0f}/100".format(score.quantity_score), "inline": True},
        {"name": "📈 Market", "value": _money(l.market_price) if l.market_price else "n/a", "inline": True},
        {"name": "🧠 Trigger", "value": score.reason, "inline": False},
    ], l.url)

def stock_change(listing: Listing, previous_quantity: int) -> dict:
    delta = listing.quantity - previous_quantity
    direction = "increased" if delta > 0 else "dropped"
    return _embed(_display_name(listing), "Quantity **{} by {}** since the previous check.".format(direction, abs(delta)), "STOCK_CHANGE", [
        {"name": "📦 Previous", "value": str(previous_quantity), "inline": True},
        {"name": "📦 Current", "value": str(listing.quantity), "inline": True},
        {"name": "💵 Landed", "value": _money(listing.landed_unit_price), "inline": True},
        {"name": "⭐ Seller", "value": _seller(listing), "inline": True},
    ], listing.url)

def bundle(bundle: Bundle) -> dict:
    lines = "\n".join("• [{} — {}]({}) — {}".format(x.card_name, x.listing.set_name or "Unknown set", x.listing.url, _money(x.unit_landed)) for x in bundle.lines)
    embed = _embed("{} cards from {}".format(len(bundle.lines), bundle.seller_name), lines, "BUNDLE", [
        {"name": "🛒 Combined purchase", "value": _money(bundle.total), "inline": True},
        {"name": "💰 Purchase savings", "value": _money(bundle.purchase_saving), "inline": True},
        {"name": "🚚 Shipping savings", "value": _money(bundle.shipping_saving), "inline": True},
        {"name": "📊 Reference total", "value": _money(bundle.market_total), "inline": True},
    ])
    return embed

def health(failures: int, detail: str) -> dict:
    return _embed(
        "Scraper health warning",
        "**{} consecutive scrape runs have had failures.**".format(failures),
        "HEALTH",
        [{"name": "Details", "value": detail[:1024], "inline": False}],
    )


def send_embeds(embeds: Iterable[dict]) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

    payload = {
        "username": "Meowth's Market",
        "allowed_mentions": {"parse": []},
        "embeds": list(embeds),
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(webhook, json=payload, timeout=20)
            if response.ok:
                return
            detail = response.text[:2000]
            error = RuntimeError(
                "Discord webhook rejected the payload (HTTP {}): {}".format(
                    response.status_code,
                    detail,
                )
            )
            if response.status_code < 500 and response.status_code != 429:
                raise error
            last_error = error
        except requests.RequestException as exc:
            last_error = exc

        if attempt < 2:
            time.sleep(2 ** attempt)

    raise RuntimeError("Discord webhook failed after 3 attempts: {}".format(last_error))
