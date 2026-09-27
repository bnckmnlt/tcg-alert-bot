from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class Card:
    name: str
    set_name: Optional[str] = None
    number: Optional[str] = None
    url: Optional[str] = None
    target_price: Optional[float] = None
    max_price: Optional[float] = None
    quantity_needed: int = 1
    min_condition: Optional[str] = None
    language: Optional[str] = None
    printing: Optional[str] = None
    enabled: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)
