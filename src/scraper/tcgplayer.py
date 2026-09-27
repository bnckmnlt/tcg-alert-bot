from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..models.listing import Listing
from ..models.seller import Seller
from .selenium import Browser

LOG = logging.getLogger("tcg-alert-bot.scraper")


def _number(text: str, default: float = 0.0) -> float:
    if not text:
        return default
    match = re.search(r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)", text)
    if not match:
        match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1).replace(",", "")) if match else default


def _first_text(root, selectors: Iterable[str]) -> str:
    for selector in selectors:
        try:
            value = root.find_element(By.CSS_SELECTOR, selector).text.strip()
            if value:
                return value
        except Exception:
            pass
    return ""


def _first_attr(root, selectors: Iterable[str], attr: str) -> str:
    for selector in selectors:
        try:
            value = root.find_element(By.CSS_SELECTOR, selector).get_attribute(attr)
            if value:
                return value.strip()
        except Exception:
            pass
    return ""


def _clean_product_url(url: str) -> str:
    # Filter parameters are useful for humans, but they can leave the product
    # page in a "no exact matches" state. The scraper deliberately keeps them
    # when loading so TCGPlayer's price points match the requested version.
    return urlunsplit(urlsplit(url)._replace(fragment=""))


def _rating(text: str) -> tuple[float | None, int | None]:
    if not text:
        return None, None
    percent = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    sales = re.search(r"(\d[\d,]*)\s*\+?\s*(?:sales|feedback)", text, re.I)
    rating = float(percent.group(1)) if percent else None
    count = int(sales.group(1).replace(",", "")) if sales else None
    if rating is not None and not 0 <= rating <= 100:
        rating = None
    return rating, count


def _seller_from_text(text: str, rating: float | None, rating_count: int | None) -> str:
    if not text or rating is None:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rating_index = next(
        (i for i, line in enumerate(lines) if re.search(r"\d{1,3}(?:\.\d+)?\s*%", line)),
        None,
    )
    if rating_index is None:
        return ""
    for line in reversed(lines[:rating_index]):
        lower = line.casefold()
        if (
            line.startswith("$")
            or "shipping" in lower
            or "near mint" in lower
            or "moderately played" in lower
            or "lightly played" in lower
            or "heavily played" in lower
            or "damaged" in lower
            or re.fullmatch(r"\d+(?:\s+of\s+\d+)?", line)
        ):
            continue
        return line
    return ""


def _quantity(text: str) -> int:
    if not text:
        return 1
    match = re.search(r"\bof\s+(\d+)\b", text, re.I)
    if match:
        return max(1, int(match.group(1)))
    match = re.search(r"(?:available|quantity)\D+(\d+)", text, re.I)
    if match:
        return max(1, int(match.group(1)))
    return max(1, int(_number(text, 1)))


def _label_value(body: str, label: str) -> float | None:
    match = re.search(
        rf"{re.escape(label)}\s*\|?\s*\$\s*([\d,]+(?:\.\d+)?)",
        body,
        re.I,
    )
    return float(match.group(1).replace(",", "")) if match else None


