from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Seller:
    name: str
    rating_percent: Optional[float] = None
    rating_count: Optional[int] = None
    url: Optional[str] = None
