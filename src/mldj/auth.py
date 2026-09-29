"""Spotify PKCE auth for a local script. Ported from cd-player's auth.ts.

Two things change in the port: localStorage becomes a gitignored JSON file under data/,
and the browser redirect becomes a one-shot loopback HTTP server on the exact redirect
URI Spotify has registered.

Phase 0 only reads what is playing, so SCOPE is the single read scope. Do not widen it;
user-modify-playback-state belongs to Phase 4.
"""

import base64
import dataclasses
import hashlib
import http.server
import json
import secrets
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mldj.clock import Clock
from mldj.transport import Transport

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing"
VERIFIER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
REFRESH_MARGIN_MS = 60_000
TOKENS_PATH = Path("data/.spotify-tokens.json")  # data/ is gitignored; this repo is public


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: int  # epoch ms


def random_verifier(length: int = 64) -> str:
    return "".join(secrets.choice(VERIFIER_ALPHABET) for _ in range(length))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(client_id: str, verifier: str) -> str:
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge(verifier),
        }
    )
    return f"{AUTH_URL}?{params}"


def parse_callback_code(path: str) -> str | None:
    query = urllib.parse.urlparse(path).query
    values = urllib.parse.parse_qs(query).get("code")
    return values[0] if values else None


def merge_token_response(prev: Tokens | None, payload: dict, now_ms: int) -> Tokens:
    """Spotify's refresh response often omits refresh_token; keep the one we already hold."""
    return Tokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token") or (prev.refresh_token if prev else ""),
        expires_at=now_ms + int(payload["expires_in"]) * 1000,
    )


def should_refresh(tokens: Tokens, now_ms: int) -> bool:
    return now_ms >= tokens.expires_at - REFRESH_MARGIN_MS


def load_tokens(path: Path = TOKENS_PATH) -> Tokens | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Tokens(raw["access_token"], raw["refresh_token"], int(raw["expires_at"]))


def save_tokens(tokens: Tokens, path: Path = TOKENS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(tokens)), encoding="utf-8")


def wait_for_code(
    port: int = 8888,
    max_requests: int = 5,
    on_ready: Callable[[], None] | None = None,
) -> str:
    """Serve loopback requests until one carries a ?code=, then return it.

    A browser may request /favicon.ico alongside the callback, so this serves up to
    max_requests rather than exactly one. on_ready fires once the socket is listening,
    which is how a caller knows it is safe to send the browser at the authorize URL.
    """
    captured: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming, not ours
            code = parse_callback_code(self.path)
            if code:
                captured.append(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p>ml-dj is authorized. You can close this tab.</p>")

        def log_message(self, *args: object) -> None:
            pass  # keep the capture console quiet

    with http.server.HTTPServer(("127.0.0.1", port), Handler) as server:
        if on_ready is not None:
            on_ready()
        for _ in range(max_requests):
            server.handle_request()
            if captured:
                break
    if not captured:
        raise SystemExit("the Spotify callback carried no ?code= - authorization failed")
    return captured[0]


def _request_tokens(
    transport: Transport, clock: Clock, prev: Tokens | None, data: dict[str, str]
) -> Tokens:
    response = transport.post(TOKEN_URL, data)
    if response.status != 200:
        raise SystemExit(
            f"Spotify token endpoint returned {response.status}: "
            f"{response.body.decode('utf-8', 'replace')[:200]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit("Spotify token endpoint returned an unreadable body")
    return merge_token_response(prev, payload, clock.now_ms())


def exchange_code(
    transport: Transport, clock: Clock, client_id: str, code: str, verifier: str
) -> Tokens:
    return _request_tokens(
        transport,
        clock,
        None,
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )


def refresh_tokens(transport: Transport, clock: Clock, client_id: str, tokens: Tokens) -> Tokens:
    return _request_tokens(
        transport,
        clock,
        tokens,
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
        },
    )


def login(transport: Transport, clock: Clock, client_id: str, path: Path = TOKENS_PATH) -> Tokens:
    """Interactive one-time authorization. Opens a browser and waits on the loopback."""
    verifier = random_verifier()
    url = authorize_url(client_id, verifier)
    print("Opening Spotify authorization. If no browser opens, visit:\n" + url)
    webbrowser.open(url)
    code = wait_for_code()
    tokens = exchange_code(transport, clock, client_id, code, verifier)
    save_tokens(tokens, path)
    return tokens


def token_provider(
    transport: Transport, clock: Clock, client_id: str, path: Path = TOKENS_PATH
) -> Callable[[], str]:
    """Return a callable that always hands back a live access token.

    The capture loop calls this on every poll, so refresh has to be transparent: a
    multi-hour session outlives a one-hour token.
    """

    def provide() -> str:
        tokens = load_tokens(path)
        if tokens is None:
            tokens = login(transport, clock, client_id, path)
        if should_refresh(tokens, clock.now_ms()):
            tokens = refresh_tokens(transport, clock, client_id, tokens)
            save_tokens(tokens, path)
        return tokens.access_token

    return provide
