"""Per-run state: trace events, counters and fault bookkeeping."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(os.getenv("STALEBENCH_DATA", "./data"))
RUNS_FILE = DATA / "runs.jsonl"
_lock = threading.Lock()

# USD per 1M tokens (input, output). List prices used for the cost column;
# override with STALEBENCH_PRICING='{"gemini/gemini-3.6-flash":[0.3,2.5]}'.
PRICING = {
    "gemini/gemini-3.6-flash": (0.30, 2.50),
    "gemini/gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini/gemini-2.5-flash": (0.30, 2.50),
    "pollinations/openai": (0.0, 0.0),
    "pollinations/openai-fast": (0.0, 0.0),
}
PRICING.update({k: tuple(v) for k, v in json.loads(os.getenv("STALEBENCH_PRICING", "{}")).items()})


def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


@dataclass
class Run:
    run_id: str
    agent: str
    task: str
    scenario: str
    repeat: int
    job: str = ""
    started: float = field(default_factory=time.time)
    events: list = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    fallbacks_used: int = 0
    faults_injected: int = 0
    llm_seen: int = 0   # LLM requests received, including injected failures
    tool_seen: int = 0  # tool requests received, including injected failures

    def event(self, kind: str, **data) -> None:
        data.update(kind=kind, t=round(time.time() - self.started, 3))
        with _lock:
            self.events.append(data)


ACTIVE: dict[str, Run] = {}


def save(result: dict) -> None:
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a") as f:
            f.write(json.dumps(result) + "\n")


def load_all() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    out = []
    for line in RUNS_FILE.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out
