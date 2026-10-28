"""Minimal native private sign-in; management UI belongs to later slices."""

from html import escape

from fastapi.responses import HTMLResponse

CSRF_COOKIE = "epm_private_admin_csrf"


def sign_in_page(identity=None, csrf="", error=None, status=401):
    if identity:
        content = f'''<h1>Private administration</h1>
        <p>Signed in as {escape(identity)}.</p>
        <p>This connection is private. Closing it or signing out does not cancel admitted work.</p>
        <p>Operator management is not enabled in this slice.</p>
        <form method="post" action="/sign-out">
        <input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">
        <button type="submit">Sign out</button></form>'''
    else:
        content = """<h1>Sign in to private administration</h1>
        <p>Paste the one-use credential printed by the private launcher. It expires after five minutes.</p>
        <form method="post" action="/sign-in">
        <label for="credential">One-use sign-in credential</label>
        <input id="credential" name="credential" type="password" autocomplete="one-time-code"
          required maxlength="128" autofocus autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="done">
        <button type="submit">Sign in</button></form>"""
    message = {
        "admin_attempt_limit": "Too many sign-in attempts. Try again in five minutes.",
        "admin_broker_unavailable": "Private administration is unavailable. Check the launcher and private listener, then try again.",
    }.get(
        error,
        "Sign-in could not be completed. Obtain a new credential through the private launcher.",
    )
    alert = f'<p role="alert">{message}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Private administration</title></head><body><main>{alert}{content}</main></body></html>""",
        status_code=status if error else 200,
    )
