"""StaleBench web app: harness proxy + benchmark API + dashboard."""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import detector, gateway, runner, tavily
from .faults import SCENARIOS
from .proxy import router
from .recorder import load_all
from .tasks import TASKS

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="StaleBench", version="1.0.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=WEB), name="static")
_bifrost = None
_detect_hits: deque = deque(maxlen=200)


@app.on_event("startup")
def _start_gateway():
    global _bifrost
    if os.getenv("BIFROST_EXTERNAL") != "1":
        _bifrost = gateway.start()


@app.on_event("shutdown")
def _stop_gateway():
    if _bifrost:
        _bifrost.terminate()


def _admin(token: str | None):
    want = os.getenv("ADMIN_TOKEN")
    if want and token != want:
        raise HTTPException(403, "Starting benchmarks needs the admin token on this public demo. "
                                 "Run StaleBench locally to benchmark your own agents.")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    primary, fallbacks = gateway.models()
    return {"ok": True, "primary_model": primary, "fallbacks": fallbacks,
            "tavily": "live" if tavily.api_key() else "offline-fixtures", "tavily_stats": tavily.stats,
            "bifrost": gateway.BIFROST_URL, "bifrost_version": gateway.BIFROST_VERSION}


@app.get("/api/meta")
def meta():
    return {"agents": runner.AGENTS, "tasks": TASKS, "scenarios": SCENARIOS}


class BenchReq(BaseModel):
    agents: list[str] | None = None
    tasks: list[str] | None = None
    scenarios: list[str] | None = None
    repeats: int = 3
    concurrency: int = 2
    detector: bool = True


@app.post("/api/bench")
def bench(req: BenchReq, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    agents = req.agents or [a["id"] for a in runner.AGENTS]
    tasks = req.tasks or [t["id"] for t in TASKS]
    scenarios = req.scenarios or list(SCENARIOS)
    bad = [a for a in agents if a not in runner.AGENT_BY_ID] + [s for s in scenarios if s not in SCENARIOS]
    if bad:
        raise HTTPException(400, f"unknown: {bad}")
    job = runner.start_job(agents, tasks, scenarios, max(1, min(req.repeats, 10)),
                           max(1, min(req.concurrency, 4)), req.detector)
    return runner.JOBS[job]


@app.get("/api/jobs")
def jobs():
    return list(runner.JOBS.values())


@app.get("/api/leaderboard")
def board(job: str | None = None):
    return runner.leaderboard(job)


@app.get("/api/runs")
def runs(agent: str | None = None, scenario: str | None = None, task: str | None = None, limit: int = 300):
    rows = [r for r in load_all() if (not agent or r["agent"] == agent) and (not scenario or r["scenario"] == scenario)
            and (not task or r["task"] == task)]
    slim = [{k: r.get(k) for k in ("run_id", "job", "agent", "task", "scenario", "repeat", "status", "success",
                                   "correct", "stale_trap", "freshness", "steps", "tool_calls", "tokens", "cost_usd",
                                   "wall_s", "fallbacks_used", "faults_injected")} for r in rows[-limit:]]
    return list(reversed(slim))


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    for r in load_all():
        if r["run_id"] == run_id:
            return r
    raise HTTPException(404, "run not found")


class DetectReq(BaseModel):
    answer: str


@app.post("/api/detect")
def detect(req: DetectReq):
    now = time.time()
    recent = [t for t in _detect_hits if now - t < 3600]
    if len(recent) >= int(os.getenv("DETECT_PER_HOUR", "40")):
        raise HTTPException(429, "The public demo's hourly detector budget is used up. Try again later.")
    if not req.answer.strip() or len(req.answer) > 4000:
        raise HTTPException(400, "Paste an answer between 1 and 4000 characters.")
    _detect_hits.append(now)
    try:
        return detector.analyze(req.answer)
    except Exception as e:
        return JSONResponse({"error": f"detector failed: {e}"}, status_code=502)
