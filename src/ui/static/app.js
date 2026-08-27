const VIEWS = [
  ["funnel", "01", "筛选", "先筛哪些论文该看"],
  ["map", "02", "地图", "主线与矛盾关系"],
  ["evidence", "03", "证据", "论断与原文摘录"],
  ["falsify", "04", "反证", "可能推翻结论的论文"],
  ["eval", "05", "评测", "可追溯性对照"],
];

const LABELS = {
  decision: { include: "纳入", exclude: "排除", pending: "待定" },
  claim: { supported: "已支持", partial: "部分支持", unsupported: "不支持", pending: "待核验" },
  parse: {
    pdf_partial_verified: "已核验摘录",
    abstract_verified: "仅摘要",
    live_abstract: "仅摘要（未读全文）",
    verified: "已核验",
    failed: "解析失败",
  },
  retrieval: {
    arxiv: "arXiv",
    openalex: "OpenAlex",
    semantic_scholar: "Semantic Scholar",
  },
  retrievalStatus: {
    success: "成功",
    rate_limited: "暂时限流",
    failed: "失败",
  },
  verdict: {
    supports: "支持",
    partially_supports: "部分支持",
    contradicts: "矛盾",
    context_only: "背景",
  },
  extraction: {
    verified: "已核验页码",
    abstract_only: "仅摘要",
    unverified: "未核验",
    failed: "失败",
  },
  source: { arxiv: "arXiv", openalex: "OpenAlex", semantic_scholar: "Semantic Scholar" },
};

const state = {
  view: "funnel",
  runId: new URLSearchParams(location.search).get("run") || "",
  runs: [],
  data: null,
  question: "检索增强大模型智能体是否提高科学文献问答的证据可追溯性？",
  ask: null,
  selectedPaper: "paper-001",
  selectedClaim: "claim-008",
  moreOpen: false,
};

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const labelOf = (group, key, fallback = key) => LABELS[group]?.[key] || fallback;

const runById = (runId) => state.runs.find((item) => item.id === runId);

const currentRunLabel = () => state.data?.display?.label || runById(state.runId)?.label || "当前结果";

const titleOf = (paperId) => {
  const paper = state.data?.papers.find((item) => item.paper_id === paperId);
  return paper?.title || paperId;
};

