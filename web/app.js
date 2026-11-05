const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
const api = async (p, o) => { const r = await fetch(p, o); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || j.error || r.status); return j; };
let META = null;

document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("nav button, .tab").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); $("#" + b.dataset.tab).classList.add("on");
  if (b.dataset.tab === "runs") loadRuns();
});
function toast(t) { const el = $("#toast"); el.textContent = t; el.style.display = "block"; setTimeout(() => el.style.display = "none", 4000); }
const cls = (x) => (x >= 0.75 ? "c-hi" : x >= 0.4 ? "c-mid" : "c-lo");

async function health() {
  try {
    const h = await api("/api/health");
    $("#health").innerHTML = `Bifrost <b>${esc(h.bifrost_version)}</b> · model <b>${esc(h.primary_model)}</b> → ${esc(h.fallbacks.join(", "))} · Tavily <b>${esc(h.tavily)}</b>`;
  } catch { $("#health").textContent = "gateway starting…"; }
}

async function loadBoard() {
  const b = await api("/api/leaderboard");
  if (!b.agents.length) { $("#boardTable").innerHTML = `<p class="muted">No runs yet. Start a benchmark below.</p>`; return b; }
  $("#boardTable").innerHTML = `<table><tr><th>Agent</th><th>Success</th><th>95% CI</th><th>Pass all repeats</th><th>Median steps</th><th>Tool calls</th><th>Median tokens</th><th>Cost / run</th><th>Median time</th><th>Freshness</th><th>Stale traps</th><th>Crashes</th><th>Runs</th></tr>` +
    b.agents.map((a, i) => `<tr><td><span class="rank ${i === 0 ? "r1" : ""}">${i + 1}</span><b>${esc(a.name)}</b><br><span class="fw">${esc(a.framework)}</span></td>
      <td class="cell ${cls(a.success_rate)}">${pct(a.success_rate)}<span class="bar"><i style="width:${a.success_rate * 100}%"></i><u style="left:${a.ci_low * 100}%;right:${100 - a.ci_high * 100}%"></u></span></td>
      <td>${pct(a.ci_low)}–${pct(a.ci_high)}</td><td>${pct(a.pass_all_repeats)}</td><td>${a.median_steps ?? "–"}</td><td>${a.mean_tool_calls ?? "–"}</td>
      <td>${a.median_tokens ?? "–"}</td><td>$${(a.mean_cost_usd ?? 0).toFixed(5)}</td><td>${a.median_wall_s ?? "–"}s</td><td>${pct(a.mean_freshness)}</td><td>${a.stale_traps}</td><td>${a.crashes}</td><td>${a.runs}</td></tr>`).join("") + `</table>`;
  renderMatrix(b);
  return b;
}

function renderMatrix(b) {
  const sc = Object.keys(META.scenarios);
  $("#matrixTable").innerHTML = `<table><tr><th>Agent</th>${sc.map((s) => `<th>${esc(META.scenarios[s].label)}</th>`).join("")}</tr>` +
    b.agents.map((a) => `<tr><td><b>${esc(a.name)}</b></td>${sc.map((s) => { const c = a.by_scenario[s]; return c ? `<td class="cell ${cls(c.success_rate)}">${pct(c.success_rate)} <span class="muted">(${c.successes}/${c.runs})</span></td>` : "<td>–</td>"; }).join("")}</tr>`).join("") + `</table>`;
}

