"""Read-only access to the Dream robot station's local HTTP API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit


class StationUnavailable(Exception):
    """The station could not provide a valid status response."""


class StationRejected(Exception):
    """The station refused a control transition."""


@dataclass(frozen=True)
class StationClient:
    base_url: str = "http://127.0.0.1:8091"
    timeout_s: float = 3.0
    control_timeout_s: float = 65.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Station URL must be an HTTP or HTTPS address.")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "status")

    def post(self, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if route not in ("start", "stop", "home"):
            raise ValueError("Unsupported station route.")
        return self._request("POST", route, body or {})

    def _request(self, method: str, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{route}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        call = request.Request(url, data=payload, method=method)
        if payload is not None:
            call.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(
                call, timeout=self.timeout_s if method == "GET" else self.control_timeout_s
            ) as response:
                result = json.load(response)
        except error.HTTPError as exc:
            try:
                detail = json.load(exc).get("error")
            except (ValueError, OSError, AttributeError):
                detail = None
            raise StationRejected(str(detail or f"Station refused {route} ({exc.code}).")) from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise StationUnavailable(f"Could not reach the Dream station for {route}.") from exc
        if not isinstance(result, dict) or not isinstance(result.get("state"), str):
            raise StationUnavailable("The Dream station returned an invalid status response.")
        return result
