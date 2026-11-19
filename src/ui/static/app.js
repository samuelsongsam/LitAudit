const VIEWS = [
  ["chat", "00", "研究概览", "与研究助手连续探索"],
  ["funnel", "01", "检索与筛选", "先看候选与筛选理由"],
  ["fulltext", "02", "全文搜索", "在当前论文正文中继续查找"],
  ["methods", "03", "方法对比", "对照方法与原文依据"],
  ["map", "04", "研究地图", "按主线查看冲突关系"],
  ["evidence", "05", "证据核验", "论断与原文摘录"],
  ["falsify", "06", "反证检查", "召回可能的风险论文"],
  ["eval", "07", "可追溯性评测", "对照无检索基线"],
  ["report", "08", "研究报告", "保存研究与方法对比结果"],
  ["library", "09", "阅读清单", "收藏、笔记与参考文献"],
];

const ONLINE_SEARCH_SOURCES = ['arxiv', 'openalex'];

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
  chat: { messages: [], pendingTopic: "" },
  chatNew: false,
  conversationHistory: [],
  historyOpen: false,
  sidebarOpen: false,
  methodFieldsExpanded: false,
  composeDrafts: {},
  panelStates: {},
  renderedPanelKey: '',
  workspacePositions: {},
  context: null,
  contextRequest: 0,
  contextReturnFocus: null,
  mapContext: null,
  historyCollapsed: false,
  pageTexts: {},
  readingPages: {},
  acquisitionIssues: new Map(),
  acquisitionTasks: new Map(),
  contextQuestions: new Map(),
  contextCitations: new Map(),
  mapTopicRefresh: new Map(),
  sources: {result:null,loading:false,testing:''},
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
  chatKey: "initial",
  draftCounter: 0,
  loadToken: 0,
  requestCounter: 0,
  chatTasks: {},
  lastFailedTask: null,
  backgroundNotice: null,
  fulltext: { query: "", paperId: "", section: "", result: null, loading: false, error: "" },
  methods: { result: null, selected: [], loading: false, error: "" },
  reviewMessage: "",
  mapRetry: { runId: "", loading: false, error: "" },
  constraints: { year_from: "", year_to: "", research_object: "", method: "", publication_type: "any" },
  resources: { data: "", compute: "", time: "" },
  queryPlan: null,
  capabilities: null,
  library: { result: null, loading: false, error: "" },
  guidance: null,
  toolsNotice: "",
  pendingTasks: {},
  readingMode: false,
  readingPaperId: "auto",
  searchSupplement: false,
  taskHistory: [],
  taskHistoryLoaded: false,
  taskHistoryLoading: false,
  taskHistoryError: "",
  formDrafts: null,
  workspaceId: "session-"+Math.random().toString(36).slice(2),
};

function emptyWorkspace() {
  return { papers: [], claims: [], evidence: [], screening: [], falsification: [],
    retrieval_runs: [], stats: {}, workspace: {}, map: {}, offline: true };
}

function activeChatTask() { return state.chatTasks[state.chatKey] || null; }

function formDrafts() {
  if (state.formDrafts) return state.formDrafts;
  try { const value=JSON.parse(sessionStorage.getItem('litaudit-form-drafts-v1')||'{}');state.formDrafts=value&&typeof value==='object'&&!Array.isArray(value)?value:{}; }
  catch { state.formDrafts={}; }
  return state.formDrafts;
}

function draftKey(type,paperId='',passageId='',field='') {
  return JSON.stringify([state.workspaceId,state.runId||'new-research',type,paperId,passageId,field]);
}

function getFormDraft(type,paperId='',passageId='',field='') {
  return formDrafts()[draftKey(type,paperId,passageId,field)]?.values||null;
}

function persistFormDrafts() {
  try { sessionStorage.setItem('litaudit-form-drafts-v1',JSON.stringify(formDrafts()));state.draftStorageError=false; }
  catch { state.draftStorageError=true; }
}

function rememberFormDraft(type,paperId,passageId,field,values) {
  const drafts=formDrafts();drafts[draftKey(type,paperId,passageId,field)]={values,updatedAt:Date.now()};
  persistFormDrafts();
}

function clearFormDraft(type,paperId='',passageId='',field='',runId=state.runId) {
  delete formDrafts()[JSON.stringify([state.workspaceId,runId||'new-research',type,paperId,passageId,field])];persistFormDrafts();
}

function copyFormDraftsToRun(fromRun,toRun) {
  if(fromRun===toRun)return;
  for(const [key,value] of Object.entries(formDrafts())) {
    try {const parts=JSON.parse(key);if(parts[0]===state.workspaceId&&parts[1]===fromRun){parts[1]=toRun;formDrafts()[JSON.stringify(parts)]={...value,values:{...value.values}};}} catch {}
  }
  persistFormDrafts();
}

function bindFormDrafts(stage) {
  stage.querySelectorAll('form[data-library-form],form[data-review-form]').forEach(form=>{
    const library=form.hasAttribute('data-library-form');
    const save=()=>{const values=new FormData(form);const draft=library?
      {favorite:values.get('favorite')==='on',reading_status:values.get('reading_status'),tags:String(values.get('tags')||'').split(/[,，]/).map(v=>v.trim()).filter(Boolean),notes:String(values.get('notes')||'')}:
      {status:values.get('status'),claim:String(values.get('claim')||''),display_value:String(values.get('display_value')||''),note:String(values.get('note')||'')};
      if(!library){draft.source_text_sha256=form.dataset.textHash;draft.source_quote=form.dataset.quote||'';}
      rememberFormDraft(library?'library':'review',form.dataset.paperId,library?'':form.dataset.passageId,library?'':form.dataset.field||'',draft);
      let notice=form.querySelector('[data-draft-notice]');if(!notice){notice=document.createElement('p');notice.dataset.draftNotice='';notice.className='tiny';form.appendChild(notice);}notice.textContent=state.draftStorageError?'草稿暂存于当前页面，浏览器存储不可用，请及时保存。':'草稿已暂存于当前浏览器；点击保存后写入研究记录。';};
    form.oninput=save;form.onchange=save;
  });
}

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

async function api(path, options, onProgress) {
  const longTask = options?.method === "POST" && (["/api/chat", "/api/search", "/api/live", "/api/fulltext/search", "/api/audit/upgrade", "/api/import/pdf", "/api/research/related", "/api/research/search-more", "/api/map-topics/refresh"].includes(path)||/^\/api\/tasks\/[^/]+\/retry$/.test(path));
  const config = longTask ? {...options, headers: {...(options.headers || {}), Prefer: "respond-async"}} : options;
  const response = await fetch(path, config);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} ${response.status}`);
  if (response.status === 202 && data.task_id) {
    const id=data.task_id;state.pendingTasks[id]={task_id:id,stage:"queued",status:data.status||"queued"};
    const stop=()=>{fetch(`/api/tasks/${encodeURIComponent(id)}`,{method:"DELETE"}).catch(()=>{});};
    const signal=options?.signal;
    if(signal?.aborted)stop();
    else signal?.addEventListener("abort",stop,{once:true});
    try {
      onProgress?.(state.pendingTasks[id]);
      for (;;) {
        signal?.throwIfAborted();
        await new Promise(resolve=>setTimeout(resolve,750));
        const progress=await fetch(`/api/tasks/${encodeURIComponent(id)}`,{signal});
        const job=await progress.json();if(!progress.ok)throw new Error(job.error||"任务状态读取失败");
        state.pendingTasks[id]=job;
        if(onProgress)onProgress(job);
        else document.querySelectorAll('[data-server-progress]').forEach(n=>{n.textContent=taskStageLabel(job.stage);});
        if(job.status==='completed')return job.result;
        if(['failed','cancelled','interrupted'].includes(job.status))throw new Error(job.error||"任务已停止");
      }
    } finally {delete state.pendingTasks[id];signal?.removeEventListener("abort",stop);}
  }
  return data;
}

function taskStageLabel(stage) {
  if(stage==='provider_wait')return '等待文献来源';
  if(stage==='map_topics')return '理解研究主题';
  if(stage==='map_topics_generate')return '根据论文整理主题';
  if(stage==='map_topics_retry')return '核对并调整主题说明';
  if(stage==='fulltext_prepare')return '准备全文获取';
  if(stage==='fulltext_download')return '连接来源并下载 PDF';
  if(stage==='fulltext_extract')return '提取 PDF 正文';
  if(stage==='fulltext_save')return '保存正文和页码';
  if(stage==='citation_lookup')return '在 OpenAlex 定位论文';
  if(stage==='citation_fetch')return '从 OpenAlex 获取引文';
  if(stage==='citation_save')return '保存引文和论文记录';
  if(stage==='method_evidence')return '从正文定位方法和实验依据';
  if(stage==='agenda_draft')return '拟定可验证的研究问题';
  if(stage==='agenda_repair')return '根据文献依据调整研究方案';
  if(stage==='answer_revision')return '根据原文调整回答';
  if(['fulltext_search','fulltext_subquestions'].includes(stage))return stage==='fulltext_search'?'检索当前正文':'逐项查找问题依据';
  return ({queued:'任务排队中',starting:'任务开始',understand:'理解研究问题',load_data:'准备研究记录',retrieval:'检索论文来源',fulltext:'处理全文与定位',map:'组织研究地图',answer:'组织有依据的回答',semantic_review:'复核中文解读与原文',search_fulltext:'检索正文片段',citation_discovery:'查找引用关系',import_pdf:'导入与解析PDF',finished:'处理完成'})[stage]||stage||'处理中';
}

function searchSupplementOptions() {
  return state.searchSupplement?{pages_per_query:1,max_requests:4,sources:ONLINE_SEARCH_SOURCES}:undefined;
}

function taskHistoryView() {
  const statuses={queued:'排队中',running:'进行中',cancel_requested:'等待安全停止',cancelled:'已停止',failed:'失败',interrupted:'服务中断',completed:'已完成'};
  const names={'/api/chat':'论文问答','/api/search':'文献检索','/api/live':'文献检索','/api/fulltext/search':'正文搜索','/api/audit/upgrade':'全文获取','/api/research/related':'引文探索','/api/research/search-more':'补充检索','/api/import/pdf':'PDF导入','/api/map-topics/refresh':'整理主题'};
  return `<details data-panel="tasks" class="task-history" ${state.taskHistoryOpen?'open':''}><summary>后台任务与失败重试</summary><p>失败、停止或服务中断后，可用已保存的输入重新执行；原任务记录保留。PDF导入需重新选择文件。</p><button type="button" class="ghost" data-load-task-history ${state.taskHistoryLoading?'disabled':''}>${state.taskHistoryLoading?'正在载入…':'刷新任务记录'}</button>${state.taskHistoryError?`<p role="alert">${esc(state.taskHistoryError)}</p>`:''}${state.taskHistory.slice(0,10).map(job=>`<article><strong>${esc(names[job.operation]||'研究任务')}</strong> · ${esc(statuses[job.status]||job.status)}<p class="tiny">${esc(job.created_at?new Date(job.created_at).toLocaleString('zh-CN',{hour12:false}):'')}${job.run_id?` · ${esc(runById(job.run_id)?.label||job.run_id)}`:''}</p>${job.error?`<p>${esc(job.error)}</p>`:''}${job.can_retry?`<button type="button" class="ghost" data-retry-background-task="${esc(job.task_id)}">重新执行此任务</button>`:''}${job.run_id?`<a href="/?run=${encodeURIComponent(job.run_id)}">查看已保存研究</a>`:''}</article>`).join('')}${state.taskHistoryLoaded&&!state.taskHistory.length?'<p>当前没有后台任务记录。</p>':''}</details>`;
}

async function loadTaskHistory() {
  if(state.taskHistoryLoading)return;
  state.taskHistoryLoading=true;state.taskHistoryOpen=true;state.taskHistoryError='';paint();
  try{const result=await api('/api/tasks');state.taskHistory=result.tasks||[];state.taskHistoryLoaded=true;}
  catch(error){state.taskHistoryError=error.message;}
  finally{state.taskHistoryLoading=false;paint();}
}

function researchConditionsView() {
  const c=state.constraints;const maxYear=new Date().getFullYear()+1;
  return `<details data-panel="search" class="research-conditions" data-chat-tool="search"><summary>检索条件</summary><div class="conditions-grid">
    <label>起始年份<input type="number" min="1800" max="${maxYear}" data-constraint="year_from" value="${esc(c.year_from)}" placeholder="不限"/></label>
    <label>截止年份<input type="number" min="1800" max="${maxYear}" data-constraint="year_to" value="${esc(c.year_to)}" placeholder="不限"/></label></div>
    <details data-panel="advanced-search" class="advanced-search-options"><summary>指定研究对象、方法或文献类型</summary><div class="conditions-grid">
    <label>研究对象<input data-constraint="research_object" value="${esc(c.research_object)}" maxlength="300" placeholder="例如医学影像"/></label>
    <label>指定方法<input data-constraint="method" value="${esc(c.method)}" maxlength="300" placeholder="例如LoRA"/></label>
    <label>文献类型<select data-constraint="publication_type">${Object.entries({any:'不限',journal:'期刊',conference:'会议',preprint:'预印本',review:'综述'}).map(([k,v])=>`<option value="${k}" ${c.publication_type===k?'selected':''}>${v}</option>`).join('')}</select></label></div>
    <label class="search-budget"><input type="checkbox" data-search-supplement ${state.searchSupplement?'checked':''}/> 补查更多结果</label><p class="tiny">对成功来源最多追加4次分页请求，来源失败会单独记录。</p></details>
    <div class="tool-actions"><button class="ghost" type="button" data-preview-plan>查看查询计划</button><button class="solid" type="button" data-direct-search>按条件检索</button></div>
    ${state.queryPlan?`<details data-panel="query-plan" class="query-plan-details"><summary>实际查询</summary><ul class="query-plan">${state.queryPlan.queries.map(q=>`<li><strong>${esc(q.source)}</strong><code>${esc(q.query)}</code></li>`).join('')}</ul></details>`:''}</details>`;
}

function importPdfView() {
  return `<details data-panel="import" class="research-conditions" data-chat-tool="import"><summary>导入论文 PDF</summary><form data-import-pdf>
    <div class="import-grid"><label>选择PDF<input type="file" name="pdf" accept="application/pdf,.pdf" required/><span class="tiny">最多25MB</span></label><label>想了解什么<input name="question" maxlength="2000" placeholder="例如：这篇论文使用了什么方法？"/></label></div>
    <details data-panel="import-metadata" class="import-metadata"><summary>补充题录（可选）</summary><div class="import-grid">
      <label>论文题名<input name="title" maxlength="1000" placeholder="默认使用文件名"/></label><label>作者<input name="authors" maxlength="2000" placeholder="多位作者用分号分隔"/></label><label>发表年份<input name="year" type="number" min="1500" max="${new Date().getFullYear()+1}"/></label>
      <label>DOI或arXiv编号<input name="identifier" maxlength="200"/></label><label>官方来源链接<input name="source_url" type="url" placeholder="https://..."/></label></div></details>
    ${state.runId?'<label class="append-choice"><input type="checkbox" name="append" checked/> 加入当前研究，保存为独立副本</label>':''}<div class="tool-actions"><button class="solid" type="submit">导入并开始阅读</button></div></form></details>`;
}

function setupStatusView() {
  const c=state.capabilities;if(!c)return '';
  const llm=c.llm_configured ?? c.llm?.configured;
  const model=c.semantic_model?.ready;
  return `<details data-panel="setup" class="setup-status" ${llm?'':'open'}><summary>运行准备：${llm?'对话已配置':'可先导入论文阅读'} · ${model?'语义模型已缓存':'语义模型待准备'}</summary><p>${llm?'当前模型：'+esc(c.llm?.model||'已配置'):'填写项目目录 .env 中的 LITAUDIT_LLM_API_KEY、LITAUDIT_LLM_BASE_URL 和 LITAUDIT_LLM_MODEL，即可启用模型对话。已有全文检索、笔记和导出可独立使用。'}</p>${model?'':'<code>python -m src.cli download-model</code>'}</details>`;
}

function resourceConditionsView() {
  return `<details class="research-conditions"><summary>我的数据、算力和时间条件</summary><div class="conditions-grid">${Object.entries({data:'数据与样本',compute:'设备与算力',time:'时间安排'}).map(([k,v])=>`<label>${v}<textarea data-resource="${k}" maxlength="2000" rows="2" placeholder="填写你的实际条件">${esc(state.resources[k])}</textarea></label>`).join('')}</div><button class="ghost" type="button" data-guidance>结合原文检查适用条件</button>${state.guidance?guidanceView(state.guidance):''}</details>`;
}

function resourceAnalysisView(analysis) {
  if(!analysis)return '';
  return `<details class="resource-analysis"><summary>查看资源条件解析${analysis.status==='ambiguous'?' · 需要选择具体配置':''}</summary>${[['reported','论文原文'],['user','你的条件']].map(([key,label])=>`<h4>${label}</h4>${(analysis[key]?.candidates||[]).map(c=>`<p>${c.capacity_gb!=null?`${esc(c.capacity_gb)} GB${c.device_count?` · ${esc(c.device_count)} 台设备`:''}${c.capacity_scope==='per_device'?' · 每台容量':c.capacity_scope==='total'?' · 合计容量':' · 容量口径待核对'}`:c.hours!=null?`${esc(c.hours)} 小时`:''} ${esc((c.model_scales||[]).join('、'))} ${esc({training:'训练',inference:'推理'}[c.phase]||'')}<br/>${esc(c.quote||c.text||'')}</p>`).join('')||'<p>尚无可唯一识别的数值条件。</p>'}`).join('')}</details>`;
}

function guidanceView(data) {
  return `<div class="guidance-list"><p>${esc(data.notice||'')}</p>${(data.suggestions||[]).map(p=>`<article><h3>${esc(p.title)}</h3>${(p.checks||[]).map(c=>`<p><strong>${esc(c.label)}</strong> · 你的条件：${esc(c.user_constraint)}<br/>${esc(c.suggestion)}</p>${c.numeric_comparison?`<p class="tool-notice">${esc(c.numeric_comparison.kind==='reported_run_time'?`原文运行 ${c.numeric_comparison.reported_hours} 小时；你的时间值 ${c.numeric_comparison.user_hours} 小时。`:`原文容量 ${c.numeric_comparison.reported_gb} GB；你的容量 ${c.numeric_comparison.user_gb} GB。`)} ${esc(c.numeric_comparison.scope)}</p>`:''}${resourceAnalysisView(c.resource_analysis)}${(c.sources||[]).map(src=>`<a href="${esc(src.pdf_url)}" target="_blank" rel="noopener">第${src.page}页 · ${esc(src.label)}</a>`).join(' · ')}`).join('')}</article>`).join('')}</div>`;
}

function filteredLibraryItems() {
  const docs=new Set((state.data?.fulltext_audit?.documents||[]).filter(d=>d.status==='parsed').map(d=>d.paper_id));
  const term=(state.librarySearch||'').toLowerCase().trim();const mode=state.libraryFilter||'all';
  return (state.library.result?.items||[]).filter(p=>(mode==='all'||mode==='favorite'&&p.favorite||mode==='fulltext'&&docs.has(p.paper_id)||p.reading_status===mode)&&(!term||[p.title,...(p.tags||[])].join(' ').toLowerCase().includes(term)));
}

function libraryCard(p) {
  const hasFulltext=(state.data?.fulltext_audit?.documents||[]).some(d=>d.paper_id===p.paper_id&&d.status==='parsed');
  const status={unread:'未读',reading:'在读',done:'已读'}[p.reading_status]||'未读';
  return `<article class="library-card"><div class="library-card-head"><div><h3>${esc(p.title)}</h3><p class="library-meta">${esc(p.year||'年份待确认')} · ${status} · ${hasFulltext?'已有全文':'仅题录 / 摘要'}${p.tags?.length?' · '+esc(p.tags.join('、')):''}</p></div><button class="ghost" type="button" data-library-favorite="${esc(p.paper_id)}" aria-pressed="${Boolean(p.favorite)}" aria-label="${p.favorite?'取消收藏':'收藏'} ${esc(p.title)}">${p.favorite?'★ 已收藏':'☆ 收藏'}</button></div>
    ${p.notes?`<p class="library-note-preview">${esc(p.notes)}</p>`:''}<div class="library-card-actions"><button class="ghost" type="button" data-open-paper-text="${esc(p.paper_id)}">${hasFulltext?'阅读与搜索全文':'获取全文'}</button><details class="library-related"><summary>扩展阅读</summary><button class="ghost" type="button" data-related-paper="${esc(p.paper_id)}" data-direction="references">探索参考文献</button><button class="ghost" type="button" data-related-paper="${esc(p.paper_id)}" data-direction="citations">探索后续引用</button></details></div>
    <details data-panel="library-editor:${esc(p.paper_id)}" class="library-editor" ${p.hasDraft?'open':''}><summary>${p.hasDraft?'继续编辑 · 未保存草稿':'笔记与阅读状态'}</summary><form data-library-form data-paper-id="${esc(p.paper_id)}"><input type="hidden" name="favorite" value="${p.favorite?'on':''}"/><div class="conditions-grid"><label>阅读状态<select name="reading_status">${Object.entries({unread:'未读',reading:'在读',done:'已读'}).map(([k,v])=>`<option value="${k}" ${p.reading_status===k?'selected':''}>${v}</option>`).join('')}</select></label><label>标签（逗号分隔）<input name="tags" maxlength="600" value="${esc((p.tags||[]).join(', '))}"/></label></div><label>阅读笔记<textarea name="notes" rows="3" maxlength="20000">${esc(p.notes||'')}</textarea></label><button type="submit" class="solid">保存阅读记录</button>${p.hasDraft?`<p class="tiny" data-draft-notice>已恢复未保存草稿；保存后写入研究记录。</p><button type="button" class="ghost" data-discard-draft="library" data-paper-id="${esc(p.paper_id)}">丢弃此草稿</button>`:''}</form></details>
    <details data-panel="library-metadata:${esc(p.paper_id)}" class="library-metadata"><summary>论文信息</summary><p>${esc((p.authors||[]).join('、')||'作者待确认')}</p><p>${esc(p.venue||'')}${p.doi_or_arxiv?' · '+esc(p.doi_or_arxiv):''}</p>${/^https?:\/\//i.test(p.url||'')?`<a href="${esc(p.url)}" target="_blank" rel="noopener">访问论文来源 ↗</a>`:''}</details></article>`;
}