function renderForm() {
  const ck = (name, items, lab) => items.map((x) => `<label class="chk"><input type="checkbox" name="${name}" value="${x.id}" checked>${esc(lab(x))}</label>`).join("");
  $("#benchForm").innerHTML = `
    <div class="formrow"><b>Agents</b><br>${ck("agents", META.agents, (a) => a.name)}</div>
    <div class="formrow"><b>Tasks</b><br>${ck("tasks", META.tasks, (t) => t.id)}</div>
    <div class="formrow"><b>Scenarios</b><br>${ck("scenarios", Object.entries(META.scenarios).map(([id, s]) => ({ id, ...s })), (s) => s.label)}</div>
    <div class="formrow">Repeats <input id="reps" type="number" value="3" min="1" max="10" style="width:64px"> · Admin token <input id="tok" type="password" placeholder="only on the public demo" style="width:200px">
    <button class="primary" id="go">Start benchmark</button></div>`;
  $("#go").onclick = async () => {
    const vals = (n) => [...document.querySelectorAll(`input[name=${n}]:checked`)].map((x) => x.value);
    try {
      const j = await api("/api/bench", { method: "POST", headers: { "Content-Type": "application/json", "x-admin-token": $("#tok").value },
        body: JSON.stringify({ agents: vals("agents"), tasks: vals("tasks"), scenarios: vals("scenarios"), repeats: +$("#reps").value }) });
      toast(`Job ${j.id} started: ${j.total} runs`); pollJobs();
    } catch (e) { toast(e.message); }
  };
  $("#scenarioList").innerHTML = Object.values(META.scenarios).map((s) => `<div class="card"><h3>${esc(s.label)}</h3><p class="muted">${esc(s.desc)}</p></div>`).join("");
  for (const [sel, items, lab] of [["#fAgent", META.agents, (a) => a.name], ["#fScenario", Object.entries(META.scenarios).map(([id, s]) => ({ id, ...s })), (s) => s.label], ["#fTask", META.tasks, (t) => t.id]])
    $(sel).innerHTML += items.map((x) => `<option value="${x.id}">${esc(lab(x))}</option>`).join("");
  ["#fAgent", "#fScenario", "#fTask"].forEach((s) => $(s).onchange = loadRuns);
}

async function pollJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs").innerHTML = jobs.map((j) => `<div class="muted">Job ${j.id}: ${j.done}/${j.total} runs · ${j.state}</div>`).join("");
  if (jobs.some((j) => j.state === "running")) { loadBoard(); setTimeout(pollJobs, 5000); } else loadBoard();
}

async function loadRuns() {
  const q = new URLSearchParams({ agent: $("#fAgent").value, scenario: $("#fScenario").value, task: $("#fTask").value });
  const runs = await api("/api/runs?" + q);
  $("#runList").innerHTML = runs.map((r) => `<div class="runitem" data-id="${r.run_id}"><span class="dot ${r.status !== "ok" ? "warn" : r.success ? "ok" : "bad"}"></span>
    <div><b>${esc(r.agent)}</b> · ${esc(r.task)}<br><small>${esc(r.scenario)} · repeat ${r.repeat} · ${r.steps} steps · ${r.tool_calls} tools · ${r.tokens} tok</small></div><small>${r.wall_s}s</small></div>`).join("") || `<p class="muted" style="padding:12px">No runs.</p>`;
  document.querySelectorAll(".runitem").forEach((el) => el.onclick = () => { document.querySelectorAll(".runitem").forEach((x) => x.classList.remove("on")); el.classList.add("on"); showRun(el.dataset.id); });
}

