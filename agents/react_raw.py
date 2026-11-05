"""Hand-rolled ReAct agent (stdlib only). Parses Action lines from plain text."""
import json, os, re, sys, time, urllib.error, urllib.request

task = json.loads(sys.stdin.read())
BASE = os.environ["OPENAI_BASE_URL"].rstrip("/")
TAV = os.environ["TAVILY_BASE_URL"].rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "x")
TKEY = os.environ.get("TAVILY_API_KEY", "x")


def post(url, body, key, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


SYSTEM = ("You are a research agent. Today's facts may differ from your training data, so verify with search.\n"
          "Respond in this exact format, one step at a time:\n"
          "Thought: <reasoning>\nAction: search[<query>]\n"
          "...or when done:\nThought: <reasoning>\nFinal Answer: <concise answer with source URLs>")
msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task["question"]}]
answer = ""
for step in range(6):
    out = post(f"{BASE}/chat/completions", {"model": os.environ.get("OPENAI_MODEL", "x"), "messages": msgs,
                                             "temperature": 0.1, "max_tokens": 500, "stop": ["Observation:"]}, KEY)
    text = out["choices"][0]["message"]["content"] or ""
    msgs.append({"role": "assistant", "content": text})
    m = re.search(r"Final Answer:\s*(.*)", text, re.S)
    if m:
        answer = m.group(1).strip()
        break
    a = re.search(r"Action:\s*search\[(.*?)\]", text, re.S)
    if not a:
        msgs.append({"role": "user", "content": "Use the exact format: Action: search[...] or Final Answer: ..."})
        continue
    try:
        res = post(f"{TAV}/search", {"query": a.group(1).strip(), "max_results": 4}, TKEY, tries=1)
        obs = "\n".join(f"- {r.get('title')}: {r.get('content','')[:300]} ({r.get('url')})" for r in res.get("results", []))
    except Exception as e:  # observe the failure and keep going
        obs = f"search failed: {e}"
    msgs.append({"role": "user", "content": f"Observation:\n{obs or 'no results'}"})
if not answer:
    answer = msgs[-1]["content"] if msgs[-1]["role"] == "assistant" else "I could not find an answer."
print(json.dumps({"answer": answer}))
