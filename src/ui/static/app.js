const VIEWS = [
  ["chat", "00", "对话首页", "与研究助手连续探索"],
  ["funnel", "01", "检索与筛选", "先看候选与筛选理由"],
  ["map", "02", "研究地图", "按主线查看冲突关系"],
  ["evidence", "03", "证据核验", "论断与原文摘录"],
  ["falsify", "04", "反证检查", "召回可能的风险论文"],
  ["eval", "05", "可追溯性评测", "对照无检索基线"],
];

const LABELS = {
  decision: { include: "纳入", exclude: "排除", pending: "待定" },
  claim: { supported: "已支持", partial: "部分支持", unsupported: "证据不足/不支持该表述", pending: "待核验" },
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
  view: new URLSearchParams(location.search).get("view") || "chat",
  runId: new URLSearchParams(location.search).get("run") || "",
  runs: [],
  data: null,
  question: "检索增强大模型智能体是否提高科学文献问答的证据可追溯性？",
  ask: null,
  chat: { messages: [], pendingChoices: [], pendingTopic: "" },
  chatNew: false,
  conversationHistory: [],
  historyOpen: false,
  selectedPaper: "paper-001",
  selectedClaim: "claim-008",
  selectedEdgeKey: "",
  graphPositions: {},
  graphRunId: "",
  graphTransform: { x: 0, y: 0, scale: 1 },
  graphSimulation: null,
  graphLayouts: {},
  chatGraphMaps: {},
  activeGraphId: "",
  moreOpen: false,
};

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

function inlineMarkdown(value) {
  return esc(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
}

function renderMarkdown(value) {
  let source = String(value ?? "").replaceAll("\\n", "\n").replace(/\r\n?/g, "\n").trim();
  source = source
    .replace(/\s+(\*\*(?:已纳入|待定|已排除|关于|结论|注意)[^*]*\*\*)/g, "\n\n$1")
    .replace(/\s+(\d+)\.\s+(?=\*\*|paper-)/g, "\n$1. ");
  if (!source) return "";
  const lines = source.split("\n");
  const output = [];
  let listType = "";
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = "";
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 4);
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
    } else if (ordered || unordered) {
      const nextType = ordered ? "ol" : "ul";
      if (listType !== nextType) {
        closeList();
        listType = nextType;
        output.push(`<${listType}>`);
      }
      output.push(`<li>${inlineMarkdown((ordered || unordered)[1])}</li>`);
    } else {
      closeList();
      output.push(`<p>${inlineMarkdown(line)}</p>`);
    }
  }
  closeList();
  return output.join("");
}

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
  const workspace = data.workspace || {};
  const reviewCount = workspace.review_item_count ?? 0;
  const kicker = data.offline
    ? `正在查看：${esc(display.label || "基准核验结果")}。主问题结论仍待核验，因为正反证据尚未调和。`
    : `正在查看：${esc(display.label || "在线检索结果")}。新增论文仅做摘要筛选，尚未生成页码级证据。`;
  const moduleHeader = moduleHeaderView();

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
        ${sidebarConversations()}
      </aside>
      <main class="main">
        <header class="top">
          <div class="kicker">${kicker}</div>
          ${moduleHeader}
          ${
            state.moreOpen
              ? `<div class="more-actions">
                  <button class="ghost" type="button" id="local-search">在当前结果里查找</button>
                  <button class="ghost" type="button" id="rebuild">重新加载基准结果</button>
                  <button class="ghost" type="button" id="export-report">下载审计报告</button>
                </div>`
              : ""
          }
          ${renderAsk()}
        </header>
        <section class="stage" id="stage"></section>
      </main>
    </div>
  `;

  bindConversationControls(document);
  const backToChat = document.getElementById("back-to-chat");
  if (backToChat) backToChat.onclick = () => setView("chat");
  renderView();
  const searchForm = document.getElementById("search-form");
  if (searchForm) searchForm.onsubmit = async (event) => {
    event.preventDefault();
    const q = event.target.q.value.trim();
    state.question = q;
    if (!q) return;
    await chatTurn(q);
  };
  const runSelect = document.getElementById("run-select");
  if (runSelect) runSelect.onchange = async (event) => await loadRun(event.target.value);
  const toggleMore = document.getElementById("toggle-more");
  if (toggleMore) toggleMore.onclick = () => {
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
    document.getElementById("export-report").onclick = async () => {
      const btn = document.getElementById("export-report");
      btn.disabled = true;
      btn.textContent = "准备报告…";
      try {
        const response = await fetch(`/api/run/${encodeURIComponent(state.runId)}/report`);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `报告生成失败（${response.status}）`);
        const blob = new Blob([payload.content || ""], { type: "text/markdown;charset=utf-8" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = payload.filename || `litaudit-${state.runId}-audit.md`;
        link.click();
        URL.revokeObjectURL(link.href);
      } catch (error) {
        state.ask = { error: `报告导出失败：${error.message}` };
        paint();
      } finally {
        const current = document.getElementById("export-report");
        if (current) {
          current.disabled = false;
          current.textContent = "下载审计报告";
        }
      }
    };
  }
}

function sidebarConversations() {
  const rows = state.conversationHistory || [];
  const items = rows.length ? rows.map((item) => '<div class="sidebar-conversation ' + (item.run_id === state.runId && !state.chatNew ? "active" : "") + '">' +
    '<button class="sidebar-open" type="button" data-conversation-run="' + esc(item.run_id) + '" title="' + esc(item.title) + '"><strong>' + esc(item.title) + '</strong><span>' + esc(item.message_count) + ' 条消息</span></button>' +
    '<div class="sidebar-row-actions"><button type="button" data-conversation-rename="' + esc(item.run_id) + '" title="重命名对话">✎</button><button type="button" data-conversation-delete="' + esc(item.run_id) + '" title="删除对话记录">×</button></div></div>').join("") : '<div class="sidebar-empty">检索完成后的对话会保存在这里。</div>';
  return '<div class="conversation-sidebar"><div class="sidebar-heading"><span>研究对话</span><small>' + rows.length + '</small></div><button class="sidebar-new" type="button" id="sidebar-new-conversation"><span aria-hidden="true">＋</span> 新建对话</button><div class="sidebar-list">' + items + '</div></div>';
}

function setView(view) {
  state.view = view;
  const url = new URL(location.href);
  if (view === "chat") url.searchParams.delete("view");
  else url.searchParams.set("view", view);
  history.replaceState({}, "", url);
  paint();
}

function moduleHeaderView() {
  if (state.view === "chat") return "";
  const view = VIEWS.find((item) => item[0] === state.view);
  const title = state.conversationHistory.find((item) => item.run_id === state.runId)?.title || currentRunLabel();
  return '<div class="module-bar"><button class="ghost" type="button" id="back-to-chat">← 返回对话</button><div><span class="history-label">当前模块</span><strong>' + esc(view?.[2] || "研究详情") + '</strong></div><div class="module-run"><span class="history-label">所属对话</span><strong>' + esc(title) + '</strong></div></div>';
}

function scopedAuditData() {
  const data = state.data || {};
  const live = data.live || {};
  const added = new Set(live.added_paper_ids || []);
  if (data.offline !== false || !live.added_paper_ids) return data;
  return { ...data, papers: (data.papers || []).filter((item) => added.has(item.paper_id)), evidence: (data.evidence || []).filter((item) => added.has(item.paper_id)), falsification: (data.falsification || []).filter((item) => added.has(item.paper_id)), claims: (data.claims || []).filter((item) => item.text === data.question || (data.evidence || []).some((e) => e.claim_id === item.claim_id && added.has(e.paper_id))) };
}

async function refreshConversations() {
  const result = await api("/api/conversations");
  state.conversationHistory = result.conversations || [];
}

function startNewConversation() {
  state.chat = { messages: [], pendingChoices: [], pendingTopic: "" };
  state.chatNew = true;
  state.view = "chat";
  state.ask = null;
  const url = new URL(location.href);
  url.searchParams.delete("run");
  url.searchParams.delete("view");
  history.replaceState({}, "", url);
  paint();
}

function bindConversationControls(root) {
  const newButton = root.querySelector("#sidebar-new-conversation");
  if (newButton) newButton.onclick = startNewConversation;
  root.querySelectorAll("[data-conversation-run]").forEach((node) => {
    node.onclick = async () => {
      state.chatNew = false;
      state.view = "chat";
      await loadRun(node.dataset.conversationRun);
    };
  });
  root.querySelectorAll("[data-conversation-rename]").forEach((node) => {
    node.onclick = async () => {
      const item = state.conversationHistory.find((row) => row.run_id === node.dataset.conversationRename);
      const title = window.prompt("输入新的对话名称", item?.title || "");
      if (title == null || !title.trim()) return;
      try {
        await api(`/api/chat/${encodeURIComponent(node.dataset.conversationRename)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }) });
        await refreshConversations();
        paint();
      } catch (error) {
        state.ask = { error: `重命名失败：${error.message}` };
        paint();
      }
    };
  });
  root.querySelectorAll("[data-conversation-delete]").forEach((node) => {
    node.onclick = async () => {
      const runId = node.dataset.conversationDelete;
      if (!window.confirm("删除这段对话记录？对应论文、证据、反证和评测快照仍会保留。")) return;
      await api(`/api/chat/${encodeURIComponent(runId)}`, { method: "DELETE" });
      await refreshConversations();
      if (runId === state.runId) startNewConversation();
      else paint();
    };
  });
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
  const views = { chat: chatView, funnel: funnelView, map: mapView, evidence: evidenceView, falsify: falsifyView, eval: evalView };
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
  stage.querySelectorAll("[data-chat-paper]").forEach((node) => {
    node.onclick = () => {
      state.view = "map";
      state.selectedPaper = node.dataset.chatPaper;
      paint();
    };
  });
  stage.querySelectorAll("[data-chat-action]").forEach((node) => {
    node.onclick = () => {
      const view = node.dataset.chatAction === "evidence" ? "evidence" : node.dataset.chatAction === "falsify" ? "falsify" : "eval";
      window.open(`/?run=${encodeURIComponent(state.runId)}&view=${encodeURIComponent(view)}`, "_blank", "noopener");
    };
  });
  stage.querySelectorAll(".clarification-submit").forEach((button) => {
    button.onclick = () => {
      const bubble = button.closest(".clarification-bubble");
      const questions = [...bubble.querySelectorAll(".clarification-question")];
      const selected = questions.map((question) => {
        const checked = question.querySelector("input[type=radio]:checked");
        if (!checked) return "";
        if (checked.value !== "__other__") return checked.value;
        return question.querySelector(".clarification-other-input")?.value.trim() || "";
      });
      if (selected.some((value) => !value)) {
        button.textContent = "请先完成三项选择";
        return;
      }
      state.chat.pendingChoices = selected;
      chatTurn(`我选择了：${selected.join("；")}`);
    };
  });
  stage.querySelectorAll(".clarification-question").forEach((question) => {
    question.querySelectorAll("input[type=radio]").forEach((radio) => {
      radio.onchange = () => {
        const other = question.querySelector(".clarification-other");
        if (!other) return;
        const active = radio.value === "__other__";
        other.hidden = !active;
        const input = other.querySelector("input");
        if (active) input?.focus();
        else if (input) input.value = "";
      };
    });
  });
  if (state.view === "map" || stage.querySelector(".paper-graph")) setupGraphInteractions();
  else stopGraphSimulation();
}

