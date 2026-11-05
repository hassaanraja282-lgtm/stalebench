"""Scripted OpenAI-compatible LLM used only by the offline test-suite.

It lets CI exercise the full path (agent -> harness proxy -> Bifrost ->
provider) with no API key. It is NOT used for any reported benchmark result.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply(body):
    msgs = body.get("messages", [])
    sys_p = next((m.get("content") or "" for m in msgs if m["role"] == "system"), "")
    last = msgs[-1]
    user = next((m.get("content") or "" for m in msgs if m["role"] == "user"), "")
    if "extract atomic factual claims" in sys_p:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", last["content"]) if s.strip()]
        return {"content": json.dumps({"claims": [{"text": s, "time_sensitive": bool(re.search(r"\d", s)),
                                                    "category": "version"} for s in sents[:4]]})}
    if "CURRENT web evidence" in sys_p:
        claim = re.search(r"CLAIM: (.*?)\n", last["content"]).group(1)
        ev = last["content"].split("EVIDENCE:", 1)[1]
        nums = re.findall(r"\d+(?:\.\d+)+|\d+", claim)
        ok = nums and all(n in ev for n in nums)
        return {"content": json.dumps({"verdict": "supported" if ok else "contradicted",
                                       "rationale": "numbers match evidence" if ok else "evidence states other values"})}
    if body.get("tools"):
        if not any(m["role"] == "tool" for m in msgs):
            return {"content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "tavily_search", "arguments": json.dumps({"query": user[:120]})}}]}
        obs = next(m["content"] for m in reversed(msgs) if m["role"] == "tool")
        return {"content": f"Based on current sources: {first_fact(obs)}"}
    if "Action: search[" in sys_p:
        if not any((m.get("content") or "").startswith("Observation:") for m in msgs):
            return {"content": f"Thought: verify.\nAction: search[{user[:100]}]"}
        obs = next(m["content"] for m in reversed(msgs) if (m.get("content") or "").startswith("Observation:"))
        return {"content": f"Thought: done.\nFinal Answer: {first_fact(obs)}"}
    if "Sources:" in user:
        return {"content": first_fact(user.split("Sources:", 1)[1])}
    return {"content": "As far as I know, Python 3.12 is the latest and Node.js 20 is the Active LTS."}


def first_fact(text):
    m = re.search(r"(?:content\"?:\s*\"|: |\n)([^\n\"]*\d[^\n\"]*)", text)
    return (m.group(1) if m else text[:200]).strip()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = {"role": "assistant", **reply(body)}
        out = {"id": "mock-1", "object": "chat.completion", "model": body.get("model"),
               "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
               "usage": {"prompt_tokens": sum(len(str(m.get("content", ""))) for m in body["messages"]) // 4,
                         "completion_tokens": len(str(msg.get("content"))) // 4 + 5, "total_tokens": 0}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8099), H).serve_forever()
