"""Desktop Google OAuth Authorization Code + PKCE flow for Loom CLI."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


class OAuthLoginError(RuntimeError):
    pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(72)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
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
            query = parse_qs(urlsplit(self.path).query)
            result["code"] = query.get("code", [""])[0]
            result["state"] = query.get("state", [""])[0]
            result["error"] = query.get("error", [""])[0]
            body = (
                b"<h1>Loom is connected</h1><p>You can close this window and return "
                b"to your terminal.</p>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            event.set()

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = timeout_seconds
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
    try:
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
