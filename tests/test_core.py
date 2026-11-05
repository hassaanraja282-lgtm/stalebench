"""Offline tests: no API keys and no Bifrost binary needed.

The proxy is pointed straight at the scripted mock LLM (standing in for
Bifrost), Tavily falls back to the fixture corpus, and agents run as real
subprocesses through the harness.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


MOCK_PORT = _free_port()
os.environ.update({"BIFROST_EXTERNAL": "1", "BIFROST_URL": f"http://127.0.0.1:{MOCK_PORT}",
                   "MOCK_LLM_URL": f"http://127.0.0.1:{MOCK_PORT}", "STALEBENCH_DATA": str(ROOT / ".test-data")})
os.environ.pop("TAVILY_API_KEY", None)
sys.path.insert(0, str(ROOT))

from stalebench import runner  # noqa: E402
from stalebench.fixtures import fixture_search  # noqa: E402
from stalebench.recorder import ACTIVE, Run  # noqa: E402
from stalebench.tasks import BY_ID  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def mock_llm():
    p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_llm.py"), str(MOCK_PORT)])
    time.sleep(0.8)
    yield
    p.terminate()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from stalebench.server import app
    return TestClient(app)


def test_wilson_penalises_small_samples():
    lo1, _ = runner.wilson(1, 1)
    lo10, _ = runner.wilson(9, 10)
    assert lo1 < 0.25 < lo10  # one lucky run ranks below 9/10


def test_final_answer_parsing():
    assert runner._final_answer('noise\n{"answer": "Python 3.15"}\n') == "Python 3.15"
    assert runner._final_answer("plain text answer") == "plain text answer"


def test_grade_requires_current_fact():
    t = BY_ID["node-lts"]
    assert runner.grade(t, "Node.js 26 is Active LTS.", use_detector=False)["correct"]
    g = runner.grade(t, "Node.js 22 is the Active LTS.", use_detector=False)
    assert not g["correct"] and g["stale_trap"]


def test_fixture_search_finds_relevant_doc():
    res = fixture_search("RBI policy repo rate")
    assert "rbi.org.in" in res["results"][0]["url"]


def test_proxy_injects_503_then_recovers(client):
    ACTIVE["t1"] = Run("t1", "closed-book", "python-stable", "model_down_raw", 1)
    body = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}
    codes = [client.post("/proxy/t1/v1/chat/completions", json=body).status_code for _ in range(3)]
    assert codes == [503, 503, 200]
    assert ACTIVE["t1"].faults_injected == 2 and ACTIVE["t1"].llm_calls == 1


def test_proxy_breaks_and_poisons_tool(client):
    ACTIVE["t2"] = Run("t2", "react-raw", "node-lts", "tool_broken", 1)
    assert client.post("/proxy/t2/tavily/search", json={"query": "node lts"}).status_code == 500
    ACTIVE["t3"] = Run("t3", "react-raw", "node-lts", "misleading", 1)
    r = client.post("/proxy/t3/tavily/search", json={"query": "node lts"}).json()
    assert r["results"][0]["url"] == BY_ID["node-lts"]["poison"]["url"]


def test_unknown_run_is_rejected(client):
    assert client.post("/proxy/nope/v1/chat/completions", json={}).status_code == 404


def test_detector_flags_stale_claim():
    from stalebench import detector
    rep = detector.analyze("Node.js 22 is the current Active LTS line.")
    assert rep["n_contradicted"] == 1 and rep["answer_freshness"] == 0.0
