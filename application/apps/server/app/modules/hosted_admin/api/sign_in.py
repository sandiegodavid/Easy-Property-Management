"""Native private sign-in; credentials are never put in URLs or browser storage."""

from html import escape

from fastapi.responses import HTMLResponse

CSRF_COOKIE = "epm_private_admin_csrf"


def sign_in_page(error=None, status=401, return_to="/"):
    content = f'''<h1>Sign in to private administration</h1>
        <p>Paste the one-use credential printed by the private launcher. It expires after five minutes.</p>
        <form method="post" action="/sign-in">
        <label for="credential">One-use sign-in credential</label>
        <input id="credential" name="credential" type="password" autocomplete="one-time-code"
          required maxlength="128" autofocus autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="done">
        <input type="hidden" name="return_to" value="{escape(return_to, quote=True)}">
        <button type="submit">Sign in</button></form>'''
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