function chatView() {
  const messages = state.chat.messages || [];
  return `<section class="chat-page">
    <div class="chat-intro">
      <span class="history-label">勘文研究助手</span>
      <h2>从一个问题开始，沿证据继续追问</h2>
      <p>我会先检索并组织研究现状，再把论文和可核验关系放回当前 run。你可以继续追问某篇论文、某条分支，或要求重新检索。</p>
    </div>
    <div class="chat-thread">
      ${messages.length ? messages.map((item, index) => chatMessage(item, index)).join("") : `<div class="chat-empty">输入一个科研问题，开始一次可回放的研究对话。</div>`}
    </div>
    <form class="search chat-compose" id="search-form">
      <input name="q" value="" autocomplete="off" placeholder="继续追问论文、证据或研究分支…" />
      <button class="solid" type="submit">发送</button>
    </form>
  </section>`;
}

function conversationHistoryView() {
  if (!state.conversationHistory.length) return `<div class="conversation-history empty">暂时没有已保存的对话。</div>`;
  return `<div class="conversation-history"><div class="conversation-history-title">历史对话</div>
    ${state.conversationHistory.map((item) => `<div class="conversation-row">
      <button class="conversation-open" type="button" data-conversation-run="${esc(item.run_id)}"><strong>${esc(item.title)}</strong><span>${esc(item.message_count)} 条消息 · ${esc(item.updated_at || "时间未知")}</span></button>
      <button class="conversation-delete" type="button" data-conversation-delete="${esc(item.run_id)}" title="只删除对话记录，不删除论文和检索结果">删除</button>
    </div>`).join("")}
  </div>`;
}

function llmErrorText(response) {
  const code = String(response?.error || "");
  const reasons = {
    missing_llm_api_key: "未配置 LLM API 密钥。",
    missing_expanded_query: "模型未给出检索词。",
    invalid_llm_route: "模型返回格式不符合约定。",
    invalid_llm_questions: "澄清问题格式不合规。",
    llm_direct_answer_failed: "直接回答生成失败。",
    llm_overview_failed: "总论生成失败。",
  };
  const extra = reasons[code] || (code.startsWith("llm_request_failed:") ? "无法完成对 DeepSeek 的调用（网络、超时或接口错误）。" : "");
  return extra ? `AI 未生成本轮内容，请重试。${extra}` : "AI 未生成本轮内容，请重试。";
}

