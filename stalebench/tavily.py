"""Tavily client with an on-disk cache.

Tavily is StaleBench's window onto the live web. It is used twice:

1. as the *tool* every research agent under test calls (through the harness
   proxy, which can break it or poison it on purpose), and
2. by the Stale-Answer Detector, which re-checks each time-sensitive claim
   against fresh sources before the run is graded.

Identical queries are cached for a few hours so repeated benchmark runs do
not spend credits twice on the same search, and so the grader sees the same
evidence for every repeat of a task.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx

TAVILY_URL = os.getenv("TAVILY_UPSTREAM", "https://api.tavily.com")
CACHE_DIR = Path(os.getenv("STALEBENCH_DATA", "./data")) / "tavily-cache"
CACHE_TTL = int(os.getenv("TAVILY_CACHE_TTL", str(6 * 3600)))
_lock = threading.Lock()
stats = {"calls": 0, "cache_hits": 0, "errors": 0}


class TavilyUnavailable(RuntimeError):
    pass


def api_key() -> str | None:
    return os.getenv("TAVILY_API_KEY") or None


def _cache_path(endpoint: str, body: dict) -> Path:
    h = hashlib.sha256((endpoint + json.dumps(body, sort_keys=True)).encode()).hexdigest()[:32]
    return CACHE_DIR / f"{endpoint}-{h}.json"


def call(endpoint: str, body: dict, *, use_cache: bool = True, timeout: float = 60) -> dict:
    """POST to a Tavily endpoint (search | extract) with caching."""
    body = {k: v for k, v in body.items() if k not in ("api_key",)}
    path = _cache_path(endpoint, body)
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        stats["cache_hits"] += 1
        return json.loads(path.read_text())
    key = api_key()
    if not key:
        raise TavilyUnavailable("TAVILY_API_KEY is not configured")
    stats["calls"] += 1
    r = httpx.post(f"{TAVILY_URL}/{endpoint}", json=body,
                   headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    if r.status_code >= 400:
        stats["errors"] += 1
        raise TavilyUnavailable(f"Tavily {endpoint} HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    with _lock:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return data


def search(query: str, **kw) -> dict:
    body = {"query": query, "max_results": kw.pop("max_results", 5), "search_depth": kw.pop("search_depth", "basic"),
            "include_answer": kw.pop("include_answer", False)}
    body.update(kw)
    return call("search", body)


def extract(urls: list[str], **kw) -> dict:
    return call("extract", {"urls": urls[:5], **kw})
