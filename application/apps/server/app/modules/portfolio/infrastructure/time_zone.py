"""Bundled, local address-to-time-zone resolution for PORT-001.

The resolver deliberately works with candidate sets. It never falls back to a
region-wide guess for a multi-zone jurisdiction: persistence is permitted only
when the bundled address index produces exactly one canonical IANA identifier.
"""

from __future__ import annotations

import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.portfolio.application.service import PortfolioError


class BundledAddressTimeZoneResolver:
    """Small offline address/postal candidate index for the local MVP."""

    _COUNTRY_CANDIDATES = {
        "GB": ("Europe/London",), "IE": ("Europe/Dublin",),
        "IS": ("Atlantic/Reykjavik",), "JP": ("Asia/Tokyo",),
        "KR": ("Asia/Seoul",), "NZ": ("Pacific/Auckland",),
        "PT": ("Europe/Lisbon",),
    }
    _SINGLE_ZONE_REGIONS = {
        ("US", "AL"): ("America/Chicago",), ("US", "CA"): ("America/Los_Angeles",),
        ("US", "CO"): ("America/Denver",), ("US", "CT"): ("America/New_York",),
        ("US", "DC"): ("America/New_York",), ("US", "DE"): ("America/New_York",),
        ("US", "GA"): ("America/New_York",), ("US", "HI"): ("Pacific/Honolulu",),
        ("US", "IA"): ("America/Chicago",), ("US", "IL"): ("America/Chicago",),
        ("US", "LA"): ("America/Chicago",), ("US", "MA"): ("America/New_York",),
        ("US", "MD"): ("America/New_York",), ("US", "ME"): ("America/New_York",),
        ("US", "MN"): ("America/Chicago",), ("US", "MO"): ("America/Chicago",),
        ("US", "MS"): ("America/Chicago",), ("US", "MT"): ("America/Denver",),
        ("US", "NC"): ("America/New_York",), ("US", "NH"): ("America/New_York",),
        ("US", "NJ"): ("America/New_York",), ("US", "NM"): ("America/Denver",),
        ("US", "NV"): ("America/Los_Angeles",), ("US", "NY"): ("America/New_York",),
        ("US", "OH"): ("America/New_York",), ("US", "OK"): ("America/Chicago",),
        ("US", "PA"): ("America/New_York",), ("US", "RI"): ("America/New_York",),
        ("US", "SC"): ("America/New_York",), ("US", "UT"): ("America/Denver",),
        ("US", "VA"): ("America/New_York",), ("US", "VT"): ("America/New_York",),
        ("US", "WA"): ("America/Los_Angeles",), ("US", "WI"): ("America/Chicago",),
        ("US", "WV"): ("America/New_York",), ("US", "WY"): ("America/Denver",),
        ("CA", "AB"): ("America/Edmonton",), ("CA", "MB"): ("America/Winnipeg",),
        ("CA", "NB"): ("America/Moncton",), ("CA", "NL"): ("America/St_Johns",),
        ("CA", "NS"): ("America/Halifax",), ("CA", "PE"): ("America/Halifax",),
        ("CA", "QC"): ("America/Toronto",), ("CA", "SK"): ("America/Regina",),
        ("CA", "YT"): ("America/Whitehorse",),
    }
    _CITY_CANDIDATES = {
        ("US", "OR", "portland"): ("America/Los_Angeles",),
        ("US", "TX", "austin"): ("America/Chicago",),
        ("US", "TX", "el paso"): ("America/Denver",),
        ("US", "FL", "miami"): ("America/New_York",),
        ("US", "FL", "pensacola"): ("America/Chicago",),
        ("CA", "BC", "vancouver"): ("America/Vancouver",),
        ("CA", "ON", "toronto"): ("America/Toronto",),
    }
    _POSTAL_CANDIDATES = {
        ("US", "OR", "972"): ("America/Los_Angeles",),
        ("US", "TX", "733"): ("America/Chicago",),
        ("US", "TX", "787"): ("America/Chicago",),
        ("US", "TX", "799"): ("America/Denver",),
        ("US", "FL", "325"): ("America/Chicago",),
        ("US", "FL", "331"): ("America/New_York",),
        ("CA", "BC", "V"): ("America/Vancouver",),
        ("CA", "ON", "M"): ("America/Toronto",),
        ("CA", "ON", "K"): ("America/Toronto",),
    }
    _STREET_CANDIDATES = {
        ("US", "TX", "500 congress ave"): ("America/Chicago",),
    }
    _REGION_CANDIDATES = {
        ("CA", "NU"): ("America/Iqaluit", "America/Rankin_Inlet", "America/Cambridge_Bay"),
    }

    def resolve(self, *, address_line_1: str, city: str, region: str | None,
                postal_code: str | None, country_code: str) -> str:
        candidates = self.candidates(
            address_line_1=address_line_1, city=city, region=region,
            postal_code=postal_code, country_code=country_code,
        )
        if len(candidates) != 1:
            raise PortfolioError(
                "The address does not resolve to one unambiguous time zone; provide a supported street, city, region, or postal code."
            )
        zone = candidates[0]
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError as error:
            raise PortfolioError("The resolved property time zone is unavailable.") from error
        return zone

    def candidates(self, *, address_line_1: str, city: str, region: str | None,
                   postal_code: str | None, country_code: str) -> tuple[str, ...]:
        """Return all local dataset candidates, without choosing among them."""
        country = _key(country_code).upper()
        region_key = None if region is None else _key(region).upper()
        city_key = _key(city)
        street_key = _key(address_line_1)
        postal_key = "" if postal_code is None else "".join(
            character for character in _key(postal_code).upper() if character.isalnum()
        )
        if region_key is None:
            return self._COUNTRY_CANDIDATES.get(country, ())
        evidence: list[set[str]] = []
        street = self._STREET_CANDIDATES.get((country, region_key, street_key))
        if street is not None:
            evidence.append(set(street))
        for size in range(len(postal_key), 0, -1):
            postal = self._POSTAL_CANDIDATES.get((country, region_key, postal_key[:size]))
            if postal is not None:
                evidence.append(set(postal))
                break
        city_match = self._CITY_CANDIDATES.get((country, region_key, city_key))
        if city_match is not None:
            evidence.append(set(city_match))
        region_candidates = self._SINGLE_ZONE_REGIONS.get(
            (country, region_key), self._REGION_CANDIDATES.get((country, region_key), ())
        )
        if region_candidates:
            evidence.append(set(region_candidates))
        if not evidence:
            return ()
        shared = set.intersection(*evidence)
        return tuple(sorted(shared))


def _key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())
