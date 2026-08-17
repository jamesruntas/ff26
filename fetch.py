"""Thin HTTP layer: one place for headers, retries, and on-disk caching.

Caching matters more than it looks. MFL explicitly asks you to cache and not
to retry aggressively, and while you are debugging pandas you should not be
re-hitting anyone's server. Cached responses are keyed by URL and dated, so a
same-day re-run is free and you keep a history you can diff.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from pathlib import Path

import requests

from config import CACHE, USER_AGENT


class FetchError(RuntimeError):
    pass


def _cache_path(url: str, headers: dict | None, tag: str) -> Path:
    key = hashlib.sha1((url + json.dumps(headers or {}, sort_keys=True)).encode()).hexdigest()[:12]
    return CACHE / f"{date.today().isoformat()}_{tag}_{key}.json"


def get_json(
    url: str,
    *,
    tag: str,
    headers: dict | None = None,
    use_cache: bool = True,
    timeout: int = 30,
    attempts: int = 3,
) -> dict | list:
    """GET a JSON document, caching the parsed body for the rest of the day."""
    path = _cache_path(url, headers, tag)
    if use_cache and path.exists():
        return json.loads(path.read_text())

    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})

    last = None
    for i in range(attempts):
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** i)
            continue

        # 429 means back off, not retry harder. MFL is explicit about this.
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 30))
            raise FetchError(
                f"{tag}: rate limited (429). Wait ~{wait}s and re-run; "
                "do not tighten the retry loop."
            )
        if resp.status_code >= 500:
            last = FetchError(f"{tag}: HTTP {resp.status_code}")
            time.sleep(2 ** i)
            continue
        if not resp.ok:
            raise FetchError(f"{tag}: HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise FetchError(f"{tag}: response was not JSON ({exc})") from exc

        path.write_text(json.dumps(body))
        return body

    raise FetchError(f"{tag}: all {attempts} attempts failed ({last})")
