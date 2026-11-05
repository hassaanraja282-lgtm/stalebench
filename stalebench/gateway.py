"""Bifrost gateway: config generation, process supervision and a thin client.

StaleBench never talks to an LLM provider directly. Every model call made by
an agent under test, and every call made by the Stale-Answer Detector, goes
through a self-hosted Bifrost gateway. Bifrost gives us:

* one OpenAI-compatible endpoint for every agent (framework independence),
* provider fallbacks (primary model -> backup model) with routing info,
* a virtual key with a hard budget so a runaway agent cannot burn money,
* request logs (tokens, latency, cost) that back our traces.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

BIFROST_VERSION = os.getenv("BIFROST_VERSION", "v2.4.0")
BIFROST_PORT = int(os.getenv("BIFROST_PORT", "8080"))
BIFROST_URL = os.getenv("BIFROST_URL", f"http://127.0.0.1:{BIFROST_PORT}")
APP_DIR = Path(os.getenv("BIFROST_APP_DIR", "./.bifrost"))

# Virtual key the harness uses for every request. Agents never see it.
VIRTUAL_KEY = os.getenv("BIFROST_VK", "sk-bf-stalebench-harness")
BUDGET_USD = float(os.getenv("BIFROST_BUDGET_USD", "5"))


def models() -> tuple[str, list[str]]:
    """(primary, fallbacks) in Bifrost's provider/model form."""
    if os.getenv("GEMINI_API_KEY"):
        fb = [os.getenv("FALLBACK_MODEL", "gemini/gemini-3.5-flash-lite")]
        if pollinations_enabled():
            fb.append("pollinations/openai")
        return os.getenv("PRIMARY_MODEL", "gemini/gemini-3.6-flash"), fb
    if os.getenv("MOCK_LLM_URL"):  # offline tests: scripted OpenAI-compatible mock
        return "mock/primary", ["mock/backup"]
    # Keyless development mode: Pollinations' anonymous OpenAI-compatible
    # endpoint registered in Bifrost as a custom provider.
    return os.getenv("PRIMARY_MODEL", "pollinations/openai"), [os.getenv("FALLBACK_MODEL", "pollinations/openai-fast")]


def pollinations_enabled() -> bool:
    if os.getenv("MOCK_LLM_URL"):
        return False
    return os.getenv("ENABLE_POLLINATIONS", "0") == "1" or not os.getenv("GEMINI_API_KEY")


