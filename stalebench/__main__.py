"""Headless CLI: python -m stalebench --repeats 3 [--agents a,b] [--tasks t] [--scenarios s]

Starts Bifrost and the harness in-process, runs the matrix, prints the
leaderboard and writes it to data/leaderboard.json.
"""
import argparse
import json
import os
import threading
import time

import uvicorn


def main():
    ap = argparse.ArgumentParser(prog="stalebench")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--agents")
    ap.add_argument("--tasks")
    ap.add_argument("--scenarios")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--no-detector", action="store_true")
    a = ap.parse_args()
    port = int(os.getenv("PORT", "8000"))
    os.environ.setdefault("HARNESS_URL", f"http://127.0.0.1:{port}")
    from . import runner
    from .faults import SCENARIOS
    from .server import app
    from .tasks import TASKS

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.3)
    split = lambda s, d: s.split(",") if s else d  # noqa: E731
    job = runner.start_job(split(a.agents, [x["id"] for x in runner.AGENTS]), split(a.tasks, [t["id"] for t in TASKS]),
                           split(a.scenarios, list(SCENARIOS)), a.repeats, a.concurrency, not a.no_detector)
    while runner.JOBS[job]["state"] != "finished":
        j = runner.JOBS[job]
        print(f"\r{j['done']}/{j['total']} runs", end="", flush=True)
        time.sleep(3)
    board = runner.leaderboard(job)
    out = os.path.join(os.getenv("STALEBENCH_DATA", "./data"), "leaderboard.json")
    with open(out, "w") as f:
        json.dump(board, f, indent=2)
    print("\n\nrank agent                 success  95%CI        steps  tools  tokens  time")
    for i, e in enumerate(board["agents"], 1):
        print(f"{i:>4} {e['name'][:22]:<22} {e['success_rate']:>6.0%}  {e['ci_low']:.2f}-{e['ci_high']:.2f}   "
              f"{e['median_steps']!s:>5}  {e['mean_tool_calls']!s:>5}  {e['median_tokens']!s:>6}  {e['median_wall_s']}s")
    server.should_exit = True


if __name__ == "__main__":
    main()
