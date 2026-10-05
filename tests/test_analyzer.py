from src.analyzer.bundles import best_watchlist_bundle
from src.analyzer.deals import score_deal
from src.analyzer.prices import historical_stats, robust_baseline
from src.models.listing import Listing
from src.models.seller import Seller
from src.scraper.tcgplayer import _label_value, _quantity, _rating


def listing(
    name,
    price,
    shipping=0,
    qty=1,
    seller="Seller",
    rating=99,
    rating_count=None,
    set_name=None,
    printing=None,
):
    return Listing(
        f"{name}-{seller}-{price}",
        name,
        set_name,
        None,
        "https://example.com",
        price,
        shipping,
        qty,
        "Near Mint",
        "English",
        Seller(seller, rating, rating_count),
        "2026-01-01T00:00:00+00:00",
        printing=printing,
    )


def test_baseline_uses_median():
    assert robust_baseline([listing("A", 10), listing("A", 11), listing("A", 12)]) == 11


def test_historical_stats_returns_median_average_and_low():
    assert historical_stats([10, 12, 14]) == (12.0, 12.0, 10.0)


def test_deal_prefers_low_landed_price():
    baseline = robust_baseline([listing("A", 10), listing("A", 11), listing("A", 12)])
    score = score_deal(listing("A", 8), baseline)
    assert score.discount_percent > 20
    assert score.score > 50


def test_market_price_is_part_of_deal_score():
    baseline = 6.5
    score = score_deal(listing("A", 6), baseline, market_price=8)
    assert score.discount_percent == 25.0
    assert score.price_score > 0


def test_quantity_affects_score_for_single_copy_targets():
    baseline = 10
    one = score_deal(listing("A", 8, qty=1), baseline)
    five = score_deal(listing("A", 8, qty=5), baseline)
    assert five.quantity_score > one.quantity_score


def test_bundle_calculates_purchase_saving():
    items = [
        listing("A", 8, seller="Same"),
        listing("B", 7, seller="Same"),
        listing("A", 10, seller="Other"),
    ]
    bundle = best_watchlist_bundle(items, {"A": 10, "B": 10})
    assert bundle is not None
    assert bundle.total == 15
    assert bundle.purchase_saving == 5


def test_bundle_keeps_same_name_cards_separate_by_set_and_printing():
    items = [
        listing("Pikachu", 5, seller="Same", set_name="Set A", printing="Normal"),
        listing("Pikachu", 4, seller="Same", set_name="Set B", printing="Reverse Holofoil"),
    ]
    targets = {
        "pikachu|set a||normal|english": 8,
        "pikachu|set b||reverse holofoil|english": 7,
    }
    bundle = best_watchlist_bundle(items, targets)
    assert bundle is not None
    assert len(bundle.lines) == 2
    assert bundle.purchase_saving == 6


def test_listing_identity_does_not_change_when_price_changes():
    a = listing("A", 10, seller="Same", set_name="Set A")
    b = listing("A", 8, seller="Same", set_name="Set A")
    assert a.card_key == b.card_key


def test_scraper_helpers_parse_current_text_shapes():
    assert _rating("99.8% (1,373 Sales)") == (99.8, 1373)
    assert _quantity("1 of 59") == 59
    assert _quantity("Quantity: 4") == 4
    assert _label_value("Market Price | $6.32", "Market Price") == 6.32