def build_config() -> dict:
    providers: dict = {}
    allowed: list[dict] = []
    if os.getenv("GEMINI_API_KEY"):
        providers["gemini"] = {
            "keys": [{"name": "gemini-key", "value": "env.GEMINI_API_KEY", "models": ["*"], "weight": 1.0}],
            "network_config": {"max_retries": 1, "retry_backoff_initial": 400, "retry_backoff_max": 2000,
                               "default_request_timeout_in_seconds": 90},
        }
        allowed.append({"provider": "gemini", "allowed_models": ["*"], "key_ids": ["*"], "weight": 1.0})
    if pollinations_enabled():
        providers["pollinations"] = {
            "keys": [{"name": "pollinations-anon", "value": "anonymous", "models": ["*"], "weight": 1.0}],
            "network_config": {"base_url": "https://text.pollinations.ai", "max_retries": 2,
                               "retry_backoff_initial": 1500, "retry_backoff_max": 6000,
                               "default_request_timeout_in_seconds": 120},
            "custom_provider_config": {
                "base_provider_type": "openai",
                "allowed_requests": {"chat_completion": True, "chat_completion_stream": True},
                "request_path_overrides": {"chat_completion": "/openai"},
            },
        }
        allowed.append({"provider": "pollinations", "allowed_models": ["*"], "key_ids": ["*"], "weight": 1.0})

    if os.getenv("MOCK_LLM_URL"):
        providers["mock"] = {
            "keys": [{"name": "mock-key", "value": "mock", "models": ["*"], "weight": 1.0}],
            "network_config": {"base_url": os.environ["MOCK_LLM_URL"], "default_request_timeout_in_seconds": 30},
            "custom_provider_config": {"base_provider_type": "openai",
                                       "allowed_requests": {"chat_completion": True, "chat_completion_stream": True}},
        }
        allowed.append({"provider": "mock", "allowed_models": ["*"], "key_ids": ["*"], "weight": 1.0})

    # A deliberately dead provider: the harness rewrites requests to
    # "outage/primary" to simulate a provider outage, and Bifrost's fallback
    # chain has to rescue the request.
    providers["outage"] = {
        "keys": [{"name": "outage-key", "value": "none", "models": ["*"], "weight": 1.0}],
        "network_config": {"base_url": "http://127.0.0.1:9", "default_request_timeout_in_seconds": 5},
        "custom_provider_config": {"base_provider_type": "openai",
                                   "allowed_requests": {"chat_completion": True, "chat_completion_stream": True}},
    }
    allowed.append({"provider": "outage", "allowed_models": ["*"], "key_ids": ["*"], "weight": 0.01})

    cfg = {
        "$schema": "https://www.getbifrost.ai/schema",
        "client": {"drop_excess_requests": False, "enable_logging": True,
                   "enforce_auth_on_inference": True},
        "providers": providers,
        "governance": {
            "virtual_keys": [{
                "id": "vk-stalebench",
                "name": "stalebench-harness",
                "value": VIRTUAL_KEY,
                "description": "Harness key: every benchmarked agent and the detector spend through this budget",
                "is_active": True,
                "provider_configs": allowed,
                "budgets": [{"max_limit": BUDGET_USD, "reset_duration": "1d"}],
            }]
        },
        "config_store": {"enabled": True, "type": "sqlite", "config": {"path": str((APP_DIR / "config.db").resolve())}},
        "logs_store": {"enabled": True, "type": "sqlite", "config": {"path": str((APP_DIR / "logs.db").resolve())}},
    }
    if os.getenv("BIFROST_SETUP_TOKEN"):
        cfg["setup_token"] = "env.BIFROST_SETUP_TOKEN"
    return cfg


def bifrost_binary() -> str:
    for cand in (os.getenv("BIFROST_BIN"), shutil.which("bifrost-http"), shutil.which("bifrost"),
                 str(Path.home() / f".cache/bifrost/{BIFROST_VERSION}/bin/bifrost-http-0")):
        if cand and Path(cand).exists():
            return cand
    raise FileNotFoundError("Bifrost binary not found: run `npx -y @maximhq/bifrost` once or set BIFROST_BIN")


def start(wait: float = 120.0) -> subprocess.Popen:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / "config.json").write_text(json.dumps(build_config(), indent=2))
    proc = subprocess.Popen(
        [bifrost_binary(), "-app-dir", str(APP_DIR), "-port", str(BIFROST_PORT), "-host", "127.0.0.1",
         "-log-level", os.getenv("BIFROST_LOG_LEVEL", "warn")],
        stdout=open(APP_DIR / "bifrost.out", "ab"), stderr=subprocess.STDOUT,
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Bifrost exited early; see {APP_DIR/'bifrost.out'}")
        try:
            h = httpx.get(f"{BIFROST_URL}/health", timeout=2, trust_env=False)
            if h.status_code == 200 and h.json().get("status") == "ok":
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Bifrost did not become healthy")


def chat(messages: list[dict], *, model: str | None = None, fallbacks: list[str] | None = None,
         temperature: float = 0.2, max_tokens: int = 1200, json_mode: bool = False,
         timeout: float = 120, tags: dict | None = None) -> dict:
    """Call Bifrost's OpenAI-compatible endpoint (used by the detector)."""
    primary, backups = models()
    body: dict = {"model": model or primary, "messages": messages, "temperature": temperature,
                  "max_tokens": max_tokens, "fallbacks": fallbacks if fallbacks is not None else backups}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"x-bf-vk": VIRTUAL_KEY}
    for k, v in (tags or {}).items():
        headers[f"x-bf-lh-{k}"] = str(v)
    r = httpx.post(f"{BIFROST_URL}/v1/chat/completions", json=body, headers=headers, timeout=timeout, trust_env=False)
    r.raise_for_status()
    return r.json()
