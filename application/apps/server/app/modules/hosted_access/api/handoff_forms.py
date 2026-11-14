"""Fixed-origin browser transfers. Credentials travel in named POST fields."""

import asyncio
from html import escape
from urllib.parse import parse_qsl

from fastapi.responses import HTMLResponse

from app.modules.hosted_access.application.managed_provider import ProviderDenied

MAX_FORM_BYTES = 20000


class FormTooLarge(ProviderDenied):
    pass


def transfer_form(origin, path, fields, *, heading, button):
    action = escape(origin + path, quote=True)
    encoded = "".join(
        f'<input type="hidden" name="{escape(name, quote=True)}" value="{escape(value, quote=True)}">'
        for name, value in fields.items()
    )
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f"<title>{escape(heading)}</title><main><h1>{escape(heading)}</h1>"
        f'<form method="post" action="{action}">{encoded}'
        f'<button type="submit">{escape(button)}</button></form></main></html>',
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": f"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action {origin}",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def read_form(request, expected):
    if (
        request.headers.get("content-type", "").split(";", 1)[0]
        != "application/x-www-form-urlencoded"
    ):
        raise ProviderDenied()
    raw = bytearray()
    async with asyncio.timeout(5):
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_FORM_BYTES:
                raise FormTooLarge()
            raw.extend(chunk)
    try:
        fields = parse_qsl(
            raw.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=len(expected),
            errors="strict",
        )
    except UnicodeError, ValueError:
        raise ProviderDenied() from None
    result = dict(fields)
    if len(fields) != len(result) or result.keys() != expected:
        raise ProviderDenied()
    return result