class TCGPlayerScraper:
    LISTINGS_CONTAINER_SELECTOR = ".product-details__listings, .product-details__all-listings"
    ROW_SELECTORS = (
        ".listing-item",
        ".product-details__listings .listing-item",
        "[data-testid*='listing']",
    )

    PRICE_SELECTORS = (
        ".listing-item__listing-data__info__price",
    )
    SHIPPING_SELECTORS = (
        ".listing-item__listing-data__info__shipping-message",
        "[class*='shipping']",
    )
    SELLER_SELECTORS = (
        ".seller-info__name",
        "[class*='seller'] a",
        "[class*='seller']",
    )
    RATING_SELECTORS = (
        ".seller-info__rating",
        "[class*='rating']",
        "[class*='feedback']",
    )
    QUANTITY_SELECTORS = (
        ".add-to-cart__available",
        "[class*='available']",
        "[class*='quantity']",
    )
    CONDITION_SELECTORS = (
        ".listing-item__condition",
        "[class*='condition']",
    )
    PRINTING_SELECTORS = (
        "[class*='printing']",
        "[class*='version']",
    )
    LANGUAGE_SELECTORS = (
        "[class*='language']",
    )

    def __init__(self, browser: Browser):
        self.browser = browser
        self.last_market_price: float | None = None
        self.last_recent_sale: float | None = None

    def _dismiss_international_modal(self) -> None:
        selectors = (
            "[data-testid='internationalModal'] [aria-label='Dismiss modal']",
            ".international-modal [aria-label='Dismiss modal']",
        )
        for selector in selectors:
            try:
                button = self.browser.driver.find_element(By.CSS_SELECTOR, selector)
                if button.is_displayed():
                    button.click()
                    time.sleep(0.5)
                    return
            except Exception:
                pass

    def _extract_price_points(self) -> None:
        body = self.browser.driver.find_element(By.TAG_NAME, "body").text
        self.last_market_price = _label_value(body, "Market Price")
        self.last_recent_sale = _label_value(body, "Most Recent Sale")

    def _has_no_exact_matches(self) -> bool:
        body = self.browser.driver.find_element(By.TAG_NAME, "body").text.lower()
        return "no exact matches for the filters you have selected" in body

    def _click_clear_filters(self) -> bool:
        for selector in (".spotlight__no-listings button", ".no-result__additional-content button"):
            try:
                element = self.browser.driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    self.browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                    self.browser.driver.execute_script("arguments[0].click();", element)
                    time.sleep(1)
                    return True
            except Exception:
                pass
        return False

    def _click_view_all_listings(self) -> None:
        selectors = (
            ".view-all-listings__more-prices",
            ".product-details__all-listings a",
        )
        for selector in selectors:
            try:
                element = self.browser.driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    if "no listings available" in element.text.strip().lower():
                        continue
                    self.browser.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", element
                    )
                    self.browser.driver.execute_script("arguments[0].click();", element)
                    time.sleep(1)
                    return
            except Exception:
                pass

    def _rows(self) -> list:
        found = []
        seen = set()
        for selector in self.ROW_SELECTORS:
            try:
                for root in self.browser.driver.find_elements(By.CSS_SELECTOR, selector):
                    key = root.id
                    if key in seen:
                        continue
                    text = root.text.strip()
                    if "$" not in text:
                        continue
                    # Listing rows normally expose price plus either a seller,
                    # condition, inventory control, or add-to-cart action.
                    lower = text.lower()
                    if not any(
                        token in lower
                        for token in ("add to cart", "near mint", "of 1", "of 2", "shipping")
                    ):
                        continue
                    # Product-level/spotlight wrappers can contain a price-like
                    # number without containing an actual seller/listing.
                    if "unknown seller" in lower and "add to cart" not in lower:
                        continue
                    seen.add(key)
                    found.append(root)
            except Exception:
                pass

        # The current TCGPlayer UI does not expose a stable listing-row class.
        # When class/test-id selectors find nothing, anchor discovery on the
        # seller action instead. A real seller row has an Add to Cart control;
        # product-level summaries such as "As low as $0.06" do not.
        if not found:
            try:
                actions = self.browser.driver.find_elements(
                    By.XPATH,
                    "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add to cart')]",
                )
                for action in actions:
                    try:
                        root = action
                        for _ in range(8):
                            root = root.find_element(By.XPATH, "./..")
                            text = root.text.strip()
                            lower = text.lower()
                            if "$" in text and ("shipping" in lower or "seller" in lower or "near mint" in lower):
                                key = root.id
                                if key not in seen:
                                    seen.add(key)
                                    found.append(root)
                                break
                    except Exception:
                        pass
            except Exception:
                pass

        # Current TCGPlayer markup contains nested elements whose class names
        # also include "listing". Keep the deepest qualifying nodes so a
        # product-level wrapper cannot be mistaken for one giant listing.
        rows = []
        for root in found:
            try:
                nested = any(
                    other is not root and self.browser.driver.execute_script(
                        "return arguments[0].contains(arguments[1]);", root, other
                    )
                    for other in found
                )
            except Exception:
                nested = False
            if not nested:
                rows.append(root)
        return rows

    def _parse_row(self, root, card_name: str, set_name: str | None, source_url: str, filters: dict | None = None) -> Listing | None:
        text = root.text.strip()

        # Only trust the known listing-price element. Broad selectors such as
        # [class*='price'] can match unrelated product-page price widgets
        # nested inside a listing wrapper (for example a tiny fee/discount).
        price_text = _first_text(root, self.PRICE_SELECTORS)
        price = _number(price_text, -1)
        if price < 0:
            # A genuine listing row normally contains its item price as the
            # first currency value in the row text.
            price = _number(text, -1)
        if price < 0:
            return None

        shipping_text = _first_text(root, self.SHIPPING_SELECTORS)
        shipping = 0.0 if re.search(r"shipping\s*:\s*included|free shipping", shipping_text, re.I) else _number(shipping_text, 0.0)

        seller_text = _first_text(root, self.SELLER_SELECTORS)
        rating_text = _first_text(root, self.RATING_SELECTORS)
        rating, rating_count = _rating(rating_text or text)
        seller_name = seller_text or _seller_from_text(text, rating, rating_count) or "Unknown seller"

        qty_text = _first_text(root, self.QUANTITY_SELECTORS)
        quantity = _quantity(qty_text or text)

        condition = _first_text(root, self.CONDITION_SELECTORS) or None
        printing = _first_text(root, self.PRINTING_SELECTORS) or (str(filters.get("printing")) if filters and filters.get("printing") else None)
        language = _first_text(root, self.LANGUAGE_SELECTORS) or (str(filters.get("language")) if filters and filters.get("language") else None)
        condition = condition or (str(filters.get("min_condition")) if filters and filters.get("min_condition") else None)
        card_number = str(filters.get("number")) if filters and filters.get("number") else None

        href = _first_attr(
            root,
            (
                ".listing-item__listing-data__listo__see-more[href]",
                "a[href*='/product/']",
                "a[href]",
            ),
            "href",
        ) or source_url

        stable = "|".join(
            str(x or "").strip().casefold()
            for x in (card_name, set_name, href, seller_name, condition, printing, language)
        )
        listing_id = hashlib.sha1(stable.encode()).hexdigest()[:20]

        return Listing(
            listing_id=listing_id,
            card_name=card_name,
            set_name=set_name,
            card_number=card_number,
            url=href,
            price=round(price, 2),
            shipping=round(shipping, 2),
            quantity=quantity,
            condition=condition,
            language=language,
            seller=Seller(seller_name, rating, rating_count),
            collected_at=datetime.now(timezone.utc).isoformat(),
            market_price=self.last_market_price,
            printing=printing,
        )

    def search(
        self,
        url: str,
        card_name: str,
        set_name: str | None = None,
        filters: dict | None = None,
    ) -> list[Listing]:
        self.browser.get(_clean_product_url(url))
        self._dismiss_international_modal()
        self._extract_price_points()

        wait = WebDriverWait(self.browser.driver, 30)
        try:
            wait.until(lambda d: self._rows() or self._has_no_exact_matches())
        except Exception:
            pass

        self._dismiss_international_modal()
        roots = self._rows()

        if not roots and self._has_no_exact_matches():
            # The "As low as $X" value on a no-exact-match page is a product
            # summary, not a seller listing. Clear the site's filters and parse
            # the actual listing rows; our watchlist matcher will enforce the
            # requested condition/language/printing afterward.
            if self._click_clear_filters():
                try:
                    wait.until(lambda d: self._rows())
                except Exception:
                    pass
                roots = self._rows()

        if not roots:
            self._click_view_all_listings()
            try:
                wait.until(lambda d: self._rows())
            except Exception:
                pass
            roots = self._rows()

        if not roots:
            body = self.browser.driver.find_element(By.TAG_NAME, "body").text.strip()
            if self._has_no_exact_matches():
                LOG.info(
                    "No exact TCGPlayer listings for %s with the selected filters "
                    "(market=%s, recent_sale=%s).",
                    card_name,
                    self.last_market_price,
                    self.last_recent_sale,
                )
            else:
                LOG.warning(
                    "No listing rows found for %s (title=%r, current_url=%s, body_chars=%d, preview=%r)",
                    card_name,
                    self.browser.driver.title,
                    self.browser.driver.current_url,
                    len(body),
                    body[:500],
                )
            return []

        listings = []
        for root in roots:
            listing = self._parse_row(root, card_name, set_name, url, filters)
            if listing is not None:
                listings.append(listing)

        # De-duplicate nested current-DOM elements.
        unique: dict[str, Listing] = {x.listing_id: x for x in listings}
        return list(unique.values())
