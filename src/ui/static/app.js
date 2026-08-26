const VIEWS = [
  ["funnel", "01", "漏斗"],
  ["map", "02", "地图"],
  ["evidence", "03", "证据"],
  ["falsify", "04", "证伪"],
  ["eval", "05", "评测"],
];

const state = {
  view: "funnel",
  runId: new URLSearchParams(location.search).get("run") || "",
  runs: [],
  data: null,
  question: "检索增强大模型智能体是否提高科学文献问答的证据可追溯性？",
  ask: null,
  selectedPaper: "paper-001",
  selectedClaim: "claim-008",
};

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const titleOf = (paperId) => {
  const paper = state.data?.papers.find((item) => item.paper_id === paperId);
  return paper?.title || paperId;
};

const hitIds = () => new Set((state.ask?.papers || []).map((item) => item.paper_id));

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

function stamp(kind, label = kind) {
  return `<span class="stamp ${esc(kind)}">${esc(label)}</span>`;
}

function renderShell() {
  const data = state.data;
  const stats = data.stats || {};
  const counts = stats.decision_counts || {};
  document.getElementById("app").innerHTML = `
    <div class="shell">
      <aside class="rail">
        <div class="brand">
          <div class="seal">勘</div>
          <div>
            <h1>勘文</h1>
            <small>LITAUDIT</small>
          </div>
        </div>
        <nav class="nav">
          ${VIEWS.map(
            ([id, num, label]) =>
              `<button data-view="${id}" class="${state.view === id ? "active" : ""}">
                <span class="num">${num}</span><span>${label}</span>
              </button>`
          ).join("")}
        </nav>
        <div class="rail-note">
          include ${counts.include ?? "—"} / exclude ${counts.exclude ?? "—"} / pending ${counts.pending ?? "—"}<br />
          证据 ${stats.verified_evidence_count ?? 0} 条已核验页码<br />
          主问题主张保持 pending。
        </div>
      </aside>
      <main class="main">
        <header class="top">
          <div class="kicker">
            <span>离线勘验 · ${esc(data.scope_version)} · ${esc(data.run_id)}</span>
            <span>claim-008 ${(data.claims.find((c) => c.claim_id === "claim-008") || {}).status || "pending"}</span>
          </div>
          <p class="question">${esc(data.question)}</p>
          <form class="search" id="search-form">
            <input name="q" value="${esc(state.question)}" placeholder="在当前候选集检索，不编造论文" />
            <select name="run">
              ${state.runs.map((run) => `<option ${run === data.run_id ? "selected" : ""}>${esc(run)}</option>`).join("")}
            </select>
            <button class="ghost" type="button" id="rebuild">重跑</button>
            <button class="solid" type="submit">检索</button>
          </form>
          ${renderAsk()}
        </header>
        <section class="stage" id="stage"></section>
      </main>
    </div>
  `;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.onclick = () => {
      state.view = button.dataset.view;
      paint();
    };
  });
  document.getElementById("search-form").onsubmit = async (event) => {
    event.preventDefault();
    const q = event.target.q.value.trim();
    state.question = q;
    if (!q) return;
    state.ask = await api(`/api/ask?run_id=${encodeURIComponent(state.runId)}&q=${encodeURIComponent(q)}`);
    paint();
  };
  document.getElementById("search-form").run.onchange = async (event) => {
    await loadRun(event.target.value);
  };
  document.getElementById("rebuild").onclick = async () => {
    document.getElementById("rebuild").textContent = "重跑中…";
    const result = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "data", run_id: state.runId || "phase2-real" }),
    });
    await loadRun(result.run_id);
  };
  renderView();
}

function renderAsk() {
  if (!state.ask) return "";
  const papers = state.ask.papers || [];
  if (!papers.length) {
    return `<div class="banner">当前离线候选没有足够关键词重叠。不会编造论文。</div>`;
  }
  return `<div class="ask-hits">${papers
    .map((item) => `<span class="pill">${esc(item.paper_id)} · ${esc(item.decision)}</span>`)
    .join("")}</div>`;
}

