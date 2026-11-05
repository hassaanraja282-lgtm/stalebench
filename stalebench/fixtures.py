"""Offline evidence corpus (used only when TAVILY_API_KEY is not set).

These snippets were captured from live sources on 2026-11-05 so the whole
pipeline (agents, fault injection, detector, scoring) can run in CI and on a
laptop with no search key. Every result produced from this corpus is labelled
`evidence_source="fixture"` in traces and in the UI; leaderboard numbers in
the README come from live Tavily runs.
"""
from __future__ import annotations

import re

CORPUS = [
    {"title": "Release transports/v2.4.0 · maximhq/bifrost", "url": "https://github.com/maximhq/bifrost/releases",
     "content": "Bifrost transports/v2.4.0 (bifrost-http) was published on 2026-10-30. It is the latest gateway release; plugins telemetry v1.9.4 and semanticcache v1.7.4 shipped the same day.",
     "published_date": "2026-10-30"},
    {"title": "Python 3.15.0 (final) is here! | Python Insider", "url": "https://blog.python.org/2026/10/python-3150-final-is-here/",
     "content": "Python 3.15.0 is the newest major release of the Python programming language, released October 9, 2026. Python 3.15.1 followed on October 21, 2026.",
     "published_date": "2026-10-09"},
    {"title": "Release 2026-10-28, Version 26.13.0 'Lithium' (LTS) · nodejs/node", "url": "https://github.com/nodejs/node/releases/tag/v26.13.0",
     "content": "This release marks the transition of Node.js 26.x into Long Term Support (LTS) with the codename 'Lithium'. Node.js 24 moved to Maintenance LTS on October 20, 2026.",
     "published_date": "2026-10-28"},
    {"title": "RBI Monetary Policy Statement, October 5 to 7, 2026", "url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63742",
     "content": "The MPC voted unanimously to increase the policy repo rate under the LAF by 25 bps to 5.50 per cent. The SDF rate stands at 5.25 per cent and the MSF rate and Bank Rate at 5.75 per cent.",
     "published_date": "2026-10-07"},
    {"title": "Tavily docs: Search API", "url": "https://docs.tavily.com/documentation/api-reference/endpoint/search",
     "content": "Tavily Search returns ranked web results with content snippets, an optional LLM answer and published dates, built for AI agents.",
     "published_date": "2026-10-01"},
]

_WORD = re.compile(r"[a-z0-9.]+")


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2}


def fixture_search(query: str, max_results: int = 3) -> dict:
    q = _tokens(query)
    scored = sorted(CORPUS, key=lambda d: -len(q & _tokens(d["title"] + " " + d["content"])))
    hits = [dict(d, score=round(len(q & _tokens(d["title"] + " " + d["content"])) / (len(q) or 1), 3))
            for d in scored[:max_results] if q & _tokens(d["title"] + " " + d["content"])]
    return {"query": query, "results": hits, "answer": None, "evidence_source": "fixture"}