function libraryView() {
  const data=state.library.result;const items=filteredLibraryItems().map(p=>({...p,...(getFormDraft('library',p.paper_id)||{}),hasDraft:Boolean(getFormDraft('library',p.paper_id))}));
  return `<section class="research-section"><div class="research-heading"><div><h2>阅读清单</h2><p>收藏论文，积累笔记，导出参考文献。</p></div><button type="button" class="ghost" data-load-library>刷新</button></div>${state.library.error?`<p class="banner danger" role="alert">${esc(state.library.error)}</p>`:''}${state.library.notice?`<p class="tool-notice" role="status">${esc(state.library.notice)}</p>`:''}
    <form data-library-filter-form class="library-toolbar"><div class="library-search"><label for="library-search">题名或标签</label><div><input id="library-search" name="search" value="${esc(state.librarySearch||'')}" placeholder="查找论文"/><button class="ghost" type="submit">筛选</button></div></div><label>阅读范围<select name="filter">${Object.entries({all:'全部候选',fulltext:'已有全文',favorite:'已收藏',reading:'在读',done:'已读'}).map(([k,v])=>`<option value="${k}" ${(state.libraryFilter||'all')===k?'selected':''}>${v}</option>`).join('')}</select></label><label>导出格式<select name="export_format">${Object.entries({bibtex:'BibTeX',ris:'RIS',markdown:'Markdown',csv:'CSV'}).map(([k,v])=>`<option value="${k}" ${(state.libraryFormat||'bibtex')===k?'selected':''}>${v}</option>`).join('')}</select></label><button type="button" class="ghost" data-library-export>导出清单</button></form>
    <p class="tiny">当前 ${items.length} 篇 · 导出使用当前筛选结果</p>${state.library.loading?'<p role="status">载入阅读记录…</p>':''}${items.map(libraryCard).join('')}${data&&!items.length?'<div class="research-empty">没有匹配的论文，试着调整题名或阅读范围。</div>':''}${!data&&!state.library.loading?'<button class="solid" data-load-library>载入阅读清单</button>':''}</section>`;
}

async function loadLibrary() {
  if(!state.runId||state.library.loading)return;
  const run=state.runId;state.library.loading=true;state.library.error='';paint();
  try{const data=await api(`/api/library/${encodeURIComponent(run)}`);if(state.runId===run){state.library.result=data;state.library.stale=false;}}
  catch(error){if(state.runId===run)state.library.error=error.message;}
  finally{if(state.runId===run){state.library.loading=false;if(state.view==='library')paint();}}
}

function coverageView() {
  const docs=state.data?.fulltext_audit?.documents||[];if(!docs.length)return '';
  return `<details class="document-coverage"><summary>正文处理覆盖与待处理内容</summary>${docs.map(d=>{const c=d.coverage||{};return `<article><strong>${esc(titleOf(d.paper_id))}</strong><p>${c.page_count??d.page_count??0} 页 · 已提取文本 ${c.text_pages?.length??0} 页 · OCR待处理 ${c.ocr_required_pages?.length??0} 页</p>${(c.ocr_required_pages||[]).length?`<p>待OCR页：${c.ocr_required_pages.join('、')}。可安装Tesseract并配置 LITAUDIT_TESSERACT_CMD。</p>`:''}<p class="tiny">表格与图像检测属于提取/定位状态，公式和图片内容仍需结合原页阅读。</p></article>`;}).join('')}</details>`;
}

function readerDialog(paperId,pageNumber) {
  openReaderContext(paperId,pageNumber);
}

function stamp(kind, label) {
  const text = label ?? labelOf("decision", kind) ?? labelOf("claim", kind) ?? labelOf("parse", kind) ?? kind;
  return `<span class="stamp ${esc(kind)}">${esc(text)}</span>`;
}

function renderShell(options) {
  rememberWorkspacePosition();
  if(state.renderedPanelKey){
    const panels=state.panelStates[state.renderedPanelKey]||{};
    document.querySelectorAll('details[data-panel]').forEach(d=>{panels[d.dataset.panel]=d.open;});
    state.panelStates[state.renderedPanelKey]=panels;
  }
  const data = state.data || emptyWorkspace();
  const workspace = data.workspace || {};
  const parsed = (data.fulltext_audit?.documents || []).filter(d => d.status === "parsed").length;
  const isNew = state.chatNew || !state.runId;
  const title = isNew ? "新研究" : state.conversationHistory.find(c=>c.run_id===state.runId)?.title || data.question || "当前研究";

  document.getElementById("app").innerHTML = `
    <div class="shell ${state.sidebarOpen?'sidebar-open':''} ${state.context?'context-open':''} ${state.historyCollapsed?'history-collapsed':''}">
      <button class="sidebar-backdrop" type="button" data-close-history aria-label="关闭研究记录" tabindex="-1"></button>
      <aside class="rail" id="research-history" aria-label="研究记录">
        <div class="brand">
          <div class="seal">勘</div>
          <div>
            <h1>勘文</h1>
            <small>LITAUDIT</small>
          </div>
        </div>
        <button class="ghost sidebar-close" type="button" data-close-history>关闭记录</button>
        ${sidebarConversations()}
        <div class="rail-footer"><button class="ghost" type="button" data-open-sources>${uiIcon('settings')}<span>检索来源</span></button><button class="icon-button" type="button" data-collapse-history aria-label="收起或展开研究记录">${uiIcon('panel')}</button></div>
      </aside>
      <main class="main">
        <header class="top">
          <div class="workspace-topline"><div class="workspace-heading"><span class="project-kicker">${isNew?'LITAUDIT / 新研究':'LITAUDIT / 研究工作台'}</span><h1 title="${esc(title)}">${esc(title)}</h1><div class="workspace-meta">${isNew?'从问题到文献，再到你的研究判断':`<span>${esc(workspace.visible_paper_count ?? scopedAuditData().papers?.length ?? 0)} 篇论文</span><span>${parsed} 篇全文</span>`}</div></div><div class="workspace-actions"><button class="ghost mobile-history-toggle" type="button" data-toggle-history aria-controls="research-history" aria-expanded="${state.sidebarOpen}">${uiIcon('panel')}研究记录</button><button class="icon-button" type="button" data-open-sources aria-label="检索来源与配置">${uiIcon('settings')}</button>${!isNew?`<button class="ghost" type="button" data-workspace-view="report">${uiIcon('export')}导出</button>`:''}</div></div>
          ${workspaceNavigation()}
          ${state.backgroundNotice ? `<div class="task-notice" role="status">${esc(state.backgroundNotice.text)} ${state.backgroundNotice.runId ? `<button class="ghost" data-open-background="${esc(state.backgroundNotice.runId)}">查看结果</button>` : ""}</div>` : ""}
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
      ${contextPanelView()}
    </div>
  `;

  bindConversationControls(document);
  bindWorkspaceObjectActions(document);
  document.querySelector('[data-collapse-history]').onclick=()=>{state.historyCollapsed=!state.historyCollapsed;document.querySelector('.shell').classList.toggle('history-collapsed',state.historyCollapsed);};
  document.querySelector('[data-toggle-history]').onclick=()=>{state.sidebarOpen=true;paint();document.querySelector('.sidebar-close')?.focus();};
  document.querySelectorAll('[data-close-history]').forEach(b=>b.onclick=()=>{state.sidebarOpen=false;paint();document.querySelector('[data-toggle-history]')?.focus();});
  document.onkeydown=e=>{if(e.key==='Escape'){const menu=document.querySelector('.nav-more');if(menu)menu.open=false;if(state.context)closeWorkspaceContext();else if(state.sidebarOpen){state.sidebarOpen=false;paint();document.querySelector('[data-toggle-history]')?.focus();}}};
  document.onclick=e=>{const menu=document.querySelector('.nav-more');if(menu&&!menu.contains(e.target))menu.open=false;};
  document.querySelectorAll("[data-workspace-view]").forEach(button => button.onclick = () => setView(button.dataset.workspaceView));
  document.querySelectorAll("[data-open-background]").forEach(button => button.onclick = async () => { state.backgroundNotice = null; state.view = "chat"; await loadRun(button.dataset.openBackground, true, true); });
  const backToChat = document.getElementById("back-to-chat");
  if (backToChat) backToChat.onclick = () => setView("chat");
  renderView(options);
  bindContextPanel();
  state.renderedPanelKey=state.chatKey+':'+state.view;
  const panels=state.panelStates[state.renderedPanelKey]||{};
  document.querySelectorAll('details[data-panel]').forEach(d=>{if(Object.hasOwn(panels,d.dataset.panel))d.open=panels[d.dataset.panel];});
  const stage=document.getElementById('stage');if(stage)stage.scrollTop=state.workspacePositions[workspaceKey()]||0;
  const searchForm = document.getElementById("search-form");
  if (searchForm) {
    searchForm.q.oninput=()=>{state.composeDrafts[state.chatKey]=searchForm.q.value;};
    searchForm.onsubmit = async (event) => {
    event.preventDefault();
    const q = event.target.q.value.trim();
    state.question = q;
    if (!q) return;
    delete state.composeDrafts[state.chatKey];
    await chatTurn(q);
  };
  }
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
  if (!VIEWS.some(item => item[0] === view)) view = "chat";
  if (view !== "chat" && (!state.runId || state.chatNew)) return;
  state.view = view;
  const url = new URL(location.href);
  if (view === "chat") url.searchParams.delete("view");
  else url.searchParams.set("view", view);
  if (url.href !== location.href) history.pushState({}, "", url);
  paint();
  if (view === "methods" && (!state.methods.result||state.methods.stale) && !state.methods.loading) loadMethods();
  if (view === "library" && (!state.library.result||state.library.stale) && !state.library.loading) loadLibrary();
}

