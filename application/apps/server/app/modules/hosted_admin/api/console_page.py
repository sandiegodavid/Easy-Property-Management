"""Private console document and closed canonical routes; no inline scripts."""

from html import escape
import re

from fastapi.responses import HTMLResponse


def console_route(path):
    return bool(
        re.fullmatch(
            r"/(?:operators(?:/[a-z0-9][a-z0-9-]{0,31})?|operations(?:/[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})?|qualification|discrepancies)?",
            path,
        )
    )


def console_page(identity, csrf):
    return HTMLResponse(f'''<!doctype html><html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Demo administration</title><link rel="stylesheet" href="/admin-assets/admin.css">
      <script type="module" src="/admin-assets/admin.js"></script></head><body>
      <a class="skip" href="#content">Skip to content</a>
      <header><strong>Demo administration</strong><p>Signed in as {escape(identity)}.</p>
      <form method="post" action="/sign-out"><input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">
      <button type="submit">Sign out</button></form></header>
      <p class="privacy">Private connection · Signing out does not cancel admitted work.</p>
      <div id="admin-root"></div><noscript><main>Enable JavaScript for asynchronous observations.
      No management changes can be made from this read-only console.</main></noscript></body></html>''')
