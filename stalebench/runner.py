"""Benchmark runner, grader and statistics."""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import detector
from .faults import SCENARIOS, apply_question
from .recorder import ACTIVE, Run, load_all, save
from .tasks import BY_ID

ROOT = Path(__file__).resolve().parent.parent
AGENTS = json.loads((ROOT / "agents" / "registry.json").read_text())
AGENT_BY_ID = {a["id"]: a for a in AGENTS}
HARNESS = os.getenv("HARNESS_URL", f"http://127.0.0.1:{os.getenv('PORT', '8000')}")
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "180"))
JOBS: dict[str, dict] = {}
_detect_cache: dict[str, dict] = {}
_detect_lock = threading.Lock()


def _final_answer(stdout: str) -> str:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return str(json.loads(line).get("answer", ""))
            except json.JSONDecodeError:
                continue
    return stdout.strip()[-2000:]


def grade(task: dict, answer: str, use_detector: bool = True) -> dict:
    """A run succeeds when the answer states the *current* fact and the
    Stale-Answer Detector finds no time-sensitive claim contradicted by live
    sources."""
    hit = all(re.search(p, answer, re.I) for p in task["must_include"]) if answer else False
    stale_trap = (not hit) and any(re.search(p, answer, re.I) for p in task.get("stale", []))
    report = None
    if use_detector and answer:
        key = answer.strip()
        with _detect_lock:
            report = _detect_cache.get(key)
        if report is None:
            try:
                report = detector.analyze(answer)
            except Exception as e:  # grader must never crash a benchmark
                report = {"error": str(e)[:300], "answer_freshness": None, "n_contradicted": 0, "claims": []}
            with _detect_lock:
                _detect_cache[key] = report
    contradicted = (report or {}).get("n_contradicted", 0)
    return {"correct": hit, "stale_trap": stale_trap, "success": bool(hit and contradicted == 0),
            "freshness": (report or {}).get("answer_freshness"), "detector": report}


def run_one(agent_id: str, task_id: str, scenario: str, repeat: int, job: str = "",
            use_detector: bool = True) -> dict:
    agent, task = AGENT_BY_ID[agent_id], BY_ID[task_id]
    rid = uuid.uuid4().hex[:12]
    run = Run(rid, agent_id, task_id, scenario, repeat, job=job)
    ACTIVE[rid] = run
    env = dict(os.environ)
    for k in ("TAVILY_API_KEY", "GEMINI_API_KEY", "BIFROST_VK"):
        env.pop(k, None)  # agents never see real credentials
    env.update({
        "OPENAI_BASE_URL": f"{HARNESS}/proxy/{rid}/v1", "OPENAI_API_KEY": f"run-{rid}",
        "OPENAI_MODEL": "bench-model",
        "TAVILY_BASE_URL": f"{HARNESS}/proxy/{rid}/tavily", "TAVILY_API_KEY": f"run-{rid}",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
    })
    question = apply_question(task["question"], task, scenario)
    t0 = time.time()
    status, stderr = "ok", ""
    try:
        p = subprocess.run(agent["cmd"], input=json.dumps({"question": question}), capture_output=True,
                           text=True, timeout=AGENT_TIMEOUT, env=env, cwd=str(ROOT))
        answer = _final_answer(p.stdout)
        stderr = p.stderr[-1500:]
        if p.returncode != 0:
            status = f"crashed (exit {p.returncode})"
    except subprocess.TimeoutExpired as e:
        answer, status = _final_answer(e.stdout or "") if isinstance(e.stdout, str) else "", "timeout"
    wall = round(time.time() - t0, 2)
    ACTIVE.pop(rid, None)
    g = grade(task, answer, use_detector) if status == "ok" else {
        "correct": False, "stale_trap": False, "success": False, "freshness": None, "detector": None}
    result = {
        "run_id": rid, "job": job, "agent": agent_id, "task": task_id, "scenario": scenario, "repeat": repeat,
        "status": status, "answer": answer, "question": question, "wall_s": wall,
        "steps": run.llm_calls, "tool_calls": run.tool_calls, "llm_requests": run.llm_seen,
        "prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens,
        "tokens": run.prompt_tokens + run.completion_tokens, "cost_usd": round(run.cost_usd, 6),
        "fallbacks_used": run.fallbacks_used, "faults_injected": run.faults_injected,
        "events": run.events, "stderr": stderr, "finished": time.time(), **g,
    }
    save(result)
    return result


def start_job(agents, tasks, scenarios, repeats: int, concurrency: int = 2, use_detector: bool = True) -> str:
    job = uuid.uuid4().hex[:8]
    combos = [(a, t, s, r) for r in range(1, repeats + 1) for s in scenarios for t in tasks for a in agents]
    JOBS[job] = {"id": job, "total": len(combos), "done": 0, "started": time.time(), "state": "running",
                 "agents": agents, "tasks": tasks, "scenarios": scenarios, "repeats": repeats}

    def work():
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            for _ in ex.map(lambda c: run_one(*c, job=job, use_detector=use_detector), combos):
                JOBS[job]["done"] += 1
        JOBS[job]["state"] = "finished"

    threading.Thread(target=work, daemon=True).start()
    return job


# ---------------------------------------------------------------- statistics
def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    s = sum(r["success"] for r in rows)
    lo, hi = wilson(s, n)

    def med(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(statistics.median(v), 4) if v else None

    def mean(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(statistics.fmean(v), 4) if v else None

    # pass^k: share of (task, scenario) cells where *every* repeat succeeded
    cells: dict = {}
    for r in rows:
        cells.setdefault((r["task"], r["scenario"]), []).append(r["success"])
    pass_all = sum(all(v) for v in cells.values()) / len(cells) if cells else 0
    return {"runs": n, "successes": s, "success_rate": round(s / n, 3) if n else 0, "ci_low": round(lo, 3),
            "ci_high": round(hi, 3), "pass_all_repeats": round(pass_all, 3),
            "crashes": sum(r["status"] != "ok" for r in rows), "stale_traps": sum(r.get("stale_trap", False) for r in rows),
            "median_steps": med("steps"), "mean_tool_calls": mean("tool_calls"), "median_tokens": med("tokens"),
            "mean_cost_usd": mean("cost_usd"), "median_wall_s": med("wall_s"), "mean_freshness": mean("freshness")}


def leaderboard(job: str | None = None) -> dict:
    rows = [r for r in load_all() if (job is None or r.get("job") == job)]
    agents = sorted({r["agent"] for r in rows})
    board = []
    for a in agents:
        ar = [r for r in rows if r["agent"] == a]
        entry = {"agent": a, "name": AGENT_BY_ID.get(a, {}).get("name", a),
                 "framework": AGENT_BY_ID.get(a, {}).get("framework", ""), **_agg(ar),
                 "by_scenario": {s: _agg([r for r in ar if r["scenario"] == s])
                                 for s in SCENARIOS if any(r["scenario"] == s for r in ar)}}
        board.append(entry)
    # rank by the lower bound of the 95% Wilson interval: one lucky run
    # cannot push an agent above a consistently good one
    board.sort(key=lambda e: (e["ci_low"], e["success_rate"], -(e["median_tokens"] or 0)), reverse=True)
    return {"agents": board, "total_runs": len(rows),
            "jobs": sorted({r.get("job", "") for r in rows})}