const hitIds = () => new Set((state.ask?.papers || []).map((item) => item.paper_id));

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} ${response.status}`);
  return data;
}

function stamp(kind, label) {
  const text = label ?? labelOf("decision", kind) ?? labelOf("claim", kind) ?? labelOf("parse", kind) ?? kind;
  return `<span class="stamp ${esc(kind)}">${esc(text)}</span>`;
}

function renderShell() {
  const data = state.data;
  const stats = data.stats || {};
  const counts = stats.decision_counts || {};
  const display = data.display || runById(data.run_id) || {};
  const kicker = data.offline
    ? `正在查看：${esc(display.label || "基准核验结果")}。主问题结论仍待核验，因为正反证据尚未调和。`
    : `正在查看：${esc(display.label || "在线检索结果")}。新增论文仅做摘要筛选，尚未生成页码级证据。`;

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
            ([id, num, label, hint]) =>
              `<button data-view="${id}" class="${state.view === id ? "active" : ""}" title="${esc(hint)}">
                <span class="num">${num}</span>
                <span class="nav-text"><span>${label}</span><small>${esc(hint)}</small></span>
              </button>`
          ).join("")}
        </nav>
        <div class="rail-note">
          纳入 ${counts.include ?? "—"} · 排除 ${counts.exclude ?? "—"} · 待定 ${counts.pending ?? "—"}<br />
          ${stats.verified_evidence_count ?? 0} 条证据已核对页码<br />
          主问题结论仍为待定。
        </div>
      </aside>
      <main class="main">
        <header class="top">
          <div class="kicker">${kicker}</div>
          <p class="question">${esc(data.question)}</p>
          <form class="search" id="search-form">
            <input name="q" value="${esc(state.question)}" placeholder="输入科研问题，例如：RAG 是否提高文献问答的可追溯性？" />
            <button class="solid" type="submit">检索文献</button>
          </form>
          <div class="history-bar">
            <div class="current-run">
              <span class="history-label">当前结果</span>
              <strong>${esc(display.label || currentRunLabel())}</strong>
              ${display.subtitle ? `<span class="history-sub">${esc(display.subtitle)}</span>` : ""}
            </div>
            <div class="history-actions">
              <label class="history-select">
                <span class="history-label">查看历史</span>
                <select name="run" id="run-select">
                  ${state.runs
                    .map(
                      (run) =>
                        `<option value="${esc(run.id)}" ${run.id === data.run_id ? "selected" : ""}>${esc(run.label)}${
                          run.subtitle ? ` · ${esc(run.subtitle)}` : ""
                        }</option>`
                    )
                    .join("")}
                </select>
              </label>
              <button class="ghost tiny-btn" type="button" id="toggle-more">${state.moreOpen ? "收起" : "更多"}</button>
            </div>
          </div>
          ${
            state.moreOpen
              ? `<div class="more-actions">
                  <button class="ghost" type="button" id="local-search">在当前结果里查找</button>
                  <button class="ghost" type="button" id="rebuild">重新加载基准结果</button>
                </div>`
              : ""
          }
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
    await liveSearch(q);
  };
  document.getElementById("run-select").onchange = async (event) => {
    await loadRun(event.target.value);
  };
  document.getElementById("toggle-more").onclick = () => {
    state.moreOpen = !state.moreOpen;
    paint();
  };
  if (state.moreOpen) {
    document.getElementById("local-search").onclick = async () => {
      const q = document.getElementById("search-form").q.value.trim();
      state.question = q;
      if (!q) return;
      state.ask = await api(`/api/ask?run_id=${encodeURIComponent(state.runId)}&q=${encodeURIComponent(q)}`);
      paint();
    };
    document.getElementById("rebuild").onclick = async () => {
      const btn = document.getElementById("rebuild");
      btn.textContent = "加载中…";
      btn.disabled = true;
      try {
        const result = await api("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source: "data", run_id: "phase2-real", offline: true }),
        });
        const listing = await api("/api/runs");
        state.runs = listing.runs || state.runs;
        await loadRun(result.run_id);
      } finally {
        btn.disabled = false;
        btn.textContent = "重新加载基准结果";
      }
    };
  }
  renderView();
}

function renderAsk() {
  if (state.ask?.error) {
    return `<div class="banner danger">${esc(state.ask.error)}</div>`;
  }
  const live = state.data?.live;
  const liveNote = live
    ? `<div class="banner">新增 ${(live.added_paper_ids || []).length} 篇候选（已与已有论文去重）。主问题结论仍为待定。</div>`
    : "";
  if (!state.ask) return liveNote;
  const papers = state.ask.papers || [];
  if (!papers.length) {
    return `${liveNote}<div class="banner">当前结果里没有足够相关的论文。不会编造文献。</div>`;
  }
  return `${liveNote}<div class="ask-hits">${papers
    .map((item) => {
      const title = titleOf(item.paper_id);
      return `<span class="pill">${esc(title.length > 42 ? title.slice(0, 41) + "…" : title)} · ${esc(
        labelOf("decision", item.decision)
      )}</span>`;
    })
    .join("")}</div>`;
}

async function liveSearch(question) {
  const button = document.querySelector("#search-form .solid");
  button.disabled = true;
  button.textContent = "正在检索…";
  try {
    let result;
    try {
      result = await api("/api/live", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
    } catch (error) {
      const message = String(error.message || "");
      if (!message.includes("not found")) throw error;
      result = await api("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "data", offline: false, question }),
      });
    }
    if (result.error) throw new Error(result.error);
    if (result.offline) {
      throw new Error("当前服务仍在离线模式。请重启界面后再试。");
    }
    const listing = await api("/api/runs");
    state.runs = listing.runs || state.runs;
    state.ask = result.ask || null;
    await loadRun(result.run_id);
  } catch (error) {
    state.ask = { error: `检索失败：${error.message}` };
    paint();
  } finally {
    const current = document.querySelector("#search-form .solid");
    if (current) {
      current.disabled = false;
      current.textContent = "检索文献";
    }
  }
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
  const pending = papers.filter((item) => item.decision === "pending");
  const exclude = papers.filter((item) => item.decision === "exclude");
  return `
    <p class="view-hint">先筛哪些论文该看：纳入、排除与待定都会保留，方便后续查证据和反证。</p>
    <div class="metrics">
      ${metric("候选论文", stats.paper_count, "")}
      ${metric("纳入", counts.include, "include")}
      ${metric("排除", counts.exclude, "exclude")}
      ${metric("待定", counts.pending, "pending")}
      ${metric("检索异常", stats.retrieval_failure_count, "warn")}
    </div>
    <div class="banner">被排除的论文也会留下，后面反证还要用。拿不准的标为待定，不会当成结论。</div>
    <div class="workspace">
      <div class="col">
        <div class="col-title">纳入 ${include.length}</div>
        <div class="stack">${include.map((paper) => paperCard(paper, hits)).join("")}</div>
        <div class="col-title" style="margin-top:14px">待定 ${pending.length}</div>
        <div class="stack">${pending.length ? pending.map((paper) => paperCard(paper, hits)).join("") : `<p class="muted">没有待定论文。</p>`}</div>
        <div class="col-title" style="margin-top:14px">排除 · 反证据来源 ${exclude.length}</div>
        <div class="stack">${exclude.map((paper) => paperCard(paper, hits)).join("")}</div>
      </div>
      ${inspector()}
    </div>
    <details>
      <summary>检索日志（${runs.length} 条，含限流失败记录）</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>来源</th><th>结果</th><th>篇数</th><th>说明</th></tr></thead>
          <tbody>
            ${runs
              .map((run) => {
                const fail = run.http_status === 429 || run.status !== "success";
                const statusLabel =
                  run.http_status === 429
                    ? "文献库暂时限流"
                    : labelOf("retrievalStatus", run.status, run.status);
                return `<tr class="${fail ? "fail" : ""}">
                  <td>${esc(labelOf("source", run.source, run.source))}</td>
                  <td>${esc(statusLabel)}</td>
                  <td>${esc(run.result_count ?? "—")}</td>
                  <td>${esc(run.http_status === 429 ? "未取得结果，不能当成零篇成功。" : run.notes || "")}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    </details>
    <details>
      <summary>筛选明细（${screening.length} 条，含内部编号）</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>论文</th><th>阶段</th><th>决定</th><th>理由</th></tr></thead>
          <tbody>
            ${screening
              .map(
                (log) => `<tr>
                  <td>${esc(titleOf(log.paper_id))}<br /><span class="tiny">${esc(log.paper_id)}</span></td>
                  <td>${esc(log.stage === "title_abstract" ? "标题摘要" : log.stage)}</td>
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
  const parseLabel = labelOf("parse", paper.parse_status, paper.parse_status || "未标注");
  return `
    <button class="paper-card ${hit} ${selected}" data-paper="${esc(paper.paper_id)}">
      <div class="stamps">${stamp(paper.decision)} ${stamp(paper.parse_status || "info", parseLabel)}</div>
      <h3>${esc(paper.title)}</h3>
      <div class="meta">${esc(paper.year || "—")}${paper.venue ? ` · ${esc(paper.venue)}` : ""}</div>
    </button>
  `;
}

function inspector() {
  const paper = state.data.papers.find((item) => item.paper_id === state.selectedPaper);
  if (!paper) return `<aside class="inspector muted">点选一篇论文查看筛选理由。</aside>`;
  const fields = paper.fields || {};
  const parseLabel = labelOf("parse", paper.parse_status, paper.parse_status || "");
  return `
    <aside class="inspector">
      <div class="stamps">${stamp(paper.decision)} ${stamp(paper.parse_status || "info", parseLabel)}</div>
      <h3>${esc(paper.title)}</h3>
      <p class="tiny">编号 ${esc(paper.paper_id)} · ${esc(paper.year || "—")} · ${esc(paper.doi_or_arxiv || "")}</p>
      ${paper.parse_error ? `<p class="tiny">${esc(paper.parse_error)}</p>` : ""}
      <p>${esc(paper.reason)}</p>
      ${fields.task ? `<p class="tiny">${esc(fields.task)}</p>` : ""}
      ${fields.method ? `<p class="tiny">${esc(fields.method)}</p>` : ""}
      ${fields.metrics ? `<p class="tiny">${esc(fields.metrics)}</p>` : ""}
      ${fields.limitations ? `<p class="muted">${esc(fields.limitations)}</p>` : ""}
      ${paper.url ? `<p><a href="${esc(paper.url)}" target="_blank" rel="noreferrer">打开原文</a></p>` : ""}
    </aside>
  `;
}

function mapView() {
  const map = state.data.map || {};
  const tracks = map.tracks || [];
  const contradiction = (map.contradictions || [])[0];
  const order = ["sciqa", "autosci", "pending", "boundary"];
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
    <p class="view-hint">按研究主线归类论文。连线来自证据冲突与反证，不是引用关系。</p>
    ${
      contradiction
        ? `<div class="banner pending">
            主问题相关论断仍待核验：${esc(contradiction.claim_text)}<br />
            支持侧：${(contradiction.support_or_context_papers || []).map(titleOf).join(" / ")}
            → 矛盾侧：${(contradiction.contradict_papers || []).map(titleOf).join(" / ")}
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
        <details>
          <summary>关系明细（${unique.length} 条）</summary>
          <div class="edge-list">
            ${unique
              .map(
                (edge) =>
                  `<div>${esc(titleOf(edge.source))} → ${esc(titleOf(edge.target))} · ${
                    edge.kind === "evidence_conflict" ? "证据冲突" : edge.kind === "falsification" ? "反证据" : esc(edge.kind)
                  }</div>`
              )
              .join("")}
          </div>
        </details>
      </div>
      ${inspector()}
    </div>
  `;
}

function evidenceView() {
  const { claims, evidence, claim_decisions: decisions } = state.data;
  const selected = claims.find((item) => item.claim_id === state.selectedClaim) || claims[0];
  if (!selected) return `<div class="banner">当前结果还没有论断。</div>`;
  const related = evidence.filter((item) => item.claim_id === selected.claim_id);
  const decision = decisions.find((item) => item.claim_id === selected.claim_id);
  return `
    <p class="view-hint">每条论断都要能回到原文摘录；没有证据的不能写成确定结论。</p>
    <div class="claim-layout">
      <div class="claim-nav">
        ${claims
          .map(
            (claim) => `<button data-claim="${esc(claim.claim_id)}" class="${claim.claim_id === selected.claim_id ? "active" : ""}">
              ${stamp(claim.status, labelOf("claim", claim.status))}
              <div class="one-line">${esc(claim.text)}</div>
            </button>`
          )
          .join("")}
      </div>
      <article class="claim ${esc(selected.status)}">
        ${stamp(selected.status, labelOf("claim", selected.status))}
        <h3>${esc(selected.text)}</h3>
        <p class="muted">${esc(selected.decision_reason)}</p>
        ${decision ? `<p class="tiny">复核说明 · ${esc(decision.reason)}</p>` : ""}
        <details class="tiny"><summary>内部编号 ${esc(selected.claim_id)}</summary></details>
        ${related.length ? related.map(evidenceBlock).join("") : `<div class="banner danger">尚无证据摘录，不能进入确定结论区。</div>`}
      </article>
    </div>
  `;
}

function evidenceBlock(item) {
  const locator = item.locator || {};
  const page = locator.page != null ? `第 ${locator.page} 页` : "无页码";
  return `
    <div class="quote">
      <div class="stamps">${stamp(item.extraction_status, labelOf("extraction", item.extraction_status))} ${stamp(
    item.verdict,
    labelOf("verdict", item.verdict)
  )}
        <span class="tiny">${esc(titleOf(item.paper_id))}</span>
      </div>
      <p>「${esc(item.snippet)}」</p>
      <div class="loc">${esc(page)}${locator.section ? ` · ${esc(locator.section)}` : ""}</div>
    </div>
  `;
}

function falsifyView() {
  const hits = state.data.falsification || [];
  if (!hits.length) return `<div class="banner">当前结果还没有反证据命中。</div>`;
  return `
    <p class="view-hint">反证可以来自被排除的论文，用来检验主结论是否过于乐观。</p>
    <div class="banner danger">以下论文提示 RAG/问答的可信度风险，属于任务边界重叠，不是直接否定全部纳入论文。</div>
    <div class="hit-grid">
      ${hits
        .map((hit) => {
          const locator = hit.locator || {};
          return `
            <article class="hit-card">
              <div class="stamps">${stamp("contradicts", "重叠风险")} ${stamp(hit.status, labelOf("claim", hit.status))}</div>
              <h3>针对主问题相关论断</h3>
              <p>${esc(hit.reason)}</p>
              <p class="tiny">${esc(titleOf(hit.paper_id))}</p>
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
    evidence_locator_rate: "证据可定位",
    verified_evidence_rate: "页码已核验",
    page_locator_rate: "页码覆盖",
    claim_evidence_link_rate: "论断有证据",
    falsification_target_coverage: "反证据覆盖",
  };
  return `
    <p class="view-hint">这里比较的是「能不能回溯到原文」，不是模型答题准确率。</p>
    <div class="banner">指标反映可追溯性，不能解释成 RAG 一定提高任务质量。</div>
    <div class="metrics">
      ${metric("评测题", metrics.question_count, "")}
      ${metric("已核验证据", metrics.verified_evidence_count, "include")}
      ${metric("页码定位", metrics.page_locator_count, "")}
      ${metric("待核验论断", pct(metrics.pending_claim_rate), "pending")}
      ${metric("已支持论断", pct(metrics.supported_claim_rate), "include")}
    </div>
    <div class="section-title">相对「不检索、只凭模型」</div>
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
  const preferred =
    state.runId ||
    listing.default_run_id ||
    state.runs.find((item) => item.id === "phase2-real")?.id ||
    state.runs[0]?.id;
  if (!preferred) {
    document.getElementById("boot").textContent = "还没有可查看的结果。请先输入科研问题并点击「检索文献」。";
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
  document.getElementById("boot").textContent = `打开失败：${error.message}`;
});