function workspaceNavigation() {
  const main=['chat','funnel','map','methods','library'];
  const labels={chat:'研究',funnel:'文献',map:'地图',fulltext:'正文搜索',methods:'对比',library:'笔记'};
  const icons={chat:'chat',funnel:'papers',map:'map',methods:'compare',library:'library'};
  const button=(v)=>`<button type="button" data-workspace-view="${v[0]}" ${v[0]===state.view?'aria-current="page" class="active"':''} ${v[0]!=='chat'&&(!state.runId||state.chatNew)?'disabled':''}>${uiIcon(icons[v[0]]||'papers')}<span>${esc(labels[v[0]]||v[2])}</span></button>`;
  return `<nav class="workspace-nav" aria-label="研究工作区">${main.map(key=>button(VIEWS.find(v=>v[0]===key))).join('')}<details class="nav-more"><summary ${!main.includes(state.view)?'class="active"':''}>更多</summary><div class="nav-more-menu">${VIEWS.filter(v=>!main.includes(v[0])&&v[0]!=='report').map(button).join('')}</div></details></nav>`;
}

function moduleHeaderView() { return ''; }

function scopedAuditData() {
  const data = state.data || {};
  const live = data.live || {};
  const added = new Set(live.matched_paper_ids ?? live.added_paper_ids ?? []);
  if (data.offline !== false || (!live.matched_paper_ids && !live.added_paper_ids)) return data;
  const retrievalIds = new Set((live.retrieval || []).map(r => r.retrieval_id));
  const queryIds = new Set((data.retrieval_runs || []).filter(r => retrievalIds.has(r.retrieval_id)).map(r => r.query_id));
  const documentSnapshots = new Set((data.fulltext_audit?.documents || []).filter(d => added.has(d.paper_id)).map(d => d.snapshot_id));
  return { ...data, papers: (data.papers || []).filter((item) => added.has(item.paper_id)), evidence: (data.evidence || []).filter((item) => added.has(item.paper_id)), falsification: (data.falsification || []).filter((item) => added.has(item.paper_id)), claims: (data.claims || []).filter((item) => item.text === data.question || added.has(item.paper_id) || (data.evidence || []).some((e) => e.claim_id === item.claim_id && added.has(e.paper_id))),
    screening: (data.screening || []).filter(s => added.has(s.paper_id)),
    stats: { ...data.stats, paper_count: (data.papers || []).filter(p => added.has(p.paper_id)).length,
      decision_counts: Object.fromEntries(["include", "exclude", "pending"].map(decision => [decision, (data.papers || []).filter(p => added.has(p.paper_id) && p.decision === decision).length])) },
    queries: (data.queries || []).filter(q => queryIds.has(q.query_id)),
    query_plans: (data.query_plans || []).filter(p => p.query_ids.some(id => queryIds.has(id))),
    source_snapshots: (data.source_snapshots || []).filter(s => retrievalIds.has(s.retrieval_id) || documentSnapshots.has(s.snapshot_id)) };
}

async function refreshConversations() {
  const result = await api("/api/conversations");
  state.conversationHistory = result.conversations || [];
}

function startNewConversation() {
  state.context=null;state.mapContext=null;
  state.loadToken += 1;
  state.chatKey = `draft:${++state.draftCounter}`;
  state.sidebarOpen=false;state.methodFieldsExpanded=false;state.libraryEditing='';state.toolsNotice='';
  state.runId = "";
  state.data = emptyWorkspace();
  state.reviewMessage = "";
  state.chat = { messages: [], pendingTopic: "" };
  state.constraints = {year_from:'',year_to:'',research_object:'',method:'',publication_type:'any'};
  state.resources = {data:'',compute:'',time:''};
  state.queryPlan = null;
  state.libraryFilter='all';state.librarySearch='';
  state.guidance = null;
  state.library = {result:null,loading:false,error:''};
  state.methods = {result:null,selected:[],loading:false,error:''};
  state.fulltext = {query:'',paperId:'',section:'',result:null,loading:false,error:''};
  state.chatNew = true;
  state.readingMode = false;
  state.agentMode = false;
  state.readingPaperId = "auto";
  state.searchSupplement=false;
  state.view = "chat";
  state.ask = null;
  const url = new URL(location.href);
  url.searchParams.delete("run");
  url.searchParams.delete("view");
  clearWorkspaceContextParams(url);
  history.pushState({}, "", url);
  paint();
}