function renderView() {
  const stage = document.getElementById("stage");
  const views = { funnel: funnelView, map: mapView, evidence: evidenceView, falsify: falsifyView, eval: evalView };
  stage.innerHTML = views[state.view]();
  stage.querySelectorAll("[data-paper]").forEach((node) => {
    node.onclick = () => {
      state.selectedPaper = node.dataset.paper;
      renderView();
    };
  });
  stage.querySelectorAll("[data-claim]").forEach((node) => {
    node.onclick = () => {
      state.selectedClaim = node.dataset.claim;
      renderView();
    };
  });
}

function funnelView() {
  const { stats, papers, retrieval_runs: runs, screening } = state.data;
  const counts = stats.decision_counts || {};
  const hits = hitIds();
  const include = papers.filter((item) => item.decision === "include");
  const exclude = papers.filter((item) => item.decision === "exclude");
  return `
    <div class="metrics">
      ${metric("候选", stats.paper_count, "")}
      ${metric("纳入", counts.include, "include")}
      ${metric("排除", counts.exclude, "exclude")}
      ${metric("待核验", counts.pending, "pending")}
      ${metric("429 / 失败", stats.retrieval_failure_count, "warn")}
    </div>
    <div class="banner">排除论文必须留在漏斗里。HTTP 429 是限流失败，不能当成零结果。</div>
    <div class="workspace">
      <div class="col">
        <div class="col-title">纳入 ${include.length}</div>
        <div class="stack">${include.map((paper) => paperCard(paper, hits)).join("")}</div>
        <div class="col-title" style="margin-top:14px">排除 · 反证据来源 ${exclude.length}</div>
        <div class="stack">${exclude.map((paper) => paperCard(paper, hits)).join("")}</div>
      </div>
      ${inspector()}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>检索</th><th>来源</th><th>状态</th><th>HTTP</th><th>条数</th><th>备注</th></tr></thead>
        <tbody>
          ${runs
            .map((run) => {
              const fail = run.http_status === 429 || run.status !== "success";
              return `<tr class="${fail ? "fail" : ""}">
                <td>${esc(run.retrieval_id)}</td>
                <td>${esc(run.source)}</td>
                <td>${stamp(fail ? "rate_limited" : "verified", run.status)}</td>
                <td>${esc(run.http_status)}</td>
                <td>${esc(run.result_count)}</td>
                <td>${esc(run.notes)}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>
    <details>
      <summary>筛选日志 ${screening.length} 条</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>论文</th><th>阶段</th><th>决定</th><th>理由</th></tr></thead>
          <tbody>
            ${screening
              .map(
                (log) => `<tr>
                  <td>${esc(log.screening_id)}</td>
                  <td>${esc(log.paper_id)}</td>
                  <td>${esc(log.stage)}</td>
                  <td>${stamp(log.decision)}</td>
                  <td>${esc(log.reason)}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </details>
  `;
}

function metric(label, value, kind) {
  return `<div class="metric ${kind}"><div class="label">${esc(label)}</div><div class="value">${esc(value ?? "—")}</div></div>`;
}

function paperCard(paper, hits) {
  const selected = paper.paper_id === state.selectedPaper ? "selected" : "";
  const hit = hits.has(paper.paper_id) ? "hit" : "";
  return `
    <button class="paper-card ${hit} ${selected}" data-paper="${esc(paper.paper_id)}">
      <div class="stamps">${stamp(paper.decision)} ${stamp(paper.parse_status || "info", paper.parse_status || "no card")}</div>
      <h3>${esc(paper.title)}</h3>
      <div class="meta">${esc(paper.paper_id)} · ${esc(paper.year)} · ${esc(paper.doi_or_arxiv)}</div>
    </button>
  `;
}

function inspector() {
  const paper = state.data.papers.find((item) => item.paper_id === state.selectedPaper);
  if (!paper) return `<aside class="inspector muted">选择一篇论文查看理由。</aside>`;
  const fields = paper.fields || {};
  return `
    <aside class="inspector">
      <div class="stamps">${stamp(paper.decision)} ${stamp(paper.parse_status || "info", paper.parse_status || "")}</div>
      <h3>${esc(paper.title)}</h3>
      ${paper.parse_error ? `<p class="tiny">${esc(paper.parse_error)}</p>` : ""}
      <p>${esc(paper.reason)}</p>
      ${fields.task ? `<p class="tiny">${esc(fields.task)}</p>` : ""}
      ${fields.method ? `<p class="tiny">${esc(fields.method)}</p>` : ""}
      ${fields.metrics ? `<p class="tiny">${esc(fields.metrics)}</p>` : ""}
      ${fields.limitations ? `<p class="muted">${esc(fields.limitations)}</p>` : ""}
      ${paper.url ? `<p><a href="${esc(paper.url)}" target="_blank" rel="noreferrer">打开来源</a></p>` : ""}
    </aside>
  `;
}

function mapView() {
  const map = state.data.map || {};
  const tracks = map.tracks || [];
  const contradiction = (map.contradictions || [])[0];
  const order = ["sciqa", "autosci", "boundary"];
  const sorted = [...tracks].sort((a, b) => order.indexOf(a.track_id) - order.indexOf(b.track_id));
  const edges = map.edges || [];
  const unique = [];
  const seen = new Set();
  for (const edge of edges) {
    const key = `${edge.source}→${edge.target}·${edge.kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(edge);
  }
  return `
    ${
      contradiction
        ? `<div class="banner pending">
            ${esc(contradiction.claim_id)} · ${esc(contradiction.claim_status)}：${esc(contradiction.claim_text)}<br />
            ${(contradiction.support_or_context_papers || []).join(" / ")}
            → ${(contradiction.contradict_papers || []).join(" / ")}
          </div>`
        : ""
    }
    <div class="workspace">
      <div class="col">
        <div class="tracks">
          ${sorted
            .map((track) => {
              const papers = state.data.papers.filter((paper) => track.paper_ids.includes(paper.paper_id));
              return `<div class="track">
                <h2>${esc(track.label)}</h2>
                <div class="stack">${papers.map((paper) => paperCard(paper, hitIds())).join("")}</div>
              </div>`;
            })
            .join("")}
        </div>
        <div class="edge-list">
          关系边来自证据冲突和反证据，不是引用图谱。
          ${unique
            .map(
              (edge) =>
                `<div>${esc(edge.source)} → ${esc(edge.target)} · ${esc(edge.kind)} · ${esc(edge.claim_id || "")}</div>`
            )
            .join("")}
        </div>
      </div>
      ${inspector()}
    </div>
  `;
}

function evidenceView() {
  const { claims, evidence, claim_decisions: decisions } = state.data;
  const selected = claims.find((item) => item.claim_id === state.selectedClaim) || claims[0];
  if (!selected) return `<div class="banner">当前 run 没有 Claim。</div>`;
  const related = evidence.filter((item) => item.claim_id === selected.claim_id);
  const decision = decisions.find((item) => item.claim_id === selected.claim_id);
  return `
    <div class="claim-layout">
      <div class="claim-nav">
        ${claims
          .map(
            (claim) => `<button data-claim="${esc(claim.claim_id)}" class="${claim.claim_id === selected.claim_id ? "active" : ""}">
              ${stamp(claim.status)} <span class="tiny">${esc(claim.claim_id)}</span>
              <div class="one-line">${esc(claim.text)}</div>
            </button>`
          )
          .join("")}
      </div>
      <article class="claim ${esc(selected.status)}">
        ${stamp(selected.status)} <span class="tiny">${esc(selected.claim_id)} · ${esc(selected.source)}</span>
        <h3>${esc(selected.text)}</h3>
        <p class="muted">${esc(selected.decision_reason)}</p>
        ${decision ? `<p class="tiny">判决账本 · ${esc(decision.reviewer)} · ${esc(decision.reason)}</p>` : ""}
        ${related.length ? related.map(evidenceBlock).join("") : `<div class="banner danger">没有 Evidence。按契约不得进入确定结论区。</div>`}
      </article>
    </div>
  `;
}

function evidenceBlock(item) {
  const locator = item.locator || {};
  const page = locator.page != null ? `第 ${locator.page} 页` : "无页码";
  return `
    <div class="quote">
      <div class="stamps">${stamp(item.extraction_status)} ${stamp(item.verdict)}
        <span class="tiny">${esc(item.evidence_id)} · ${esc(item.paper_id)}</span>
      </div>
      <p>「${esc(item.snippet)}」</p>
      <div class="loc">${esc(page)} · ${esc(locator.section)}</div>
    </div>
  `;
}

function falsifyView() {
  const hits = state.data.falsification || [];
  if (!hits.length) return `<div class="banner">当前 run 没有反证据命中。</div>`;
  return `
    <div class="banner danger">反证据可以召回 exclude 论文。当前命中任务是通用 RAG/QA，威胁为 overlap，不是 fatal。</div>
    <div class="hit-grid">
      ${hits
        .map((hit) => {
          const locator = hit.locator || {};
          return `
            <article class="hit-card">
              <div class="stamps">${stamp("contradicts", hit.threat)} ${stamp(hit.status)} ${stamp(hit.threat_level, hit.threat_level)}</div>
              <h3>${esc(hit.hit_id)} 打击 ${esc(hit.target_claim)}</h3>
              <p>${esc(hit.reason)}</p>
              <p class="tiny">${esc(hit.paper_id)} · ${esc(titleOf(hit.paper_id))}</p>
              <div class="quote">
                <p>「${esc(hit.snippet)}」</p>
                <div class="loc">第 ${esc(locator.page)} 页 · ${esc(locator.section)}</div>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function evalView() {
  const metrics = state.data.eval || {};
  const delta = metrics.delta_vs_no_retrieval || {};
  const labels = {
    evidence_locator_rate: "证据定位",
    verified_evidence_rate: "页码核验",
    page_locator_rate: "页码覆盖",
    claim_evidence_link_rate: "论断链接",
    falsification_target_coverage: "反证据覆盖",
  };
  return `
    <div class="banner">比较的是可追溯性，不是模型准确率，也不能解释成 RAG 的因果效应。</div>
    <div class="metrics">
      ${metric("题目", metrics.question_count, "")}
      ${metric("verified", metrics.verified_evidence_count, "include")}
      ${metric("页码", metrics.page_locator_count, "")}
      ${metric("pending", pct(metrics.pending_claim_rate), "pending")}
      ${metric("supported", pct(metrics.supported_claim_rate), "include")}
    </div>
    <div class="section-title">相对无检索代理</div>
    <div class="bars">
      ${Object.entries(delta)
        .map(([key, value]) => {
          const lit = (metrics.litaudit || {})[key] || 0;
          return `<div class="bar-row">
            <div>${esc(labels[key] || key)}</div>
            <div class="bar"><span style="width:${Math.round(lit * 100)}%"></span></div>
            <div>+${esc(value)}</div>
          </div>`;
        })
        .join("")}
    </div>
    <p class="tiny">gold paper ${esc(metrics.gold_paper_recall)} · gold claim ${esc(metrics.gold_claim_coverage)}</p>
    <ul class="limit-list">${(metrics.limitations || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
  `;
}

function pct(value) {
  return value == null ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function paint() {
  const boot = document.getElementById("boot");
  const app = document.getElementById("app");
  if (boot) {
    boot.hidden = true;
    boot.style.display = "none";
  }
  if (app) {
    app.hidden = false;
    app.removeAttribute("hidden");
  }
  renderShell();
}

async function loadRun(runId) {
  state.runId = runId;
  state.data = await api(`/api/run/${encodeURIComponent(runId)}`);
  const url = new URL(location.href);
  url.searchParams.set("run", runId);
  history.replaceState({}, "", url);
  paint();
}

async function boot() {
  const listing = await api("/api/runs");
  state.runs = listing.runs || [];
  const preferred = state.runId || listing.default_run_id || state.runs[0];
  if (!preferred) {
    document.getElementById("boot").textContent = "还没有可回放的 run。先执行 python -m src.cli run --offline --run-id phase2-real";
    return;
  }
  await loadRun(preferred);
}

window.addEventListener("keydown", (event) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  const index = Number(event.key) - 1;
  if (index >= 0 && index < VIEWS.length) {
    state.view = VIEWS[index][0];
    paint();
  }
});

boot().catch((error) => {
  document.getElementById("boot").textContent = `界面启动失败：${error.message}`;
});
