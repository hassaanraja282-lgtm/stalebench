"""Benchmark task suite: time-sensitive research questions.

Each task has a question, the patterns a correct *current* answer must
contain, the stale values a model trained on old data tends to give, and a
"poison" document used by the misleading-input fault (a plausible but outdated
page injected into the agent's search results).

`must_include` / `stale` are checked deterministically; the Stale-Answer
Detector then audits every time-sensitive claim in the answer against live
sources, so an answer can also fail for an outdated side-claim.
"""
from __future__ import annotations

TASKS = [
    {
        "id": "bifrost-version",
        "question": "What is the latest released version of the Bifrost LLM gateway (transports/bifrost-http) by Maxim AI, and roughly when was it released?",
        "must_include": [r"v?2\.4(\.0)?\b"],
        "stale": [r"v?1\.\d+\.\d+", r"v?2\.[0-3]\.\d+"],
        "poison": {"title": "Bifrost 1.3 release notes", "url": "https://example-mirror.dev/bifrost-1-3",
                   "content": "Bifrost v1.3.0 is the latest stable release of the gateway (published 2025)."},
    },
    {
        "id": "python-stable",
        "question": "What is the newest stable feature release of CPython (major.minor), and in which month and year was it released?",
        "must_include": [r"3\.15"],
        "stale": [r"3\.1[0-3]\b"],
        "poison": {"title": "Python 3.12 is the newest release", "url": "https://old-blog.example.com/python-312",
                   "content": "Python 3.12 is the most recent stable version of Python, released October 2023."},
    },
    {
        "id": "node-lts",
        "question": "Which Node.js major version is the current Active LTS line right now?",
        "must_include": [r"\b26\b"],
        "stale": [r"\b(18|20|22|24)\b(?!\.)"],
        "poison": {"title": "Node.js 20 Active LTS", "url": "https://nodefacts.example.org/lts",
                   "content": "Node.js 20 'Iron' is the current Active LTS release line."},
    },
    {
        "id": "rbi-repo",
        "question": "What is the Reserve Bank of India's current policy repo rate?",
        "must_include": [r"5\.5(0)?\s*(%|per ?cent)"],
        "stale": [r"6\.5(0)?\s*%", r"5\.25\s*%", r"6\.25\s*%"],
        "poison": {"title": "RBI keeps repo rate at 6.5%", "url": "https://finance-archive.example.in/rbi",
                   "content": "The RBI has held the policy repo rate unchanged at 6.50%."},
    },
]

# Ground truth verified with live sources on 2026-11-05 (python.org 3.15.0 on
# 2026-10-09; Node 26 Active LTS since 2026-10-28; RBI repo hiked to 5.50% on
# 2026-10-07; Bifrost transports/v2.4.0 tagged 2026-10-30).
# Answers that are true at build time are confirmed against live Tavily search
# before each benchmark (see `stalebench verify-tasks`); a task whose answer
# drifted is flagged instead of silently grading agents against stale truth.

BY_ID = {t["id"]: t for t in TASKS}
