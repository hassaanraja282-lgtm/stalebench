"""Stale-Answer Detector (Tavily problem statement).

Given an LLM-generated answer, the detector:

1. uses Bifrost (an LLM call) to pull out the discrete factual claims and
   flag which ones are *time-sensitive* (pricing, versions, leadership,
   laws, counts, dates);
2. for each time-sensitive claim, runs a live Tavily search and, with a
   second Bifrost call, decides whether current sources SUPPORT, CONTRADICT,
   or leave the claim UNVERIFIED;
3. assigns a freshness score in [0,1] to each claim and to the answer.

Both technologies are load-bearing: Tavily supplies the current evidence and
Bifrost does every piece of reasoning (through the gateway's budget + fallback
chain). When no Tavily key is configured, an offline fixture provider is used
so the pipeline still runs; results are marked `evidence_source="fixture"`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from . import gateway, tavily
from .fixtures import fixture_search

VERDICTS = ("supported", "contradicted", "unverified")
_FRESHNESS = {"supported": 1.0, "unverified": 0.5, "contradicted": 0.0}


@dataclass
class Claim:
    text: str
    time_sensitive: bool
    category: str = "other"
    verdict: str = "unverified"
    freshness: float = 0.5
    rationale: str = ""
    evidence_source: str = "none"
    sources: list[str] = field(default_factory=list)


def _extract_json(text: str):
    text = text.strip()
    m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if m:
        text = m.group(0)
    return json.loads(text)


def extract_claims(answer: str) -> list[Claim]:
    prompt = [
        {"role": "system", "content": (
            "You extract atomic factual claims from an answer and judge which are time-sensitive. "
            "Time-sensitive = pricing, product/API versions, leadership or staffing, laws/regulations, "
            "release dates, 'current/latest' facts, counts that change. "
            "Return ONLY JSON: {\"claims\":[{\"text\":str,\"time_sensitive\":bool,"
            "\"category\":\"pricing|version|leadership|law|date|count|other\"}]}")},
        {"role": "user", "content": answer},
    ]
    resp = gateway.chat(prompt, json_mode=True, max_tokens=900, tags={"stage": "extract"})
    content = resp["choices"][0]["message"]["content"]
    data = _extract_json(content)
    out: list[Claim] = []
    for c in data.get("claims", []):
        if c.get("text"):
            out.append(Claim(text=c["text"].strip(), time_sensitive=bool(c.get("time_sensitive")),
                             category=c.get("category", "other")))
    return out


def _verify(claim: Claim) -> Claim:
    try:
        res = tavily.search(claim.text, max_results=5, include_answer=True)
        claim.evidence_source = "tavily"
    except tavily.TavilyUnavailable:
        res = fixture_search(claim.text)
        claim.evidence_source = "fixture"
    results = res.get("results", [])[:5]
    claim.sources = [r.get("url", "") for r in results if r.get("url")]
    evidence = "\n".join(f"- {r.get('title','')}: {r.get('content','')[:400]} ({r.get('url','')})"
                         for r in results) or "(no results)"
    if res.get("answer"):
        evidence = f"Summary: {res['answer']}\n" + evidence
    prompt = [
        {"role": "system", "content": (
            "Decide whether CURRENT web evidence supports a claim. "
            "Return ONLY JSON {\"verdict\":\"supported|contradicted|unverified\",\"rationale\":str}. "
            "Use 'contradicted' only when evidence clearly states something different; "
            "'unverified' when evidence is absent or ambiguous.")},
        {"role": "user", "content": f"CLAIM: {claim.text}\n\nEVIDENCE:\n{evidence}"},
    ]
    resp = gateway.chat(prompt, json_mode=True, max_tokens=400, tags={"stage": "verify"})
    data = _extract_json(resp["choices"][0]["message"]["content"])
    verdict = data.get("verdict", "unverified")
    claim.verdict = verdict if verdict in VERDICTS else "unverified"
    claim.rationale = (data.get("rationale") or "")[:500]
    claim.freshness = _FRESHNESS[claim.verdict]
    return claim


def analyze(answer: str) -> dict:
    """Full detector pass over one answer. Returns a JSON-able report."""
    claims = extract_claims(answer)
    checked = [_verify(c) for c in claims if c.time_sensitive]
    # non-time-sensitive claims are reported but not scored for freshness
    other = [c for c in claims if not c.time_sensitive]
    scored = checked
    answer_freshness = (sum(c.freshness for c in scored) / len(scored)) if scored else 1.0
    return {
        "answer_freshness": round(answer_freshness, 3),
        "n_claims": len(claims),
        "n_time_sensitive": len(checked),
        "n_supported": sum(c.verdict == "supported" for c in scored),
        "n_contradicted": sum(c.verdict == "contradicted" for c in scored),
        "n_unverified": sum(c.verdict == "unverified" for c in scored),
        "claims": [asdict(c) for c in (checked + other)],
    }
