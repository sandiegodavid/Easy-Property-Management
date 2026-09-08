"""Canonical tenant contact normalization shared by writes and searches."""

import re
import unicodedata


_PHONE_SEPARATORS = frozenset({
    "+", "(", ")", ".", "/", " ",
    "-", "‐", "‑", "‒", "–", "—", "―", "−",
})


def normalize_contact_value(method_kind: str, value: str) -> str:
    normalized_input = unicodedata.normalize("NFKC", value).strip()
    if method_kind == "email":
        normalized = normalized_input.casefold()
    elif method_kind == "phone":
        normalized = ("+" if normalized_input.startswith("+") else "") + re.sub(r"\D", "", normalized_input)
    else:
        raise ValueError("Contact method kind is invalid.")
    if not normalized or normalized == "+":
        raise ValueError("Contact value must contain a usable email or phone value.")
    return normalized


def contact_search_terms(value: str) -> tuple[str, ...]:
    raw = unicodedata.normalize("NFKC", value).strip().casefold()
    terms = {raw}
    if phone_value := phone_search_value(raw):
        terms.add(phone_value)
        if raw.startswith("+"):
            terms.add(f"+{phone_value}")
    return tuple(term for term in terms if term)


def like_contains_pattern(value: str) -> str:
    """Build a literal SQL LIKE contains pattern using a backslash escape."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _is_phone_like(value: str) -> bool:
    """Only punctuation and digits qualify for phone-format normalization."""
    if not any(character.isdigit() for character in value):
        return False
    return all(character.isdigit() or character.isspace() or character in _PHONE_SEPARATORS for character in value)


def phone_search_value(value: str) -> str | None:
    """Return a canonical phone query only when the input is phone-like."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not _is_phone_like(normalized):
        return None
    try:
        return normalize_contact_value("phone", normalized).lstrip("+")
    except ValueError:
        return None
