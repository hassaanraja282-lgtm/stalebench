# StaleBench

**Benchmark research agents, not just models, on the one thing users notice first: is the answer still true today?**

StaleBench runs any research agent (any language, any framework, unmodified) against identical time-sensitive questions, through the same self-hosted **Bifrost** gateway and the same **Tavily** search tool, repeated under injected faults. Every answer is graded for the *current* fact and then audited claim-by-claim by a built-in **Stale-Answer Detector** that re-checks each time-sensitive claim against the live web.

Built solo for the **Geek Room Global AI Hackathon 2026**.

| | |
|---|---|
| Primary problem statement | **Build a Benchmarking Platform for AI Agents, Not Just Models** (Bifrost track) |
| Integrated Tavily problem statement | **Build a Stale-Answer Detector for AI Applications** |
| Gateway | [Bifrost](https://github.com/maximhq/bifrost) `transports/v2.4.0`, self-hosted, binary (no Docker needed locally) |
| Live demo | https://stalebench.onrender.com (Render free tier; first load can take ~1 min to wake) |
| Search | [Tavily](https://tavily.com) Search + Extract |
| Model | Gemini (primary + backup) via Bifrost's `gemini` provider |

---

## The problem

LLM leaderboards rank *models*. Teams ship *agents*: a model plus a prompt, a loop, tools, retries and a framework. Two agents on the same model can behave completely differently when a provider is down, a tool returns garbage, or a search result is confidently out of date. And the most common failure users actually see is not a crash, it is a **stale answer**: last year's version number, a replaced CEO, an old interest rate, stated with total confidence.

There is no easy way to put two agents written in different frameworks side by side, on identical tasks, under identical faults, and see *why* one is more reliable.

## The solution

```
  agent (any language / framework, unmodified)
     │  OPENAI_BASE_URL = /proxy/<run>/v1        TAVILY_BASE_URL = /proxy/<run>/tavily
     ▼                                              ▼
  ┌──────────────── harness proxy (records every step, injects faults) ───────────────┐
  │  LLM: pin model · 503s · dead primary            Tool: 500s · poisoned top result    │
  └──────────────┬───────────────────────────────────────────────┬─────────────────────┘
                 ▼                                               ▼
        Bifrost gateway (self-hosted)                      Tavily Search / Extract
        virtual key + daily budget · fallbacks             live web evidence, cached per query
        Gemini primary → backup model · routing info
                 │                                               │
                 └──────────► Stale-Answer Detector ◄────────────┘
                              claims → live re-check → verdict + freshness
                                         ▼
                      grade · Wilson-CI ranking · step traces · dashboard
```

1. **Framework-independent by construction.** The harness gives each run two base URLs. Any agent that honours the standard `OPENAI_BASE_URL` / `OPENAI_API_KEY` and a `TAVILY_BASE_URL` works unchanged: the bundled agents are a stdlib Python ReAct loop, an `openai`-SDK function caller, a closed-book control, and a **Node.js** search-then-answer agent. Agents receive the task as JSON on stdin and print `{"answer": ...}`.
2. **Every step is recorded at the choke points the harness owns.** LLM calls (tokens, latency, cost, which model *really* served the call, tool calls requested) and tool calls (query, results, source) become an inspectable trace per run.
3. **Faults are injected without touching the agent.**
   | Scenario | What happens |
   |---|---|
   | `baseline` | No faults. |
   | `model_down_raw` | First 2 LLM calls return HTTP 503. Does the agent retry, degrade or crash? |
   | `model_down_gateway` | The primary provider is dead for the whole run; Bifrost's fallback chain must reroute. |
   | `tool_broken` | First 2 Tavily calls return HTTP 500 with an HTML body. |
   | `misleading` | An outdated, authoritative-looking page is injected as the top search result and the question carries a stale "hint". |
4. **Grading checks truth *now*.** Each task (e.g. newest CPython release, current Node.js Active LTS, RBI repo rate, latest Bifrost release) has the current fact verified against live sources on 2026-11-05. A run succeeds only if the answer states the current fact **and** the Stale-Answer Detector finds no time-sensitive claim in it contradicted by live evidence.
5. **Rankings resist lucky runs.** Every (agent, task, scenario) cell is repeated N times. Agents are ranked by the **lower bound of the 95% Wilson interval** on success rate, with "pass all repeats" (pass^k) reported next to it, so one lucky run cannot beat a consistently good agent.
6. **Comparison UI.** Leaderboard, agent × fault matrix, run list with step-by-step traces, and the standalone Stale-Answer Detector.

## How Bifrost contributes

Bifrost is the only path to a model, for the agents *and* for the grader:

- **One OpenAI-compatible endpoint** (`/v1/chat/completions`) that every agent already speaks, so no agent is rewritten. The harness pins the model, so every agent is compared on the same LLM.
- **Fallback chain** (`fallbacks: [...]`): in `model_down_gateway` the harness routes requests to a deliberately dead provider (`outage/primary`, a Bifrost custom provider pointing at a closed port) and Bifrost reroutes to the real Gemini model. `extra_fields.routing_info` tells the trace which model actually served each step, so the benchmark can show *how much reliability the gateway adds* compared with `model_down_raw`.
- **Governance:** all traffic goes through a harness **virtual key with a daily USD budget**, so a looping agent cannot burn money. Agents never see a real provider key.
- **Per-request log metadata** (`x-bf-lh-run`, `x-bf-lh-agent`, `x-bf-lh-scenario`) tags every call in Bifrost's own logs with the benchmark run it belongs to.
- **Retries and provider network config** for the Gemini provider, and custom providers (`custom_provider_config`) for the outage simulator and keyless dev mode.
- Every reasoning step of the **Stale-Answer Detector** (claim extraction, verdicts) is a Bifrost call with the same fallbacks.

Config is generated at startup in `stalebench/gateway.py` and written to Bifrost's `config.json`.

## How Tavily contributes

- **The tool under test:** every research agent searches (and the SDK agent also extracts pages) through Tavily via the harness proxy, which is where tool faults and poisoned results are injected.
- **The evidence behind grading:** the Stale-Answer Detector re-checks every time-sensitive claim with a live Tavily search (`include_answer`, top 5 results) and shows the sources next to each verdict.
- **Fair repeats, fewer credits:** identical queries are cached for 6 hours, so every repeat of a task sees the same evidence and credits are spent once.

## Results: first live run (2026-11-05)

Real run on the public Render deploy: 4 agents × 3 tasks (`python-stable`, `node-lts`, `bifrost-version`) × 5 scenarios × 1 repeat = 60 runs, Gemini `gemini-3.6-flash` (fallback `gemini-3.5-flash-lite`) through Bifrost v2.4.0, live Tavily search, Stale-Answer Detector on. Kept deliberately small to stay inside free-tier rate and credit limits. Raw data: [`results/`](results/) (leaderboard, job, and every run's full trace).

| Rank | Agent | Success | 95% Wilson CI | Crashes | Stale traps | baseline | model_down_raw | model_down_gateway | tool_broken | misleading |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | OpenAI SDK tool-caller | 11/15 (73%) | 48–89% | 2 | 1 | 2/3 | 2/3 | 2/3 | 3/3 | 2/3 |
| 2 | Search-then-answer (Node.js) | 3/15 (20%) | 7–45% | 6 | 4 | 1/3 | 0/3 | 1/3 | 0/3 | 1/3 |
| 3 | Closed-book LLM | 0/15 (0%) | 0–20% | 5 | 5 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| 4 | ReAct (hand-rolled) | 0/15 (0%) | 0–20% | 12 | 0 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |

What it shows:
- **The agent loop matters more than the model.** Same model, same tool: the tool-caller with retries passed 11/15, while the hand-rolled ReAct loop and the one-shot Node agent crashed on any upstream error.
- **The closed-book control is always stale** (5 stale traps, 0 passes): the model alone believes older versions are current, which is exactly what the detector is for.
- **Real-world faults showed up on their own.** The run hit 17 genuine HTTP 429 quota responses from the Gemini free tier on top of the injected faults; agents without retry logic crashed on them, which is the reliability gap this benchmark is built to expose.
- With 1 repeat per cell the intervals are wide; rerun with `--repeats 3` or more on a paid key for tighter rankings.

## The Stale-Answer Detector

`POST /api/detect {"answer": "..."}` or the **Stale-Answer Detector** tab:

1. Bifrost call: extract atomic claims, flag which are time-sensitive (pricing, version, leadership, law, date, count).
2. For each time-sensitive claim: Tavily search for current evidence.
3. Bifrost call: verdict `supported` / `contradicted` / `unverified` with a rationale.
4. Freshness per claim (1.0 / 0.0 / 0.5) and for the whole answer.

The UI keeps **evidence** (source links and snippets from Tavily) visibly separate from **inference** (the model's rationale). When no Tavily key is configured, an offline corpus captured on 2026-11-05 is used and every result is labelled `evidence: fixture`.

## Run it

Requirements: Python 3.11+, Node.js 18+ (for the Node agent). No Docker needed.

```bash
git clone https://github.com/hassaanraja282-lgtm/stalebench && cd stalebench
pip install -r requirements.txt
npx -y @maximhq/bifrost --help      # downloads the Bifrost binary once (or set BIFROST_BIN)

export GEMINI_API_KEY=...           # Google AI Studio key
export TAVILY_API_KEY=tvly-...      # Tavily key
uvicorn stalebench.server:app --port 8000   # starts Bifrost on :8080 automatically
open http://localhost:8000
```

Headless run (CI-friendly):

```bash
python -m stalebench --repeats 3                       # all agents × tasks × scenarios
python -m stalebench --agents react-raw,node-rag --scenarios baseline,misleading --repeats 5
```

Benchmark your own agent: add an entry to `agents/registry.json` with the command that starts it. It must read `{"question": ...}` from stdin, use `OPENAI_BASE_URL`/`OPENAI_API_KEY` for the model and `TAVILY_BASE_URL`/`TAVILY_API_KEY` for search, and print `{"answer": ...}` as its last line.

Useful environment variables: `PRIMARY_MODEL` / `FALLBACK_MODEL` (Bifrost `provider/model` names), `BIFROST_BUDGET_USD` (virtual-key daily budget), `ADMIN_TOKEN` (required to start benchmarks on a public deploy), `AGENT_TIMEOUT`, `STALEBENCH_PRICING`.

### Deploy (Render free tier)

`render.yaml` builds the Dockerfile, which downloads the official Bifrost `linux/amd64` binary. Set `GEMINI_API_KEY` and `TAVILY_API_KEY` in the dashboard.

### Tests

```bash
pytest -q
```

The offline suite needs no keys and no Bifrost: it points the proxy at a scripted mock LLM (`tests/mock_llm.py`, test-only, never used for reported results) and Tavily at the fixture corpus, and checks fault injection, poisoning, grading, Wilson ranking and the detector.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/bench` | Start a job `{agents, tasks, scenarios, repeats}` |
| `GET` | `/api/leaderboard` | Ranked agents with per-scenario breakdown |
| `GET` | `/api/runs`, `/api/runs/{id}` | Run list and full trace |
| `POST` | `/api/detect` | Stale-Answer Detector |
| `POST` | `/proxy/{run}/v1/chat/completions` | Agent-facing LLM endpoint (→ Bifrost) |
| `POST` | `/proxy/{run}/tavily/search`, `/extract` | Agent-facing tool endpoint (→ Tavily) |

## Project layout

```
stalebench/gateway.py    Bifrost config, process supervision, client
stalebench/proxy.py      harness proxy: tracing + fault injection
stalebench/faults.py     fault scenarios
stalebench/detector.py   Stale-Answer Detector (Tavily + Bifrost)
stalebench/runner.py     job runner, grading, Wilson statistics
stalebench/tasks.py      time-sensitive task suite with poison docs
agents/                  four reference agents in two languages
web/                     dashboard
tests/                   offline test-suite
```

## Technologies

Python 3.12, FastAPI, httpx, the `openai` SDK, Node.js 22, Bifrost v2.4.0 (gateway, governance, fallbacks, custom providers), Tavily Search and Extract APIs, Google Gemini via Bifrost, vanilla HTML/CSS/JS, Render (Docker).

## AI tools used

This project was built with the help of Hark, an AI assistant, which wrote most of the code, tests, documentation and pitch deck under Raja Hassaan's direction. All benchmark numbers come from real runs of the code in this repository.

## License

MIT, see [LICENSE](LICENSE).
