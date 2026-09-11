"""Desktop Google OAuth Authorization Code + PKCE flow for Loom CLI."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

_LOGIN_SUCCESS_PAGE = b"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Loom connected</title>
  <style>
    :root {
      color-scheme: dark;
      --ink: #0d0d0f;
      --line: rgba(255,255,255,.14);
      --white: #f5f3ee;
      --muted: #99979f;
      --violet: #8b5cf6;
      --violet-bright: #a78bfa;
    }
    * { box-sizing: border-box; }
    body {
      display: grid;
      min-height: 100vh;
      margin: 0;
      place-items: center;
      padding: 24px;
      color: var(--white);
      background:
        linear-gradient(rgba(255,255,255,.024) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.024) 1px, transparent 1px),
        radial-gradient(circle at 68% -12%, rgba(139,92,246,.2), transparent 34rem),
        #070708;
      background-size: 42px 42px, 42px 42px, auto, auto;
      font-family:
        Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .alert {
      position: relative;
      width: min(560px, 100%);
      overflow: hidden;
      padding: 34px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(13,13,15,.96);
      box-shadow: 0 32px 100px rgba(0,0,0,.42);
    }
    .alert::after {
      content: "";
      position: absolute;
      top: -70px;
      right: -50px;
      width: 190px;
      height: 190px;
      border: 1px solid rgba(167,139,250,.16);
      border-radius: 50%;
      box-shadow: 0 0 70px rgba(139,92,246,.14);
    }
    .label {
      margin: 0 0 34px;
      color: var(--violet-bright);
      font: 650 10px/1 "SFMono-Regular", Consolas, monospace;
      letter-spacing: .14em;
      text-transform: uppercase;
    }
    .status {
      display: grid;
      width: 42px;
      height: 42px;
      margin-bottom: 22px;
      place-items: center;
      border: 1px solid rgba(167,139,250,.45);
      border-radius: 12px;
      color: #ddd6fe;
      background: rgba(139,92,246,.15);
      box-shadow: 0 0 28px rgba(139,92,246,.16);
      font-size: 18px;
    }
    h1 {
      margin: 0;
      font-size: clamp(32px, 7vw, 52px);
      font-weight: 660;
      line-height: .96;
      letter-spacing: -.055em;
    }
    p {
      max-width: 410px;
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.6;
    }
    strong { color: var(--white); font-weight: 620; }
  </style>
</head>
<body>
  <main class="alert" role="status" aria-live="polite">
    <p class="label">Loom / Authentication complete</p>
    <div class="status" aria-hidden="true">&#10003;</div>
    <h1>You&apos;re connected.</h1>
    <p>
      Google sign-in was successful. You can close this tab and
      <strong>return to your terminal</strong>.
    </p>
  </main>
</body>
</html>"""


class OAuthLoginError(RuntimeError):
    pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(72)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def google_login(api_url: str, *, timeout_seconds: int = 180) -> dict[str, Any]:
    config_response = httpx.get(
        f"{api_url}/v1/auth/google/config",
        params={"client_kind": "cli"},
        timeout=30,
    )
    config_response.raise_for_status()
    config = cast(dict[str, Any], config_response.json())
    if not config.get("enabled") or not config.get("client_id"):
        raise OAuthLoginError(
            "Google login is not configured on this Loom server. "
            "Self-hosters must set GOOGLE_CLI_CLIENT_ID and GOOGLE_OAUTH_ENABLED=true."
        )

    result: dict[str, str] = {}
    event = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/oauth/callback":
                body = b"Not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            query = parse_qs(parsed.query)
            result["code"] = query.get("code", [""])[0]
            result["state"] = query.get("state", [""])[0]
            result["error"] = query.get("error", [""])[0]
            body = _LOGIN_SUCCESS_PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            event.set()

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth/callback"
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    query = urlencode(
        {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(config.get("scopes") or ["openid", "email", "profile"]),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "prompt": "select_account",
        }
    )
    authorization_url = f"{config['authorization_endpoint']}?{query}"
    print("Opening Google sign-in in your browser...")
    if not webbrowser.open(authorization_url):
        print(f"Open this URL to continue:\n{authorization_url}")
    deadline = time.monotonic() + timeout_seconds
    try:
        while not event.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not event.is_set():
        raise OAuthLoginError("Google login timed out. Run `loom login` to try again.")
    if result.get("error"):
        raise OAuthLoginError(f"Google login was not completed: {result['error']}")
    if result.get("state") != state or not result.get("code"):
        raise OAuthLoginError("Google login returned an invalid callback.")

    response = httpx.post(
        f"{api_url}/v1/auth/google/exchange",
        json={
            "client_kind": "cli",
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        raise OAuthLoginError(str(detail or "Google login failed"))
    return cast(dict[str, Any], response.json())
