"""The HTTP boundary. Every network call goes through a Transport so tests never hit the wire.

UrllibTransport deliberately never raises for an HTTP status: urllib raises HTTPError on
4xx/5xx, but the capture loop needs to read a 429's Retry-After header, so statuses come
back as ordinary Responses. A transport-level failure (DNS, timeout, refused) surfaces as
status 0.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_RETRY_MS = 10_000


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> object:
        """Decode the body, or None when there is no body (e.g. a 204)."""
        return json.loads(self.body) if self.body else None

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup; HTTP header casing is not guaranteed."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response: ...

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


def _json_request(
    url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str] | None = None,
) -> urllib.request.Request:
    """A POST carrying a JSON body. The content-type is ours, not the caller's: a form
    content-type on a JSON body earns a 400 whose message names nothing useful."""
    body = json.dumps(payload).encode("utf-8")
    merged = {**dict(headers or {}), "Content-Type": "application/json"}
    return urllib.request.Request(url, data=body, headers=merged, method="POST")


class UrllibTransport:
    """stdlib transport. No third-party HTTP client in Phase 0."""

    def __init__(self, timeout_s: float = 10.0) -> None:
        self._timeout_s = timeout_s

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        return self._send(request)

    def post(
        self,
        url: str,
        data: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        body = urllib.parse.urlencode(dict(data)).encode("utf-8")
        merged = {"Content-Type": "application/x-www-form-urlencoded", **dict(headers or {})}
        request = urllib.request.Request(url, data=body, headers=merged, method="POST")
        return self._send(request)

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._send(_json_request(url, payload, headers))

    def _send(self, request: urllib.request.Request) -> Response:
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                return Response(response.status, response.read(), dict(response.headers))
        except urllib.error.HTTPError as err:
            # A 429 or 401 is information, not an exception; the caller decides what to do.
            return Response(err.code, err.read(), dict(err.headers))
        except urllib.error.URLError as err:
            return Response(0, str(err.reason).encode("utf-8"), {})


def retry_after_ms(response: Response, default_ms: int = DEFAULT_RETRY_MS) -> int:
    """Spotify sends Retry-After in whole seconds on a 429. Absent or malformed -> default."""
    raw = response.header("Retry-After")
    try:
        return max(0, int(float(raw))) * 1000  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default_ms
