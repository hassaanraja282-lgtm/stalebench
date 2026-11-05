"""Fault scenarios injected by the harness proxy.

Agents are never modified. Every scenario is applied *between* the agent and
the outside world, at the two choke points the harness owns:

* the LLM endpoint (harness proxy -> Bifrost), and
* the search tool endpoint (harness proxy -> Tavily).
"""
from __future__ import annotations

SCENARIOS = {
    "baseline": {
        "label": "Baseline",
        "desc": "No faults. Same model, same tools, same tasks for every agent.",
    },
    "model_down_raw": {
        "label": "Model outage (no gateway failover)",
        "desc": "The first 2 LLM calls of the run fail with HTTP 503. Does the agent retry, degrade, or crash?",
        "llm_fail_first": 2,
    },
    "model_down_gateway": {
        "label": "Model outage (Bifrost failover)",
        "desc": "The primary provider is down for the whole run. Bifrost's fallback chain reroutes to the backup model; the trace records which model really served each step.",
        "llm_dead_primary": True,
    },
    "tool_broken": {
        "label": "Broken search tool",
        "desc": "The first 2 Tavily calls return HTTP 500 with a non-JSON body.",
        "tool_fail_first": 2,
    },
    "misleading": {
        "label": "Misleading input",
        "desc": "An outdated but authoritative-looking page is injected as the top search result, and the question carries a stale 'hint'.",
        "poison": True,
    },
}


def apply_question(question: str, task: dict, scenario: str) -> str:
    if SCENARIOS[scenario].get("poison") and task.get("poison"):
        return f"{question}\n\n(Hint from a teammate: {task['poison']['content']})"
    return question