function claimsHtml(rep) {
  if (!rep) return "";
  if (rep.error) return `<p class="muted">Detector error: ${esc(rep.error)}</p>`;
  const v = { supported: "ok", contradicted: "bad", unverified: "warn" };
  return `<div class="kpis"><div class="kpi"><b>${pct(rep.answer_freshness)}</b>answer freshness</div><div class="kpi"><b>${rep.n_supported}</b>supported</div><div class="kpi"><b>${rep.n_contradicted}</b>contradicted</div><div class="kpi"><b>${rep.n_unverified}</b>unverified</div></div>` +
    rep.claims.map((c) => `<div class="claim">${c.time_sensitive ? `<span class="score ${cls(c.freshness)}">${pct(c.freshness)}</span>` : ""}
      <span class="pill ${c.time_sensitive ? v[c.verdict] : ""}">${c.time_sensitive ? esc(c.verdict) : "not time-sensitive"}</span><span class="pill">${esc(c.category)}</span>${c.evidence_source !== "none" ? `<span class="pill vio">evidence: ${esc(c.evidence_source)}</span>` : ""}
      <div style="margin-top:6px"><b>${esc(c.text)}</b></div>
      ${c.time_sensitive ? `<div class="ev-q"><b>Inference (model):</b> ${esc(c.rationale)}</div><div class="ev-q"><b>Evidence (sources):</b> ${c.sources.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(new URL(u).hostname)}</a>`).join(" · ") || "none found"}</div>` : ""}</div>`).join("");
}

async function showRun(id) {
  const r = await api("/api/runs/" + id);
  const evs = r.events.map((e) => {
    if (e.kind === "llm") {
      const f = e.injected ? "fault" : "llm";
      return `<div class="ev ${f}"><span class="t">+${e.t}s</span><b>LLM call</b> ${e.injected ? `<span class="pill bad">${esc(e.injected)}</span>` : `<span class="pill">${e.status}</span>`}
      ${e.served_by ? `<span class="pill ${e.fallback ? "warn" : ""}">served by ${esc(e.served_by)}${e.fallback ? " (Bifrost fallback)" : ""}</span>` : ""}
      ${e.prompt_tokens != null ? `<span class="pill">${e.prompt_tokens}→${e.completion_tokens} tok</span>` : ""}${e.latency ? `<span class="pill">${e.latency}s</span>` : ""}
      ${e.tool_calls && e.tool_calls.length ? `<span class="pill vio">calls ${esc(e.tool_calls.join(", "))}</span>` : ""}${e.output ? `<pre>${esc(e.output)}</pre>` : ""}${e.error ? `<pre>${esc(e.error)}</pre>` : ""}</div>`;
    }
    return `<div class="ev ${e.injected ? "fault" : "tool"}"><span class="t">+${e.t}s</span><b>${esc(e.name)}</b> <span class="pill">${esc(e.query)}</span>
      ${e.injected ? `<span class="pill bad">${esc(e.injected)}</span>` : `<span class="pill vio">${esc(e.source || "")}</span>`}${e.poisoned ? `<span class="pill bad">poisoned result injected</span>` : ""}
      ${(e.results || []).map((x) => `<div class="ev-q">· ${esc(x.title)} <span class="muted">${esc(x.url)}</span></div>`).join("")}</div>`;
  }).join("");
  $("#trace").innerHTML = `<h3>${esc(r.agent)} · ${esc(r.task)} · ${esc(r.scenario)} · repeat ${r.repeat}</h3>
    <span class="pill ${r.success ? "ok" : "bad"}">${r.success ? "success" : "fail"}</span><span class="pill">${esc(r.status)}</span>${r.stale_trap ? `<span class="pill bad">gave a stale value</span>` : ""}
    <span class="pill">${r.steps} steps</span><span class="pill">${r.tool_calls} tool calls</span><span class="pill">${r.tokens} tokens</span><span class="pill">$${r.cost_usd}</span><span class="pill">${r.wall_s}s</span>${r.fallbacks_used ? `<span class="pill warn">${r.fallbacks_used} fallback(s)</span>` : ""}
    <h4>Question</h4><div class="answer">${esc(r.question)}</div><h4>Final answer</h4><div class="answer">${esc(r.answer)}</div>
    <h4>Trace</h4>${evs || '<p class="muted">no steps recorded</p>'}${r.stderr ? `<h4>stderr</h4><pre class="answer">${esc(r.stderr)}</pre>` : ""}
    <h4>Stale-Answer Detector</h4>${claimsHtml(r.detector)}`;
}

$("#detectBtn").onclick = async () => {
  const b = $("#detectBtn"); b.disabled = true; b.textContent = "Checking claims against the live web…";
  try { $("#detectOut").innerHTML = claimsHtml(await api("/api/detect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer: $("#answerIn").value }) })); }
  catch (e) { $("#detectOut").innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  b.disabled = false; b.textContent = "Check freshness";
};

(async () => { META = await api("/api/meta"); renderForm(); health(); await loadBoard(); pollJobs(); setInterval(health, 30000); })();