function chatMessage(item, messageIndex = 0) {
  if (item.role === "user") return `<div class="chat-message user"><div class="chat-role">你</div><div class="chat-bubble">${esc(item.content)}</div></div>`;
  const response = item.response || {};
  if (response.overview_mode === "llm_error") return `<div class="chat-message assistant"><div class="chat-role">勘文 AI · 服务状态</div><article class="chat-bubble assistant-bubble"><div class="chat-error">${esc(llmErrorText(response))}</div></article></div>`;
  if (response.overview_mode === "clarification") return `<div class="chat-message assistant">
    <div class="chat-role">勘文 AI · 研究范围确认</div>
    <article class="chat-bubble assistant-bubble clarification-bubble">
      <div class="chat-overview">${esc(item.content).replaceAll("\\n", "<br />")}</div>
      <div class="clarification-questions">${(response.clarification_questions || []).map((question, questionIndex) => `<fieldset class="clarification-question"><legend>${questionIndex + 1}. ${esc(question.question)}</legend>${(question.options || []).map((option) => `<label><input type="radio" name="clarification-${questionIndex}" value="${esc(option)}"> ${esc(option)}</label>`).join("")}<label><input type="radio" name="clarification-${questionIndex}" value="__other__"> 其他</label><div class="clarification-other" hidden><input class="clarification-other-input" type="text" maxlength="200" placeholder="请填写你的范围或要求" /></div></fieldset>`).join("")}</div>
      <button class="solid clarification-submit" type="button">提交选择并继续</button>
    </article>
  </div>`;
  if (response.overview_mode === "direct_answer") return `<div class="chat-message assistant direct"><div class="chat-role">勘文 AI · 直接回答</div><article class="chat-bubble assistant-bubble"><div class="chat-overview rich-text">${renderMarkdown(item.content)}</div></article></div>`;
  const papers = response.papers || [];
  return `<div class="chat-message assistant">
    <div class="chat-role">勘文 AI · LLM 生成</div>
    <article class="chat-bubble assistant-bubble">
      <h3>总论概览</h3>
      <div class="chat-overview rich-text">${renderMarkdown(item.content)}</div>
      <h3>本轮相关论文</h3>
      ${response.paper_selection?.retrieval_status === "all_failed" ? `<div class="chat-retrieval-warning">本轮在线检索未成功：${(response.paper_selection.retrieval_failures || []).map((item) => `${esc(labelOf("source", item.source, item.source))}（${esc(labelOf("retrievalStatus", item.status, item.status))}）`).join("、")}。不能据此判断没有相关论文。</div>` : response.paper_selection?.retrieval_status === "partial_failed" ? `<div class="chat-retrieval-warning">部分检索源失败（例如 Semantic Scholar 限流）；成功源返回的论文仍可使用，以下结果不是完整召回。本轮仅为摘要筛选，主问题不会被自动标为已支持。</div>` : ""}
      <div class="chat-result-note">${esc(response.paper_selection?.message || "仅显示本轮问题匹配的论文。")}${response.paper_selection ? ` 本轮展示 ${esc(response.paper_selection.matched_count)} 篇 · 在线新增 ${esc(response.paper_selection.added_count)} 篇 · 审计 run 共 ${esc(response.paper_selection.total_run_count)} 篇。` : ""}</div>
      <div class="chat-papers">${papers.length ? papers.map(chatPaper).join("") : "<span class=\"muted\">本轮没有匹配到足够相关的论文。</span>"}</div>
      <h3>研究地图</h3>
      <div class="chat-map">${response.map?.nodes?.length ? mapView(response.map, { embed: true, graphId: `chat-map-${messageIndex}` }) : "当前结果尚未形成结构化关系图。"}</div>
      <h3>后续核验模块</h3>
      <div class="chat-actions">${(response.actions || []).filter((action) => ["evidence", "falsify", "eval"].includes(action.kind)).map((action) => `<button class="chat-action" type="button" data-chat-action="${esc(action.kind)}"><strong>${esc(action.label)}</strong><span>原有页面保留 · 本轮不展开</span></button>`).join("")}</div>
    </article>
  </div>`;
}

function chatPaper(paper) {
  return `<button class="chat-paper" type="button" data-chat-paper="${esc(paper.paper_id)}">
    <span class="stamps">${stamp(paper.decision, labelOf("decision", paper.decision))} ${stamp(paper.parse_status || "info", labelOf("parse", paper.parse_status, "摘要级结果"))}</span>
    <strong>${esc(paper.title)}</strong>
    <span class="tiny">${esc(paper.year || "—")} · ${esc(paper.reason || "当前候选论文")}</span>
  </button>`;
}

