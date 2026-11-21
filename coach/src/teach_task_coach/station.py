"""Read-only access to the Dream robot station's local HTTP API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit


class StationUnavailable(Exception):
    """The station could not provide a valid status response."""


@dataclass(frozen=True)
class StationClient:
    base_url: str = "http://127.0.0.1:8091"
    timeout_s: float = 3.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Station URL must be an HTTP or HTTPS address.")

    def status(self) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/status"
        try:
            with request.urlopen(url, timeout=self.timeout_s) as response:
                payload = json.load(response)
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise StationUnavailable("Could not read the Dream station status.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), str):
            raise StationUnavailable("The Dream station returned an invalid status response.")
        return payload
