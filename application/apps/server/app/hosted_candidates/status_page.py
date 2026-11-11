"""Self-contained safe interstitial; no JavaScript, forms, resources or replay."""

from datetime import UTC, datetime

CSS = """
:root { color-scheme: light dark; font: 1rem/1.6 system-ui, sans-serif;
  background: #e8ede8; color: #203b36; }
body { margin: 0; padding: clamp(1rem, 5vw, 3rem); }
main { max-inline-size: 38rem; margin: 8vh auto; padding: clamp(1rem, 4vw, 2rem);
  border: 1px solid #617b72; border-block-start: 4px solid #17685a;
  border-radius: 1rem; background: #f0f4ef; overflow-wrap: anywhere; }
h1 { font-size: clamp(1.5rem, 5vw, 2rem); line-height: 1.3; }
a { display: inline-block; padding: .65rem 1rem; color: inherit;
  border: 1px solid currentColor; border-radius: .4rem; }
a:focus-visible { outline: 3px solid currentColor; outline-offset: 4px; }
@media (prefers-color-scheme: dark) {
  :root { background: #1d2521; color: #e4eee8; }
  main { background: #26312b; border-color: #8cbcaf; }
}
"""


def page():
    checked = datetime.now(UTC).strftime("%b %d, %Y, %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Temporarily unavailable | Easy Property Management</title>
<link rel="stylesheet" href="/status.css"></head>
<body><main><h1>Temporarily unavailable</h1>
<p>This service is not ready to open. Please try again later.</p>
<p>This page cannot confirm whether an earlier submission was saved.
Keep any open form. Check its original result when the service is available;
do not submit it again from this page.</p>
<p>Availability checked <time>{checked}</time>. This is not a check of your records.</p>
<a href="/">Check availability again</a>
<p>Refresh checks availability once. It never resends a form.</p>
</main></body></html>""".encode()