function bindConversationControls(root) {
  const newButton = root.querySelector("#sidebar-new-conversation");
  if (newButton) newButton.onclick = startNewConversation;
  root.querySelectorAll("[data-conversation-run]").forEach((node) => {
    node.onclick = async () => {
      state.sidebarOpen = false;
      state.chatNew = false;
      state.view = "chat";
      await loadRun(node.dataset.conversationRun, true, true);
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
  if (!state.ask) return '';
  const papers = state.ask.papers || [];
  if (!papers.length) {
    return `<div class="banner">当前结果里没有足够相关的论文，请尝试调整检索词或范围。</div>`;
  }
  return `<div class="ask-hits">${papers
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

function renderView({preserveGraphLayout=false}={}) {
  const stage = document.getElementById("stage");
  const views = { chat: chatView, funnel: funnelView, fulltext: fulltextView, methods: methodsView, map: mapView, evidence: evidenceView, falsify: falsifyView, eval: evalView, report: reportView, library: libraryView };
  stage.innerHTML = (views[state.view] || chatView)();
  bindResearchControls(stage);
  bindWorkbenchTools(stage);
  bindFormDrafts(stage);
  bindWorkspaceObjectActions(stage);
  stage.querySelectorAll("[data-audit-export]").forEach(button => {
    button.onclick = async () => {
      button.disabled = true;
      try {
        const report = await api(`/api/run/${encodeURIComponent(state.runId)}/report`);
        const url = URL.createObjectURL(new Blob([report.content], {type: "text/markdown;charset=utf-8"}));
        const link = document.createElement("a"); link.href = url; link.download = report.filename; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { button.textContent = `导出失败：${error.message}`; }
      finally { button.disabled = false; }
    };
  });
  stage.querySelectorAll("[data-upgrade-audit]").forEach((button) => {
    button.onclick = async () => {
      button.disabled = true;
      button.textContent = "正在保存全文与核验定位，请稍候…";
      try {
        const result = await api("/api/audit/upgrade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({run_id: state.runId, acquire: button.dataset.upgradeAudit === "download"}) });
        state.view = "evidence";
        await loadRun(result.run_id);
      } catch (error) {
        button.disabled = false;
        button.textContent = `未完成：${error.message}，点击重试`;
      }
    };
  });
  stage.querySelectorAll("[data-paper]").forEach((node) => {
    node.onclick = () => {
      state.selectedPaper = node.dataset.paper;
      openPaperContext(node.dataset.paper);
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
      state.selectedPaper = node.dataset.chatPaper;
      openPaperContext(node.dataset.chatPaper);
    };
  });
  stage.querySelectorAll("[data-chat-action]").forEach((node) => {
    node.onclick = () => {
      const view = node.dataset.chatAction === "evidence" ? "evidence" : node.dataset.chatAction === "falsify" ? "falsify" : "eval";
      setView(view);
    };
  });
  bindClarification(stage);
  if (state.view === "map" || stage.querySelector(".paper-graph")) setupGraphInteractions(preserveGraphLayout);
  else stopGraphSimulation();
}

const METHOD_FIELDS = { task: "研究问题", method: "核心方法", data: "数据集", sample_size: "样本规模", experiment: "实验设置", baseline: "比较基线", metrics: "评价指标", results: "主要结果", resources: "资源要求", conditions: "适用条件" };
const REVIEW_LABELS = { accepted: "人工已确认", rejected: "人工已排除", pending: "待人工确认", stale: "原文已更新，请重新确认" };

function passageLink(passage) {
  return passage.pdf_url || `/api/fulltext/${encodeURIComponent(state.runId)}/${encodeURIComponent(passage.paper_id)}#page=${Number(passage.page) || 1}`;
}

function reviewEditor(passage, field = "", review = null, inline = false) {
  const savedDraft=getFormDraft('review',passage.paper_id,passage.passage_id,field);
  const staleDraft=Boolean(savedDraft&&savedDraft.source_text_sha256!==passage.text_sha256);
  const draft=staleDraft?null:savedDraft;
  if(draft)review={...(review||{}),...draft};
  const claimField=`<label>我的论断或阅读结论（可选）<input name="claim" maxlength="2000" value="${esc(review?.claim || "")}" placeholder="记录你从这段原文得到的结论"/></label>`;
  const form=`<form data-review-form data-passage-id="${esc(passage.passage_id)}" data-paper-id="${esc(passage.paper_id)}" data-field="${esc(field)}" data-text-hash="${esc(passage.text_sha256)}" data-quote="${esc(passage.quote||'')}">
    ${staleDraft?`<details class="draft-version-warning"><summary>原文版本已变化，旧草稿保留供核对</summary><p>旧草稿未自动套用到新原文，请核对后重新填写。</p><p>${esc(savedDraft.display_value||savedDraft.claim||'')}</p><p>${esc(savedDraft.note||'')}</p><blockquote>${esc(savedDraft.source_quote||'')}</blockquote></details>`:''}
    <label>人工判断<select name="status">${["pending", "accepted", "rejected"].map(status => `<option value="${status}" ${review?.status === status ? "selected" : ""}>${REVIEW_LABELS[status]}</option>`).join("")}</select></label>
    ${field ? `<label>字段展示值（人工修订）<textarea name="display_value" maxlength="2000" rows="2">${esc(review?.display_value || passage.value || passage.summary || "")}</textarea></label>` : ""}
    <label>备注<textarea name="note" rows="2" maxlength="4000" placeholder="记录适用条件、疑问或需要进一步核对的信息">${esc(review?.note || "")}</textarea></label>
    ${inline&&field?`<details class="review-claim"><summary>补充研究判断（可选）</summary>${claimField}</details>`:claimField}
    <p class="tiny">人工记录单独保存，原文依据保留可查。</p>
    ${draft?`<p class="tiny" data-draft-notice>已恢复未保存草稿；保存后写入研究记录。</p><button type="button" class="ghost" data-discard-draft="review" data-paper-id="${esc(passage.paper_id)}" data-passage-id="${esc(passage.passage_id)}" data-field="${esc(field)}">丢弃此草稿</button>`:''}<button type="submit" class="solid">保存人工记录</button></form>`;
  return inline?`<div class="review-editor review-editor-inline">${form}</div>`:`<details class="review-editor"><summary>${field ? "确认或修订此方法字段" : "加入研究证据与备注"}</summary>${form}</details>`;
}

function fulltextView() {
  const local = state.fulltext;
  const result = local.result || state.data?.fulltext_index || {};
  const papers = scopedAuditData().papers || [];
  const hits = (result.hits || []).filter(hit=>!local.paperId||hit.paper_id===local.paperId);
  return `<section class="research-section"><div class="research-heading"><div><h2>在论文全文中继续查找</h2><p>输入问题或术语，按论文与章节筛选正文片段，再回到对应原文页核对。</p></div><button type="button" class="ghost" data-workspace-goto="evidence">获取或查看全文</button></div>
    <form id="fulltext-search" class="research-search"><label class="research-query">问题或检索词<input name="query" value="${esc(local.query)}" placeholder="例如：实验设置、研究方法、evaluation metrics" maxlength="2000" required/></label>
    <label>论文范围<select name="paper_id"><option value="">全部当前论文</option>${papers.map(p => `<option value="${esc(p.paper_id)}" ${local.paperId === p.paper_id ? "selected" : ""}>${esc(p.title)}</option>`).join("")}</select></label>
    <label>章节<select name="section"><option value="">全部章节</option>${["abstract", "introduction", "method", "result", "discussion", "conclusion"].map(s => `<option value="${s}" ${local.section === s ? "selected" : ""}>${({abstract:"摘要",introduction:"引言",method:"方法",result:"结果",discussion:"讨论",conclusion:"结论"})[s]}</option>`).join("")}</select></label>
    <button type="submit" class="solid" ${local.loading ? "disabled" : ""}>${local.loading ? "正在检索正文…" : "搜索全文"}</button></form>
    ${local.error ? `<div class="banner danger" role="alert">${esc(local.error)}</div>` : ""}
    ${state.reviewMessage ? `<p class="review-feedback" role="status">${esc(state.reviewMessage)}</p>` : ""}
    <p class="muted">${esc(result.indexed_paper_count ?? 0)} 篇已建索引论文 · ${esc(result.passage_count ?? 0)} 个正文片段 · ${hits.length} 个命中${local.result ? ` · 查询：${esc(result.query || local.query)}` : " · 当前研究已保存的检索线索"}</p>
    ${result.notice ? `<p class="tiny">${esc(result.notice)}</p>` : ""}
    ${coverageView()}<div class="passage-list">${hits.length ? hits.map(hit => `<article class="passage-card"><div class="stamps"><span class="stamp info">正文检索线索</span><span>第 ${esc(hit.page)} 页${hit.section ? ` · ${esc(hit.section)}` : ""}</span></div><h3>${esc(hit.title || titleOf(hit.paper_id))}</h3><blockquote>${esc(hit.text)}</blockquote>${hit.context?.length?`<details><summary>前后文与相邻页</summary>${hit.context.map(c=>`<p class="tiny">PDF第${c.page}页 · ${esc(c.position)}</p><blockquote>${esc(c.text)}</blockquote>`).join('')}</details>`:''}<div class="passage-actions"><a href="${esc(passageLink(hit))}" target="_blank" rel="noopener">打开原文第 ${esc(hit.page)} 页 ↗</a><button class="ghost" data-read-pdf="${esc(hit.paper_id)}" data-page="${hit.page}">在工作区阅读原文</button><button class="ghost" type="button" data-ask-passage="${esc(hit.passage_id)}">基于这段继续提问</button></div>${reviewEditor(hit)}<details><summary>定位与检索信息</summary><p class="tiny">片段 ${esc(hit.passage_id)} · 得分 ${esc(hit.score ?? "—")}</p><p class="tiny">文本 SHA-256：${esc(hit.text_sha256 || "—")}</p></details></article>`).join("") : `<div class="research-empty"><h3>${result.passage_count ? "当前条件没有匹配片段" : "先为研究获取全文"}</h3><p>${result.passage_count ? "尝试使用中英文方法术语，或放宽论文和章节条件。" : "在证据页面点击获取全文并核验，完成后回到这里搜索方法、实验和正文内容。"}</p><button type="button" class="solid" data-workspace-goto="evidence">前往全文获取</button></div>`}</div></section>`;
}

function defaultComparisonIds(papers) {
  const readable=papers.filter(p=>p.has_fulltext);
  return (readable.length?readable:papers).slice(0,3).map(p=>p.paper_id);
}

function alternativeCandidatesView(paper,key,current) {
  const others=(paper.fields?.[key]?.candidates||[]).filter(c=>c.passage_id!==current.passage_id||c.quote!==current.quote);
  return others.length?`<details class="alternative-candidates"><summary>查看其他 ${others.length} 个原文候选</summary>${others.map(c=>`<article><p>PDF第 ${c.page} 页</p><blockquote>${esc(c.quote||c.text)}</blockquote>${reviewEditor(c,key)}</article>`).join('')}</details>`:'';
}

function conditionValues(value) {
  if(Array.isArray(value))return value.join('、')||'尚未提取';
  if(value&&typeof value==='object')return Object.entries(value).map(([k,v])=>`${({model_scale:'模型规模',batch_size:'批量',precision:'精度',folds:'验证折数',sequence_length:'序列长度',resolution:'分辨率'})[k]||k}：${Array.isArray(v)?v.join('、'):v}`).join('；')||'尚未提取';
  return value||'尚未提取';
}

function experimentComparisonView(papers,result) {
  if(!result?.comparability)return '';
  const ids=new Set(papers.map(p=>p.paper_id));const pairs=(result.comparability.pairs||[]).filter(p=>ids.has(p.left_paper_id)&&ids.has(p.right_paper_id));
  const labels={different:'条件不同',missing:'缺少依据',matching_mentions:'提及相同项目，仍需核对',partial_overlap:'仅部分重合'};
  return `<details data-panel="experiment-comparison" class="experiment-comparison"><summary>实验配置线索与比较条件</summary><p>${esc(result.comparability.notice)}</p>${pairs.map(pair=>`<article><h3>${esc(titleOf(pair.left_paper_id))} / ${esc(titleOf(pair.right_paper_id))}</h3><p class="tool-notice">${esc(pair.notice)}</p>${pair.checks.map(c=>`<p><strong>${esc(c.label)}</strong> · ${esc(labels[c.status]||c.status)}<br/>左：${esc(conditionValues(c.left_values))}<br/>右：${esc(conditionValues(c.right_values))}</p>`).join('')}</article>`).join('')}${papers.map(p=>`<details><summary>${esc(p.title)} · ${(p.experiment_contexts||[]).length} 条原文配置线索</summary>${(p.experiment_contexts||[]).map(c=>`<article class="configuration-card"><p>PDF第 ${c.source.page} 页 · 同一句原文中的配置线索，待人工核对</p><blockquote>${esc(c.source.quote)}</blockquote>${Object.entries(c.condition_mentions||{}).filter(([k])=>k!=='scope').map(([k,v])=>`<p>${esc({datasets:'数据集',metrics:'指标',settings:'设置'}[k]||k)}：${esc(conditionValues(v))}</p>`).join('')}<button type="button" class="ghost" data-read-pdf="${esc(p.paper_id)}" data-page="${c.source.page}">核对原页</button></article>`).join('')||'<p>当前没有足够明确的实验配置线索；可继续查找正文。</p>'}</details>`).join('')}</details>`;
}

function methodsView() {
  const result = state.methods.result;
  const allPapers = result?.papers || [];
  const selectedIds = state.methods.selected.length ? state.methods.selected : defaultComparisonIds(allPapers);
  const papers = allPapers.filter(p => selectedIds.includes(p.paper_id));
  const coreFields=new Set(['task','method','data','metrics','results','conditions']);
  const fields=Object.entries(METHOD_FIELDS).filter(([key])=>state.methodFieldsExpanded||coreFields.has(key));
  return `<section class="research-section"><div class="research-heading"><div><h2>方法与实验对比</h2><p>先看核心差异，需要时展开原文核对和人工修订。</p></div><button type="button" class="ghost" data-method-export ${!result ? "disabled" : ""}>导出对比 CSV</button></div>
    ${state.methods.error ? `<div class="banner danger" role="alert">${esc(state.methods.error)}</div>` : ""}${state.reviewMessage ? `<p class="review-feedback" role="status">${esc(state.reviewMessage)}</p>` : ""}
    ${state.methods.loading ? `<p class="research-task" role="status">正在整理全文方法字段…</p>` : ""}
    ${resourceConditionsView()}
    ${experimentComparisonView(papers,result)}
    ${allPapers.length ? `<details data-panel="paper-selection" class="paper-selection"><summary>比较论文 · 已选 ${papers.length} 篇（可修改）</summary><fieldset class="comparison-picker"><legend>选择对比论文（最多四篇）</legend>${allPapers.map(p => `<label><input type="checkbox" data-compare-paper value="${esc(p.paper_id)}" ${selectedIds.includes(p.paper_id) ? "checked" : ""}/> ${esc(p.title)}</label>`).join("")}</fieldset></details><div class="method-fields-toggle"><span>${state.methodFieldsExpanded?'显示全部 10 项':'显示 6 项核心对比'} · 结果是否可比请核对实验条件</span><label><input type="checkbox" data-method-fields-toggle ${state.methodFieldsExpanded?'checked':''}/> 显示全部对比项目</label></div><div class="comparison-scroll" tabindex="0" role="region" aria-label="论文方法对比表，可左右滚动"><p class="comparison-scroll-hint">左右滑动查看其他论文</p><table class="comparison-table"><thead><tr><th>对比项目</th>${papers.map(p => `<th>${esc(p.title)}${!p.has_fulltext ? '<p class="tiny">尚未获取全文</p>' : ""}</th>`).join("")}</tr></thead><tbody>${fields.map(([key,label]) => `<tr><th scope="row">${label}</th>${papers.map(p=>methodFieldCell(p,key)).join("")}</tr>`).join("")}</tbody></table></div>` : !state.methods.loading ? `<div class="research-empty"><h3>整理当前论文的方法线索</h3><p>获取全文后，可在这里比较方法并核对原文。</p><button class="solid" type="button" data-load-methods>载入方法对比</button><button class="ghost" type="button" data-workspace-goto="evidence">获取全文</button></div>` : ""}
    ${result?.notice ? `<details class="method-source"><summary>关于对比结果</summary><p class="tiny">${esc(result.notice)}</p></details>` : ""}</section>`;
}

function methodFieldCell(p,key) {
  const item=p.fields?.[key]||{};const c=item.candidate;
  if(!c)return `<td class="method-empty"><span aria-label="原文记录为空">—</span><button class="ghost compact" data-method-search="${esc(p.paper_id)}" data-field-query="${esc(METHOD_FIELDS[key])}">选择依据</button></td>`;
  const value=item.review?.display_value||c.value||c.summary||c.quote||c.text;
  return `<td><span class="stamp ${item.status==='accepted'?'include':'pending'}">${esc(REVIEW_LABELS[item.status]||REVIEW_LABELS.pending)}</span><p class="method-value">${esc(value)}</p><div class="panel-actions">${sourceButton(c,`第 ${c.page} 页`)}<button type="button" class="ghost compact" data-edit-method-field="${esc(p.paper_id)}" data-field="${esc(key)}">依据与修订</button></div></td>`;
}

function bindWorkbenchTools(stage) {
  stage.querySelectorAll('[data-open-chat-tool]').forEach(b=>b.onclick=()=>{
    const toolbox=stage.querySelector('.chat-toolbox');if(toolbox)toolbox.open=true;
    const detail=stage.querySelector(`[data-chat-tool="${b.dataset.openChatTool}"]`);if(detail){detail.open=true;detail.scrollIntoView({block:'nearest',behavior:'smooth'});}
  });
  stage.querySelectorAll('[data-ask-missing]').forEach(b=>b.onclick=()=>{state.readingMode=true;state.readingPaperId='auto';setView('chat');const input=document.querySelector('#search-form input[name=q]');if(input){input.value=`请基于刚才所选论文继续解释${b.dataset.askMissing}，给出原文依据；材料不足时说明缺少什么。`;state.composeDrafts[state.chatKey]=input.value;input.focus();}});
  const supplementToggle=stage.querySelector('[data-search-supplement]');if(supplementToggle)supplementToggle.onchange=()=>{state.searchSupplement=supplementToggle.checked;};
  stage.querySelectorAll('[data-load-task-history]').forEach(b=>b.onclick=loadTaskHistory);
  stage.querySelectorAll('[data-retry-background-task]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;try{const result=await api(`/api/tasks/${encodeURIComponent(b.dataset.retryBackgroundTask)}/retry`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(result.run_id)await loadRun(result.run_id,true,true);await loadTaskHistory();}
    catch(error){state.taskHistoryError=error.message;await loadTaskHistory();}finally{b.disabled=false;}
  });
  stage.querySelectorAll('[data-search-more]').forEach(b=>b.onclick=async()=>{
    const run=state.runId;b.disabled=true;try{const result=await api('/api/research/search-more',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,failed_only:b.dataset.searchMore==='failed',search_supplement:b.dataset.searchMore==='failed'?undefined:{pages_per_query:1,max_requests:4,sources:ONLINE_SEARCH_SOURCES}})});if(state.runId!==run)return;await loadRun(result.run_id,false,true);setView('funnel');}
    catch(error){state.toolsNotice=error.message;paint();}finally{b.disabled=false;}
  });
  stage.querySelectorAll('[data-discard-draft]').forEach(b=>b.onclick=()=>{clearFormDraft(b.dataset.discardDraft,b.dataset.paperId,b.dataset.passageId||'',b.dataset.field||'');paint();});
  const readingSelect=stage.querySelector('[data-reading-paper]');if(readingSelect)readingSelect.onchange=()=>{state.readingPaperId=readingSelect.value;const summary=readingSelect.closest?.('details')?.querySelector('summary');if(summary)summary.textContent='范围：'+(state.readingPaperId==='all'?'全部当前论文':state.readingPaperId==='auto'?'自动识别':titleOf(state.readingPaperId));};
  const agentToggle=stage.querySelector('[data-agent-mode]');if(agentToggle)agentToggle.onchange=()=>{state.agentMode=agentToggle.checked;if(state.agentMode)state.readingMode=false;paint();};
  const readingToggle=stage.querySelector('[data-reading-mode]');if(readingToggle)readingToggle.onchange=()=>{state.readingMode=readingToggle.checked;if(state.readingMode)state.agentMode=false;const input=stage.querySelector('#search-form input[name=q]');if(input)input.placeholder=state.readingMode?'围绕当前论文继续提问…':'输入研究问题，或论文题名、arXiv编号…';};
  stage.querySelectorAll('[data-constraint]').forEach(input=>input.oninput=()=>{state.constraints[input.dataset.constraint]=input.value;});
  stage.querySelectorAll('[data-resource]').forEach(input=>input.oninput=()=>{state.resources[input.dataset.resource]=input.value;});
  stage.querySelectorAll('[data-preview-plan],[data-direct-search]').forEach(button=>button.onclick=async()=>{
    const input=document.querySelector('#search-form input[name=q]');const question=input?.value.trim()||state.data?.question||'';
    if(!question){state.toolsNotice='请先输入研究问题。';paint();return;}
    state.toolsNotice='';
    button.disabled=true;
    try {
      const result=await api(button.hasAttribute('data-preview-plan')?'/api/query-plan':'/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,constraints:state.constraints,search_supplement:searchSupplementOptions()})});
      if(result.run_id){await loadRun(result.run_id,false,true);setView('funnel');}
      else{state.queryPlan=result;paint();const toolbox=document.querySelector('.chat-toolbox');if(toolbox)toolbox.open=true;const details=document.querySelector('[data-chat-tool=search]');if(details)details.open=true;const plan=document.querySelector('.query-plan-details');if(plan)plan.open=true;}
    }catch(error){state.toolsNotice=error.message;paint();}finally{button.disabled=false;}
  });
  stage.querySelectorAll('[data-import-pdf]').forEach(form=>form.onsubmit=async event=>{
    event.preventDefault();const input=form.querySelector('[name=pdf]');const file=input.files?.[0];if(!file)return;
    const button=form.querySelector('button[type=submit]');button.disabled=true;button.textContent='正在导入并解析…';form.querySelector('[data-import-error]')?.remove();
    try {
      if(file.size>25*1024*1024)throw new Error('PDF文件不得超过25MB');
      const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
      const values=new FormData(form);const result=await api('/api/import/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:values.get('append')==='on'?state.runId:undefined,authors:String(values.get('authors')||'').split(/[;；\n]/).map(a=>a.trim()).filter(Boolean),year:values.get('year')?Number(values.get('year')):undefined,source_url:values.get('source_url')||undefined,filename:file.name,content_base64:content,title:values.get('title')||'',question:values.get('question')||'',identifier:values.get('identifier')||''})});
      await loadRun(result.run_id,false,true);setView('fulltext');
    }catch(error){const notice=document.createElement('p');notice.dataset.importError='';notice.className='banner danger';notice.setAttribute('role','alert');notice.textContent=`导入未完成：${error.message}`;form.appendChild(notice);}finally{button.disabled=false;button.textContent='导入并开始阅读';}
  });
  stage.querySelectorAll('[data-read-pdf]').forEach(b=>b.onclick=()=>readerDialog(b.dataset.readPdf,b.dataset.page));
  stage.querySelectorAll('[data-library-filter-form]').forEach(form=>{
    const apply=()=>{const v=new FormData(form);state.libraryFilter=v.get('filter');state.librarySearch=v.get('search');state.libraryFormat=v.get('export_format');paint();};
    form.onsubmit=e=>{e.preventDefault();apply();};
    const filter=form.querySelector('[name=filter]');if(filter)filter.onchange=apply;
    const format=form.querySelector('[name=export_format]');if(format)format.onchange=()=>{state.libraryFormat=format.value;};
  });
  stage.querySelectorAll('[data-load-library]').forEach(b=>b.onclick=loadLibrary);
  stage.querySelectorAll('[data-library-favorite]').forEach(b=>b.onclick=async()=>{
    const run=state.runId;const paperId=b.dataset.libraryFavorite;const item=state.library.result?.items?.find(p=>p.paper_id===paperId);if(!item)return;
    const draft=getFormDraft('library',paperId);const favorite=!(draft?.favorite??item.favorite);b.disabled=true;
    state.library.error='';state.library.notice='';
    try {
      const result=await api('/api/library/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,paper_id:paperId,favorite})});
      if(state.runId!==run)return;
      copyFormDraftsToRun(run,result.run_id);
      if(result.run_id!==run)await adoptResearchRun(result.run_id);
      if(draft)rememberFormDraft('library',paperId,'','',{...draft,favorite});
      if(result.run_id===run&&state.library.result)state.library.result.items=state.library.result.items.map(p=>p.paper_id===paperId?result.item:p);
      else {await loadLibrary();}
      state.library.notice=favorite?'已收藏论文。':'已取消收藏。';if(state.context?.paperId===paperId)state.context.notice=state.library.notice;paint();
    }catch(error){state.library.error=error.message;paint();}finally{b.disabled=false;}
  });
  stage.querySelectorAll('[data-library-form]').forEach(form=>form.onsubmit=async event=>{
    event.preventDefault();const button=form.querySelector('button');button.disabled=true;const run=state.runId;const values=new FormData(form);
    state.library.error='';state.library.notice='';
    try {
      const result=await api('/api/library/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,paper_id:form.dataset.paperId,favorite:values.get('favorite')==='on',reading_status:values.get('reading_status'),tags:String(values.get('tags')||'').split(/[,，]/).map(x=>x.trim()).filter(Boolean),notes:values.get('notes')})});
      clearFormDraft('library',form.dataset.paperId,'','',run);
      if(state.runId!==run)return;
      copyFormDraftsToRun(run,result.run_id);
      await adoptResearchRun(result.run_id);await loadLibrary();
      state.library.notice='阅读记录已保存。';if(state.context?.paperId===form.dataset.paperId)state.context.notice=state.library.notice;paint();
    }catch(error){state.library.error=error.message;if(state.context?.paperId===form.dataset.paperId)state.context.error=error.message;paint();}finally{button.disabled=false;}
  });
  stage.querySelectorAll('[data-library-export]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;try{const form=b.closest('form');const values=form?new FormData(form):null;if(values){state.libraryFilter=values.get('filter');state.librarySearch=values.get('search');state.libraryFormat=values.get('export_format');}const params=new URLSearchParams({format:state.libraryFormat||'bibtex'});filteredLibraryItems().forEach(p=>params.append('paper_id',p.paper_id));if(!filteredLibraryItems().length)throw new Error('当前筛选没有论文，请先调整条件');const result=await api(`/api/library/${encodeURIComponent(state.runId)}/export?${params}`);downloadText(result.filename,result.content);state.library.notice='已导出当前筛选清单；笔记草稿请先保存后再导出。';paint();}
    catch(error){state.library.error=error.message;paint();}finally{b.disabled=false;}
  });
  stage.querySelectorAll('[data-open-paper-text]').forEach(b=>b.onclick=()=>openPaperContext(b.dataset.openPaperText,'reader'));
  stage.querySelectorAll('[data-related-paper]').forEach(b=>b.onclick=()=>{openPaperContext(b.dataset.relatedPaper,'citations');exploreContextCitations(b.dataset.direction);});
  stage.querySelectorAll('[data-guidance]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;try{state.guidance=await api('/api/research/guidance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:state.runId,paper_ids:state.methods.selected.length?state.methods.selected:null,user_resources:state.resources})});paint();const detail=document.querySelector('[data-guidance]')?.closest('details');if(detail)detail.open=true;}
    catch(error){state.reviewMessage=error.message;paint();}finally{b.disabled=false;}
  });
}

