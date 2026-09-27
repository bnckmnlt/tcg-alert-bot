from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from .alerts.discord import (
    bundle as bundle_embed,
    deal as deal_embed,
    price_drop,
    send_embeds,
    stock_change,
)
from .analyzer.bundles import best_watchlist_bundle
from .analyzer.deals import score_deal
from .analyzer.prices import PriceSignal, robust_baseline
from .models.listing import Listing
from .scraper.selenium import Browser
from .scraper.tcgplayer import TCGPlayerScraper

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("STATE_DB", str(ROOT / "data" / "state.sqlite3")))
WATCHLIST_PATH = Path(os.getenv("WATCHLIST", str(ROOT / "data" / "watchlist.json")))
LOG = logging.getLogger("tcg-alert-bot")


CONDITION_RANK = {
    "damaged": 0,
    "heavily played": 1,
    "moderately played": 2,
    "lightly played": 3,
    "near mint": 4,
}


def load_watchlist() -> list[dict]:
    with WATCHLIST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["watchlist"]


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _card_key(item: dict) -> str:
    return "|".join(
        _norm(item.get(key))
        for key in ("name", "set_name", "number", "printing", "language")
    )


def _matches_watchlist(listing: Listing, item: dict) -> bool:
    min_condition = _norm(item.get("min_condition"))
    if min_condition and listing.condition:
        minimum = CONDITION_RANK.get(min_condition)
        actual = CONDITION_RANK.get(_norm(listing.condition))
        if minimum is not None and actual is not None and actual < minimum:
            return False

    language = _norm(item.get("language"))
    if language and listing.language and _norm(listing.language) != language:
        return False

    printing = _norm(item.get("printing"))
    if printing and listing.printing and _norm(listing.printing) != printing:
        return False

    return True


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS observations (
            listing_id TEXT PRIMARY KEY,
            card_name TEXT NOT NULL,
            seller_name TEXT NOT NULL,
            price REAL NOT NULL,
            shipping REAL NOT NULL,
            quantity INTEGER NOT NULL,
            seller_rating REAL,
            seller_rating_count INTEGER,
            set_name TEXT,
            condition TEXT,
            language TEXT,
            printing TEXT,
            market_price REAL,
            url TEXT NOT NULL,
            observed_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS alerts (alert_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)")

    # Migrate databases created by older versions.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(observations)")}
    migrations = {
        "seller_rating_count": "INTEGER",
        "set_name": "TEXT",
        "condition": "TEXT",
        "language": "TEXT",
        "printing": "TEXT",
        "market_price": "REAL",
    }
    for column, kind in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {column} {kind}")
    return conn


def previous(conn: sqlite3.Connection, listing_id: str):
    return conn.execute(
        "SELECT price, shipping, quantity FROM observations WHERE listing_id=?",
        (listing_id,),
    ).fetchone()


def already_alerted(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM alerts WHERE alert_key=?", (key,)).fetchone() is not None


def mark_alert(conn: sqlite3.Connection, key: str, now: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO alerts(alert_key, sent_at) VALUES (?, ?)",
        (key, now),
    )


def save_listing(conn: sqlite3.Connection, listing: Listing) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO observations
        (listing_id, card_name, seller_name, price, shipping, quantity,
         seller_rating, seller_rating_count, set_name, condition, language,
         printing, market_price, url, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listing.listing_id,
            listing.card_name,
            listing.seller.name,
            listing.price,
            listing.shipping,
            listing.quantity,
            listing.seller.rating_percent,
            listing.seller.rating_count,
            listing.set_name,
            listing.condition,
            listing.language,
            listing.printing,
            listing.market_price,
            listing.url,
            listing.collected_at,
        ),
    )


def run() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    watchlist = [x for x in load_watchlist() if x.get("enabled", True)]
    conn = db()
    all_listings: list[Listing] = []
    embeds: list[dict] = []

    try:
        with Browser() as browser:
            scraper = TCGPlayerScraper(browser)

            for item in watchlist:
                raw = scraper.search(
                    item["url"],
                    item["name"],
                    item.get("set_name"),
                    item,
                )
                listings = [x for x in raw if _matches_watchlist(x, item)]

                if len(listings) != len(raw):
                    LOG.info(
                        "Filtered %d listings from %s using watchlist constraints",
                        len(raw) - len(listings),
                        item["name"],
                    )

                all_listings.extend(listings)
                baseline = robust_baseline(listings)
                if not baseline:
                    LOG.info(
                        "No eligible listings for %s; no price/deal alert will be generated.",
                        item["name"],
                    )
                    continue

                # target_price is a soft goal: it helps describe the desired
                # buy level, but does not hide a listing that is still compelling
                # relative to market/recent listings. Use max_price for a hard cap.
                hard_max = item.get("max_price")
                hard_max = float(hard_max) if hard_max is not None else None
                preferred_quantity = max(1, int(item.get("quantity_needed", 1)))

                for listing in sorted(listings, key=lambda x: x.landed_unit_price)[:10]:
                    if hard_max is not None and listing.landed_unit_price > hard_max:
                        continue

                    old = previous(conn, listing.listing_id)
                    if old:
                        old_landed = float(old[0]) + float(old[1])
                        drop_percent = (
                            (1 - listing.landed_unit_price / old_landed) * 100
                            if old_landed > 0
                            else 0
                        )
                        threshold = float(item.get("price_drop_percent", 10))
                        if drop_percent >= threshold:
                            signal = PriceSignal(
                                listing=listing,
                                baseline=old_landed,
                                discount_percent=round(drop_percent, 1),
                                reason="{:.1f}% below the previous observed landed price".format(
                                    drop_percent
                                ),
                            )
                            key = "PRICE_DROP:{}:{:.2f}:{:.2f}".format(
                                listing.listing_id,
                                listing.price,
                                listing.shipping,
                            )
                            if not already_alerted(conn, key):
                                embeds.append(price_drop(signal))
                                mark_alert(conn, key, listing.collected_at)

                    score = score_deal(
                        listing,
                        baseline,
                        preferred_quantity,
                        listing.market_price,
                    )
                    if score.score >= float(item.get("deal_score_threshold", 70)):
                        key = "DEAL:{}:{:.2f}:{:.2f}".format(
                            listing.listing_id,
                            listing.price,
                            listing.shipping,
                        )
                        if not already_alerted(conn, key):
                            embeds.append(deal_embed(score))
                            mark_alert(conn, key, listing.collected_at)

                    if old:
                        old_qty = int(old[2])
                        if listing.quantity < old_qty:
                            drop = old_qty - listing.quantity
                            dramatic = drop >= max(2, round(old_qty * 0.5))
                            below_need = listing.quantity < preferred_quantity
                            if dramatic or below_need:
                                key = "STOCK_CHANGE:{}:{}".format(
                                    listing.listing_id,
                                    listing.quantity,
                                )
                                if not already_alerted(conn, key):
                                    embeds.append(stock_change(listing, old_qty))
                                    mark_alert(conn, key, listing.collected_at)

                    save_listing(conn, listing)

        targets = {}
        for item in watchlist:
            reference = item.get("market_price")
            if reference is None and all_listings:
                matches = [
                    x for x in all_listings
                    if _norm(x.card_name) == _norm(item.get("name"))
                    and _norm(x.set_name) == _norm(item.get("set_name"))
                ]
                prices = [x.market_price for x in matches if x.market_price]
                reference = prices[0] if prices else None
            if reference is None and item.get("target_price") is not None:
                reference = item["target_price"]
            if reference and float(reference) > 0:
                targets[_card_key(item)] = float(reference)
                # Keep the simple-name alias for backwards-compatible bundles.
                targets[item["name"]] = float(reference)

        if targets:
            candidate = best_watchlist_bundle(all_listings, targets)
            if candidate and candidate.purchase_saving >= float(os.getenv("BUNDLE_MIN_SAVING", "5")):
                key = "BUNDLE:" + "|".join(sorted(x.listing.listing_id for x in candidate.lines))
                if not already_alerted(conn, key):
                    embeds.append(bundle_embed(candidate))
                    now = all_listings[0].collected_at if all_listings else ""
                    mark_alert(conn, key, now)

        conn.commit()
        for i in range(0, len(embeds), 10):
            send_embeds(embeds[i:i + 10])
        LOG.info("Finished: %d listings, %d alerts", len(all_listings), len(embeds))
    finally:
        conn.close()


if __name__ == "__main__":
    run()
