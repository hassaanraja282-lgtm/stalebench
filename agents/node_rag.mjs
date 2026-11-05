// Search-then-answer agent in Node.js (no framework, global fetch).
import { readFileSync } from "node:fs";

const task = JSON.parse(readFileSync(0, "utf8"));
const BASE = process.env.OPENAI_BASE_URL.replace(/\/$/, "");
const TAV = process.env.TAVILY_BASE_URL.replace(/\/$/, "");
const auth = (k) => ({ "Content-Type": "application/json", Authorization: `Bearer ${k}` });

async function search(query) {
  try {
    const r = await fetch(`${TAV}/search`, { method: "POST", headers: auth(process.env.TAVILY_API_KEY),
      body: JSON.stringify({ query, max_results: 5, include_answer: true }) });
    if (!r.ok) return { results: [], error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) { return { results: [], error: String(e) }; }
}

async function llm(messages) {
  for (let i = 0; i < 2; i++) {
    const r = await fetch(`${BASE}/chat/completions`, { method: "POST", headers: auth(process.env.OPENAI_API_KEY),
      body: JSON.stringify({ model: process.env.OPENAI_MODEL || "x", messages, temperature: 0.1, max_tokens: 500 }) });
    if (r.ok) return (await r.json()).choices[0].message.content;
    if (r.status < 500 || i === 1) throw new Error(`LLM HTTP ${r.status}`);
    await new Promise((res) => setTimeout(res, 1500));
  }
}

const res = await search(task.question);
const ctx = (res.results || []).map((x, i) => `[${i + 1}] ${x.title} (${x.url}) ${x.published_date || ""}\n${(x.content || "").slice(0, 500)}`).join("\n\n");
const answer = await llm([
  { role: "system", content: "Answer using only the sources. Prefer the most recent authoritative source. Cite [n] with URLs. If sources are missing say so." },
  { role: "user", content: `Question: ${task.question}\n\nSources:\n${ctx || "(search unavailable)"}` },
]);
console.log(JSON.stringify({ answer }));
