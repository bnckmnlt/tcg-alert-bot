from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Iterable
import requests
from ..analyzer.bundles import Bundle
from ..analyzer.deals import DealScore
from ..analyzer.prices import PriceSignal
from ..models.listing import Listing

COLORS = {"PRICE_DROP": 0x57F287, "DEAL": 0xFF6B35, "BUNDLE": 0x5865F2, "STOCK_CHANGE": 0xED4245}

def _money(value: float) -> str:
    return "$" + "{:,.2f}".format(value)

def _seller(listing: Listing) -> str:
    rating = "{:.1f}%".format(listing.seller.rating_percent) if listing.seller.rating_percent is not None else "n/a"
    count = "" if listing.seller.rating_count is None else " • {:,} sales".format(listing.seller.rating_count)
    return "{} ({}{})".format(listing.seller.name, rating, count)

def _embed(title: str, description: str, kind: str, fields: list[dict], url: str | None = None) -> dict:
    embed = {
        "title": "{}  •  {}".format(kind.replace("_", " "), title),
        "description": description,
        "color": COLORS[kind],
        "fields": fields,
        "footer": {"text": "TCGPlayer Alert Bot • price + shipping + quantity + seller weighted"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if url:
        embed["url"] = url
    return embed

def price_drop(signal: PriceSignal) -> dict:
    l = signal.listing
    return _embed(l.card_name, "**{:.1f}% below** the recent observed landed price.".format(signal.discount_percent), "PRICE_DROP", [
        {"name": "💵 Price", "value": _money(l.price), "inline": True},
        {"name": "🚚 Shipping", "value": _money(l.shipping), "inline": True},
        {"name": "🧮 Landed", "value": _money(l.landed_unit_price), "inline": True},
        {"name": "📦 Quantity", "value": str(l.quantity), "inline": True},
        {"name": "⭐ Seller", "value": _seller(l), "inline": True},
        {"name": "📉 Baseline", "value": _money(signal.baseline), "inline": True},
    ], l.url)

def deal(score: DealScore) -> dict:
    l = score.listing
    return _embed(l.card_name, "**Deal score {:.0f}/100** • {:.1f}% below baseline.".format(score.score, score.discount_percent), "DEAL", [
        {"name": "💵 Landed price", "value": _money(l.landed_unit_price), "inline": True},
        {"name": "🚚 Shipping", "value": _money(l.shipping), "inline": True},
        {"name": "📦 Quantity", "value": str(l.quantity), "inline": True},
        {"name": "⭐ Seller", "value": _seller(l), "inline": True},
        {"name": "🎯 Price", "value": "{:.0f}/100".format(score.price_score), "inline": True},
        {"name": "🏪 Seller", "value": "{:.0f}/100".format(score.seller_score), "inline": True},
        {"name": "📈 Market", "value": _money(l.market_price) if l.market_price else "n/a", "inline": True},
    ], l.url)

def stock_change(listing: Listing, previous_quantity: int) -> dict:
    delta = listing.quantity - previous_quantity
    direction = "increased" if delta > 0 else "dropped"
    return _embed(listing.card_name, "Quantity **{} by {}** since the previous check.".format(direction, abs(delta)), "STOCK_CHANGE", [
        {"name": "📦 Previous", "value": str(previous_quantity), "inline": True},
        {"name": "📦 Current", "value": str(listing.quantity), "inline": True},
        {"name": "💵 Landed", "value": _money(listing.landed_unit_price), "inline": True},
        {"name": "⭐ Seller", "value": _seller(listing), "inline": True},
    ], listing.url)

def bundle(bundle: Bundle) -> dict:
    lines = "\n".join("• [{}]({}) — {}".format(x.card_name, x.listing.url, _money(x.unit_landed)) for x in bundle.lines)
    embed = _embed("{} cards from {}".format(len(bundle.lines), bundle.seller_name), lines, "BUNDLE", [
        {"name": "🛒 Combined purchase", "value": _money(bundle.total), "inline": True},
        {"name": "💰 Purchase savings", "value": _money(bundle.purchase_saving), "inline": True},
        {"name": "🚚 Shipping savings", "value": _money(bundle.shipping_saving), "inline": True},
        {"name": "📊 Reference total", "value": _money(bundle.market_total), "inline": True},
    ])
    return embed

def send_embeds(embeds: Iterable[dict]) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    response = requests.post(webhook, json={
        "username": "TCG Alert Bot",
        "allowed_mentions": {"parse": []},
        "embeds": list(embeds),
    }, timeout=20)
    if not response.ok:
        detail = response.text[:2000]
        raise RuntimeError(
            "Discord webhook rejected the payload (HTTP {}): {}".format(
                response.status_code,
                detail,
            )
        )
