"""Harness proxy: the only door between an agent and the world.

Each run gets its own base URLs:

    OPENAI_BASE_URL = http://<harness>/proxy/<run_id>/v1
    TAVILY_BASE_URL = http://<harness>/proxy/<run_id>/tavily

so any agent that reads those two standard environment variables can be
benchmarked unchanged, whatever framework or language it is written in. The
proxy records every step, injects the run's fault scenario, pins the model so
every agent is compared on the same LLM, and forwards LLM traffic to Bifrost
under the harness's budgeted virtual key.
"""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import gateway, tavily
from .faults import SCENARIOS
from .fixtures import fixture_search
from .recorder import ACTIVE, cost_of
from .tasks import BY_ID

router = APIRouter()
_client = httpx.AsyncClient(timeout=180, trust_env=False)  # local hop to Bifrost: never via a proxy


def _run(run_id: str):
    run = ACTIVE.get(run_id)
    if not run:
        return None, JSONResponse({"error": {"message": "unknown or finished run"}}, status_code=404)
    return run, None


@router.post("/proxy/{run_id}/v1/chat/completions")
async def chat(run_id: str, request: Request):
    run, err = _run(run_id)
    if err:
        return err
    body = await request.json()
    sc = SCENARIOS[run.scenario]
    run.llm_seen += 1
    n_msgs = len(body.get("messages", []))
    tools = [t.get("function", {}).get("name") for t in body.get("tools", []) or []]

    if run.llm_seen <= sc.get("llm_fail_first", 0):
        run.faults_injected += 1
        run.event("llm", status=503, injected="model unavailable (503)", messages=n_msgs)
        return JSONResponse({"error": {"message": "The model is overloaded. Please try again later.",
                                       "type": "service_unavailable", "code": 503}}, status_code=503)

    primary, fallbacks = gateway.models()
    requested = body.get("model")
    body["model"] = primary  # every agent is compared on the same model
    body["fallbacks"] = fallbacks
    if sc.get("llm_dead_primary"):
        body["model"] = "outage/primary"
        body["fallbacks"] = [primary] + fallbacks
        run.faults_injected += 1
    body.pop("stream", None)
    body.pop("stream_options", None)

    t0 = time.time()
    try:
        r = await _client.post(f"{gateway.BIFROST_URL}/v1/chat/completions", json=body,
                               headers={"x-bf-vk": gateway.VIRTUAL_KEY,
                                        "x-bf-lh-run": run_id, "x-bf-lh-agent": run.agent,
                                        "x-bf-lh-scenario": run.scenario})
    except httpx.HTTPError as e:
        run.event("llm", status=599, error=str(e)[:200], messages=n_msgs)
        return JSONResponse({"error": {"message": f"gateway error: {e}"}}, status_code=502)
    dt = round(time.time() - t0, 3)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
    if r.status_code >= 400:
        run.event("llm", status=r.status_code, latency=dt, error=str(data)[:300], messages=n_msgs)
        return JSONResponse(data, status_code=r.status_code)

    usage = data.get("usage") or {}
    pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    ri = (data.get("extra_fields") or {}).get("routing_info") or {}
    served = f"{ri.get('provider', '?')}/{ri.get('model', '?')}"
    is_fb = bool(ri.get("is_fallback")) or (body["model"] != served and ri.get("provider") is not None)
    run.llm_calls += 1
    run.prompt_tokens += pt
    run.completion_tokens += ct
    c = cost_of(served, pt, ct)
    run.cost_usd += c
    if is_fb:
        run.fallbacks_used += 1
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    calls = [tc.get("function", {}).get("name") for tc in msg.get("tool_calls") or []]
    run.event("llm", status=200, latency=dt, requested=requested, served_by=served, fallback=is_fb,
              prompt_tokens=pt, completion_tokens=ct, cost=round(c, 6), messages=n_msgs, tools_offered=tools,
              tool_calls=calls, output=(msg.get("content") or "")[:600])
    return JSONResponse(data)


async def _tool(run_id: str, endpoint: str, request: Request):
    run, err = _run(run_id)
    if err:
        return err
    body = await request.json()
    sc = SCENARIOS[run.scenario]
    run.tool_seen += 1
    query = body.get("query") or ",".join(body.get("urls", [])[:3])
    if run.tool_seen <= sc.get("tool_fail_first", 0):
        run.faults_injected += 1
        run.event("tool", name=f"tavily.{endpoint}", query=query, status=500, injected="tool error (500)")
        return PlainTextResponse("<html><body>502 Bad Gateway (upstream reset)</body></html>", status_code=500)

    t0 = time.time()
    source = "tavily"
    try:
        data = tavily.call(endpoint, {k: v for k, v in body.items() if k != "api_key"})
    except tavily.TavilyUnavailable as e:
        if endpoint == "search":
            data, source = fixture_search(query, body.get("max_results", 3)), "fixture"
        else:
            run.event("tool", name=f"tavily.{endpoint}", query=query, status=503, error=str(e)[:200])
            return JSONResponse({"detail": str(e)}, status_code=503)
    data = dict(data)
    if endpoint == "search" and sc.get("poison"):
        task = BY_ID.get(run.task, {})
        if task.get("poison"):
            data["results"] = [dict(task["poison"], score=0.99, published_date="2023-06-01")] + list(data.get("results", []))
            data["answer"] = None
            run.faults_injected += 1
    run.tool_calls += 1
    results = data.get("results", [])
    run.event("tool", name=f"tavily.{endpoint}", query=query, status=200, latency=round(time.time() - t0, 3),
              source=source, poisoned=bool(sc.get("poison")),
              results=[{"title": x.get("title", ""), "url": x.get("url", "")} for x in results[:5]])
    return JSONResponse(data)


@router.post("/proxy/{run_id}/tavily/search")
async def tool_search(run_id: str, request: Request):
    return await _tool(run_id, "search", request)


@router.post("/proxy/{run_id}/tavily/extract")
async def tool_extract(run_id: str, request: Request):
    return await _tool(run_id, "extract", request)
