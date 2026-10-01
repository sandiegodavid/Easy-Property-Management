"""Canonical provider-category name normalization."""

import unicodedata


def normalize_provider_category_name(value: str) -> str:
    """Produce the catalog's Unicode-, whitespace-, and case-normalized key."""
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