function downloadText(filename, content) {
  const url=URL.createObjectURL(new Blob([content],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function loadMethods() {
  if (!state.runId || state.methods.loading) return;
  const run = state.runId;state.methods.loading=true;state.methods.error="";paint();
  try { const result=await api(`/api/methods/${encodeURIComponent(run)}`);if(state.runId===run){state.methods.result=result;state.methods.stale=false;} }
  catch(error){if(state.runId===run)state.methods.error=`方法对比加载失败：${error.message}`;}
  finally{if(state.runId===run){state.methods.loading=false;if(state.view==='methods')paint();}}
}

function savedResearchReviews() {
  return (state.data?.research_workspace?.reviews || []).filter(review => review.status !== "rejected");
}

function researchReviewView() {
  const reviews=savedResearchReviews();
  return `<section class="saved-research"><h3>我的正文证据与方法记录</h3><p class="muted">人工确认与备注独立保存，可回到原文；原有论断判决保留在下方。</p>${reviews.length ? reviews.map(review => `<article class="passage-card"><div class="stamps"><span class="stamp ${review.status === "accepted" ? "include" : "pending"}">${esc(REVIEW_LABELS[review.status] || REVIEW_LABELS.pending)}</span>${review.field ? `<span>${esc(METHOD_FIELDS[review.field] || review.field)}</span>` : ""}</div><h4>${esc(review.title || titleOf(review.paper_id))}</h4>${review.claim ? `<p><strong>我的论断或结论：</strong>${esc(review.claim)}</p>` : ""}<blockquote>${esc(review.text || review.snippet || "")}</blockquote>${review.note ? `<p class="review-note">${esc(review.note)}</p>` : ""}<a href="${esc(passageLink(review))}" target="_blank" rel="noopener">核对原文第 ${esc(review.page || "—")} 页 ↗</a><p class="tiny">人工记录 · ${esc(review.updated_at || "")}</p></article>`).join("") : `<p>还没有人工记录。可在全文搜索结果或方法对比中选择片段并保存。</p><button type="button" class="ghost" data-workspace-goto="fulltext">查找正文证据</button>`}</section>`;
}

function reportView() {
  return `<section class="research-section"><h2>保存研究成果</h2><p>导出当前研究的审计记录，以及附原文定位和人工确认状态的方法对比表。</p><div class="report-options"><article class="passage-card"><h3>研究审计报告</h3><p>研究范围、论文筛选、论断证据与后续核查事项。</p><button class="solid" type="button" data-audit-export>下载 Markdown 报告</button></article><article class="passage-card"><h3>方法与实验对比</h3><p>任务、方法、数据、基线、指标、资源条件以及页码依据。</p><button class="solid" type="button" data-method-export>下载 CSV 对比表</button></article></div>${researchReviewView()}</section>`;
}

function bindResearchControls(stage) {
  stage.querySelectorAll("[data-workspace-goto]").forEach(b=>b.onclick=()=>setView(b.dataset.workspaceGoto));
  stage.querySelectorAll("[data-example-query]").forEach(b=>b.onclick=()=>{const input=stage.querySelector('input[name="q"]');if(input){input.value=b.dataset.exampleQuery;state.composeDrafts[state.chatKey]=input.value;input.focus();}});
  const demo=stage.querySelector('[data-open-demo]');if(demo)demo.onclick=()=>loadRun(state.runs.find(r=>r.id==='phase2-real')?.id||state.runs[0]?.id,true,true);
  const stop=stage.querySelector('[data-stop-wait]');if(stop)stop.onclick=()=>activeChatTask()?.controller.abort();
  const retry=stage.querySelector('[data-retry-task]');if(retry)retry.onclick=()=>chatTurn(state.lastFailedTask?.message,state.lastFailedTask?.options);
  const form=stage.querySelector('#fulltext-search');if(form)form.onsubmit=async event=>{
    event.preventDefault();if(state.fulltext.loading)return;
    const values=new FormData(form);const run=state.runId;
    Object.assign(state.fulltext,{query:String(values.get('query')||'').trim(),paperId:String(values.get('paper_id')||''),section:String(values.get('section')||''),loading:true,error:''});
    const body={run_id:run,query:state.fulltext.query,paper_ids:state.fulltext.paperId?[state.fulltext.paperId]:null,section:state.fulltext.section||null};paint();
    try{const result=await api('/api/fulltext/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(state.runId===run)state.fulltext.result=result;}
    catch(error){if(state.runId===run)state.fulltext.error=`正文检索失败：${error.message}`;}
    finally{if(state.runId===run){state.fulltext.loading=false;paint();}}
  };
  stage.querySelectorAll('[data-ask-passage]').forEach(button=>button.onclick=()=>{const hit=(state.fulltext.result||state.data?.fulltext_index)?.hits?.find(h=>h.passage_id===button.dataset.askPassage);if(!hit)return;openReaderContext(hit.paper_id,hit.page,hit.text);state.context.selection=hit.text;renderWorkspaceContext();document.querySelector('[data-context-question] textarea')?.focus();});
  stage.querySelectorAll('[data-review-form]').forEach(form=>form.onsubmit=async event=>{
    event.preventDefault();const button=form.querySelector('button[type=submit]');button.disabled=true;const values=new FormData(form);const run=state.runId;
    try{
      const result=await api('/api/workspace/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,passage_id:form.dataset.passageId,paper_id:form.dataset.paperId,field:form.dataset.field||'',status:values.get('status'),claim:values.get('claim'),note:values.get('note'),display_value:values.get('display_value')||'',quote:form.dataset.quote||undefined,expected_text_sha256:form.dataset.textHash||undefined})});
      clearFormDraft('review',form.dataset.paperId,form.dataset.passageId,form.dataset.field||'',run);
      if(state.runId!==run)return;
      const oldFulltext=state.fulltext;copyFormDraftsToRun(run,result.run_id);const loaded=await adoptResearchRun(result.run_id);if(!loaded)return;
      state.fulltext={...oldFulltext,result:null};state.reviewMessage='人工记录已保存。';if(state.context?.paperId===form.dataset.paperId)state.context.notice=state.reviewMessage;
      if(state.view==='methods'){await loadMethods();}else paint();
    }catch(error){button.disabled=false;state.reviewMessage=`保存失败：${error.message}`;if(state.context?.paperId===form.dataset.paperId)state.context.error=state.reviewMessage;paint();}
  });
  stage.querySelectorAll('[data-load-methods]').forEach(b=>b.onclick=loadMethods);
  stage.querySelectorAll('[data-method-fields-toggle]').forEach(input=>input.onchange=()=>{state.methodFieldsExpanded=input.checked;paint();});
  stage.querySelectorAll('[data-map-retry]').forEach(button=>button.onclick=async()=>{
    const run=state.runId;if(state.mapRetry.loading&&state.mapRetry.runId===run)return;
    const pending=state.data?.map?.status==='pending';
    state.mapRetry={runId:run,loading:true,error:""};paint();
    try{
      await api('/api/map/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run})});
      if(state.runId!==run)return;
      const loaded=await loadRun(run,false);if(!loaded)return;
      if(state.data?.map?.status==='unavailable')state.mapRetry.error='地图仍未就绪，请检查模型缓存与运行环境后重试。';
    }catch(error){if(state.runId===run)state.mapRetry.error=`${pending?'生成':'重试'}地图失败：${error.message}`;}
    finally{if(state.mapRetry.runId===run)state.mapRetry.loading=false;if(state.runId===run)paint();}
  });
  stage.querySelectorAll('[data-compare-paper]').forEach(b=>b.onchange=()=>{
    const checked=[...stage.querySelectorAll('[data-compare-paper]:checked')].map(x=>x.value);if(checked.length>4){b.checked=false;return;}
    if(!checked.length){b.checked=true;return;}state.methods.selected=checked;paint();
  });
  stage.querySelectorAll('[data-method-search]').forEach(b=>b.onclick=()=>{const field=Object.entries(METHOD_FIELDS).find(([k,v])=>v===b.dataset.fieldQuery)?.[0]||'';openFieldContext(b.dataset.methodSearch,field,b.dataset.fieldQuery);});
  stage.querySelectorAll('[data-method-export]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;try{const params=new URLSearchParams();const ids=state.methods.selected.length?state.methods.selected:(state.view==='methods'?defaultComparisonIds(state.methods.result?.papers||[]):[]);ids.forEach(id=>params.append('paper_id',id));const result=await api(`/api/methods/${encodeURIComponent(state.runId)}/export?${params}`);const url=URL.createObjectURL(new Blob([result.content.startsWith('\uFEFF') ? result.content : '\uFEFF'+result.content],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=result.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(error){state.reviewMessage=`导出失败：${error.message}`;paint();}finally{b.disabled=false;}
  });
}

function chatView() {
  const messages=state.chat.messages||[];const task=activeChatTask();const hasMessages=Boolean(messages.length);
  const failed=state.lastFailedTask?.key===state.chatKey?state.lastFailedTask:null;
  const compose=`<form class="search chat-compose" id="search-form"><input name="q" value="${esc(state.composeDrafts[state.chatKey]||'')}" autocomplete="off" aria-label="研究问题" placeholder="${state.readingMode?'围绕当前论文继续提问…':'输入研究问题，或论文题名、arXiv编号…'}" ${task?'disabled':''}/><button class="solid" type="submit" ${task?'disabled':''}>${task?'处理中…':'发送'}</button></form>`;
  const tools=`<div class="chat-quick-actions"><button class="ghost" type="button" data-open-chat-tool="search">检索条件</button><button class="ghost" type="button" data-open-chat-tool="import">导入 PDF</button></div><details data-panel="chat-tools" class="chat-toolbox"><summary>更多设置与任务</summary><div class="chat-tools">${researchConditionsView()}${importPdfView()}${taskHistoryView()}${setupStatusView()}</div></details>`;
  return `<section class="chat-page ${hasMessages?'has-messages':'is-empty'}">
    ${!hasMessages?`<div class="chat-hero"><span class="history-label">勘文 · 研究助手</span><h2>${state.runId?'围绕论文，继续探索':'开始你的下一项研究'}</h2><p>${state.runId?'从方法、数据或实验条件开始提问，回答可以回到原文。':'告诉勘文你想研究什么，或导入一篇论文开始阅读。'}</p></div>${compose}${readingScopeControl()}`:''}
    ${tools}${state.toolsNotice?`<p class="tool-notice" role="status">${esc(state.toolsNotice)}</p>`:''}
    <div class="chat-thread">${hasMessages?messages.map((item,index)=>chatMessage(item,index)).join(''):`<div class="chat-empty"><div class="research-examples">${[
      ['比较 LoRA 与 QLoRA 的低显存微调方法','LoRA 与 QLoRA'],['医学图像分割有哪些重要方法？','医学图像分割'],['对比学习如何用于时间序列异常检测？','时间序列异常检测']].map(([q,label])=>`<button type="button" class="ghost" data-example-query="${esc(q)}">${esc(label)}</button>`).join('')}</div>${state.runs.length?'<button type="button" class="ghost text-button" data-open-demo>打开已有研究</button>':''}</div>`}
      ${task?`<div class="research-task" role="status" aria-live="polite"><strong data-server-progress>正在处理研究问题</strong><p>已等待 <span data-task-elapsed>${Math.floor((Date.now()-task.started)/1000)}</span> 秒，已完成的材料会保留。</p><button class="ghost" type="button" data-stop-wait>停止等待</button></div>`:''}
      ${failed&&!task?`<div class="task-notice" role="alert">${esc(failed.error)} <button class="ghost" type="button" data-retry-task>重试</button></div>`:''}</div>
    ${hasMessages?`${readingScopeControl()}${compose}`:''}</section>`;
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
  if (code === "no_fulltext") return "当前选择的论文尚无可检索正文。请获取全文或导入 PDF 后进行全文分析；也可关闭正文阅读模式，基于已有摘要提问。";
  if (code === "no_materials") return "当前范围内没有可用于回答的摘要或正文，请补充文献材料或调整范围。";
  if (code === "answer_audit_rejected") return "回答未通过引用完整性检查，未展示未经支持的陈述。已有论文与审计数据已保留，可查看证据后重新提问。";
  const reasons = {
    no_fulltext: "当前选择的论文尚无可检索正文，请先获取全文或调整论文范围。",
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

function citationView(response) {
  const audit=response.answer_audit;if(!audit?.ok)return '';
  const groups=groupAnswerSources(answerCitations(response));
  const paperCount=groups.filter(group=>group.paperId).length;
  const sourceCount=groups.reduce((count,group)=>count+group.sources.length,0);
  const summary=paperCount?`引用来源 · ${paperCount} 篇论文`:sourceCount?`证据记录 · ${sourceCount} 处`:'阅读记录';
  return `<details class="audit-citations"><summary>${summary}</summary>${answerSourceGroupsView(groups)}${answerCoverageView(audit)}<p class="tiny">${audit.human_verified?'人工已确认':'人工记录：未确认'}</p></details>`;
}

function readingScopeControl() {
  const papers=readablePapers();
  if(!state.runId)return '';
  const agent=`<label class="reading-scope"><input type="checkbox" data-agent-mode ${state.agentMode?'checked':''}/> 自动补充全文依据（试用，最多两篇）</label>`;
  if(!papers.length)return agent;
  const title=state.readingPaperId==='all'?'全部当前论文':state.readingPaperId==='auto'?'自动识别':titleOf(state.readingPaperId);
  return `${agent}<div class="reading-scope"><label><input type="checkbox" data-reading-mode ${state.readingMode?'checked':''}/> 基于当前论文全文回答</label><details data-panel="reading-scope" class="reading-scope-options"><summary>范围：${esc(title)}</summary><label>论文范围<select data-reading-paper><option value="auto" ${state.readingPaperId==='auto'?'selected':''}>根据本轮问题确定</option><option value="all" ${state.readingPaperId==='all'?'selected':''}>全部当前论文</option>${papers.map(p=>`<option value="${esc(p.paper_id)}" ${state.readingPaperId===p.paper_id?'selected':''}>${esc(p.title)}</option>`).join('')}</select></label><p class="tiny">本轮明确提到的论文优先，实际范围随回答显示。</p></details></div>`;
}

function readingScopeView(response) {
  const scope=response.reading_scope||{};
  const audit=response.answer_audit||{};
  const papers=[...new Map((scope.paper_ids||audit.considered_paper_ids||[]).map((id,i)=>[id,scope.titles?.[i]||titleOf(id)]))];
  if(!papers.length)return '';
  const cited=new Set(answerCitations(response).map(source=>source.paper_id).filter(Boolean));
  const counts=[`分析范围 ${papers.length} 篇`];
  const available=Array.isArray(scope.available_fulltext_paper_ids)?new Set(scope.available_fulltext_paper_ids).size:scope.available_fulltext_count;
  if(Number.isInteger(available))counts.push(`可读全文 ${available} 篇`);
  if(cited.size||['research_agenda','grounded_reading','evidence_only'].includes(audit.kind))counts.push(`实际引用 ${cited.size} 篇`);
  return `<details class="workspace-context-strip answer-scope"><summary>${counts.join(' · ')}</summary><div class="answer-scope-papers">${papers.map(([id,title])=>`<button type="button" class="selection-chip" data-inspect-paper="${esc(id)}" title="${esc(title)}">${esc(title)}${cited.has(id)?' <span class="answer-scope-cited">已引用</span>':''}</button>`).join('')}</div></details>`;
}

function answerCoverageView(audit) {
  const coverage=audit.question_coverage;if(!coverage?.length)return '';
  const labels={answered:'已关联原文',partial:'部分内容',insufficient_evidence:'—'};
  return `<details class="answer-coverage"><summary>问题与原文 · ${coverage.filter(q=>q.status==='answered').length}/${coverage.length}</summary>${coverage.map(q=>`<p><strong>${esc(q.label)}</strong><span>${esc(labels[q.status]||'—')}</span></p>`).join('')}</details>`;
}

function clarificationMessage(item, messageIndex) {
  const raw = item.response.clarification_questions;
  const questions = (Array.isArray(raw) ? raw : []).filter(q => typeof q?.question === "string" && q.question.trim());
  const active = state.chat.pendingTopic && messageIndex === state.chat.messages.length - 1;
  const overview = item.content ? `<p class="clarification-overview">${esc(item.content)}</p>` : "";
  let content;
  if (!active) {
    content = `<details class="clarification-history"><summary>当时的范围确认</summary>${overview}${questions.map(q => `<p>${esc(q.question)}</p>`).join("")}</details>`;
  } else {
    const question = questions[0];
    const options = [...new Set((Array.isArray(question?.options) ? question.options : [])
      .filter(option => typeof option === "string" && option.trim()).map(option => option.trim()))].slice(0, 3);
    const choices = options.map(option => `<label><input type="radio" name="clarification-choice" value="${esc(option)}"/><span>${esc(option)}</span></label>`).join("");
    const field = question ? `<fieldset class="clarification-question">
      <legend>${esc(question.question)}</legend>
      ${choices ? `<div class="clarification-options">${choices}<label><input type="radio" name="clarification-choice" data-clarification-custom/><span>自己填写</span></label></div>` : ""}
      <div class="clarification-other"${choices ? " hidden" : ""}><input class="clarification-other-input" type="text" maxlength="200" aria-label="补充检索范围" placeholder="用一句话补充检索范围"/></div>
    </fieldset>` : "";
    content = `${overview}<form data-clarification-form>${field}<div class="clarification-actions">
      ${question ? '<button class="solid" type="submit" disabled>按此范围检索</button>' : ""}
      <button class="ghost" type="button" data-clarification-skip>按原问题检索</button>
    </div></form>`;
  }
  return `<div class="chat-message assistant"><div class="chat-role">勘文 · 研究范围</div><article class="chat-bubble assistant-bubble clarification-bubble">${content}</article></div>`;
}

function bindClarification(stage) {
  const form = stage.querySelector("[data-clarification-form]");
  if (!form) return;
  const topic = state.chat.pendingTopic;
  const skip = form.querySelector("[data-clarification-skip]");
  skip.onclick = () => chatTurn(topic, {skipClarification: true});
  const submit = form.querySelector("button[type=submit]");
  if (!submit) return;
  const input = form.querySelector(".clarification-other-input");
  const other = form.querySelector(".clarification-other");
  const radios = [...form.querySelectorAll("input[type=radio]")];
  const selected = () => radios.find(radio => radio.checked);
  const value = () => {
    const choice = selected();
    if (!radios.length || choice?.hasAttribute("data-clarification-custom")) return input.value.trim();
    return choice?.value || "";
  };
  const syncSubmit = () => { submit.disabled = !value(); };
  input.oninput = syncSubmit;
  radios.forEach(radio => radio.onchange = () => {
    other.hidden = !selected()?.hasAttribute("data-clarification-custom");
    if (!other.hidden) input.focus();
    syncSubmit();
  });
  syncSubmit();
  form.onsubmit = event => {
    event.preventDefault();
    const answer = value();
    if (answer) return chatTurn(answer, {clarificationTopic: topic, clarificationContext: [answer]});
  };
}

function agentExecutionView(response) {
  const a=response.agent_execution;if(!a)return '';
  const labels={completed:'补证完成',insufficient_evidence:'补证结束，尚无正文依据',budget_exhausted:'已达到补证上限',no_progress:'停止重复动作',timeout:'补证超时',failed:'补证服务失败',tool_failed:'补证工具失败',model_failed:'补证模型失败',invalid_action:'工具参数无效，已停止',interrupted:'上次执行中断，未重复执行',cancelled:'补证已取消'};
  return `<details><summary>${esc(labels[a.status]||'补证已停止')} · ${(a.steps||[]).length} 步</summary><p>以下回答仍需通过材料引用核验。</p>${(a.steps||[]).map(s=>`<p>${esc({read_papers:'读取摘要',search_fulltext:'检索正文',acquire_fulltext:'获取全文'}[s.tool]||s.tool)} · ${esc(s.status==='completed'?'已完成':'未确认完成')}</p>`).join('')}</details>`;
}

function chatMessage(item,messageIndex=0) {
  if(item.role==='user')return `<div class="chat-message user"><div class="chat-role">你</div><div class="chat-bubble">${esc(item.content)}</div></div>`;
  const response=item.response||{};
  if(response.overview_mode==='llm_error')return `<div class="chat-message assistant"><div class="chat-role">勘文</div><article class="chat-bubble assistant-bubble"><p role="status">${esc(llmErrorText(response))}</p><div class="panel-actions">${['no_fulltext','no_materials'].includes(response.error)?'<button class="ghost" type="button" data-open-chat-tool="import">导入 PDF</button>':(response.error==='missing_llm_api_key'||String(response.error||'').startsWith('llm_request_failed:'))?'<button class="ghost" type="button" data-open-sources>连接设置</button>':''}</div></article></div>`;
  if(response.overview_mode==='clarification')return clarificationMessage(item,messageIndex);
  if(response.overview_mode==='map_answer')return `<div class="chat-message assistant"><div class="chat-role">勘文 · 研究地图</div><article class="chat-bubble assistant-bubble">${mapAnswerView(response,item.content)}</article></div>`;
  if(['direct_answer','method_evidence'].includes(response.overview_mode))return `<div class="chat-message assistant direct"><div class="chat-role">勘文</div><article class="chat-bubble assistant-bubble">${agentExecutionView(response)}${readingScopeView(response)}${readingAnswerView(response,item.content)}</article></div>`;
  const papers=response.papers||[];const currentMap=state.data?.map?.nodes?.length?state.data.map:response.map;
  return `<div class="chat-message assistant"><div class="chat-role">勘文</div><article class="chat-bubble assistant-bubble"><div class="chat-overview rich-text">${renderMarkdown(cleanAssistantText(item.content))}</div>${citationView(response)}${papers.length?`<div class="research-result-heading"><h3>相关文献</h3><span>${papers.length} 篇</span></div><div class="chat-papers">${papers.map(chatPaper).join('')}</div>`:''}${response.paper_selection?.retrieval_failures?.length?`<details class="source-status-details"><summary>检索来源状态</summary>${response.paper_selection.retrieval_failures.map(r=>`<p>${esc(labelOf('source',r.source))} · ${esc(labelOf('retrievalStatus',r.status))}</p>`).join('')}</details>`:''}${currentMap?.nodes?.length?`<details class="chat-map-details" data-panel="chat-map:${messageIndex}"><summary>${uiIcon('map')}研究地图 · ${(currentMap.tracks||[]).length} 个主题</summary><div class="chat-map">${mapView(currentMap,{embed:true,graphId:'chat-map-'+messageIndex})}</div></details>`:''}</article></div>`;
}

function chatPaper(paper) {
  return `<button class="chat-paper" type="button" data-chat-paper="${esc(paper.paper_id)}">
    <span class="stamps">${stamp(paper.decision, labelOf("decision", paper.decision))} ${stamp(paper.parse_status || "info", labelOf("parse", paper.parse_status, "摘要级结果"))}</span>
    <strong>${esc(paper.title)}</strong>
    <span class="tiny">${esc(paper.year || "—")} · ${esc(paper.reason || "当前候选论文")}</span>
  </button>`;
}

async function chatTurn(message, options = {}) {
  if (!message || activeChatTask()) return;
  const {clarificationTopic = null, clarificationContext = [], skipClarification = false} = options;
  const continuingSearch = skipClarification || Boolean(clarificationTopic);
  const readingMode = !continuingSearch && state.readingMode;
  const readingPaperId = continuingSearch ? "auto" : state.readingPaperId;
  const owner = state.chatKey;
  const requestedRunId = state.chatNew ? null : state.runId || null;
  const controller = new AbortController();
  const task = { id: ++state.requestCounter, key: owner, started: Date.now(), message, controller };
  state.chatTasks[owner] = task;
  state.lastFailedTask = null;
  state.question = message;
  state.chat.pendingTopic = "";
  state.chat.messages.push({ role: "user", content: message });
  const conversationBeforeRunChange = state.chat.messages.slice();
  paint();
  const timer = setInterval(() => {
    if (state.chatKey !== owner) return;
    document.querySelectorAll("[data-task-elapsed]").forEach(node => { node.textContent = Math.floor((Date.now() - task.started) / 1000); });
  }, 1000);
  try {
    const result = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ message, run_id: requestedRunId, agent_mode:!continuingSearch&&Boolean(state.agentMode)&&Boolean(requestedRunId),agent_request_id:`${task.started}-${owner}-${task.id}`, conversation_context: conversationBeforeRunChange.slice(0, -1), clarification_context: clarificationContext, clarification_topic: clarificationTopic, skip_clarification: skipClarification || undefined, constraints:state.constraints,search_supplement:searchSupplementOptions(),user_resources:state.resources,reading_mode:readingMode,map_context:continuingSearch?undefined:state.mapContext,reading_paper_id:!['auto','all'].includes(readingPaperId)?readingPaperId:undefined,reading_scope_mode:readingPaperId==='all'?'all':readingPaperId==='auto'?'auto':'selected',request_id:`${task.started}-${owner}-${task.id}` }) });
    if (state.chatKey !== owner) {
      state.backgroundNotice = { text: result.run_id ? "后台研究已完成，结果已保存在原研究中。" : "后台任务已返回；切回原研究可继续查看。", runId: result.run_id || requestedRunId };
      await refreshConversations();
      paint();
      return;
    }
    if(result.response?.map_answer)state.mapContext={map_version:result.response.map_answer.map_version,cluster_ids:result.response.map_answer.selected_cluster_ids};
    if(result.response?.reading_scope?.source==='message')state.readingPaperId='auto';
    state.chat.messages.push({ role: "assistant", content: result.response?.overview || "", response: result.response || {} });
    if (result.status === "needs_clarification") {
      state.chat.pendingTopic = clarificationTopic || message;
      state.chat.messages[state.chat.messages.length - 1].response.clarification_questions = result.response.clarification_questions || [];
      return;
    }
    if (result.status === "insufficient_evidence") {
      state.lastFailedTask = {key:owner,message,options,error:'当前论文正文材料不足，可获取全文或调整范围后重试。'};
      return;
    }
    if (result.status === "llm_unavailable") {
      state.lastFailedTask = { key: owner, message, options, error: "AI 服务暂未完成回答，可检查配置后重试。" };
      return;
    }
    if (result.run_id) {
      state.chatNew = false;
      const listing = await api("/api/runs");
      state.runs = listing.runs || state.runs;
      await refreshConversations();
      if (state.chatKey !== owner) return;
      await loadRun(result.run_id, false, true);
      const persisted = state.chat.messages || [];
      const seen = new Set(persisted.map(item => `${item.role}\u0000${item.content}`));
      state.chat.messages = conversationBeforeRunChange.filter(item => {
        const key = `${item.role}\u0000${item.content}`;
        if (seen.has(key)) return false;
        seen.add(key);return true;
      }).concat(persisted);
      return;
    }
    if (result.status !== "completed") throw new Error("服务未返回可回放的研究结果");
  } catch (error) {
    const messageText = error.name === "AbortError" ? "已停止等待。服务端可能继续处理，可稍后查看研究记录。" : `对话失败：${error.message}`;
    if (state.chatKey === owner) {
      state.lastFailedTask = { key: owner, message, options, error: messageText };
    } else {
      state.backgroundNotice = { text: messageText, runId: requestedRunId };
    }
  } finally {
    clearInterval(timer);
    delete state.chatTasks[owner];
    paint();
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

function searchCoverageView() {
  const live=state.data?.live||{};const coverage=live.coverage||{};if(!state.runId)return '';
  const report=live.filter_report||{};const plan=Array.isArray(live.query_plan)?live.query_plan:(live.query_plan?.queries||[]);const budget=live.search_budget||{};
  const failed=ONLINE_SEARCH_SOURCES.some(source=>['failed','partial'].includes(coverage[source]?.status));
  return `<details class="research-conditions"><summary>本次检索覆盖与补查</summary><p>本次执行的检索批次与来源结果。${live.constraints?`当前条件：${esc(JSON.stringify(live.constraints))}`:''}</p>${Object.entries(coverage).map(([source,c])=>`<article><p><strong>${esc(labelOf('source',source))}</strong> · ${c.successful_queries||0}/${c.query_count||0} 次查询成功 · 返回 ${c.raw_result_count||0} 条 · 合并后 ${c.visible_unique_count||0} 篇${c.truncated?' · 已截取一部分结果':''} · ${esc(c.status||'')}</p>${c.batches?.length?`<details><summary>查看 ${c.batches.length} 个实际请求批次</summary>${c.batches.map(batch=>`<p class="tiny">第${batch.page}批 · ${esc(batch.status)} · 新增独特论文 ${batch.new_unique_count??0} 篇${batch.stop_reason?` · ${esc(batch.stop_reason)}`:''}</p>`).join('')}</details>`:''}</article>`).join('')}${budget.enabled?`<p>本轮额外分页使用 ${budget.additional_requests_used??0} / ${budget.max_requests??0} 次请求，新增 ${budget.additional_unique_count??0} 篇独特论文。此预算不含基础查询和引文请求。</p>`:''}<p>元数据条件筛选：${report.before_filter??'—'} 条输入，保留 ${report.kept??'—'} 条，${(report.needs_confirmation||[]).length} 条需人工核查。</p><div class="tool-actions"><button type="button" class="ghost" data-search-more="more">补充检索并保留已有材料</button>${failed?'<button type="button" class="ghost" data-search-more="failed">仅重试失败来源</button>':''}</div>${plan.length?`<details><summary>查看实际查询</summary>${plan.map(q=>`<p>${esc(q.source)} · ${esc(q.purpose)}<code>${esc(q.query)}</code></p>`).join('')}</details>`:''}</details>`;
}

function funnelView() {
  const data=scopedAuditData();const papers=data.papers||[];const filter=state.paperFilter||'all';const q=(state.paperSearch||'').trim().toLowerCase();
  const ready=new Set(readablePapers().map(p=>p.paper_id));
  const shown=papers.filter(p=>(filter==='all'||p.decision===filter)&&(p.title+' '+(p.abstract||'')).toLowerCase().includes(q))
    .sort((a,b)=>Number(ready.has(b.paper_id))-Number(ready.has(a.paper_id)));
  const counts=data.stats?.decision_counts||{};
  return `<section class="research-section"><div class="research-heading"><div><span class="project-kicker">RESEARCH LIBRARY</span><h2>研究文献</h2><p>${papers.length} 篇候选 · ${counts.include||0} 篇纳入 · ${readablePapers().length} 篇可分析全文</p></div><button class="ghost" type="button" data-search-more="more">${uiIcon('plus')}补充检索</button></div><form class="paper-list-toolbar" data-paper-filter-form><label>${uiIcon('search')}<input name="search" value="${esc(state.paperSearch||'')}" placeholder="搜索当前论文"/></label><select name="filter" aria-label="筛选论文">${Object.entries({all:'全部论文',include:'已纳入',pending:'待定',exclude:'已排除'}).map(([k,v])=>`<option value="${k}" ${filter===k?'selected':''}>${v}</option>`).join('')}</select><button class="ghost" type="submit">筛选</button></form>${state.toolsNotice?`<p class="tool-notice">${esc(state.toolsNotice)}</p>`:''}<div class="paper-list">${shown.map(paperResultRow).join('')||'<div class="research-empty">没有匹配的论文。</div>'}</div>${searchCoverageView()}<details><summary>筛选记录 · ${(data.screening||[]).length} 条</summary>${(data.screening||[]).map(row=>`<p>${esc(titleOf(row.paper_id))} · ${esc(row.reason)}</p>`).join('')}</details></section>`;
}

function paperResultRow(p) {
  const doc=paperDocument(p.paper_id);
  const status=doc?.status==='parsed'?'全文已就绪':doc?.status==='needs_ocr'?'PDF 已保存 · 待识别':doc?.status==='failed'?'全文获取遇阻':'摘要';
  const id=esc(p.paper_id);
  const action=doc?.status==='parsed'
    ? `<button class="solid compact paper-result-primary" type="button" data-open-paper-analysis="${id}">全文分析</button><button class="ghost compact" type="button" data-open-paper-text="${id}">阅读原文</button>`
    : `<button class="ghost compact paper-result-primary" type="button" data-open-paper-text="${id}">${doc?.response_path?'查看 PDF 状态':'获取全文'}</button>`;
  return `<article class="paper-row"><div class="paper-row-main"><div class="paper-row-meta">${stamp(p.decision)}<span>${esc(p.year||'')} · ${status}</span></div><button class="text-button paper-row-title" type="button" data-inspect-paper="${id}">${esc(p.title)}</button><p class="paper-row-meta">${esc((p.authors||[]).slice(0,3).join('、'))}</p><p class="paper-row-reason">${esc(p.reason||'')}</p></div><div class="paper-row-actions">${action}</div></article>`;
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
  const paper = scopedAuditData().papers.find((item) => item.paper_id === state.selectedPaper);
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
  if (map.status === "pending" || map.status === "unavailable" || map.algorithm === "unavailable") {
    const retry = state.mapRetry.runId === state.runId ? state.mapRetry : {};
    const count = (scopedAuditData().papers || []).length;
    const pending = map.status === "pending";
    const detail = pending ? `<p>${esc(map.embedding?.reason || "引文结果已保存，可按需生成研究地图。")}</p>` :
      `<p>请先准备语义模型缓存，再重试地图生成：</p><pre class="model-command">python -m src.cli download-model</pre><details><summary>查看运行原因</summary><p class="tiny">${esc(map.embedding?.reason || "语义模型尚未就绪")}</p></details>`;
    const label = retry.loading ? "正在生成地图…" : pending ? "生成地图" : "重试地图";
    return `<section class="research-empty" role="status"><h2>${pending ? "生成研究地图" : "研究地图暂未生成"}</h2><p>当前研究保留了 ${count} 篇候选论文，可继续查看文献、全文与证据。</p>${detail}${retry.error ? `<p class="banner danger" role="alert">${esc(retry.error)}</p>` : ""}<button class="solid" type="button" data-map-retry ${retry.loading ? "disabled" : ""}>${label}</button><button class="ghost" type="button" data-workspace-goto="funnel">查看已保存文献</button></section>`;
  }
  const embed = Boolean(options.embed);
  const graphId = options.graphId || `map-${state.data?.run_id || "main"}`;
  const topicRefresh = mapTopicRefreshEntry(map);
  if (mapOverride) state.chatGraphMaps[graphId] = map;
  const contradiction = (map.contradictions || [])[0];
  const nodes = map.nodes || [];
  const edges = map.edges || [];
  const edgePolicy = map.edge_policy || {};
  const semanticMap = map.embedding?.backend === "specter2";
  ensureGraphPositions(nodes, map, graphId);
  const selectedEdge = !embed && edges.find((edge, index) => edgeKey(edge, index) === state.selectedEdgeKey);
  const edgeSummary = edgePolicy.candidate_edge_count > edges.length
    ? `${edges.length} 条关键近邻边（从 ${edgePolicy.candidate_edge_count} 条候选中筛选）`
    : `${edges.length} 条语义相似边`;
  const semanticEdgeCount = edges.filter((edge) => edge.kind === "semantic_similarity").length;
  const evidenceEdgeCount = edges.filter((edge) => edge.kind === "evidence_conflict" || edge.kind === "falsification").length;
  const clusterLegend = topicRefresh?.showTopics ? '' : (map.tracks || []).map((track, index) =>
    `<button class="legend-group" type="button" data-open-topic="${esc(track.cluster_id||track.track_id)}"><i class="legend-node cluster-${index % 6}"></i>${esc(track.label)}<span>${esc((track.paper_ids || []).length)}</span></button>`
  ).join("");
  const legendBlock = embed
    ? `<div class="graph-legend chat-graph-legend">
        ${clusterLegend}
        <span class="legend-group"><i class="legend-line semantic"></i>悬停近邻 ${semanticEdgeCount}</span>
      </div>`
    : `<div class="graph-legend">
        ${clusterLegend}
        <span class="legend-group"><i class="legend-line semantic"></i>${semanticMap ? "悬停显示 SPECTER2 关键近邻" : "悬停显示文本近邻"}</span>
      </div>`;
  return `
    ${embed ? "" : `<p class="view-hint">${semanticMap ? "节点间距离来自 SPECTER2 余弦距离的二维投影；颜色表示语义社区，节点越大表示关键近邻越多。" : "当前为文本表示演示图；位置与近邻由已记录的表示后端计算。"}悬停或选择论文时才显示近邻线与分数。</p>`}
    ${
      !embed && contradiction
        ? `<div class="banner pending">
            主问题相关论断仍待核验：${esc(contradiction.claim_text)}<br />
            支持侧：${(contradiction.support_or_context_papers || []).map(titleOf).join(" / ")}
            → 矛盾侧：${(contradiction.contradict_papers || []).map(titleOf).join(" / ")}
          </div>`
        : ""
    }
    <div class="workspace ${embed ? "graph-embed" : "map-workspace"}">
      <div class="col">
        <div class="graph-toolbar">
          <div class="graph-toolbar-copy">
            <strong>研究地图</strong>
            <span>${nodes.length} 篇论文 · ${edgeSummary} · ${semanticMap ? "SPECTER2 语义星图" : "文本关系演示图"}</span>
           </div>
          ${topicRefresh || !embed ? `<div class="graph-controls">
            ${topicRefresh ? `<button class="ghost tiny-btn" type="button" data-refresh-map-topics ${topicRefresh.task?'disabled':''}>${topicRefresh.task?'整理中…':topicRefresh.retry?'重试整理主题':'整理主题'}</button>` : ''}
            ${embed ? '' : `<button class="ghost tiny-btn" type="button" data-graph-action="relayout" data-graph-id="${esc(graphId)}">重新布局</button>
            <button class="ghost tiny-btn" type="button" data-graph-action="fit" data-graph-id="${esc(graphId)}">适配视图</button>
            <button class="ghost tiny-btn" type="button" data-graph-action="reset" data-graph-id="${esc(graphId)}">重置位置</button>`}
          </div>` : ''}
        </div>
        ${topicRefresh ? mapTopicRefreshView(topicRefresh,map) : ''}
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
          ${embed ? "" : `<div class="graph-hint">选择主题或论文，查看右侧详情 · 拖拽与缩放探索关系</div>`}
        </div>
        ${legendBlock}
        ${embed ? "" : `<details>
          <summary>关系明细（${edges.length} 条）</summary>
          <div class="edge-list">
            ${edges.map((edge, index) => `<div data-edge="${esc(edgeKey(edge, index))}">${esc(titleOf(edge.source))} ↔ ${esc(titleOf(edge.target))} · ${esc(edgeKindLabel(edge.kind))} ${edge.weight ? `· ${esc(edge.weight)}` : ""}</div>`).join("")}
          </div>
        </details>`}
      </div>
      ${!embed && selectedEdge ? relationInspector(selectedEdge) : ""}
    </div>
  `;
}

function edgeKindLabel(kind) {
  if (kind === "evidence_conflict") return "证据冲突";
  if (kind === "falsification") return "反证命中";
  if (kind === "semantic_similarity") return "语义相似";
  if (kind === "citation") return "引用关系";
  return kind || "关系";
}

function graphEdgeClass(kind) {
  if (kind === "evidence_conflict") return "conflict";
  if (kind === "falsification") return "falsification";
  if (kind === "semantic_similarity") return "semantic";
  return "default";
}

function graphEdgeMarker(kind, graphId = "") {
  const relationClass = graphEdgeClass(kind);
  const prefix = graphId ? `${graphId}-` : "";
  if (relationClass === "conflict") return `${prefix}arrow-evidence-conflict`;
  if (relationClass === "falsification") return `${prefix}arrow-falsification`;
  if (relationClass === "heuristic" || relationClass === "semantic") return `${prefix}arrow-heuristic`;
  return `${prefix}arrow-default`;
}

function edgeKey(edge, index) {
  return `${edge.source}->${edge.target}:${edge.kind || "relation"}:${edge.claim_id || edge.hit_id || edge.weight || index}`;
}

function shortGraphTitle(title, limit = 19) {
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
  if (Number.isFinite(Number(node.semantic_x)) && Number.isFinite(Number(node.semantic_y))) {
    return { x: 90 + Number(node.semantic_x) * 940, y: 70 + Number(node.semantic_y) * 540 };
  }
  const track = graphTrackIndex(node, map);
  const trackItems = (map.tracks || [])[track]?.paper_ids || [];
  const row = Math.max(0, trackItems.indexOf(node.paper_id));
  const trackCount = Math.max(1, (map.tracks || []).length);
  const columns = Math.min(3, trackCount);
  const centerX = columns === 1 ? 600 : 170 + (track % columns) * (860 / (columns - 1));
  const centerY = trackCount <= columns ? 330 : 185 + Math.floor(track / columns) * 300;
  const angle = (Math.PI * 2 * row) / Math.max(1, trackItems.length) - Math.PI / 2;
  const radius = Math.min(180, 72 + trackItems.length * 8);
  return {
    x: centerX + Math.cos(angle) * radius - 104,
    y: centerY + Math.sin(angle) * radius - 44,
  };
}

function ensureGraphPositions(nodes, map, graphId = `map-${state.data?.run_id || "main"}`) {
  const ctx = getGraphContext(graphId);
  const runKey = `${map.run_id || state.data?.run_id || graphId}:layout-${map.layout_version || 1}:${(map.edges || []).length}`;
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
  const clusterIndex = Math.max(0, graphTrackIndex(node, getGraphMap(graphId))) % 6;
  const radius = Math.min(28, 16 + Number(node.semantic_degree || 0) * 1.8);
  const cluster = node.track_id ? String(node.track_id).replace("semantic-", "簇 ") : "";
  return `<g class="graph-node cluster-${clusterIndex} ${esc(node.decision)} ${selected} ${faded}" data-paper="${esc(node.paper_id)}" transform="translate(${position.x} ${position.y})" tabindex="0" role="button" aria-label="${esc(node.title)}">
    <title>${esc(node.title)} · ${esc(graphStatusLabel(node))}</title>
    <circle r="${radius.toFixed(1)}"></circle>
    <text class="graph-node-title" x="${(radius + 8).toFixed(1)}" y="-3">${esc(title)}</text>
    <text class="graph-node-meta" x="${(radius + 8).toFixed(1)}" y="15">${esc(cluster)} · ${esc(node.year || "—")}</text>
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
  const parallel = graphParallelRank(edge, index, nodes, edges || []);
  const path = graphEdgePath(source, target, parallel);
  const midpoint = graphEdgeMidpoint(source, target, parallel);
  const related = state.selectedPaper && [edge.source, edge.target].includes(state.selectedPaper) ? "related" : "";
  return `<circle class="graph-edge-hit" data-edge="${esc(edgeKey(edge, index))}" cx="${midpoint.x.toFixed(1)}" cy="${midpoint.y.toFixed(1)}" r="18"></circle><path class="graph-edge ${relationClass} ${selected} ${related}" data-edge="${esc(edgeKey(edge, index))}" data-source="${esc(sourceNode?.paper_id || edge.source)}" data-target="${esc(targetNode?.paper_id || edge.target)}" d="${path}"><title>${esc(edgeKindLabel(edge.kind))}：${esc(titleOf(edge.source))} ↔ ${esc(titleOf(edge.target))}${edge.weight ? ` · cosine=${esc(edge.weight)}` : ""}</title></path>`;
}

function graphEdgePath(source, target, index = 0) {
  const sourceCenter = { x: source.x, y: source.y };
  const targetCenter = { x: target.x, y: target.y };
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
  const center = { x: position.x, y: position.y };
  const vx = vector.x;
  const vy = vector.y;
  const scale = 22 / Math.max(1, Math.hypot(vx, vy));
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
    <p class="tiny">${esc(titleOf(edge.source))} ↔ ${esc(titleOf(edge.target))}${edge.weight ? ` · cosine=${esc(edge.weight)}` : ""}</p>
    ${claim ? `<p><strong>关联论断</strong><br />${esc(claim.text)}</p>` : ""}
    ${edge.evidence_ids?.length ? `<p class="tiny">Evidence：${edge.evidence_ids.map((id) => esc(id)).join("、")}</p>` : ""}
    ${edge.hit_id ? `<p class="tiny">反证命中：${esc(edge.hit_id)} · 威胁 ${esc(hit?.threat || edge.threat || "—")}</p>` : ""}
    <p>${esc(edge.note || (graphEdgeClass(edge.kind) === "semantic" ? "语义相似边，不是页码证据、引用关系或确定支持。" : "该关系来自当前 run 的结构化记录，不是引用网络推断。"))}</p>
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
  const maxX = Math.max(...positions.map((position) => position.x + 180));
  const minY = Math.min(...positions.map((position) => position.y - 30));
  const maxY = Math.max(...positions.map((position) => position.y + 30));
  const width = Math.max(180, maxX - minX);
  const height = Math.max(60, maxY - minY);
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
    position.x = Math.max(36, Math.min(1110, position.x));
    position.y = Math.max(36, Math.min(640, position.y));
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
        const overlapX = 230 - Math.abs(dx);
        const overlapY = 62 - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        collisionCount += 1;
        const leftFixed = left.paper_id === fixedId;
        const rightFixed = right.paper_id === fixedId;
        const split = leftFixed || rightFixed ? 1 : 0.5;
        if (overlapX / 230 < overlapY / 62) {
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
  const map = getGraphMap(graphId);
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
        const overlapX = 230 - Math.abs(dx);
        const overlapY = 62 - Math.abs(dy);
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
    if (map.layout !== "specter2_cosine_mds") edges.forEach((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      const sourceVelocity = velocities[edge.source];
      const targetVelocity = velocities[edge.target];
      if (!source || !target || !sourceVelocity || !targetVelocity) return;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desiredDistance = 185 + (1 - Number(edge.weight || 0.82)) * 420;
      const force = Math.max(-1.4, Math.min(1.4, (distance - desiredDistance) * 0.0022));
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
      const track = graphTrackIndex(node, map);
      const trackCount = Math.max(1, (map.tracks || []).length);
      const columns = Math.min(3, trackCount);
      const targetX = map.layout === "specter2_cosine_mds" ? 90 + Number(node.semantic_x || 0.5) * 940 : (columns === 1 ? 600 : 170 + (track % columns) * (860 / (columns - 1))) - 104;
      const targetY = map.layout === "specter2_cosine_mds" ? 70 + Number(node.semantic_y || 0.5) * 540 : (trackCount <= columns ? 330 : 185 + Math.floor(track / columns) * 300) - 44;
      const anchorStrength = map.layout === "specter2_cosine_mds" ? 0.004 : 0.0007;
      velocity.x += (targetX - position.x) * anchorStrength;
      velocity.y += (targetY - position.y) * anchorStrength;
      velocity.x *= 0.91;
      velocity.y *= 0.91;
      position.x = Math.max(36, Math.min(1110, position.x + velocity.x));
      position.y = Math.max(36, Math.min(640, position.y + velocity.y));
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

function setupSingleGraph(svg, preserveLayout = false) {
  const graphId = svg.dataset.graphId || svg.id;
  const map = getGraphMap(graphId);
  const nodes = map.nodes || [];
  const edges = map.edges || [];
  state.activeGraphId = graphId;
  state.graphPositions = positionsFor(graphId);
  state.graphTransform = getGraphContext(graphId).transform;
  applyGraphTransform(svg, graphId);
  if (preserveLayout) {
    updateGraphGeometry(svg, graphId);
  } else if (graphId.startsWith("chat-map-")) {
    resolveGraphCollisions(nodes, positionsFor(graphId), "", 60);
    updateGraphGeometry(svg, graphId);
    fitGraphFor(svg, graphId, map);
  } else {
    startGraphSimulation(nodes, edges, svg, graphId);
  }

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
    nodeElement.addEventListener("pointerenter", () => {
      const paperId = nodeElement.dataset.paper;
      const neighborIds = new Set([paperId]);
      svg.querySelectorAll(".graph-edge.semantic").forEach((edgeElement) => {
        const incident = edgeElement.dataset.source === paperId || edgeElement.dataset.target === paperId;
        edgeElement.classList.toggle("related", incident);
        if (incident) {
          neighborIds.add(edgeElement.dataset.source);
          neighborIds.add(edgeElement.dataset.target);
        }
      });
      svg.querySelectorAll(".graph-node").forEach((candidate) => {
        candidate.classList.toggle("faded", !neighborIds.has(candidate.dataset.paper));
      });
    });
    nodeElement.addEventListener("pointerleave", () => {
      if (state.selectedPaper) return;
      svg.querySelectorAll(".graph-edge.semantic.related").forEach((edgeElement) => edgeElement.classList.remove("related"));
      svg.querySelectorAll(".graph-node.faded").forEach((candidate) => candidate.classList.remove("faded"));
    });
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

function setupGraphInteractions(preserveLayout = false) {
  stopGraphSimulation();
  document.getElementById("stage")?.querySelectorAll("svg.paper-graph").forEach((svg) => setupSingleGraph(svg, preserveLayout));
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

function auditWorkbench() {
  const data = scopedAuditData();
  const fulltext = data.fulltext_audit || {};
  const docs = fulltext.documents || [];
  const checks = fulltext.checks || [];
  const claims = new Set((data.claims || []).map(c => c.claim_id));
  const papers = new Set((data.papers || []).map(p => p.paper_id));
  const evidence = new Set((data.evidence || []).map(e => e.evidence_id));
  const actions = (data.next_actions || []).filter(a => a.status === "open" && (a.target_type === "claim" ? claims.has(a.target_id) : a.target_type === "paper" ? papers.has(a.target_id) : a.target_type === "evidence" ? evidence.has(a.target_id) : true));
  const actionNames = {acquire_fulltext: "补充全文", verify_evidence: "核验证据", resolve_conflict: "复核冲突", retrieve_more: "补充检索", human_review: "人工复核"};
  return `<section class="audit-workbench">
    <div class="audit-heading"><div><span class="eyebrow">证据审计工作区</span><h2>证据与原文记录</h2><p class="muted">全文文件、原文页码与人工确认记录。</p></div>
    <div class="audit-buttons"><button class="solid" data-upgrade-audit="download">获取全文并核验</button><button class="ghost" data-upgrade-audit="local">仅核验本地文件</button><button class="ghost" data-audit-export>下载审计报告</button><span class="tiny">生成独立审计快照 · 原运行保留</span></div></div>
    <div class="audit-metrics"><div><strong>${docs.filter(d => d.status === "parsed").length}</strong><span>已解析全文</span></div><div><strong>${checks.filter(c => c.status === "matched").length} / ${checks.length}</strong><span>摘录定位匹配</span></div><div><strong>${(data.decision_traces || []).filter(t => claims.has(t.claim_id)).length}</strong><span>可查看的判决记录</span></div><div><strong>${actions.length}</strong><span>待处理事项</span></div></div>
    ${!docs.length ? '<div class="banner">此运行尚未生成全文审计。点击上方按钮创建增强审计快照。</div>' : ''}
    <details open><summary>全文与证据定位</summary><div class="audit-documents">${docs.map(d => `<div class="audit-document"><strong>${esc(titleOf(d.paper_id))}</strong>${d.status === "parsed" ? `<span>已解析 ${esc(d.page_count)} 页</span>` : d.status === "failed" ? `<span>获取或解析失败</span>${d.error_code ? `<span class="tiny">${esc(d.error_code)}</span>` : ''}` : ""}${d.response_path ? `<a target="_blank" rel="noopener" href="/api/fulltext/${encodeURIComponent(state.runId)}/${encodeURIComponent(d.paper_id)}">查看原文 PDF ↗</a>` : ''}</div>`).join('')}</div></details>
    <details ${actions.length ? 'open' : ''}><summary>下一步建议（${actions.length}）</summary><div class="audit-actions">${actions.map(a => `<div><strong>${esc(actionNames[a.kind] || a.kind)} · ${esc(a.target_id)}</strong><p>${esc(a.reason)}</p></div>`).join('') || '<p class="muted">暂无待处理事项。</p>'}</div></details>
    <details><summary>查询计划与来源快照</summary>${(data.query_plans || []).map(p => `<p class="tiny">${esc(p.scope_version)} · ${esc(p.status)} · ${esc(p.query_ids.join(' / '))}</p>`).join('')}
    ${(data.queries || []).map(q => `<p><strong>${esc(q.source)}</strong> · ${esc(q.query)}</p>`).join('')}
    <div class="audit-sources">${(data.source_snapshots || []).map(s => `<div><strong>${esc(s.source)} · ${esc(s.status)}</strong><span class="tiny">${esc(s.error_code || s.content_sha256 || "无快照文件")}</span></div>`).join('')}</div></details>
  </section>`;
}

function evidenceView() {
  const { claims, evidence, claim_decisions: decisions } = scopedAuditData();
  const selected = claims.find((item) => item.claim_id === state.selectedClaim) || claims[0];
  if (!selected) return auditWorkbench() + researchReviewView() + `<div class="banner">当前结果还没有结构化论断；可从正文片段建立人工研究记录。</div>`;
  const related = evidence.filter((item) => item.claim_id === selected.claim_id);
  const decision = decisions.find((item) => item.claim_id === selected.claim_id);
  const trace = (state.data?.decision_traces || []).find(item => item.claim_id === selected.claim_id);
  return `
    ${auditWorkbench()}
    ${researchReviewView()}
    <p class="view-hint">选择论断，查看对应摘录与人工记录。</p>
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
        ${trace ? `<details class="tiny"><summary>查看本次判决记录</summary><p>${esc(trace.rationale)}</p><p>规则：${esc(trace.rule_version)} · 最终状态：${esc(labelOf("claim", trace.final_status))}</p><p>模型判决：${esc(trace.model_name || "未执行新的模型判决")} · 记录时间：${esc(trace.created_at)}</p><p>所用证据：${esc(trace.evidence_ids.join(' / '))}</p></details>` : ''}
        <details class="tiny"><summary>内部编号 ${esc(selected.claim_id)}</summary></details>
        ${related.length ? related.map(evidenceBlock).join("") : `<div class="banner danger">原文记录：—</div>`}
      </article>
    </div>
  `;
}

function evidenceBlock(item) {
  const check = (state.data?.fulltext_audit?.checks || []).find(c => c.evidence_id === item.evidence_id);
  const span = (state.data?.evidence_spans || []).find(s => s.evidence_id === item.evidence_id);
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
      ${check ? `<p class="tiny">本次定位检查：${check.status === "matched" ? "指定页精确匹配" : "未精确匹配，需要复核"}；原人工判决保留。</p>` : ''}
      ${span ? `<details class="tiny"><summary>证据链与文件指纹</summary><p>${esc(item.claim_id)} → ${esc(span.span_id)} → ${esc(item.paper_id)} → ${esc(span.snapshot_id || "尚缺全文快照")}</p><p style="overflow-wrap:anywhere">摘录 SHA-256：${esc(span.snippet_sha256)}</p></details>` : ''}
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
    <p class="view-hint">当前运行的证据可追溯性，不是模型答题准确率。</p>
    <div class="banner">指标反映可追溯性，不能解释成 RAG 一定提高任务质量。</div>
    <div class="metrics">
      ${metric("当前论文", metrics.paper_count, "")}
      ${metric("已核验证据", metrics.verified_evidence_count, "include")}
      ${metric("页码定位", metrics.page_locator_count, "")}
      ${metric("待核验论断", pct(metrics.pending_claim_rate), "pending")}
      ${metric("已支持论断", pct(metrics.supported_claim_rate), "include")}
    </div>
    ${Object.keys(delta).length ? '<div class="section-title">相对「不检索、只凭模型」</div>' : ''}
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

function paint(options) {
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
  renderShell(options);
}

async function loadRun(runId, repaint = true, push = false, preserveContext = false, signal) {
  const token = ++state.loadToken;
  if (!signal) state.chatKey = `run:${runId}`;
  const runPath = encodeURIComponent(runId);
  const [data, conversation] = await Promise.all([
    api(`/api/run/${runPath}`, {signal}),
    api(`/api/chat/${runPath}`, {signal}).catch(() => null),
  ]);
  signal?.throwIfAborted();
  if (token !== state.loadToken) return false;
  state.chatKey = `run:${runId}`;
  const changed = state.runId !== runId;
  const initialLoad = !state.data;
  const hadReadable = readablePapers().length>0;
  state.runId = runId;
  if(changed)state.agentMode=false;
  state.data = data;
  if (!preserveContext && (changed || data.research_context?.user_resources)) state.resources = {data:'',compute:'',time:'',...(data.research_context?.user_resources||{})};
  if (!preserveContext && (changed || data.research_context?.constraints || data.manifest?.constraints)) state.constraints = {year_from:'',year_to:'',research_object:'',method:'',publication_type:'any',...(data.research_context?.constraints || data.manifest?.constraints || {})};
  state.chat = { messages: conversation?.messages || [], pendingTopic: "" };
  state.chatNew = false;
  const readable = readablePapers();
  if ((!preserveContext && changed) || initialLoad || !readable.length || !hadReadable) state.readingMode = readable.length>0;
  if(!['auto','all'].includes(state.readingPaperId)&&!readable.some(p=>p.paper_id===state.readingPaperId))state.readingPaperId='auto';
  if (changed) {
    if(!preserveContext){state.context=null;state.mapContext=null;state.contextRequest++;}
    if(!preserveContext){state.sidebarOpen=false;state.methodFieldsExpanded=false;state.libraryEditing='';state.toolsNotice='';state.readingPaperId="auto";state.searchSupplement=false;state.libraryFilter='all';state.librarySearch='';state.queryPlan=null;}
    state.reviewMessage = "";
    state.fulltext = { query: "", paperId: "", section: "", result: null, loading: false, error: "" };
    state.methods = { result: null, selected: preserveContext ? state.methods.selected : [], loading: false, error: "" };
    state.library = { result: null, loading: false, error: "" };
    state.guidance = null;
  }
  const url = new URL(location.href);
  if (changed && !preserveContext && url.searchParams.get("run") !== runId) clearWorkspaceContextParams(url);
  url.searchParams.set("run", runId);
  if (state.view === "chat") url.searchParams.delete("view");
  else url.searchParams.set("view", state.view);
  if (url.href !== location.href) {
    if (push) history.pushState({}, "", url);
    else history.replaceState({}, "", url);
  }
  if (repaint) paint();
  if (state.view === "methods" && !state.methods.result) loadMethods();
  if (state.view === "library" && !state.library.result) loadLibrary();
  return true;
}

async function boot() {
  try {const health=await api('/api/health');state.capabilities=health.capabilities||null;if(health.workspace_id)state.workspaceId=health.workspace_id;} catch {}
  const [listing] = await Promise.all([api("/api/runs"), refreshConversations()]);
  state.runs = listing.runs || [];
  const preferred =
    state.runId ||
    listing.default_run_id ||
    state.runs.find((item) => item.id === "phase2-real")?.id ||
    state.runs[0]?.id;
  if (!preferred) {
    state.data = emptyWorkspace();
    state.chatNew = true;
    state.chatKey = `draft:${++state.draftCounter}`;
    state.view = "chat";
    paint();
    return;
  }
  const params = new URLSearchParams(location.search);
  state.view = params.get("view") || state.view;
  const context = workspaceContextFromUrl(params);
  if (await loadRun(preferred) && context) restoreWorkspaceContext(context);
}

if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("popstate", async (event) => {
  const params = new URLSearchParams(location.search);
  state.view = params.get("view") || "chat";
  const run = params.get("run");
  const context = event.state?.workspaceContext || workspaceContextFromUrl(params);
  if(run===state.runId&&state.renderedPanelKey===state.chatKey+':'+state.view){restoreWorkspaceContext(context);return;}
  if (run) {if(await loadRun(run))restoreWorkspaceContext(context);}
  else {
    state.loadToken += 1;
    state.chatKey = `draft:${++state.draftCounter}`;
    state.chat = { messages: [], pendingTopic: "" };
    state.chatNew = true;state.runId = "";state.data = emptyWorkspace();state.view = "chat";paint();
  }
});

boot().catch((error) => {
  document.getElementById("boot").textContent = `打开失败：${error.message}`;
});
