"""US state names and abbreviations use the same address evidence."""

import pytest

from app.modules.portfolio.application.service import PortfolioError
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver


@pytest.mark.parametrize(
    ("region", "city", "postal", "expected"),
    [
        ("New York", "New York", "10005", "America/New_York"),
        ("NY", "New York", "10005", "America/New_York"),
        ("  nEw\u00a0  yOrK  ", "New York", "10005", "America/New_York"),
        ("New Jersey", "Princeton", "08540", "America/New_York"),
        ("Oregon", "Portland", "97205", "America/Los_Angeles"),
        ("California", "Los Angeles", "90001", "America/Los_Angeles"),
        ("Texas", "Austin", "78701", "America/Chicago"),
        ("Texas", "El Paso", "79901", "America/Denver"),
        ("Florida", "Miami", "33101", "America/New_York"),
        ("Florida", "Pensacola", "32501", "America/Chicago"),
        ("District of Columbia", "Washington", "20001", "America/New_York"),
    ],
)
def test_us_state_names_resolve_from_existing_address_evidence(region, city, postal, expected):
    assert (
        BundledAddressTimeZoneResolver().resolve(
            address_line_1="2345 Time Square Street",
            city=city,
            region=region,
            postal_code=postal,
            country_code="us",
        )
        == expected
    )


@pytest.mark.parametrize(
    ("region", "city", "postal", "country"),
    [
        ("Texas", "Unknown", None, "US"),
        ("Oregon", "Bend", None, "US"),
        ("Texas", "Austin", "79901", "US"),
        ("New Yrok", "New York", "10005", "US"),
        ("New York", "New York", "10005", "CA"),
    ],
)
def test_state_aliases_do_not_guess_missing_conflicting_or_non_us_evidence(
    region, city, postal, country
):
    with pytest.raises(PortfolioError, match="unambiguous time zone"):
        BundledAddressTimeZoneResolver().resolve(
            address_line_1="1 Main",
            city=city,
            region=region,
            postal_code=postal,
            country_code=country,
        )
