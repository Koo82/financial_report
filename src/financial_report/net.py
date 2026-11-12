"""Small HTTP helpers shared by the market-data collectors."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


class FetchError(RuntimeError):
    """Raised when a remote source cannot be read."""


def get_text(
    url: str,
    *,
    timeout: float = 20.0,
    attempts: int = 2,
    sleep: Callable[[float], None] | None = None,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Read a URL as text, retrying transient failures with backoff."""

    pause = sleep or time.sleep
    last: Exception | None = None

    for attempt in range(attempts):
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                **dict(headers or {}),
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset, errors="replace")
        except OSError as exc:
            last = exc
        else:
            if text.strip():
                return text
            last = FetchError(f"empty response from {url}")

        if attempt + 1 < attempts:
            pause(1.5 * (attempt + 1))

    raise FetchError(f"could not fetch {url}: {last}") from last


def get_json(
    url: str,
    *,
    timeout: float = 20.0,
    attempts: int = 2,
    sleep: Callable[[float], None] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    text = get_text(
        url,
        timeout=timeout,
        attempts=attempts,
        sleep=sleep,
        headers=headers,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid JSON from {url}: {exc}") from exc
