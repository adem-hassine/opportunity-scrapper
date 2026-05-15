from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openclaw.models.domain import Opportunity


@dataclass(frozen=True, slots=True)
class PlatformSession:
    platform: str
    base_url: str
    login_required: bool = True


class OpportunityScraper(Protocol):
    platform: str

    async def fetch_new_opportunities(self) -> list[Opportunity]:
        """Return fresh opportunities extracted from a target platform."""

