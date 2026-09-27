# TCG Alert Bot

Python + Selenium + Discord webhook alerts for TCGPlayer listings.

## Alerts

- 🟢 **PRICE_DROP** — compares the current landed price with the previous observation of the same listing.
- 🔥 **DEAL** — scores listings using price, shipping, seller rating, and quantity.
- 📦 **BUNDLE** — finds a same-seller combination of watchlist cards and reports estimated purchase savings plus shipping savings.
- 🚨 **STOCK_CHANGE** — alerts when a strong listing loses a large portion of its available quantity.

## Scoring

Deal scoring intentionally prioritizes the things that affect the purchase:

- 55% price/discount
- 20% shipping
- 15% seller reputation
- 10% available quantity

Price is evaluated against both the current TCGplayer Market Price (when present) and the median landed price of the listings collected for that watch item. Market Price and Most Recent Sale are product-page price points; the latter is informational and the former is included in deal scoring.

## Watchlist

Edit `data/watchlist.json`.

`target_price` is your desired buy level and is treated as a soft goal: listings above it can still alert when the market/recent-listing, shipping, seller, and quantity signals are strong. Use `max_price` when you want a hard landed-price ceiling. `market_price` is used as the reference value for bundle savings when supplied; otherwise the scraper uses the product page's current Market Price.

Example:

```json
{
  "watchlist": [
    {
      "name": "Example Card",
      "set_name": "Example Set",
      "url": "https://www.tcgplayer.com/search/product/all?q=Example%20Card",
      "target_price": 20.00,
      "market_price": 25.00,
      "quantity_needed": 1,
      "min_condition": "Near Mint",
      "language": "English",
      "printing": "Normal",
      "price_drop_percent": 10,
      "deal_score_threshold": 70,
      "enabled": true,
      "tags": ["priority"]
    }
  ]
}
```

## Discord

Create a Discord webhook and add it as the GitHub Actions repository secret:

`DISCORD_WEBHOOK_URL`

The bot sends modern Discord embeds with:

- clickable listing URLs
- link buttons
- price, shipping, landed cost, quantity, and seller rating
- deal scoring details
- bundle purchase savings
- estimated shipping savings

Link buttons do not require a Discord bot/interactions server. They simply open the TCGPlayer listing.

## GitHub Actions persistence

The scheduled workflow runs every two hours.

SQLite stores:

- last observed listing price/shipping/quantity
- sent-alert fingerprints

The SQLite file is restored from and saved to GitHub Actions cache on every run. This prevents repeated alerts across ephemeral runners without requiring a database server.

For a very long-lived production deployment, an external database can replace SQLite without changing the analyzer layer.

## Local run

```bash
cd /home/montealto/Projects/tcg-alert-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
python -m src.main
```

## GitHub Actions

Add `DISCORD_WEBHOOK_URL` under:

**Repository → Settings → Secrets and variables → Actions**

Then use **Run workflow** for the first manual test. The schedule is:

`17 */2 * * *`

GitHub cron is UTC, so this corresponds to every two hours at 17 minutes past the hour in UTC.

## Important scraper note

TCGPlayer's product pages can show **no exact matches for the selected filters** even while the product has listings in other conditions/printings. The scraper now treats that state as a legitimate zero-listing result instead of changing the user's filters behind their back. It also dismisses the international-shipping modal, recognizes current listing-container patterns, and can activate the product page's listings control when listings are lazy-loaded.

Watchlist condition/language/printing fields are also represented in the listing identity, so price changes on the same seller listing keep the same `listing_id`. That is important for price-drop detection.

The scraper fails closed on pages that do not expose usable listing rows. It does not invent prices from product-level market data.