async function chatTurn(message) {
  const input = document.querySelector("#search-form input[name=q]");
  const button = document.querySelector("#search-form .solid");
  if (!message) return;
  state.question = message;
  state.chat.messages.push({ role: "user", content: message });
  const conversationBeforeRunChange = state.chat.messages.slice();
  if (input) input.value = "";
  if (button) { button.disabled = true; button.textContent = "研究中…"; }
  paint();
  const requestedRunId = state.chatNew ? null : state.runId || null;
  try {
    const result = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, run_id: requestedRunId, conversation_context: conversationBeforeRunChange.slice(0, -1), clarification_context: state.chat.pendingChoices || [], clarification_topic: state.chat.pendingTopic || null }) });
    state.chat.messages.push({ role: "assistant", content: result.response.overview, response: result.response });
    if (result.status === "needs_clarification") {
      state.chat.pendingTopic = message;
      state.chat.pendingChoices = [];
      state.chat.messages[state.chat.messages.length - 1].response.clarification_questions = result.response.clarification_questions || [];
      paint();
      return;
    }
    if (result.status === "llm_unavailable") {
      paint();
      return;
    }
    if (result.run_id) {
      state.runId = result.run_id;
      state.chatNew = false;
      state.chat.pendingChoices = [];
      state.chat.pendingTopic = "";
      const listing = await api("/api/runs");
      state.runs = listing.runs || state.runs;
      await refreshConversations();
      await loadRun(result.run_id, false);
      const persisted = state.chat.messages || [];
      const seen = new Set(persisted.map((item) => `${item.role}\u0000${item.content}`));
      state.chat.messages = conversationBeforeRunChange.filter((item) => {
        const key = `${item.role}\u0000${item.content}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      }).concat(persisted);
      paint();
      return;
    }
    if (result.status === "completed" && ["direct_answer", "llm_error"].includes(result.response?.overview_mode)) {
      paint();
      return;
    }
    throw new Error("服务未返回可回放的研究结果");
  } catch (error) {
    state.chat.messages.push({ role: "assistant", content: `对话失败：${error.message}`, response: { overview_mode: "error" } });
    paint();
  } finally {
    const current = document.querySelector("#search-form .solid");
    if (current) { current.disabled = false; current.textContent = "发送"; }
  }
}

function retrievalFailureCount() {
  const summary = state.data.retrieval_summary;
  if (summary && typeof summary.round_failure_count === "number") return summary.round_failure_count;
  return state.data.stats?.retrieval_failure_count ?? 0;
}

function retrievalRoundRuns() {
  const summary = state.data.retrieval_summary;
  if (summary?.round_runs?.length) return summary.round_runs;
  return state.data.retrieval_runs || [];
}

function retrievalHistoryRuns() {
  return state.data.retrieval_summary?.history_runs || [];
}

function retrievalStatusLabel(run) {
  if (run.status_label) return run.status_label;
  if (run.http_status === 429) return "文献库暂时限流";
  return labelOf("retrievalStatus", run.status, run.status);
}

function retrievalNote(run) {
  if (run.note_text) return run.note_text;
  if (run.http_status === 429) return "未取得结果，不能当成零篇成功。";
  return run.notes || "";
}

function retrievalTableRows(runs) {
  return runs
    .map((run) => {
      const fail = run.http_status === 429 || run.status !== "success";
      return `<tr class="${fail ? "fail" : ""}">
        <td>${esc(labelOf("source", run.source, run.source))}</td>
        <td>${esc(retrievalStatusLabel(run))}</td>
        <td>${esc(run.result_count ?? "—")}</td>
        <td>${esc(retrievalNote(run))}</td>
      </tr>`;
    })
    .join("");
}

function funnelView() {
  const { stats, papers, screening } = state.data;
  const roundRuns = retrievalRoundRuns();
  const historyRuns = retrievalHistoryRuns();
  const hints = state.data.retrieval_summary?.hints || [];
  const counts = stats.decision_counts || {};
  const hits = hitIds();
  const include = papers.filter((item) => item.decision === "include");
  const pending = papers.filter((item) => item.decision === "pending");
  const exclude = papers.filter((item) => item.decision === "exclude");
  return `
    <p class="view-hint">先筛哪些论文该看：纳入、排除与待定都会保留，方便后续查证据和反证。</p>
    ${hints.length ? `<div class="banner">${hints.map((item) => esc(item)).join("<br />")}</div>` : ""}
    <div class="metrics">
      ${metric("候选论文", stats.paper_count, "")}
      ${metric("纳入", counts.include, "include")}
      ${metric("排除", counts.exclude, "exclude")}
      ${metric("待定", counts.pending, "pending")}
      ${metric("本轮检索异常", retrievalFailureCount(), "warn")}
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
    <details open>
      <summary>本轮检索（${roundRuns.length} 条）</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>来源</th><th>结果</th><th>篇数</th><th>说明</th></tr></thead>
          <tbody>${roundRuns.length ? retrievalTableRows(roundRuns) : `<tr><td colspan="4" class="muted">暂无本轮检索记录。</td></tr>`}</tbody>
        </table>
      </div>
    </details>
    ${
      historyRuns.length
        ? `<details>
            <summary>历史检索记录（${historyRuns.length} 条，含金标 run 继承记录）</summary>
            <div class="table-wrap">
              <table>
                <thead><tr><th>来源</th><th>结果</th><th>篇数</th><th>说明</th></tr></thead>
                <tbody>${retrievalTableRows(historyRuns)}</tbody>
              </table>
            </div>
          </details>`
        : ""
    }
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

function getGraphContext(graphId) {
  if (!state.graphLayouts[graphId]) {
    state.graphLayouts[graphId] = { positions: {}, transform: { x: 0, y: 0, scale: 1 }, runId: "" };
  }
  return state.graphLayouts[graphId];
}

function getGraphMap(graphId) {
  if (state.chatGraphMaps[graphId]) return state.chatGraphMaps[graphId];
  return state.data?.map || {};
}

function graphMarkerId(graphId, kind) {
  return `${graphId}-${kind}`;
}

function positionsFor(graphId) {
  return getGraphContext(graphId).positions;
}

function mapView(mapOverride = null, options = {}) {
  const map = mapOverride || state.data?.map || {};
  const embed = Boolean(options.embed);
  const graphId = options.graphId || `map-${state.data?.run_id || "main"}`;
  if (mapOverride) state.chatGraphMaps[graphId] = map;
  const contradiction = (map.contradictions || [])[0];
  const nodes = map.nodes || [];
  const edges = map.edges || [];
  ensureGraphPositions(nodes, map, graphId);
  const selectedEdge = !embed && edges.find((edge, index) => edgeKey(edge, index) === state.selectedEdgeKey);
  const edgeSummary = `${edges.length} 条有向关系`;
  const evidenceEdgeCount = edges.filter((edge) => edge.kind === "evidence_conflict" || edge.kind === "falsification").length;
  const heuristicEdgeCount = edges.length - evidenceEdgeCount;
  const legendBlock = embed
    ? `<div class="graph-legend chat-graph-legend">
        <span class="legend-group"><i class="legend-line heuristic"></i>摘要启发边 ${heuristicEdgeCount}</span>
        <span class="legend-group"><i class="legend-line conflict"></i>证据边 ${evidenceEdgeCount}</span>
      </div>`
    : `<div class="graph-legend">
        <span class="legend-group"><i class="legend-node include"></i>纳入</span>
        <span class="legend-group"><i class="legend-node exclude"></i>排除</span>
        <span class="legend-group"><i class="legend-node pending"></i>待定</span>
        <span class="legend-group"><i class="legend-line conflict"></i>证据冲突</span>
        <span class="legend-group"><i class="legend-line falsification"></i>反证命中</span>
        <span class="legend-group"><i class="legend-line heuristic"></i>摘要启发边</span>
      </div>`;
  return `
    ${embed ? "" : `<p class="view-hint">论文用方框表示；实线为证据/反证边，虚线为摘要级启发边。拖动节点可整理布局，不代表新增证据。</p>`}
    ${
      !embed && contradiction
        ? `<div class="banner pending">
            主问题相关论断仍待核验：${esc(contradiction.claim_text)}<br />
            支持侧：${(contradiction.support_or_context_papers || []).map(titleOf).join(" / ")}
            → 矛盾侧：${(contradiction.contradict_papers || []).map(titleOf).join(" / ")}
          </div>`
        : ""
    }
    <div class="workspace ${embed ? "graph-embed" : ""}">
      <div class="col">
        <div class="graph-toolbar">
          <div class="graph-toolbar-copy">
            <strong>论文关系图</strong>
            <span>${nodes.length} 篇论文 · ${edgeSummary} · 证据边 ${evidenceEdgeCount} · 启发边 ${heuristicEdgeCount}</span>
           </div>
          ${embed ? "" : `<div class="graph-controls">
            <button class="ghost tiny-btn" type="button" data-graph-action="relayout" data-graph-id="${esc(graphId)}">重新布局</button>
            <button class="ghost tiny-btn" type="button" data-graph-action="fit" data-graph-id="${esc(graphId)}">适配视图</button>
            <button class="ghost tiny-btn" type="button" data-graph-action="reset" data-graph-id="${esc(graphId)}">重置位置</button>
          </div>`}
        </div>
        <div class="graph-wrap ${embed ? "graph-wrap-embed" : ""}">
          <svg id="${esc(graphId)}" class="paper-graph ${embed ? "paper-graph-embed" : ""}" data-graph-id="${esc(graphId)}" viewBox="0 0 1200 680" role="img" aria-label="论文关系图">
            <defs>
              <marker id="${graphMarkerId(graphId, "arrow-evidence-conflict")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path class="arrow-head conflict" d="M 0 0 L 10 5 L 0 10 z"></path>
              </marker>
              <marker id="${graphMarkerId(graphId, "arrow-falsification")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path class="arrow-head falsification" d="M 0 0 L 10 5 L 0 10 z"></path>
              </marker>
              <marker id="${graphMarkerId(graphId, "arrow-default")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path class="arrow-head default" d="M 0 0 L 10 5 L 0 10 z"></path>
              </marker>
              <marker id="${graphMarkerId(graphId, "arrow-heuristic")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path class="arrow-head heuristic" d="M 0 0 L 10 5 L 0 10 z"></path>
              </marker>
            </defs>
            <rect class="graph-surface" x="0" y="0" width="1200" height="680"></rect>
            <g class="graph-viewport" data-graph-viewport="${esc(graphId)}">
              <g class="graph-edges">
                ${edges.map((edge, index) => graphEdge(edge, index, nodes, edges, graphId)).join("")}
              </g>
              <g class="graph-nodes">
                ${nodes.map((node) => graphNode(node, nodes, edges, graphId)).join("")}
              </g>
            </g>
          </svg>
          ${embed ? "" : `<div class="graph-hint">拖动画布可平移 · 滚轮可缩放 · 拖动方框整理布局</div>`}
        </div>
        ${legendBlock}
        ${embed ? "" : `<details>
          <summary>关系明细（${edges.length} 条）</summary>
          <div class="edge-list">
            ${edges.map((edge, index) => `<div data-edge="${esc(edgeKey(edge, index))}">${esc(titleOf(edge.source))} → ${esc(titleOf(edge.target))} · ${esc(edgeKindLabel(edge.kind))}</div>`).join("")}
          </div>
        </details>`}
      </div>
      ${!embed && selectedEdge ? relationInspector(selectedEdge) : embed ? "" : inspector()}
    </div>
  `;
}

function edgeKindLabel(kind) {
  if (kind === "evidence_conflict") return "证据冲突";
  if (kind === "falsification") return "反证命中";
  if (kind === "decision_boundary") return "纳入→排除边界";
  if (kind === "track_affinity") return "同主线弱关联";
  if (kind === "pending_review") return "纳入→待定提醒";
  if (kind === "citation") return "引用关系";
  return kind || "关系";
}

function graphEdgeClass(kind) {
  if (kind === "evidence_conflict") return "conflict";
  if (kind === "falsification") return "falsification";
  if (kind === "decision_boundary" || kind === "track_affinity" || kind === "pending_review") return "heuristic";
  return "default";
}

function graphEdgeMarker(kind, graphId = "") {
  const relationClass = graphEdgeClass(kind);
  const prefix = graphId ? `${graphId}-` : "";
  if (relationClass === "conflict") return `${prefix}arrow-evidence-conflict`;
  if (relationClass === "falsification") return `${prefix}arrow-falsification`;
  if (relationClass === "heuristic") return `${prefix}arrow-heuristic`;
  return `${prefix}arrow-default`;
}

function edgeKey(edge, index) {
  return `${edge.source}->${edge.target}:${edge.kind || "relation"}:${edge.claim_id || edge.hit_id || index}`;
}

function shortGraphTitle(title, limit = 25) {
  const clean = String(title || "未命名论文").replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean;
}

function graphStatusLabel(node) {
  const decision = labelOf("decision", node.decision, node.decision);
  const evidenceCount = (node.evidence_status || []).length;
  return `${decision} · ${evidenceCount ? `${evidenceCount} 条证据` : "暂无证据"}`;
}

function graphTrackIndex(node, map) {
  const tracks = map.tracks || [];
  const index = tracks.findIndex((track) => (track.paper_ids || []).includes(node.paper_id));
  return index < 0 ? 0 : index;
}

function seededGraphPosition(node, index, map) {
  const track = graphTrackIndex(node, map);
  const trackItems = (map.tracks || [])[track]?.paper_ids || [];
  const row = Math.max(0, trackItems.indexOf(node.paper_id));
  return {
    x: 130 + track * 310 + (row % 2) * 26,
    y: 110 + Math.floor(row / 2) * 150 + (index % 2) * 12,
  };
}

function ensureGraphPositions(nodes, map, graphId = `map-${state.data?.run_id || "main"}`) {
  const ctx = getGraphContext(graphId);
  const runKey = map.run_id || state.data?.run_id || graphId;
  if (ctx.runId !== runKey) {
    ctx.runId = runKey;
    ctx.positions = {};
    ctx.transform = { x: 0, y: 0, scale: 1 };
    if (!graphId.startsWith("chat-map-")) {
      try {
        ctx.positions = JSON.parse(localStorage.getItem(`litaudit:graph-layout:${runKey}`) || "{}");
      } catch {
        ctx.positions = {};
      }
    }
  }
  nodes.forEach((node, index) => {
    if (!ctx.positions[node.paper_id]) ctx.positions[node.paper_id] = seededGraphPosition(node, index, map);
  });
  if (!graphId.startsWith("chat-map-")) {
    state.graphRunId = runKey;
    state.graphPositions = ctx.positions;
    state.graphTransform = ctx.transform;
    state.activeGraphId = graphId;
  }
}

function graphNode(node, nodes, edges, graphId = state.activeGraphId) {
  const layout = positionsFor(graphId);
  const position = layout[node.paper_id];
  const selected = node.paper_id === state.selectedPaper ? "selected" : "";
  const neighbor = state.selectedEdgeKey && edges.some((edge, index) => {
    if (edgeKey(edge, index) !== state.selectedEdgeKey) return false;
    return edge.source === node.paper_id || edge.target === node.paper_id;
  });
  const faded = state.selectedEdgeKey && !neighbor && node.paper_id !== state.selectedPaper ? "faded" : "";
  const title = shortGraphTitle(node.title);
  const split = title.length > 17 ? [title.slice(0, 17), title.slice(17)] : [title];
  return `<g class="graph-node ${esc(node.decision)} ${selected} ${faded}" data-paper="${esc(node.paper_id)}" transform="translate(${position.x} ${position.y})" tabindex="0" role="button" aria-label="${esc(node.title)}">
    <title>${esc(node.title)} · ${esc(graphStatusLabel(node))}</title>
    <rect width="208" height="88" rx="2"></rect>
    <text class="graph-node-title" x="14" y="25">${split.map((line, index) => `<tspan x="14" dy="${index ? 20 : 0}">${esc(line)}</tspan>`).join("")}</text>
    <text class="graph-node-meta" x="14" y="69">${esc(node.year || "—")} · ${esc(graphStatusLabel(node))}</text>
  </g>`;
}

function graphEdge(edge, index, nodes, edges, graphId = state.activeGraphId) {
  const layout = positionsFor(graphId);
  const source = layout[edge.source] || { x: 100, y: 100 };
  const target = layout[edge.target] || { x: 700, y: 300 };
  const sourceNode = nodes.find((node) => node.paper_id === edge.source);
  const targetNode = nodes.find((node) => node.paper_id === edge.target);
  const selected = edgeKey(edge, index) === state.selectedEdgeKey ? "selected" : "";
  const relationClass = graphEdgeClass(edge.kind);
  const marker = graphEdgeMarker(edge.kind, graphId);
  const parallel = graphParallelRank(edge, index, nodes, edges || []);
  const path = graphEdgePath(source, target, parallel);
  const midpoint = graphEdgeMidpoint(source, target, parallel);
  return `<circle class="graph-edge-hit" data-edge="${esc(edgeKey(edge, index))}" cx="${midpoint.x.toFixed(1)}" cy="${midpoint.y.toFixed(1)}" r="22"></circle><path class="graph-edge ${relationClass} ${selected}" data-edge="${esc(edgeKey(edge, index))}" data-source="${esc(sourceNode?.paper_id || edge.source)}" data-target="${esc(targetNode?.paper_id || edge.target)}" marker-end="url(#${marker})" d="${path}"><title>${esc(edgeKindLabel(edge.kind))}：${esc(titleOf(edge.source))} → ${esc(titleOf(edge.target))}</title></path>`;
}

function graphEdgePath(source, target, index = 0) {
  const sourceCenter = { x: source.x + 104, y: source.y + 44 };
  const targetCenter = { x: target.x + 104, y: target.y + 44 };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const ux = dx / distance;
  const uy = dy / distance;
  const parallelRank = typeof index === "object" ? index.rank : index;
  const parallelCount = typeof index === "object" ? index.count : 1;
  const curve = parallelCount > 1 ? (parallelRank - (parallelCount - 1) / 2) * 76 : 0;
  const control = {
    x: (sourceCenter.x + targetCenter.x) / 2 - uy * curve,
    y: (sourceCenter.y + targetCenter.y) / 2 + ux * curve,
  };
  const start = graphRectangleAnchor(source, { x: control.x - sourceCenter.x, y: control.y - sourceCenter.y });
  const end = graphRectangleAnchor(target, { x: control.x - targetCenter.x, y: control.y - targetCenter.y });
  return `M ${start.x.toFixed(1)} ${start.y.toFixed(1)} Q ${control.x.toFixed(1)} ${control.y.toFixed(1)} ${end.x.toFixed(1)} ${end.y.toFixed(1)}`;
}

function graphRectangleAnchor(position, vector) {
  const center = { x: position.x + 104, y: position.y + 44 };
  const vx = vector.x;
  const vy = vector.y;
  const scaleX = Math.abs(vx) < 0.001 ? Infinity : 98 / Math.abs(vx);
  const scaleY = Math.abs(vy) < 0.001 ? Infinity : 38 / Math.abs(vy);
  const scale = Math.min(scaleX, scaleY);
  return { x: center.x + vx * scale, y: center.y + vy * scale };
}

function graphParallelRank(edge, index, nodes, edges) {
  const group = edges.filter((candidate) => candidate.source === edge.source && candidate.target === edge.target);
  return { rank: Math.max(0, group.indexOf(edge)), count: Math.max(1, group.length) };
}

function graphEdgeMidpoint(source, target, index = 0) {
  const values = graphEdgePath(source, target, index).match(/[-\d.]+/g).map(Number);
  const [startX, startY, controlX, controlY, endX, endY] = values;
  return {
    x: 0.25 * startX + 0.5 * controlX + 0.25 * endX,
    y: 0.25 * startY + 0.5 * controlY + 0.25 * endY,
  };
}

function relationInspector(edge) {
  const claim = state.data.claims.find((item) => item.claim_id === edge.claim_id);
  const hit = state.data.falsification.find((item) => item.hit_id === edge.hit_id);
  return `<aside class="inspector relation-inspector">
    <div class="stamps"><span class="stamp ${esc(edge.kind === "falsification" ? "falsification" : edge.kind === "evidence_conflict" ? "contradicts" : "info")}">${esc(edgeKindLabel(edge.kind))}</span></div>
    <h3>${esc(edgeKindLabel(edge.kind))}</h3>
    <p class="tiny">${esc(titleOf(edge.source))} → ${esc(titleOf(edge.target))}</p>
    ${claim ? `<p><strong>关联论断</strong><br />${esc(claim.text)}</p>` : ""}
    ${edge.evidence_ids?.length ? `<p class="tiny">Evidence：${edge.evidence_ids.map((id) => esc(id)).join("、")}</p>` : ""}
    ${edge.hit_id ? `<p class="tiny">反证命中：${esc(edge.hit_id)} · 威胁 ${esc(hit?.threat || edge.threat || "—")}</p>` : ""}
    <p>${esc(edge.note || (graphEdgeClass(edge.kind) === "heuristic" ? "摘要级启发边，不是页码证据或引用关系。" : "该关系来自当前 run 的结构化记录，不是引用网络推断。"))}</p>
    <details class="tiny"><summary>内部关系编号</summary><p>${esc(edgeKey(edge, state.data.map.edges.indexOf(edge)))}</p></details>
  </aside>`;
}

function stopGraphSimulation() {
  if (state.graphSimulation?.frame) cancelAnimationFrame(state.graphSimulation.frame);
  state.graphSimulation = null;
  state.graphDragging = "";
}

function applyGraphTransform(svg = null, graphId = state.activeGraphId) {
  const targetSvg = svg || document.getElementById(graphId);
  if (!targetSvg) return;
  const ctx = getGraphContext(graphId);
  const viewport = targetSvg.querySelector(`[data-graph-viewport="${graphId}"]`) || targetSvg.querySelector(".graph-viewport");
  if (!viewport) return;
  const transform = ctx.transform;
  viewport.setAttribute("transform", `translate(${transform.x.toFixed(1)} ${transform.y.toFixed(1)}) scale(${transform.scale.toFixed(3)})`);
  if (!svg) {
    state.graphTransform = transform;
  }
}

function updateGraphGeometry(svg = null, graphId = state.activeGraphId) {
  const targetSvg = svg || document.getElementById(graphId);
  if (!targetSvg) return;
  const map = getGraphMap(graphId);
  const nodes = map.nodes || [];
  const edges = map.edges || [];
  const layout = positionsFor(graphId);
  targetSvg.querySelectorAll(".graph-node").forEach((element) => {
    const position = layout[element.dataset.paper];
    if (position) element.setAttribute("transform", `translate(${position.x.toFixed(1)} ${position.y.toFixed(1)})`);
  });
  targetSvg.querySelectorAll(".graph-edge, .graph-edge-hit").forEach((element) => {
    const index = edges.findIndex((edge, edgeIndex) => edgeKey(edge, edgeIndex) === element.dataset.edge);
    if (index < 0) return;
    const edge = edges[index];
    const source = layout[edge.source];
    const target = layout[edge.target];
    if (source && target) {
      const parallel = graphParallelRank(edge, index, nodes, edges);
      if (element.tagName.toLowerCase() === "circle") {
        const midpoint = graphEdgeMidpoint(source, target, parallel);
        element.setAttribute("cx", midpoint.x.toFixed(1));
        element.setAttribute("cy", midpoint.y.toFixed(1));
      } else {
        element.setAttribute("d", graphEdgePath(source, target, parallel));
      }
    }
  });
  applyGraphTransform(targetSvg, graphId);
}

function graphPoint(svg, event, graphId = svg?.dataset?.graphId || state.activeGraphId) {
  const ctx = getGraphContext(graphId);
  const bounds = svg.getBoundingClientRect();
  const canvasX = ((event.clientX - bounds.left) / Math.max(1, bounds.width)) * 1200;
  const canvasY = ((event.clientY - bounds.top) / Math.max(1, bounds.height)) * 680;
  return {
    x: (canvasX - ctx.transform.x) / ctx.transform.scale,
    y: (canvasY - ctx.transform.y) / ctx.transform.scale,
  };
}

function fitGraphFor(svg, graphId, map = getGraphMap(graphId)) {
  const nodes = map.nodes || [];
  if (!nodes.length) return;
  const layout = positionsFor(graphId);
  const positions = nodes.map((node) => layout[node.paper_id]).filter(Boolean);
  if (!positions.length) return;
  const minX = Math.min(...positions.map((position) => position.x));
  const maxX = Math.max(...positions.map((position) => position.x + 208));
  const minY = Math.min(...positions.map((position) => position.y));
  const maxY = Math.max(...positions.map((position) => position.y + 88));
  const width = Math.max(208, maxX - minX);
  const height = Math.max(88, maxY - minY);
  const scale = Math.min(1.05, Math.max(0.55, Math.min(1120 / width, 600 / height)));
  const ctx = getGraphContext(graphId);
  ctx.transform = {
    scale,
    x: (1200 - width * scale) / 2 - minX * scale,
    y: (680 - height * scale) / 2 - minY * scale,
  };
  if (!graphId.startsWith("chat-map-")) state.graphTransform = ctx.transform;
  applyGraphTransform(svg, graphId);
}

function fitGraph() {
  fitGraphFor(document.getElementById(state.activeGraphId), state.activeGraphId);
}

function saveGraphPositions() {
  try {
    localStorage.setItem(`litaudit:graph-layout:${state.graphRunId}`, JSON.stringify(state.graphPositions));
  } catch {
    // Layout persistence is optional; the graph remains usable when storage is unavailable.
  }
}

function resolveGraphCollisions(nodes, positions, fixedId = "", passes = 4) {
  const activeNodes = nodes.filter((node) => positions[node.paper_id]);
  const clamp = (position) => {
    position.x = Math.max(24, Math.min(968, position.x));
    position.y = Math.max(24, Math.min(568, position.y));
  };
  for (let pass = 0; pass < passes; pass += 1) {
    let collisionCount = 0;
    for (let leftIndex = 0; leftIndex < activeNodes.length; leftIndex += 1) {
      const left = activeNodes[leftIndex];
      const leftPosition = positions[left.paper_id];
      for (let rightIndex = leftIndex + 1; rightIndex < activeNodes.length; rightIndex += 1) {
        const right = activeNodes[rightIndex];
        const rightPosition = positions[right.paper_id];
        const dx = rightPosition.x - leftPosition.x;
        const dy = rightPosition.y - leftPosition.y;
        const overlapX = 224 - Math.abs(dx);
        const overlapY = 104 - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        collisionCount += 1;
        const leftFixed = left.paper_id === fixedId;
        const rightFixed = right.paper_id === fixedId;
        const split = leftFixed || rightFixed ? 1 : 0.5;
        if (overlapX / 224 < overlapY / 104) {
          const direction = Math.sign(dx) || (leftIndex % 2 ? 1 : -1);
          const correction = overlapX + 2;
          if (!leftFixed) leftPosition.x -= direction * correction * split;
          if (!rightFixed) rightPosition.x += direction * correction * split;
        } else {
          const direction = Math.sign(dy) || (rightIndex % 2 ? 1 : -1);
          const correction = overlapY + 2;
          if (!leftFixed) leftPosition.y -= direction * correction * split;
          if (!rightFixed) rightPosition.y += direction * correction * split;
        }
        clamp(leftPosition);
        clamp(rightPosition);
      }
    }
    if (!collisionCount) break;
  }
}

function startGraphSimulation(nodes, edges, svg, graphId) {
  stopGraphSimulation();
  const layout = positionsFor(graphId);
  const velocities = Object.fromEntries(nodes.map((node) => [node.paper_id, { x: 0, y: 0 }]));
  const simulation = { nodes, edges, velocities, frame: 0, ticks: 0, svg, graphId };
  state.graphSimulation = simulation;
  const tick = () => {
    if (state.graphSimulation !== simulation || !document.getElementById(graphId)) return;
    const positions = layout;
    const activeNodes = nodes.filter((node) => node.paper_id !== state.graphDragging);
    for (let leftIndex = 0; leftIndex < activeNodes.length; leftIndex += 1) {
      const left = activeNodes[leftIndex];
      const leftPosition = positions[left.paper_id];
      const leftVelocity = velocities[left.paper_id];
      for (let rightIndex = leftIndex + 1; rightIndex < activeNodes.length; rightIndex += 1) {
        const right = activeNodes[rightIndex];
        const rightPosition = positions[right.paper_id];
        const rightVelocity = velocities[right.paper_id];
        const dx = rightPosition.x - leftPosition.x;
        const dy = rightPosition.y - leftPosition.y;
        const distance = Math.max(30, Math.hypot(dx, dy));
        const force = Math.min(2.5, 4200 / (distance * distance));
        const ux = dx / distance || (leftIndex % 2 ? 1 : -1);
        const uy = dy / distance || (rightIndex % 2 ? 1 : -1);
        leftVelocity.x -= ux * force;
        leftVelocity.y -= uy * force;
        rightVelocity.x += ux * force;
        rightVelocity.y += uy * force;

        // Keep the actual rectangular paper cards apart, not only their centers.
        const overlapX = 224 - Math.abs(dx);
        const overlapY = 104 - Math.abs(dy);
        if (overlapX > 0 && overlapY > 0) {
          if (overlapX < overlapY) {
            const direction = Math.sign(dx) || (leftIndex % 2 ? 1 : -1);
            const push = Math.min(4, overlapX * 0.12) * direction;
            leftVelocity.x -= push;
            rightVelocity.x += push;
          } else {
            const direction = Math.sign(dy) || (rightIndex % 2 ? 1 : -1);
            const push = Math.min(4, overlapY * 0.12) * direction;
            leftVelocity.y -= push;
            rightVelocity.y += push;
          }
        }
      }
    }
    edges.forEach((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      const sourceVelocity = velocities[edge.source];
      const targetVelocity = velocities[edge.target];
      if (!source || !target || !sourceVelocity || !targetVelocity) return;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const force = Math.max(-1.2, Math.min(1.2, (distance - 300) * 0.0014));
      const ux = dx / distance;
      const uy = dy / distance;
      if (edge.source !== state.graphDragging) {
        sourceVelocity.x += ux * force;
        sourceVelocity.y += uy * force;
      }
      if (edge.target !== state.graphDragging) {
        targetVelocity.x -= ux * force;
        targetVelocity.y -= uy * force;
      }
    });
    activeNodes.forEach((node) => {
      const position = positions[node.paper_id];
      const velocity = velocities[node.paper_id];
      velocity.x += (600 - position.x) * 0.00018;
      velocity.y += (340 - position.y) * 0.00018;
      velocity.x *= 0.91;
      velocity.y *= 0.91;
      position.x = Math.max(24, Math.min(968, position.x + velocity.x));
      position.y = Math.max(24, Math.min(568, position.y + velocity.y));
    });
    resolveGraphCollisions(nodes, positions, state.graphDragging, 5);
    updateGraphGeometry(svg, graphId);
    simulation.ticks += 1;
    if (simulation.ticks < 220) simulation.frame = requestAnimationFrame(tick);
    else {
      resolveGraphCollisions(nodes, positions, state.graphDragging, 40);
      updateGraphGeometry(svg, graphId);
      simulation.frame = 0;
      if (!graphId.startsWith("chat-map-")) {
        state.graphPositions = layout;
        saveGraphPositions();
      }
    }
  };
  simulation.frame = requestAnimationFrame(tick);
}

function setupSingleGraph(svg) {
  const graphId = svg.dataset.graphId || svg.id;
  const map = getGraphMap(graphId);
  const nodes = map.nodes || [];
  const edges = map.edges || [];
  state.activeGraphId = graphId;
  state.graphPositions = positionsFor(graphId);
  state.graphTransform = getGraphContext(graphId).transform;
  applyGraphTransform(svg, graphId);
  if (graphId.startsWith("chat-map-")) {
    fitGraphFor(svg, graphId, map);
    return;
  }
  startGraphSimulation(nodes, edges, svg, graphId);

  let pan = null;
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const ctx = getGraphContext(graphId);
    const factor = event.deltaY < 0 ? 1.08 : 0.92;
    const previousScale = ctx.transform.scale;
    const nextScale = Math.max(0.45, Math.min(1.8, previousScale * factor));
    const point = graphPoint(svg, event, graphId);
    ctx.transform.scale = nextScale;
    ctx.transform.x += point.x * (previousScale - nextScale);
    ctx.transform.y += point.y * (previousScale - nextScale);
    if (!graphId.startsWith("chat-map-")) state.graphTransform = ctx.transform;
    applyGraphTransform(svg, graphId);
  }, { passive: false });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".graph-node") || event.target.closest(".graph-edge, .graph-edge-hit")) return;
    pan = { x: event.clientX, y: event.clientY, transform: { ...getGraphContext(graphId).transform } };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!pan) return;
    const ctx = getGraphContext(graphId);
    const bounds = svg.getBoundingClientRect();
    const factor = 1200 / Math.max(1, bounds.width);
    ctx.transform.x = pan.transform.x + (event.clientX - pan.x) * factor;
    ctx.transform.y = pan.transform.y + (event.clientY - pan.y) * factor;
    if (!graphId.startsWith("chat-map-")) state.graphTransform = ctx.transform;
    applyGraphTransform(svg, graphId);
  });
  svg.addEventListener("pointerup", () => { pan = null; });

  svg.querySelectorAll(".graph-node").forEach((nodeElement) => {
    let drag = null;
    nodeElement.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      const point = graphPoint(svg, event, graphId);
      const position = positionsFor(graphId)[nodeElement.dataset.paper];
      drag = { offsetX: point.x - position.x, offsetY: point.y - position.y, moved: false };
      state.graphDragging = nodeElement.dataset.paper;
      nodeElement.classList.add("dragging");
      nodeElement.setPointerCapture(event.pointerId);
    });
    nodeElement.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const point = graphPoint(svg, event, graphId);
      const position = positionsFor(graphId)[nodeElement.dataset.paper];
      position.x = Math.max(24, Math.min(968, point.x - drag.offsetX));
      position.y = Math.max(24, Math.min(568, point.y - drag.offsetY));
      drag.moved = true;
      updateGraphGeometry(svg, graphId);
    });
    nodeElement.addEventListener("pointerup", () => {
      if (!drag) return;
      if (drag.moved) {
        nodeElement.dataset.dragged = "true";
        window.setTimeout(() => delete nodeElement.dataset.dragged, 0);
        if (!graphId.startsWith("chat-map-")) {
          state.graphPositions = positionsFor(graphId);
          saveGraphPositions();
        }
      }
      drag = null;
      state.graphDragging = "";
      nodeElement.classList.remove("dragging");
    });
    nodeElement.onclick = (event) => {
      event.stopPropagation();
      if (nodeElement.dataset.dragged === "true") return;
      state.selectedPaper = nodeElement.dataset.paper;
      state.selectedEdgeKey = "";
      renderView();
    };
    nodeElement.onkeydown = (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      state.selectedPaper = nodeElement.dataset.paper;
      state.selectedEdgeKey = "";
      renderView();
    };
  });
  svg.querySelectorAll(".graph-edge, .graph-edge-hit").forEach((edgeElement) => {
    edgeElement.onclick = (event) => {
      event.stopPropagation();
      state.selectedEdgeKey = edgeElement.dataset.edge;
      renderView();
    };
  });
}

