"""Canonical validation and normalization for shared party contacts."""

from __future__ import annotations

import re
import unicodedata


_EXTENSION = re.compile(r"(?i)\s*(?:x|ext\.?|extension|#)\s*([0-9]{1,6})\s*$")
_PHONE_SEPARATORS = frozenset({
    "+", "(", ")", ".", "/", " ",
    "-", "‐", "‑", "‒", "–", "—", "―", "−",
})


def normalize_contact_value(
    method_kind: str,
    value: str,
    extension: str | None = None,
) -> tuple[str, str | None, str]:
    """Return normalized value, extension, and trimmed display value."""
    if not isinstance(value, str):
        raise ValueError("Contact value must be text.")
    display = unicodedata.normalize("NFKC", value).strip()
    if len(display) > 320:
        raise ValueError("Contact value must be at most 320 characters.")
    if method_kind == "email":
        if extension is not None:
            raise ValueError("Email contact methods cannot have an extension.")
        return _normalize_email(display), None, display
    if method_kind != "phone":
        raise ValueError("Contact method kind is invalid.")

    embedded = _EXTENSION.search(display)
    embedded_extension = embedded.group(1) if embedded else None
    main = display[:embedded.start()].rstrip() if embedded else display
    explicit = _normalize_extension(extension)
    if explicit is not None and embedded_extension is not None and explicit != embedded_extension:
        raise ValueError("Phone extension conflicts with the extension in the contact value.")
    normalized_extension = explicit or _normalize_extension(embedded_extension)
    if not _is_valid_phone_main(main):
        raise ValueError("Phone contains unsupported characters.")
    digits = "".join(character for character in main if character in "0123456789")
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone must contain 7 to 15 digits.")
    normalized = ("+" if main.startswith("+") else "") + digits
    return normalized, normalized_extension, display


def contact_search_terms(value: str) -> tuple[str, ...]:
    raw = unicodedata.normalize("NFKC", value).strip().casefold()
    terms = {raw}
    if phone_value := phone_search_value(raw):
        terms.add(phone_value)
        terms.add(phone_value.lstrip("+"))
    return tuple(sorted(term for term in terms if term))


def like_contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def phone_search_value(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or not any(character in "0123456789" for character in normalized):
        return None
    if not _is_valid_phone_main(normalized):
        return None
    digits = "".join(character for character in normalized if character in "0123456789")
    if not 1 <= len(digits) <= 15:
        return None
    return ("+" if normalized.startswith("+") else "") + digits


def _normalize_email(value: str) -> str:
    if len(value) > 254 or any(character.isspace() or unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("Email address is invalid.")
    if value.count("@") != 1:
        raise ValueError("Email address must contain exactly one @ character.")
    local, domain = value.rsplit("@", 1)
    if not 1 <= len(local) <= 64 or not domain:
        raise ValueError("Email address is invalid.")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise ValueError("Email domain is invalid.") from error
    labels = ascii_domain.split(".")
    if any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("Email domain is invalid.")
    return f"{local.casefold()}@{ascii_domain}"


def _normalize_extension(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 6:
        raise ValueError("Phone extension must contain 1 to 6 digits.")
    return value


def _is_valid_phone_main(value: str) -> bool:
    """Accept only ASCII digits, supported separators, and one leading plus."""
    if value.count("+") > 1 or ("+" in value and not value.startswith("+")):
        return False
    return all(
        character in "0123456789" or character in _PHONE_SEPARATORS
        for character in value
    )
