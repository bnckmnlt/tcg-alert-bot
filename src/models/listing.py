from dataclasses import dataclass
from typing import Optional
from .seller import Seller

@dataclass(frozen=True)
class Listing:
    listing_id: str
    card_name: str
    set_name: Optional[str]
    card_number: Optional[str]
    url: str
    price: float
    shipping: float
    quantity: int
    condition: Optional[str]
    language: Optional[str]
    seller: Seller
    collected_at: str
    market_price: Optional[float] = None
    printing: Optional[str] = None

    @property
    def identity_key(self) -> str:
        parts = (self.card_name, self.set_name, self.card_number, self.printing,
                 self.language, self.condition)
        return "|".join((x or "").strip().casefold() for x in parts)

    @property
    def card_key(self) -> str:
        return "|".join((x or "" for x in (self.card_name, self.set_name, self.card_number, self.printing, self.language)))

    @property
    def landed_unit_price(self) -> float:
        return round(self.price + self.shipping, 2)

    @property
    def available_value(self) -> float:
        return round(self.landed_unit_price * self.quantity, 2)
