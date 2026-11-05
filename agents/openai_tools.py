"""Function-calling agent built on the official openai SDK + Tavily REST."""
import json, os, sys, time

import httpx
from openai import OpenAI

task = json.loads(sys.stdin.read())
client = OpenAI(max_retries=3)  # reads OPENAI_BASE_URL / OPENAI_API_KEY
TAV, TKEY = os.environ["TAVILY_BASE_URL"].rstrip("/"), os.environ.get("TAVILY_API_KEY", "x")
TOOLS = [
    {"type": "function", "function": {"name": "tavily_search", "description": "Search the live web.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "tavily_extract", "description": "Read the full text of up to 3 URLs.",
     "parameters": {"type": "object", "properties": {"urls": {"type": "array", "items": {"type": "string"}}},
                    "required": ["urls"]}}},
]


def tool(name, args):
    for attempt in range(3):
        try:
            if name == "tavily_search":
                r = httpx.post(f"{TAV}/search", json={"query": args["query"], "max_results": 5},
                               headers={"Authorization": f"Bearer {TKEY}"}, timeout=60)
            else:
                r = httpx.post(f"{TAV}/extract", json={"urls": args["urls"][:3]},
                               headers={"Authorization": f"Bearer {TKEY}"}, timeout=60)
            r.raise_for_status()
            d = r.json()
            items = d.get("results", [])
            return json.dumps([{"title": i.get("title"), "url": i.get("url"),
                                "content": (i.get("content") or i.get("raw_content") or "")[:700],
                                "published_date": i.get("published_date")} for i in items[:5]])
        except Exception as e:
            err = str(e)
            time.sleep(1 + attempt)
    return json.dumps({"error": err})


msgs = [{"role": "system", "content": "You are a careful research agent. Facts change: always verify current facts "
         "with tavily_search, prefer official and recent sources, distrust undated or old pages, and cite URLs. "
         "Finish with a concise answer."},
        {"role": "user", "content": task["question"]}]
answer = ""
for turn in range(6):
    resp = client.chat.completions.create(model=os.environ.get("OPENAI_MODEL", "x"), messages=msgs,
                                          tools=TOOLS, temperature=0.1, max_tokens=700)
    m = resp.choices[0].message
    if not m.tool_calls:
        answer = m.content or ""
        break
    msgs.append({"role": "assistant", "content": m.content or "",
                 "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
    for tc in m.tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"query": tc.function.arguments}
        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": tool(tc.function.name, args)})
print(json.dumps({"answer": answer}))