function setupGraphInteractions() {
  stopGraphSimulation();
  document.getElementById("stage")?.querySelectorAll("svg.paper-graph").forEach((svg) => setupSingleGraph(svg));
  document.querySelectorAll("[data-graph-action]").forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.graphAction;
      const targetGraphId = button.dataset.graphId || state.activeGraphId;
      const map = getGraphMap(targetGraphId);
      const nodes = map.nodes || [];
      if (action === "relayout") {
        getGraphContext(targetGraphId).positions = {};
        try {
          localStorage.removeItem(`litaudit:graph-layout:${state.graphRunId}`);
        } catch {
          // Ignore storage errors; relayout still works for the current page.
        }
        ensureGraphPositions(nodes, map, targetGraphId);
        getGraphContext(targetGraphId).transform = { x: 0, y: 0, scale: 1 };
        renderView();
      } else if (action === "fit") {
        state.activeGraphId = targetGraphId;
        fitGraphFor(document.getElementById(targetGraphId), targetGraphId, map);
      } else if (action === "reset") {
        getGraphContext(targetGraphId).positions = {};
        getGraphContext(targetGraphId).transform = { x: 0, y: 0, scale: 1 };
        try {
          localStorage.removeItem(`litaudit:graph-layout:${state.graphRunId}`);
        } catch {
          // Ignore storage errors; the reset is still visible in this render.
        }
        renderView();
      }
    };
  });
  document.querySelectorAll(".edge-list [data-edge]").forEach((edgeElement) => {
    edgeElement.onclick = () => {
      state.selectedEdgeKey = edgeElement.dataset.edge;
      renderView();
    };
  });
}

function evidenceView() {
  const { claims, evidence, claim_decisions: decisions } = scopedAuditData();
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
  const hits = scopedAuditData().falsification || [];
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
  const metrics = scopedAuditData().eval || {};
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

async function loadRun(runId, repaint = true) {
  state.runId = runId;
  state.data = await api(`/api/run/${encodeURIComponent(runId)}`);
  try {
    const conversation = await api(`/api/chat/${encodeURIComponent(runId)}`);
    state.chat = { messages: conversation.messages || [], pendingChoices: [], pendingTopic: "" };
  } catch {
    state.chat = { messages: [] };
  }
  const url = new URL(location.href);
  url.searchParams.set("run", runId);
  history.replaceState({}, "", url);
  if (repaint) paint();
}

async function boot() {
  const [listing] = await Promise.all([api("/api/runs"), refreshConversations()]);
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
  state.view = new URLSearchParams(location.search).get("view") || state.view;
  await loadRun(preferred);
}

boot().catch((error) => {
  document.getElementById("boot").textContent = `打开失败：${error.message}`;
});
