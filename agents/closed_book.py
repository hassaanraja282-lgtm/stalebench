"""Closed-book control agent: one LLM call, no tools (stdlib only)."""
import json, os, sys, urllib.request

task = json.loads(sys.stdin.read())
base, key = os.environ["OPENAI_BASE_URL"].rstrip("/"), os.environ.get("OPENAI_API_KEY", "x")
body = {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2, "max_tokens": 400,
        "messages": [{"role": "system", "content": "Answer concisely and state facts as of today."},
                     {"role": "user", "content": task["question"]}]}
req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
with urllib.request.urlopen(req, timeout=150) as r:  # no retry on purpose: a naive agent
    out = json.load(r)
print(json.dumps({"answer": out["choices"][0]["message"]["content"]}))
