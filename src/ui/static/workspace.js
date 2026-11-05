/* Research objects open beside the current task. No external UI runtime. */
const WORKSPACE_ICONS = {
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  chat:'<path d="M20 11a8 8 0 0 1-8 8H5l-4 3 1.5-6A8 8 0 1 1 20 11Z"/>',
  papers:'<path d="M7 3h10l4 4v14H7z"/><path d="M17 3v5h4M3 6v13M11 12h6M11 16h6"/>',
  map:'<circle cx="5" cy="5" r="3"/><circle cx="19" cy="6" r="3"/><circle cx="13" cy="19" r="3"/><path d="m8 5 8 1M6.5 8l5 8M17.5 9l-3 7"/>',
  compare:'<path d="M3 4h18v16H3zM10 4v16M3 10h18M3 15h18"/>',
  library:'<path d="M4 3h13v18l-6.5-4L4 21zM20 5v14"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  arrow:'<path d="m12 5-7 7 7 7M5 12h15"/>',
  settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  panel:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/>',
  export:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  source:'<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2"/>'
};

function uiIcon(name) {
  return `<svg class="ui-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${WORKSPACE_ICONS[name]||WORKSPACE_ICONS.papers}</svg>`;
}

function workspaceKey() { return state.chatKey+':'+state.view; }

function rememberWorkspacePosition() {
  const stage=document.getElementById('stage');
  if(stage&&state.renderedPanelKey)state.workspacePositions[state.renderedPanelKey]=stage.scrollTop;
  const body=document.querySelector('.context-body');
  if(body&&state.context)state.context.scroll=body.scrollTop;
  const reader=document.querySelector('.reader-scroll');
  if(reader&&state.context)state.context.readerScroll=reader.scrollTop;
}

function clearWorkspaceContextParams(url) {
  for(const key of ['panel','paper','tab','page'])url.searchParams.delete(key);
}

function contextHistory(replace=false) {
  const c=state.context;if(!c)return;
  const url=new URL(location.href);clearWorkspaceContextParams(url);url.searchParams.set('panel',c.kind);
  if(c.paperId){url.searchParams.set('paper',c.paperId);url.searchParams.set('tab',c.tab||'overview');}
  if(c.tab==='reader')url.searchParams.set('page',c.page||1);
  const entry={workspaceContext:{kind:c.kind,paperId:c.paperId,tab:c.tab,page:c.page,clusterId:c.clusterId,field:c.field,query:c.query,mapVersion:c.map?.map_version,topic:c.kind==='topic'?c.topic:undefined},runId:state.runId};
  if(replace)history.replaceState(entry,'',url);
  else history.pushState(entry,'',url);
}

function workspaceContextFromUrl(params) {
  if(params.get('panel')!=='paper'||!params.get('paper'))return null;
  const tab=params.get('tab');
  const page=params.get('page');
  return {kind:'paper',paperId:params.get('paper'),
    tab:['overview','reader','analysis','notes','citations'].includes(tab)?tab:page?'reader':'overview',page};
}

function restoreWorkspaceContext(descriptor) {
  if(!descriptor){state.context=null;state.contextRequest++;renderWorkspaceContext();return;}
  if(descriptor.kind==='sources'){openWorkspaceContext({kind:'sources'},false);return;}
  if(descriptor.kind==='topic'){
    const historical=(state.chat.messages||[]).map(m=>m.response?.map_answer).find(a=>a?.map_version===descriptor.mapVersion);
    const graph=historical?{tracks:historical.topics,map_version:historical.map_version}:state.data?.map||{};
    const topic=findGraphTopic(graph,descriptor.clusterId)||descriptor.topic;
    if(topic){state.mapContext={map_version:descriptor.mapVersion||graph.map_version,cluster_ids:[topic.cluster_id||topic.track_id]};openWorkspaceContext({kind:'topic',clusterId:descriptor.clusterId,topic,map:graph},false);return;}
  }
  if(descriptor.kind==='paper'&&paperInWorkspace(descriptor.paperId)){
    const c={...descriptor,kind:'paper',page:Math.max(1,Number(descriptor.page)||1)};
    if(c.tab==='field'){
      const item=state.methods.result?.papers?.find(p=>p.paper_id===c.paperId)?.fields?.[c.field];c.reviewHit=item?.candidate;c.review=item?.review;c.hits=[];
    }
    openWorkspaceContext(c,false);return;
  }
  state.context=null;state.contextRequest++;renderWorkspaceContext();
}

function openWorkspaceContext(context, push=true) {
  rememberWorkspacePosition();
  const old=state.context;state.context={...context,ownerRun:state.runId,scroll:context.scroll||0};
  state.contextRequest=(state.contextRequest||0)+1;
  if(!old)state.contextReturnFocus=document.activeElement;
  renderWorkspaceContext();if(push)contextHistory();
}

function closeWorkspaceContext() {
  rememberWorkspacePosition();state.context=null;state.contextRequest++;
  renderWorkspaceContext();const url=new URL(location.href);
  clearWorkspaceContextParams(url);history.replaceState({},'',url);
  state.contextReturnFocus?.isConnected&&state.contextReturnFocus.focus();
}

function paperInWorkspace(id) { return (scopedAuditData().papers||[]).find(p=>p.paper_id===id); }
function paperDocument(id) { return (state.data?.fulltext_audit?.documents||[]).find(d=>d.paper_id===id); }
function readablePapers() { return (scopedAuditData().papers||[]).filter(p=>paperDocument(p.paper_id)?.status==='parsed'); }

function openPaperContext(id, tab='overview') {
  if(!paperInWorkspace(id))return;
  openWorkspaceContext({kind:'paper',paperId:id,tab,page:state.readingPages[id]||1});
}

function openReaderContext(id,page=1,quote='') {
  if(!paperInWorkspace(id))return;
  const previous=state.context?.paperId===id?state.context:{};
  openWorkspaceContext({...previous,kind:'paper',paperId:id,tab:'reader',page:Math.max(1,Number(page)||1),quote,selection:'',questionDraft:'',readerScroll:0});
}

function openFieldContext(id,field,query='') {
  if(!paperInWorkspace(id))return;
  const item=state.methods.result?.papers?.find(p=>p.paper_id===id)?.fields?.[field];
  openWorkspaceContext({kind:'paper',paperId:id,tab:'field',field,query:query||METHOD_FIELDS[field]||'',hits:[],searching:false,reviewHit:item?.candidate,review:item?.review});
  if(!item?.candidate&&state.context.query)searchContextPassages(state.context.query);
}

function findGraphTopic(graph,id) {
  const matches=t=>t.cluster_id===id||t.track_id===id;
  return graph.topics?.find(matches)||graph.tracks?.find(matches);
}

function openTopicContext(id, map=null) {
  const graph=map||state.data?.map||{};
  const topic=findGraphTopic(graph,id);
  if(!topic)return;
  state.mapContext={map_version:graph.map_version||topic.map_version,cluster_ids:[topic.cluster_id||topic.track_id]};
  openWorkspaceContext({kind:'topic',clusterId:topic.cluster_id||topic.track_id,topic,map:graph});
}

function sourceButton(source,label='查看原文') {
  return `<button type="button" class="source-pill" data-context-source="${esc(source.paper_id)}" data-page="${esc(source.page||1)}" data-quote="${esc(source.quote||source.snippet||'')}">${uiIcon('source')}${esc(label)}</button>`;
}

function contextQuestionKey(c,run=state.runId) {
  if(c?.paperId)return JSON.stringify([run,'paper',c.paperId]);
  if(c?.clusterId)return JSON.stringify([run,'topic',c.clusterId]);
  return null;
}

function contextQuestionProgress(entry) {
  if(entry?.task){
    const task=entry.task;
    return `<div class="panel-actions context-question-progress"><p class="inline-progress" role="status" data-context-question-stage>${esc(task.label)}</p><span class="tiny" aria-hidden="true">已等待 <span data-context-question-elapsed>${Math.floor((Date.now()-task.started)/1000)}</span> 秒</span><button type="button" class="ghost" data-stop-context-question>停止等待</button></div>`;
  }
  return entry?.error?`<div class="panel-actions context-question-progress"><p role="status">${esc(entry.error)}</p><button class="ghost" type="button" data-retry-context-question>重试本次请求</button></div>`:'';
}

function contextCitationKey(c,run=state.runId) {
  return c?.paperId?JSON.stringify([run,c.paperId]):null;
}

const CITATION_LABELS={references:'参考文献',citations:'后续引用'};

function citationResultMessage(result) {
  if(result.message)return result.message;
  if(result.status==='already_present')return '找到的引文已在当前研究中。';
  if(result.status==='empty')return '这次没有找到符合条件的引文。';
  if(result.status==='unavailable')return ({timeout:'引文来源响应超时，可以重试。',rate_limited:'引文来源暂时限流，可以稍后重试。',not_found:'引文来源暂无这篇论文的记录。'})[result.source_status]||'引文来源暂时不可用，可以重试。';
  return result.added_count?`已新增 ${result.added_count} 篇论文。`:'已保存引文关系。';
}

function contextCitationsView(c) {
  const entry=state.contextCitations.get(contextCitationKey(c));
  const task=entry?.task;
  const result=entry?.result;
  const progress=task?`<div class="panel-actions citation-progress"><p class="inline-progress" role="status" data-citation-stage>${esc(task.label)}</p><span class="tiny" aria-hidden="true">已等待 <span data-citation-elapsed>${Math.floor((Date.now()-task.started)/1000)}</span> 秒</span><button type="button" class="ghost" data-stop-citations>停止等待</button></div>`:'';
  const direction=CITATION_LABELS[entry?.retry?.direction];
  const retry=entry?.retry?`<button class="ghost" type="button" data-retry-citations>重试${esc(direction||'引文查找')}</button>`:'';
  const error=entry?.error?`<p role="status" class="source-diagnostic">${esc(entry.error)}</p>`:'';
  const open=result?.runId&&result.runId!==state.runId?`<a class="ghost" data-open-citation-run href="/?run=${encodeURIComponent(result.runId)}&amp;view=${encodeURIComponent(state.view)}&amp;panel=paper&amp;paper=${encodeURIComponent(c.paperId)}&amp;tab=citations">打开已保存研究</a>`:'';
  const rows=(result?.papers||[]).map(p=>{
    const title=esc(p.title||p.paper_id);
    const heading=paperInWorkspace(p.paper_id)?`<button class="text-button" type="button" data-inspect-paper="${esc(p.paper_id)}">${title}</button>`:
      /^https?:\/\//i.test(p.url||'')?`<a class="text-button" href="${esc(p.url)}" target="_blank" rel="noopener">${title}</a>`:`<strong>${title}</strong>`;
    return `<article class="paper-row"><div class="paper-row-main">${heading}<p class="paper-row-meta">${[p.year,p.reason].filter(Boolean).map(esc).join(' · ')}</p></div></article>`;
  }).join('');
  return `<div class="context-citations"><h3>沿引文继续探索</h3><p class="muted">查看这篇论文的参考文献或后续研究。</p><div class="panel-actions">${Object.entries(CITATION_LABELS).map(([key,label])=>`<button class="ghost" type="button" data-panel-related="${key}" ${task?'disabled':''}>${label}</button>`).join('')}</div>${progress}${error}${result?`<div data-citation-results><h3>${esc(CITATION_LABELS[result.direction])}</h3><p class="source-diagnostic" role="status">${esc(citationResultMessage(result))}</p>${rows?`<div class="paper-list">${rows}</div>`:''}</div>`:''}${open||retry?`<div class="panel-actions">${retry}${open}</div>`:''}</div>`;
}

function contextPanelView() {
  const c=state.context;
  if(!c)return '<aside id="context-panel" class="context-panel" hidden></aside>';
  const paper=c.paperId?paperInWorkspace(c.paperId):null;
  const acquisition=paper&&state.acquisitionTasks.get(`${state.runId}:${c.paperId}`);
  const progress=acquisition?`<div class="panel-actions"><p class="inline-progress" role="status" data-fulltext-stage>${esc(acquisition.label)}</p><span class="tiny" aria-hidden="true">已等待 <span data-fulltext-elapsed>${Math.floor((Date.now()-acquisition.started)/1000)}</span> 秒</span><button type="button" class="ghost" data-stop-fulltext>停止获取</button></div>`:'';
  const title=c.kind==='sources'?'检索来源':c.kind==='topic'?(c.topic?.label||'研究主题'):paper?.title||'研究材料';
  let content='';
  if(c.kind==='sources')content=sourceSettingsView();
  else if(c.kind==='topic')content=topicContextView(c);
  else if(paper)content=paperContextView(paper,c);
  const questionProgress=contextQuestionProgress(state.contextQuestions.get(contextQuestionKey(c)));
  return `<aside id="context-panel" class="context-panel" aria-label="研究材料面板"><header class="context-header"><div><span class="project-kicker">${c.kind==='sources'?'工作区设置':c.kind==='topic'?'研究地图':'论文工作区'}</span><h2 title="${esc(title)}">${esc(title)}</h2></div><button class="icon-button context-close" type="button" data-close-context aria-label="返回研究任务">${uiIcon('close')}</button></header>${paper?`<div class="context-tabs" role="tablist" aria-label="论文内容">${[['overview','概览'],['reader','原文'],['analysis','全文分析'],['notes','笔记'],['citations','引文'],...(c.field?[['field','字段依据']]:[])].map(([key,label])=>`<button type="button" role="tab" aria-selected="${c.tab===key}" data-context-tab="${key}">${label}</button>`).join('')}</div>`:''}<div class="context-body">${progress}${questionProgress}${c.notice?`<p class="inline-progress" role="status">${esc(c.notice)}</p>`:''}${c.error?`<p class="banner danger" role="alert">${esc(c.error)}</p>`:''}${content}</div><div class="context-resize" role="separator" aria-label="调整材料面板宽度" aria-orientation="vertical" tabindex="0"></div></aside>`;
}

function paperContextView(p,c) {
  const doc=paperDocument(p.paper_id);const readable=doc?.status==='parsed';
  if(c.tab==='reader')return readerContextView(p,c,doc);
  if(c.tab==='analysis')return readable?paperAnalysisView(p,c,doc):fulltextAcquisitionView(p,c,doc);
  if(c.tab==='notes'){
    const item=state.library.result?.items?.find(x=>x.paper_id===p.paper_id);
    if(!item)return '<p class="inline-progress" role="status">正在打开阅读记录…</p>';
    const merged={...item,...(getFormDraft('library',p.paper_id)||{}),hasDraft:Boolean(getFormDraft('library',p.paper_id))};
    const html=libraryCard(merged);return `<div class="context-notes">${html}</div>`;
  }
  if(c.tab==='citations')return contextCitationsView(c);
  if(c.tab==='field')return contextFieldView(p,c);
  return `<article class="context-paper"><p class="paper-metadata">${esc(p.year||'年份未记录')}${p.venue?' · '+esc(p.venue):''}</p><p class="paper-metadata">${esc((p.authors||[]).join('、'))}</p><div class="panel-actions"><button class="${readable?'ghost':'solid'}" type="button" data-context-read>${uiIcon('papers')}${readable?'阅读原文':'获取全文'}</button>${readable?'<button class="solid" type="button" data-context-tab="analysis">全文分析</button>':''}<button class="ghost" type="button" data-panel-compare>${uiIcon('compare')}加入对比</button><button class="ghost" type="button" data-context-tab="notes">${uiIcon('library')}笔记</button></div><section class="paper-overview"><h3>摘要</h3><p>${esc(p.abstract||'—')}</p></section>${p.reason?`<section><h3>筛选理由</h3><p>${esc(p.reason)}</p></section>`:''}<details class="paper-metadata"><summary>论文信息</summary><p>${esc(p.doi_or_arxiv||'')}</p>${/^https?:\/\//i.test(p.url||'')?`<a href="${esc(p.url)}" target="_blank" rel="noopener">论文来源 ↗</a>`:''}<p>${readable?`已处理 ${doc.page_count} 页`:'题录与摘要'}</p></details></article>`;
}

function fulltextIssue(doc, attempted=false) {
  const code=doc?.error_code||'';
  if(code==='pdf_processing_timeout')return 'PDF 已保存，正文提取超时。可以先打开 PDF，或重试提取正文。';
  if(code==='acquisition_wait_timeout')return '等待全文获取超时。可以重试或导入本地 PDF。';
  if(code==='acquisition_stopped')return '已停止等待。可以重试或导入本地 PDF。';
  if(code==='acquisition_load_failed')return '全文获取已结束，打开结果时连接中断。可重新打开已保存结果。';
  if(code==='acquisition_request_failed')return '读取全文任务失败。可重试或导入本地 PDF。';
  if(doc?.status==='needs_ocr')return 'PDF 已保存。可先打开原件，扫描页的正文分析需要文字识别。';
  const http=code.match(/^http_(\d{3})$/)?.[1]||doc?.error_message?.match(/HTTP Error (\d{3})/)?.[1];
  if(code==='arxiv_withdrawn')return '论文当前版本已撤回。可打开论文来源页查看撤回说明。';
  if(http==='404'||http==='410')return `来源没有提供当前版本的 PDF（${http}）。可在论文来源页核对版本和全文入口。`;
  if(http==='401'||http==='403')return `来源限制了 PDF 下载（${http}）。可从有访问权限的渠道取得 PDF 后导入。`;
  if(http==='429')return '全文来源正在限流（429）。稍后可重试，或导入本地 PDF。';
  if(code==='fulltext_not_available'||!doc)return attempted
    ?'当前来源未提供可自动下载的公开 PDF。可打开「论文来源」查看全文，拿到文件后点「导入本地 PDF」。'
    :'当前只有题录和摘要。点击「获取开放全文」尝试下载，或导入本地 PDF。正文处理完成后会打开「全文分析」。';
  if(code==='pdf_parse_failed')return 'PDF 解析失败。可打开已保存的文件检查，或导入可阅读的 PDF。';
  if(code==='pdf_timeout')return '来源响应超时。可重试，或从论文来源下载 PDF 后导入。';
  if(code==='pdf_connection_failed')return '连接全文来源时中断。可重试，或在浏览器中打开论文来源下载 PDF。';
  if(code==='response_not_pdf')return '全文链接返回了网页。请打开论文来源页查找可下载的 PDF。';
  if(code==='pdf_too_large')return 'PDF 超过处理大小限制。';
  return doc.status==='failed'?'这次没有成功获取可分析的正文。可重试，或从论文来源页取得 PDF 后导入。':'可获取开放 PDF，或导入本地 PDF。';
}

function fulltextAcquisitionView(p,c,doc) {
  const key=`${state.runId}:${p.paper_id}`;
  const issue=state.acquisitionIssues.get(key);
  const active=state.acquisitionTasks.has(key);
  const acquisition=state.data?.manifest?.acquisition;
  const attempted=Boolean(issue || (acquisition?.download_requested && acquisition.requested_paper_ids?.includes(p.paper_id)));
  const record=issue||doc;
  const original=doc?.response_path?`<a class="ghost" href="/api/fulltext/${encodeURIComponent(state.runId)}/${encodeURIComponent(p.paper_id)}" target="_blank" rel="noopener">打开已保存的 PDF ↗</a>`:'';
  const saved=issue?.result_run_id?`<a class="ghost" href="/?run=${encodeURIComponent(issue.result_run_id)}&amp;panel=paper&amp;paper=${encodeURIComponent(p.paper_id)}&amp;tab=analysis">打开已保存结果</a>`:'';
  const source=/^https?:\/\//i.test(p.url||'')?`<a href="${esc(p.url)}" target="_blank" rel="noopener">论文来源 ↗</a>`:'';
  const actions=active?'':`<button type="button" class="solid" data-panel-acquire ${c.busy?'disabled':''}>${record?.status==='needs_ocr'?'重试文字识别':record?.error_code==='pdf_processing_timeout'?'重试正文提取':attempted?'重新获取全文':'获取开放全文'}</button><button type="button" class="ghost" data-panel-import ${c.busy?'disabled':''}>导入本地 PDF</button>`;
  return `<section class="research-empty"><h3>获取论文全文</h3>${active?'':`<p${attempted?' role="status"':''}>${esc(fulltextIssue(record,attempted))}</p>`}<div class="panel-actions">${actions}${saved}${original}</div>${source}<input type="file" data-panel-file accept="application/pdf,.pdf" hidden/></section>`;
}

function paperAnalysisView(p,c,doc) {
  const busy=Boolean(state.contextQuestions.get(contextQuestionKey(c))?.task);
  return `<section class="paper-analysis"><div class="paper-analysis-header"><h3>全文分析</h3><p>已处理 ${esc(doc.page_count)} 页。可查找方法、数据、实验设置与结果的原文依据。</p><div class="panel-actions"><button class="solid" type="button" data-analyze-paper ${busy?'disabled':''}>分析方法与实验</button><button class="ghost" type="button" data-context-tab="reader">阅读原文</button></div></div>${contextQuestionForm(p,c)}</section>`;
}

function readerContextView(p,c,doc) {
  if(doc?.status!=='parsed')return fulltextAcquisitionView(p,c,doc);
  const total=doc.page_count||1;const page=Math.min(total,Math.max(1,c.page||1));c.page=page;
  const pages=Array.from({length:Math.min(3,total-page+1)},(_,i)=>page+i);
  return `<div class="context-reader"><div class="reader-toolbar"><div class="reader-pager"><button type="button" class="icon-button" data-reader-prev ${page<=1?'disabled':''} aria-label="上一页">${uiIcon('arrow')}</button><label>页码<input type="number" data-reader-jump min="1" max="${total}" value="${page}" aria-label="跳转到PDF页"/></label><span data-reader-page>/ ${total}</span><button type="button" class="icon-button" data-reader-next ${page>=total?'disabled':''} aria-label="下一页"><span style="display:inline-flex;transform:rotate(180deg)">${uiIcon('arrow')}</span></button></div><div><button type="button" class="ghost compact" data-reader-zoom="-">−</button><span data-reader-zoom-label>${Math.round((c.zoom||1)*100)}%</span><button type="button" class="ghost compact" data-reader-zoom="+">＋</button></div></div>${c.quote?`<details class="reader-quotation" open><summary>引用片段</summary><blockquote>${esc(c.quote)}</blockquote></details>`:''}<div class="reader-scroll" tabindex="0" aria-label="连续原文阅读"><div class="reader-canvas" style="width:${Math.round((c.zoom||1)*100)}%">${pages.map(n=>`<div class="reader-page-wrap" data-page="${n}"><img class="reader-page" src="/api/pdf-page/${encodeURIComponent(state.runId)}/${encodeURIComponent(p.paper_id)}/${n}" alt="${esc(p.title)} PDF第${n}页" loading="${n===page?'eager':'lazy'}"/><div class="reader-text-layer" data-reader-text-page="${n}"></div><span class="reader-page-label">第 ${n} 页</span></div>`).join('')}</div></div><div class="context-footer"><button class="solid" type="button" data-ask-reader>围绕选中原文提问</button><a href="/api/fulltext/${encodeURIComponent(state.runId)}/${encodeURIComponent(p.paper_id)}#page=${page}" target="_blank" rel="noopener">打开 PDF ↗</a></div>${contextQuestionForm(p,c)}</div>`;
}

function contextQuestionForm(p,c) {
  const focus=c.tab==='reader'?(c.selection?` · ${esc(c.selection.slice(0,90))}`:` · 第 ${c.page||1} 页`):'';
  const entry=state.contextQuestions.get(contextQuestionKey(c));
  const draft=c.questionDraft??getFormDraft('context-question',p.paper_id)?.question;
  const answer=entry?.answer||(state.chat.messages||[]).findLast(item=>{
    const scope=item.response?.reading_scope?.paper_ids;
    return item.role==='assistant'&&(item.response?.method_analysis?.paper_id===p.paper_id||(scope?.length===1&&scope[0]===p.paper_id));
  });
  return `<form data-context-question class="context-question"><div class="selection-chip">${esc(p.title)}${focus}</div><label>围绕这篇论文提问<textarea name="question" rows="2" maxlength="2000" placeholder="例如：实验用了哪些基线？">${esc(draft||'')}</textarea></label><button class="solid" type="submit" ${entry?.task?'disabled':''}>提问</button></form>${answer?`<article class="context-answer">${readingAnswerView(answer.response||{},answer.content||'')}</article>`:''}`;
}

function contextFieldView(p,c) {
  const hit=c.reviewHit;
  return `<section><h3>${esc(METHOD_FIELDS[c.field]||'正文依据')}</h3><form class="context-search" data-context-search><label>查找原文<input name="query" value="${esc(c.query||'')}" required maxlength="2000"/></label><button class="solid" type="submit" ${c.searching?'disabled':''}>${c.searching?'查找中…':'搜索'}</button></form>${hit?`<article class="passage-card"><blockquote>${esc(hit.quote||hit.text)}</blockquote>${sourceButton(hit,`第 ${hit.page} 页`)}${reviewEditor(hit,c.field||'',c.review,true)}</article>`:''}<div class="context-hits">${(c.hits||[]).map((h,i)=>`<article class="passage-card"><span class="paper-row-meta">第 ${h.page} 页 · ${esc(h.section||'正文')}</span><blockquote>${esc(h.text)}</blockquote><div class="panel-actions">${sourceButton(h,`查看第 ${h.page} 页`)}<button type="button" class="ghost" data-select-field-hit="${i}">选择这段依据</button></div></article>`).join('')}</div></section>`;
}

function topicContextView(c) {
  const t=c.topic;
  const ids=t.paper_ids||t.member_paper_ids||[];
  const archived=new Map((t.papers||[]).map(p=>[p.paper_id,p]));
  const tasks=new Map((t.paper_tasks||[]).map(task=>[task.paper_id,task]));
  const direction=t.common_direction;
  const sourceView=s=>`<p><strong>${esc(archived.get(s.paper_id)?.title||titleOf(s.paper_id))}</strong> · ${s.field==='abstract'?'摘要':'题名'}</p><blockquote>${esc(s.quote)}</blockquote>`;
  const paperRows=ids.map(id=>{
    const current=paperInWorkspace(id);
    const p=current||archived.get(id);
    if(!p)return '';
    const task=tasks.get(id);
    const row=`<span class="paper-row-main"><strong>${esc(p.title)}</strong>${task?`<span class="topic-task">${esc(task.task)}</span>`:''}<span class="paper-row-meta">${esc(p.year||'')}${current?` · ${paperDocument(id)?.status==='parsed'?'已有全文':'摘要'}`:''}</span></span>`;
    return current?`<button class="paper-row" type="button" data-inspect-paper="${esc(id)}">${row}</button>`:`<article>${row}</article>`;
  }).join('');
  return `<article class="topic-card">
    <div class="topic-heading"><span class="source-pill">主题 ${esc(t.display_index||'')} · ${ids.length} 篇论文</span><h3>${esc(t.label)}</h3></div>
    <details class="topic-name-editor"><summary>编辑主题名称${t.label_source==='human'?' · 手动命名':''}</summary><form class="context-search" data-topic-label><label>主题名称<input name="label" maxlength="80" required value="${esc(t.label)}"/></label><button class="solid" type="submit">保存名称</button></form></details>
    <div class="panel-actions"><button class="solid" type="button" data-topic-ask>解释这个主题</button><button class="ghost" type="button" data-topic-compare>比较方法</button></div>
    <section><h4>${direction?'共同方向':'分组依据'}</h4><p>${esc(direction||'按题名与摘要的语义相近程度分组，可逐篇查看研究任务。')}</p>
    ${direction&&t.common_sources?.length?`<details><summary>共同方向来源</summary>${t.common_sources.map(sourceView).join('')}</details>`:''}</section>
    <section><h4>各篇论文</h4><div class="topic-paper-list">${paperRows}</div>
    ${tasks.size?`<details><summary>逐篇任务来源</summary>${[...tasks.values()].map(task=>sourceView(task.source)).join('')}</details>`:''}</section>
  </article>`;
}

function sourceSettingsView() {
  const d=state.sources;
  if(!d?.result)return '<p class="inline-progress" role="status">正在读取检索来源…</p>';
  const sources=d.result.sources.filter(source=>ONLINE_SEARCH_SOURCES.includes(source.id));
  return `<section class="source-settings"><p class="muted">分别检查检索来源的连接和配置。</p>${sources.map(s=>sourceSettingsCard(s,d.testing===s.id)).join('')}</section>`;
}

function sourceSettingsCard(s, testing) {
  const statuses={untested:'尚未测试',connected:'连接正常',rate_limited:'已限流',authentication_failed:'认证失败',
    authentication_required:'需要密钥',network_error:'网络连接失败',unavailable:'服务暂不可用',failed:'连接失败'};
  const connection=s.connection||{};
  const key=s.configuration?.environment_variable;
  const config=key?`<details${!s.key_configured&&connection.status!=='connected'?' open':''}><summary>配置 API Key</summary><p>在本机项目的 .env 中填写，保存后重启勘文。</p><code>${esc(key)}=你的密钥</code>${s.configuration.apply_url?`<p><a href="${esc(s.configuration.apply_url)}" target="_blank" rel="noopener">获取 API Key ↗</a></p>`:''}</details>`:'';
  return `<article class="source-card"><div><h3>${esc(s.label)}</h3><span class="source-state ${esc(connection.status||'')}">${esc(statuses[connection.status]||'尚未测试')}${connection.http_status&&connection.http_status!==200?` · ${esc(connection.http_status)}`:''}</span></div><p>${key?(s.key_configured?'API Key 已配置':'API Key 未配置 · 匿名访问'):'公共访问'}</p>${connection.message?`<p class="source-diagnostic" role="status">${esc(connection.message)}</p>`:''}${s.rate_limit?.cooldown_seconds?`<p class="tiny">建议 ${Math.ceil(s.rate_limit.cooldown_seconds)} 秒后重试</p>`:''}<button class="ghost" type="button" data-test-source="${esc(s.id)}" ${testing?'disabled':''}>${testing?'测试中…':'测试连接'}</button>${config}</article>`;
}

function renderWorkspaceContext() {
  const shell=document.querySelector('.shell');if(!shell)return;
  shell.classList.toggle('context-open',Boolean(state.context));
  const old=document.getElementById('context-panel');if(old)old.outerHTML=contextPanelView();
  bindContextPanel();
}

function bindContextPanel() {
  const panel=document.getElementById('context-panel');if(!panel||!state.context)return;
  const c=state.context;const run=state.runId;
  panel.querySelector('[data-close-context]')?.addEventListener('click',closeWorkspaceContext);
  panel.querySelectorAll('[data-context-tab]').forEach(b=>b.onclick=()=>switchPaperContextTab(c,b.dataset.contextTab));
  bindResearchControls(panel);bindWorkbenchTools(panel);bindFormDrafts(panel);bindWorkspaceObjectActions(panel);
  panel.querySelectorAll('[data-panel-compare]').forEach(b=>b.onclick=()=>{const selected=state.methods.selected.length?state.methods.selected:defaultComparisonIds(state.methods.result?.papers||[]);if(!selected.includes(c.paperId)&&selected.length<4)state.methods.selected=[...selected,c.paperId];c.notice='已加入方法对比';renderWorkspaceContext();});
  panel.querySelector('[data-context-read]')?.addEventListener('click',()=>switchPaperContextTab(c,'reader'));
  panel.querySelector('[data-panel-acquire]')?.addEventListener('click',acquireContextPaper);
  panel.querySelector('[data-stop-fulltext]')?.addEventListener('click',()=>state.acquisitionTasks.get(`${run}:${c.paperId}`)?.controller.abort());
  const questionEntry=state.contextQuestions.get(contextQuestionKey(c,run));
  panel.querySelector('[data-stop-context-question]')?.addEventListener('click',()=>questionEntry?.task?.controller.abort());
  panel.querySelector('[data-retry-context-question]')?.addEventListener('click',()=>{
    if(questionEntry?.retry)runContextQuestion(c,questionEntry.retry);
  });
  panel.querySelector('[data-panel-import]')?.addEventListener('click',()=>panel.querySelector('[data-panel-file]').click());
  panel.querySelector('[data-panel-file]')?.addEventListener('change',importContextPaper);
  panel.querySelector('[data-analyze-paper]')?.addEventListener('click',()=>askFromContext('分析这篇论文的方法与实验',false,'methods_experiments'));
  panel.querySelectorAll('[data-panel-related]').forEach(b=>b.onclick=()=>exploreContextCitations(b.dataset.panelRelated));
  const citationEntry=state.contextCitations.get(contextCitationKey(c,run));
  panel.querySelector('[data-stop-citations]')?.addEventListener('click',()=>citationEntry?.task?.controller.abort());
  panel.querySelector('[data-retry-citations]')?.addEventListener('click',()=>{
    if(citationEntry?.retry)runContextCitation(c,citationEntry.retry);
  });
  if(c.kind==='sources'&&!state.sources?.result&&!state.sources?.loading)loadSources();
  panel.querySelectorAll('[data-test-source]').forEach(b=>b.onclick=()=>testSource(b.dataset.testSource));
  if(c.tab==='notes'){
    const editor=panel.querySelector('.library-editor');if(editor)editor.open=true;
    if(!state.library.result&&!state.library.loading)loadLibrary().then(()=>{if(state.context===c)renderWorkspaceContext();});
  }
  panel.querySelector('[data-context-search]')?.addEventListener('submit',e=>{e.preventDefault();searchContextPassages(new FormData(e.target).get('query'));});
  panel.querySelectorAll('[data-select-field-hit]').forEach(b=>b.onclick=()=>{c.reviewHit=c.hits[Number(b.dataset.selectFieldHit)];renderWorkspaceContext();});
  panel.querySelectorAll('[data-reader-prev],[data-reader-next]').forEach(b=>b.onclick=()=>jumpContextPage(c.page+(b.hasAttribute('data-reader-prev')?-1:1)));
  panel.querySelector('[data-reader-jump]')?.addEventListener('change',e=>jumpContextPage(Number(e.target.value)));
  panel.querySelectorAll('[data-reader-zoom]').forEach(b=>b.onclick=()=>{c.zoom=Math.max(.7,Math.min(2,(c.zoom||1)+(b.dataset.readerZoom==='+'?.15:-.15)));renderWorkspaceContext();});
  panel.querySelector('[data-ask-reader]')?.addEventListener('click',()=>{
    const selection=window.getSelection();const text=selection?.toString().trim();
    if(text&&selection.anchorNode&&panel.querySelector('.reader-scroll')?.contains(selection.anchorNode)){c.selection=text.slice(0,3500);const page=selection.anchorNode.parentElement?.closest('[data-page]');if(page)c.page=Number(page.dataset.page);}
    else c.selection=c.quote||'';
    renderWorkspaceContext();document.querySelector('[data-context-question] textarea')?.focus();
  });
  const form=panel.querySelector('[data-context-question]');
  if(form){
    form.querySelector('textarea').oninput=e=>{
      c.questionDraft=e.target.value;
      rememberFormDraft('context-question',c.paperId,'','',{question:c.questionDraft});
    };
    form.onsubmit=e=>{e.preventDefault();askFromContext(new FormData(form).get('question'));};
  }
  panel.querySelector('[data-topic-label]')?.addEventListener('submit',saveContextTopicLabel);
  panel.querySelector('[data-topic-ask]')?.addEventListener('click',()=>askFromContext('解释这个主题的研究内容、共同点和代表论文。',true));
  panel.querySelector('[data-topic-compare]')?.addEventListener('click',()=>{state.methods.selected=(c.topic.paper_ids||c.topic.member_paper_ids||[]).filter(id=>paperDocument(id)?.status==='parsed').slice(0,4);setView('methods');});
  if(c.tab==='reader')hydrateReaderText(panel,c,run);
  const body=panel.querySelector('.context-body');if(body)body.scrollTop=c.scroll||0;
  const scroll=panel.querySelector('.reader-scroll');if(scroll)scroll.scrollTop=c.readerScroll||0;
  const resize=panel.querySelector('.context-resize');if(resize){resize.onpointerdown=e=>{resize.setPointerCapture(e.pointerId);resize.onpointermove=m=>{const width=Math.max(340,Math.min(innerWidth*.58,innerWidth-m.clientX));document.documentElement.style.setProperty('--context-width',width+'px');};resize.onpointerup=()=>{resize.onpointermove=null;};};resize.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const width=panel.getBoundingClientRect().width+(e.key==='ArrowLeft'?24:-24);document.documentElement.style.setProperty('--context-width',Math.max(340,Math.min(innerWidth*.58,width))+'px');}};}
}

function switchPaperContextTab(context,tab) {
  context.tab=tab;context.scroll=0;contextHistory(true);renderWorkspaceContext();
}

function bindWorkspaceObjectActions(root) {
  root.querySelectorAll('[data-edit-method-field]').forEach(b=>b.onclick=()=>openFieldContext(b.dataset.editMethodField,b.dataset.field));
  root.querySelectorAll('[data-paper-filter-form]').forEach(form=>form.onsubmit=e=>{e.preventDefault();const v=new FormData(form);state.paperSearch=String(v.get('search')||'');state.paperFilter=String(v.get('filter')||'all');paint();});
  root.querySelectorAll('[data-inspect-paper]').forEach(b=>b.onclick=()=>openPaperContext(b.dataset.inspectPaper));
  root.querySelectorAll('[data-open-paper-analysis]').forEach(b=>b.onclick=()=>openPaperContext(b.dataset.openPaperAnalysis,'analysis'));
  root.querySelectorAll('[data-context-source]').forEach(b=>b.onclick=()=>openReaderContext(b.dataset.contextSource,b.dataset.page,b.dataset.quote));
  root.querySelectorAll('[data-open-topic]').forEach(b=>b.onclick=()=>{const version=b.dataset.mapVersion;const historical=version&&(state.chat.messages||[]).map(m=>m.response?.map_answer).find(a=>a?.map_version===version);openTopicContext(b.dataset.openTopic,historical?{tracks:historical.topics,map_version:historical.map_version}:null);});
  root.querySelectorAll('[data-open-sources]').forEach(b=>b.onclick=()=>openWorkspaceContext({kind:'sources'}));
  root.querySelectorAll('[data-refresh-map-topics]').forEach(b=>b.onclick=refreshMapTopics);
  root.querySelectorAll('[data-stop-map-topics]').forEach(b=>b.onclick=()=>mapTopicRefreshEntry(state.data?.map)?.task?.controller.abort());
}

function mapTopicRefreshEntry(map) {
  const current=state.data?.map;
  if(!state.runId||!current?.nodes?.length||!map)return null;
  if(map!==current&&(!map.map_version||map.map_version!==current.map_version||(map.run_id&&map.run_id!==state.runId)))return null;
  const entry=state.mapTopicRefresh.get(state.runId);
  return entry?.mapVersion===current.map_version?entry:{};
}

function mapTopicRefreshView(entry,map) {
  const task=entry.task;
  if(task)return `<div class="map-topic-notice"><p class="inline-progress" role="status" data-map-topic-stage>${esc(task.label)}</p><span class="tiny" aria-hidden="true">已等待 <span data-map-topic-elapsed>${Math.floor((Date.now()-task.started)/1000)}</span> 秒</span><button type="button" class="ghost tiny-btn" data-stop-map-topics>停止等待</button></div>`;
  if(!entry.message)return '';
  const topics=entry.showTopics?(map.topics||map.tracks||[]):[];
  const cards=topics.map((topic,index)=>`<button class="legend-group" type="button" data-open-topic="${esc(topic.cluster_id||topic.track_id)}"><i class="legend-node cluster-${index%6}" aria-hidden="true"></i>${esc(topic.label)}<span>${esc(topic.member_count??topic.paper_ids?.length??0)} 篇</span></button>`).join('');
  return `<div class="map-topic-notice"><p role="status" data-map-topic-status>${esc(entry.message)}</p></div>${cards?`<div class="graph-legend map-topic-results" aria-label="主题整理结果" data-map-topic-results>${cards}</div>`:''}`;
}

function applyMapTopicRefresh(current,result) {
  const existing=new Map((current.topics||[]).map(topic=>[topic.cluster_id,topic]));
  const topics=result.topics.map(topic=>{
    const saved=existing.get(topic.cluster_id);
    return saved?.label_source==='human'&&saved.label_updated_at>(topic.label_updated_at||'')
      ? {...topic,label:saved.label,label_source:'human',label_updated_at:saved.label_updated_at}:topic;
  });
  const byTrack=new Map(topics.filter(topic=>topic.track_id).map(topic=>[topic.track_id,topic]));
  const next={...current,map_version:result.map_version,topic_naming_status:result.naming_status,topics,
    tracks:(current.tracks||[]).map(track=>({...track,...byTrack.get(track.track_id)}))};
  state.data.map=next;
  const panel=state.context;
  if(panel?.kind==='topic'&&panel.map===current){
    const topic=findGraphTopic(next,panel.clusterId);
    if(topic){panel.topic=topic;panel.map=next;}
  }
}

function mapTopicRefreshMessage(result,previousNaming) {
  const count=result.topics.length;
  const status=result.refresh_status||({model:previousNaming==='model'?'cached':'generated',mixed:'partial',terms_after_error:'fallback'}[result.naming_status])||'local';
  if(!count||status==='empty')return {message:'当前地图暂无可整理的主题。'};
  if(status==='cached')return {message:`已显示上次整理的 ${count} 个主题。`,showTopics:true};
  if(status==='generated')return {message:`已整理 ${count} 个主题。点击主题查看论文与依据。`,showTopics:true};
  if(status==='partial')return {message:`已显示 ${count} 个主题，部分主题使用论文关键词。`,showTopics:true};
  if(status==='fallback')return {message:result.refresh_reason==='timeout'?'生成主题说明超时。已保留已有主题，可以重试。':'本次未能生成主题说明。已保留已有主题，可以重试。',showTopics:true,retry:true};
  return {message:`已显示 ${count} 个关键词主题。配置对话模型后可生成主题说明。`,showTopics:true};
}

async function refreshMapTopics() {
  const run=state.runId, map=state.data?.map;
  const previous=mapTopicRefreshEntry(map);
  if(!previous||previous.task)return;
  const mapVersion=map.map_version;
  const controller=new AbortController();
  const task={controller,started:Date.now(),label:'准备整理主题'};
  const requestId=previous.retryRequestId||`topics-${task.started}-${++state.requestCounter}`;
  const entry={mapVersion,task};
  state.mapTopicRefresh.set(run,entry);
  const current=()=>state.runId===run&&state.mapTopicRefresh.get(run)===entry&&state.data?.map?.map_version===entry.mapVersion;
  const repaint=()=>{if(current()&&['map','chat'].includes(state.view))paint({preserveGraphLayout:true});};
  const updateProgress=()=>{
    if(!current())return;
    document.querySelectorAll('[data-map-topic-stage]').forEach(el=>{if(el.textContent!==task.label)el.textContent=task.label;});
    document.querySelectorAll('[data-map-topic-elapsed]').forEach(el=>{el.textContent=Math.floor((Date.now()-task.started)/1000);});
  };
  const deadline=setTimeout(()=>controller.abort(new DOMException('等待主题结果超时','TimeoutError')),60_000);
  const clock=setInterval(updateProgress,1000);
  repaint();
  try {
    const result=await api('/api/map-topics/refresh',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({run_id:run,request_id:requestId})},job=>{
        task.serverId=job.task_id||task.serverId;
        task.serverStatus=job.status;
        task.label=taskStageLabel(job.stage);
        updateProgress();
      });
    controller.signal.throwIfAborted();
    if(!Array.isArray(result?.topics)||result.run_id!==run||!result.map_version){
      entry.message='主题整理结果读取失败，可以重试。';entry.retry=true;
    }else if(mapVersion&&result.map_version!==mapVersion){
      entry.message='地图已更新，请重新打开地图后整理当前主题。';
    }else{
      if(current())applyMapTopicRefresh(state.data.map,result);
      entry.mapVersion=result.map_version;
      Object.assign(entry,mapTopicRefreshMessage(result,map.topic_naming_status));
    }
  }catch(error){
    const terminal=['completed','failed','cancelled','interrupted'].includes(task.serverStatus);
    if(!terminal&&!(controller.signal.aborted&&task.serverId))entry.retryRequestId=requestId;
    entry.retry=true;
    entry.message=controller.signal.reason?.name==='TimeoutError'?'等待主题结果超时，可以重试。':
      controller.signal.aborted?'已停止等待，可以重新整理主题。':error.name==='TypeError'?'与勘文的连接中断，可以重试。':'主题整理暂时未完成，可以重试。';
  }finally{
    clearTimeout(deadline);clearInterval(clock);entry.task=null;
    repaint();
  }
}

async function hydrateReaderText(panel,c,run) {
  for(const layer of panel.querySelectorAll('[data-reader-text-page]')){
    const page=Number(layer.dataset.readerTextPage);
    const key=JSON.stringify([run,c.paperId,page]);
    state.pageTexts[key]??=api(`/api/pdf-text/${encodeURIComponent(run)}/${encodeURIComponent(c.paperId)}/${page}`).catch(error=>{
      delete state.pageTexts[key];
      throw error;
    });
    try {
      const data=await state.pageTexts[key];
      if(state.runId!==run||state.context!==c||!layer.isConnected)return;
      const normalize=t=>String(t||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
      const words=data.words||[];const normalized=words.map(w=>normalize(w.text));const corpus=normalized.join('');
      const needle=normalize(c.quote||'').slice(0,600);const marks=new Set();
      if(needle.length>=12){let start=corpus.indexOf(needle);let length=needle.length;if(start<0&&needle.length>80){length=80;start=corpus.indexOf(needle.slice(0,80));}if(start>=0){let offset=0;normalized.forEach((word,i)=>{if(offset+word.length>start&&offset<start+length)marks.add(i);offset+=word.length;});}}
      layer.innerHTML=words.map((w,i)=>`<span ${marks.has(i)?'class="quote-highlight"':''} style="left:${w.x*100}%;top:${w.y*100}%;width:${w.width*100}%;height:${w.height*100}%;font-size:${w.height*75}cqw" data-word="${i}">${esc(w.text)} </span>`).join('');
      layer.closest('.reader-page-wrap').style.aspectRatio=data.width+'/'+data.height;
    }catch { if(layer.isConnected)layer.dataset.textStatus='image-only'; }
  }
}

function jumpContextPage(page) {
  const c=state.context;const total=paperDocument(c.paperId)?.page_count||1;
  c.page=Math.max(1,Math.min(total,page||1));c.quote='';c.selection='';c.readerScroll=0;state.readingPages[c.paperId]=c.page;contextHistory(true);renderWorkspaceContext();
}

async function searchContextPassages(query) {
  const c=state.context;const run=state.runId;c.query=String(query||'');c.searching=true;c.error='';renderWorkspaceContext();
  try {const result=await api('/api/fulltext/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,query:c.query,paper_ids:[c.paperId]})});if(state.context===c&&state.runId===run)c.hits=result.hits||[];}
  catch(error){if(state.context===c)c.error=error.message;}
  finally{c.searching=false;if(state.context===c)renderWorkspaceContext();}
}

async function adoptResearchRun(id, signal) {
  rememberWorkspacePosition();
  const previous={context:state.context,token:state.contextRequest,key:state.chatKey,mapContext:state.mapContext,selected:[...state.methods.selected],methods:state.methods.result,library:state.library.result,reading:state.readingMode,scope:state.readingPaperId,expanded:state.methodFieldsExpanded,filter:state.libraryFilter,search:state.librarySearch};
  const run=state.runId;copyFormDraftsToRun(run,id);const loaded=await loadRun(id,false,id!==run,true,signal);
  if(!loaded)return false;
  if(previous.context&&state.contextRequest===previous.token&&state.context===previous.context)previous.context.ownerRun=id;
  if(!state.methods.result)state.methods.result=previous.methods;state.methods.stale=id!==run;
  if(!state.library.result)state.library.result=previous.library;state.library.stale=id!==run;
  if(id!==run){
    if(Object.hasOwn(state.composeDrafts,previous.key))state.composeDrafts[state.chatKey]=state.composeDrafts[previous.key];
    for(const [key,value] of Object.entries(state.workspacePositions))if(key.startsWith(previous.key+':'))state.workspacePositions[state.chatKey+key.slice(previous.key.length)]=value;
    for(const [key,value] of Object.entries(state.panelStates))if(key.startsWith(previous.key+':'))state.panelStates[state.chatKey+key.slice(previous.key.length)]={...value};
  }
  return true;
}

async function acquireContextPaper() {
  const c=state.context;const run=state.runId;const owner=state.chatKey;const paperId=c?.paperId;
  const issueKey=`${run}:${paperId}`;
  if(!paperId||c.busy||state.acquisitionTasks.has(issueKey))return;
  const controller=new AbortController();
  const task={controller,started:Date.now(),label:'提交全文获取任务'};
  const currentPaper=()=>state.runId===run&&state.chatKey===owner&&state.context?.paperId===paperId;
  const updateProgress=()=>{
    if(!currentPaper())return;
    const stage=document.querySelector('[data-fulltext-stage]');
    const elapsed=document.querySelector('[data-fulltext-elapsed]');
    if(stage&&stage.textContent!==task.label)stage.textContent=task.label;
    if(elapsed)elapsed.textContent=Math.floor((Date.now()-task.started)/1000);
  };
  const deadline=setTimeout(()=>controller.abort(new DOMException('等待全文获取超时','TimeoutError')),180_000);
  const clock=setInterval(updateProgress,1000);
  state.acquisitionTasks.set(issueKey,task);
  state.acquisitionIssues.delete(issueKey);
  c.error='';c.notice='';renderWorkspaceContext();
  let savedRun;
  try {
    const result=await api('/api/audit/upgrade',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({run_id:run,acquire:true,paper_ids:[paperId]})},job=>{
      task.label=job.status==='completed'?'打开已保存结果':job.stage==='starting'?'准备全文获取':taskStageLabel(job.stage);
      updateProgress();
    });
    const record=result.acquisition?.documents?.find(doc=>doc.paper_id===paperId);
    if(result.acquisition&&record?.status!=='parsed'&&record?.status!=='needs_ocr'&&!record?.pdf_saved){
      state.acquisitionIssues.set(issueKey,record||{status:'missing',error_code:'fulltext_not_available'});
      return;
    }
    savedRun=result.run_id;
    if(!savedRun)throw new Error('全文任务未返回研究记录');
    if(!currentPaper()){
      state.backgroundNotice={text:'论文全文处理已结束，结果已保存。',runId:savedRun};
      paint();return;
    }
    const panel=state.context;
    task.label='打开已保存结果';updateProgress();
    if(!await adoptResearchRun(savedRun,controller.signal)||state.context!==panel)return;
    if(['reader','analysis'].includes(panel.tab)&&paperDocument(paperId)?.status==='parsed')panel.tab='analysis';
    contextHistory(true);
    paint();
  }catch {
    const code=savedRun?'acquisition_load_failed':controller.signal.reason?.name==='TimeoutError'?'acquisition_wait_timeout':controller.signal.aborted?'acquisition_stopped':'acquisition_request_failed';
    state.acquisitionIssues.set(issueKey,{status:'failed',error_code:code,result_run_id:savedRun});
  }finally{
    clearTimeout(deadline);clearInterval(clock);state.acquisitionTasks.delete(issueKey);
    if(currentPaper()||(state.runId===savedRun&&state.context?.paperId===paperId))renderWorkspaceContext();
  }
}

async function importContextPaper(event) {
  const file=event.target.files?.[0];if(!file)return;
  const c=state.context;const run=state.runId;
  if(!c?.paperId||c.busy||state.acquisitionTasks.has(`${run}:${c.paperId}`))return;
  c.busy=true;c.error='';renderWorkspaceContext();
  try {if(file.size>25*1024*1024)throw new Error('PDF文件不得超过25MB');const content=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});const p=paperInWorkspace(c.paperId);const result=await api('/api/import/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,paper_id:c.paperId,filename:file.name,title:p.title,identifier:p.doi_or_arxiv||'',content_base64:content,question:state.data?.question||''})});if(state.context!==c||state.runId!==run)return;if(!await adoptResearchRun(result.run_id)||state.context!==c)return;c.paperId=result.paper_id||c.paperId;c.tab=paperDocument(c.paperId)?.status==='parsed'?'analysis':'reader';c.busy=false;contextHistory(true);paint();}
  catch(error){if(state.context===c)c.error=error.message;}
  finally{c.busy=false;if(state.context===c)renderWorkspaceContext();}
}

function exploreContextCitations(direction) {
  const c=state.context;
  if(!c?.paperId||!Object.hasOwn(CITATION_LABELS,direction))return;
  return runContextCitation(c,{run_id:state.runId,paper_id:c.paperId,direction,constraints:{...state.constraints}});
}

const CITATION_WAIT_TIMEOUT=60_000;

async function runContextCitation(c,body) {
  const run=body.run_id;
  const key=contextCitationKey(c,run);
  if(!key||state.context!==c||state.runId!==run||c.paperId!==body.paper_id)return;
  const entry=state.contextCitations.get(key)||{};
  if(entry.task)return;
  entry.opening?.abort();
  const controller=new AbortController();
  const task={controller,started:Date.now(),label:`正在查找${CITATION_LABELS[body.direction]}`};
  const requestId=body.request_id||`citation-${task.started}-${++state.requestCounter}`;
  entry.task=task;
  entry.error='';
  entry.retry=null;
  state.contextCitations.set(key,entry);
  const current=()=>contextCitationKey(state.context)===key;
  const updateProgress=()=>{
    if(!current())return;
    const stage=document.querySelector('[data-citation-stage]');
    const elapsed=document.querySelector('[data-citation-elapsed]');
    if(stage&&stage.textContent!==task.label)stage.textContent=task.label;
    if(elapsed)elapsed.textContent=Math.floor((Date.now()-task.started)/1000);
  };
  const deadline=setTimeout(()=>controller.abort(new DOMException('等待引文结果超时','TimeoutError')),CITATION_WAIT_TIMEOUT);
  const clock=setInterval(updateProgress,1000);
  const originalIds=new Set((state.data?.papers||[]).map(p=>p.paper_id));
  let resultRun;
  let legacyResult=false;
  rememberWorkspacePosition();
  renderWorkspaceContext();
  try {
    const result=await api('/api/research/related',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({...body,request_id:requestId})},job=>{
      task.serverId=job.task_id||task.serverId;
      task.serverStatus=job.status;
      task.label=taskStageLabel(job.stage);
      updateProgress();
    });
    controller.signal.throwIfAborted();
    if(!result?.run_id)throw new Error('引文任务未返回研究结果，可以重试。');
    resultRun=result.run_id;
    legacyResult=!result.related;
    entry.result={direction:body.direction,...result.related,runId:resultRun};
    if(result.related?.status==='unavailable')entry.retry={...body,request_id:undefined};
  }catch(error){
    const terminal=['completed','failed','cancelled','interrupted'].includes(task.serverStatus);
    entry.retry={...body,request_id:terminal||(controller.signal.aborted&&task.serverId)?undefined:requestId};
    entry.error=controller.signal.reason?.name==='TimeoutError'?'等待引文结果超时，可以重试。':
      controller.signal.aborted?'已停止等待，可以重试。':
      error.name==='TypeError'?'与勘文的连接中断，可以重试。':error.message||'本次引文查找未完成，可以重试。';
  }finally{
    clearTimeout(deadline);
    clearInterval(clock);
    entry.task=null;
    if(current())renderWorkspaceContext();
  }
  if(!resultRun||!current()||(resultRun===run&&!legacyResult))return;
  const opening=new AbortController();
  entry.opening=opening;
  const openDeadline=setTimeout(()=>opening.abort(),8000);
  try {
    if(!await adoptResearchRun(resultRun,opening.signal)||opening.signal.aborted)return;
    if(legacyResult){
      const papers=(scopedAuditData().papers||[]).filter(p=>!originalIds.has(p.paper_id));
      entry.result={...entry.result,status:papers.length?'completed':'empty',papers,added_count:papers.length};
    }
    state.contextCitations.set(contextCitationKey(c,resultRun),{result:entry.result});
    if(contextCitationKey(state.context)===contextCitationKey(c,resultRun))contextHistory(true);
    paint();
  }catch{
    // The preview and saved-run link remain available when opening the run fails.
  }finally{
    clearTimeout(openDeadline);
    if(entry.opening===opening)entry.opening=null;
  }
}

const CONTEXT_QUESTION_TIMEOUT=150_000;

function askFromContext(question,topic=false,preset) {
  const c=state.context;
  question=String(question||'').trim();
  if(!question||!contextQuestionKey(c))return;
  const selectedPage=!topic&&!preset&&c.tab==='reader'?{paper_id:c.paperId,page:c.page||1,quote:c.selection||c.quote||''}:undefined;
  if(!topic&&!preset&&!state.contextQuestions.get(contextQuestionKey(c))?.task){
    c.questionDraft=question;
    rememberFormDraft('context-question',c.paperId,'','',{question});
  }
  return runContextQuestion(c,{message:question,run_id:state.runId,reading_mode:!topic,
    map_context:topic?state.mapContext:undefined,reading_paper_id:topic?undefined:c.paperId,
    reading_scope_mode:topic?'auto':'selected',reading_selection:selectedPage,analysis_preset:preset,
    user_resources:{...state.resources}});
}

async function runContextQuestion(c,body) {
  const run=body.run_id;
  const key=contextQuestionKey(c,run);
  if(!key||state.context!==c||state.runId!==run)return;
  const entry=state.contextQuestions.get(key)||{};
  if(entry.task)return;
  const controller=new AbortController();
  const task={controller,started:Date.now(),label:body.analysis_preset?'准备定位正文依据':'准备本次提问'};
  const requestId=body.request_id||'context-'+task.started+'-'+(++state.requestCounter);
  entry.task=task;
  entry.error='';
  entry.retry=null;
  state.contextQuestions.set(key,entry);
  c.error='';
  const current=()=>contextQuestionKey(state.context)===key;
  const updateProgress=()=>{
    if(!current())return;
    const stage=document.querySelector('[data-context-question-stage]');
    const elapsed=document.querySelector('[data-context-question-elapsed]');
    if(stage&&stage.textContent!==task.label)stage.textContent=task.label;
    if(elapsed)elapsed.textContent=Math.floor((Date.now()-task.started)/1000);
  };
  const deadline=setTimeout(()=>controller.abort(new DOMException('等待回答超时','TimeoutError')),CONTEXT_QUESTION_TIMEOUT);
  const clock=setInterval(updateProgress,1000);
  rememberWorkspacePosition();
  renderWorkspaceContext();
  let resultRun;
  try {
    const result=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({...body,request_id:requestId})},job=>{
      task.serverId=job.task_id||task.serverId;
      task.serverStatus=job.status;
      task.label=taskStageLabel(job.stage);
      updateProgress();
    });
    task.serverStatus='completed';
    controller.signal.throwIfAborted();
    if(result.status!=='completed'){
      const message=result.status==='llm_unavailable'?llmErrorText(result.response||{}):result.response?.overview;
      throw new Error(message||'本次回答未完成，请重试。');
    }
    entry.answer={content:result.response?.overview||'',response:result.response};
    resultRun=result.run_id||run;
    if(current()){
      const panel=state.context;
      if(body.reading_mode&&!body.analysis_preset&&getFormDraft('context-question',panel.paperId)?.question===body.message){
        clearFormDraft('context-question',panel.paperId);
        if(panel.questionDraft===body.message)panel.questionDraft='';
      }
      if(result.response?.map_answer){
        const answer=result.response.map_answer;
        state.mapContext={map_version:answer.map_version,cluster_ids:answer.selected_cluster_ids};
        if(panel.kind==='topic'){
          panel.topic=(answer.topics||[]).find(t=>t.cluster_id===panel.clusterId)||panel.topic;
          panel.map={tracks:answer.topics,map_version:answer.map_version};
        }
      }
    }
  }catch(error){
    const terminal=['completed','failed','cancelled','interrupted'].includes(task.serverStatus);
    entry.retry={...body,request_id:terminal||(controller.signal.aborted&&task.serverId)?undefined:requestId};
    entry.error=controller.signal.reason?.name==='TimeoutError'?'等待回答超时，可以重试本次请求。':
      controller.signal.aborted?'已停止等待，可以重试本次请求。':
      error.name==='TypeError'?'与服务的连接中断，可以重试本次请求。':error.message||'本次回答未完成，请重试。';
  }finally{
    clearTimeout(deadline);
    clearInterval(clock);
    entry.task=null;
    if(current()){
      rememberWorkspacePosition();
      renderWorkspaceContext();
    }
  }
  if(resultRun&&state.runId===run)void syncContextQuestionHistory(run,resultRun,key,entry);
}

async function syncContextQuestionHistory(run,resultRun,key,entry) {
  try {
    const signal=AbortSignal.timeout(8000);
    if(resultRun!==run){
      if(contextQuestionKey(state.context)!==key||!await adoptResearchRun(resultRun,signal))return;
      if(state.runId!==resultRun)return;
      const savedKey=JSON.stringify([resultRun,...JSON.parse(key).slice(1)]);
      if(!state.contextQuestions.has(savedKey))state.contextQuestions.set(savedKey,entry);
      contextHistory(true);
      paint();
    }else{
      const chat=state.chat;
      const {messages}=await api(`/api/chat/${encodeURIComponent(run)}`,{signal});
      if(state.runId!==run||state.chat!==chat||activeChatTask()||!Array.isArray(messages)||messages.length<chat.messages.length)return;
      chat.messages=messages;
      if(state.view==='chat')paint();
    }
  }catch {
    // The answer is already visible and saved. A slow history request is independent.
  }
}

async function saveContextTopicLabel(event) {
  event.preventDefault();const c=state.context;const run=state.runId;if(!c||c.kind!=='topic')return;
  const form=event.target;const label=String(new FormData(form).get('label')||'').trim();if(!label)return;
  const button=form.querySelector('button');button.disabled=true;c.error='';
  try {
    const result=await api('/api/map-topics/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,cluster_id:c.clusterId,map_version:c.map?.map_version||c.topic.map_version,label})});
    if(state.runId!==run||state.context!==c)return;
    c.topic=result.topic;c.notice='主题名称已保存';
    const update=topic=>topic.cluster_id===c.clusterId?{...topic,...result.topic}:topic;
    const map=state.data?.map;
    if(map?.tracks)map.tracks=map.tracks.map(update);
    if(map?.topics)map.topics=map.topics.map(update);
    paint();
  }catch(error){if(state.context===c){c.error=error.message;renderWorkspaceContext();}}
  finally{button.disabled=false;}
}

async function loadSources() {
  state.sources={...(state.sources||{}),loading:true};
  try{state.sources.result=await api('/api/sources');}catch(error){if(state.context?.kind==='sources')state.context.error=error.message;}
  finally{state.sources.loading=false;if(state.context?.kind==='sources')renderWorkspaceContext();}
}

async function testSource(source) {
  state.sources.testing=source;renderWorkspaceContext();
  try{const result=await api('/api/sources/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})});state.sources.result.sources=state.sources.result.sources.map(s=>s.id===source?result.source:s);}
  catch(error){if(state.context?.kind==='sources')state.context.error=error.message;}
  finally{state.sources.testing='';if(state.context?.kind==='sources')renderWorkspaceContext();}
}

function cleanAssistantText(value) {
  return String(value||'').replace(/\*\*本轮问题覆盖\*\*[\s\S]*$/,'').split('\n').filter(line=>!/^\s*(?:本条仅列出待核验内容|引用完整性检查已通过|定位核验不代表|仅在所引证据范围内成立|以上为有原文绑定|部分候选解读经一次有界修订|本轮中文解读尚未完成来源复核|(?:还|仍|尚)?需要补充(?:样本|样本规模|数据集|实验|指标|信息|材料)|覆盖状态来自当前检索窗口)/.test(line)).join('\n').trim();
}

function answerCitations(response) {
  const audit=response.answer_audit||{};
  if(audit.citations?.length)return audit.citations.filter(Boolean);
  const rows=audit.questions?.length?audit.questions:audit.sections;
  if(rows?.length)return rows.flatMap(row=>(row.sources||[]).filter(Boolean));
  const methods=response.method_analysis;
  return (methods?.fields||[]).flatMap(field=>field.candidate?[{...field.candidate,paper_id:methods.paper_id}]:[]);
}

function groupAnswerSources(sources) {
  const groups=new Map();
  for(const source of sources||[]){
    if(!source||typeof source!=='object')continue;
    const paperId=source.paper_id;
    const page=Number(source.page);
    const field=source.source_kind||source.field;
    const fulltext=field!=='title'&&field!=='abstract'&&Number.isInteger(page)&&page>0;
    const location=fulltext?`第 ${page} 页`:field==='title'?'题名':field==='abstract'||source.certainty==='abstract_only'?'摘要':'论文详情';
    const quote=String(source.quote||source.snippet||'');
    const evidenceId=paperId?null:[source.claim_id,source.evidence_ids,source.title];
    const key=paperId||JSON.stringify(evidenceId);
    if(!groups.has(key))groups.set(key,{paperId,title:source.title||(paperId?titleOf(paperId):'论断证据'),sources:[],seen:new Set()});
    const group=groups.get(key);
    const identity=JSON.stringify([location,quote.trim().replace(/\s+/g,' ')||source.passage_id||'']);
    if(group.seen.has(identity))continue;
    group.seen.add(identity);
    group.sources.push({...source,quote,location,fulltext});
  }
  return [...groups.values()];
}

function answerSourceGroupsView(groups, {agenda=false} = {}) {
  return groups.map(group=>{
    const counts=new Map();
    for(const source of group.sources)counts.set(source.location,(counts.get(source.location)||0)+1);
    const seen=new Map();
    const chips=group.sources.map(source=>{
      const position=(seen.get(source.location)||0)+1;
      seen.set(source.location,position);
      const label=counts.get(source.location)>1?`${source.location} · 摘录 ${position}`:source.location;
      const badge=source.certainty==='uncertain'?'<span class="stamp pending">待核验</span>':'';
      if(source.paper_id&&source.fulltext&&!agenda)return sourceButton(source,label)+badge;
      const open=!source.paper_id?'':source.fulltext?sourceButton(source,'打开原文'):
        `<button type="button" class="source-pill" data-inspect-paper="${esc(source.paper_id)}">${esc(source.quote?'论文详情':label)}</button>`;
      const excerpt=source.quote?`<details class="answer-source-excerpt"${agenda?' data-agenda-source-excerpt':''}><summary>${esc(label)}</summary><blockquote>${esc(source.quote)}</blockquote>${open}</details>`:open+badge;
      if(agenda&&typeof source.attribution==='string'&&source.attribution.trim()){
        return `<div class="agenda-source-evidence"><p data-agenda-source-attribution>${esc(source.attribution)}</p>${excerpt}</div>`;
      }
      return excerpt;
    }).join('');
    return `<div class="citation-row answer-source-group"><strong>${esc(group.title)}</strong>${chips?`<div class="answer-source-actions">${chips}</div>`:''}</div>`;
  }).join('');
}

function researchAgendaView(response, audit, modelNote) {
  const labels={comparison:'对照',control:'控制条件',metrics:'评价指标'};
  const compact=text=>text.replace(/[\s，。；、：,.;:]+/g,'');
  const cards=audit.questions.map(question=>{
    const rows=Object.entries(labels).filter(([key])=>typeof question.design?.[key]==='string'&&question.design[key].trim());
    return {question,rows};
  });
  const partial=audit.answer_status==='partial';
  const heading=!partial?'值得分析的研究问题':cards.some(card=>card.rows.length===3)?'初步验证方案':'研究问题提纲';
  const questions=cards.map(({question,rows})=>{
    const completeDesign=rows.length===3;
    const scope={cross_paper:partial&&!completeDesign?'比较提纲':'跨论文依据',single_paper:'单篇线索'}[question.scope];
    const design=completeDesign?`<dl class="agenda-design" data-agenda-design>${rows.map(([key,label])=>
      `<dt>${label}</dt><dd>${esc(question.design[key])}</dd>`).join('')}</dl>`:'';
    const plan=typeof question.analysis_plan==='string'?question.analysis_plan.trim():'';
    const designText=rows.map(([key])=>compact(question.design[key]));
    const repeatedPlan=completeDesign&&[...designText,designText.join('')].includes(compact(plan));
    const procedure=plan&&!repeatedPlan?`<p data-agenda-procedure><strong>${completeDesign?'验证步骤':'怎么分析'}</strong> ${esc(plan)}</p>`:'';
    return `<section data-agenda-card="${completeDesign?'proposal':'outline'}">
      ${scope?`<span class="research-agenda-scope">${scope}</span>`:''}
      <h4>${esc(question.question)}</h4>
      ${question.motivation?`<p><strong>为什么值得分析</strong> ${esc(question.motivation)}</p>`:''}
      ${design}
      ${procedure}
      <div class="answer-sources answer-source-list">${answerSourceGroupsView(groupAnswerSources(question.sources),{agenda:true})}</div>
    </section>`;
  }).join('');
  return `<div class="reading-answer research-agenda" data-agenda-status="${esc(audit.answer_status||'unclassified')}"><h3>${heading}</h3>${modelNote}${questions}${citationView(response)}</div>`;
}

function readingAnswerView(response,content) {
  const methods=response.method_analysis;
  if(methods?.fields?.length)return `<div class="reading-answer method-evidence-answer">${methods.fields.map(field=>{
    const candidate=field.candidate;
    return `<section><h4>${esc(field.label)}</h4>${candidate?.quote&&candidate.page
      ?`<blockquote>${esc(candidate.quote)}</blockquote><div class="answer-sources">${sourceButton({...candidate,paper_id:methods.paper_id},`查看第 ${candidate.page} 页原文`)}</div>`
      :'<p class="muted">本次未定位到匹配的原文。</p>'}</section>`;
  }).join('')}</div>`;
  const audit=response.answer_audit||{};
  const modelStatus={timed_out:'模型响应超时',unavailable:'模型暂时不可用',draft_invalid:'模型未返回可用方案',review_rejected:'本轮方案未通过核验'}[audit.model_status];
  const fallback=audit.kind==='research_agenda'?'先显示基于现有材料的分析线索':'先显示找到的原文';
  const modelNote=modelStatus?`<p class="tiny" role="status">${modelStatus}，${fallback}。</p>`:'';
  if(audit.kind==='research_agenda'){
    if(audit.questions?.length)return researchAgendaView(response,audit,modelNote);
    return `<div class="reading-answer research-agenda" data-agenda-status="insufficient_evidence"><h3>暂无验证方案</h3><div class="rich-text">${renderMarkdown(cleanAssistantText(content))}</div></div>`;
  }
  if(audit.kind==='grounded_reading'&&audit.sections?.length)return `<div class="reading-answer">${audit.sections.map(s=>`<section><h4>${esc({paper_report:'论文要点',explanation:'方法解读',suggestion:'研究建议'}[s.kind]||'研究解读')}</h4><div class="rich-text">${renderMarkdown(cleanAssistantText(s.text))}</div><div class="answer-sources answer-source-list">${answerSourceGroupsView(groupAnswerSources(s.sources))}</div></section>`).join('')}${citationView(response)}</div>`;
  return `${modelNote}<div class="rich-text">${renderMarkdown(cleanAssistantText(content))}</div>${citationView(response)}`;
}

function mapAnswerView(response,content) {
  const answer=response.map_answer||{};
  const selected=new Set(answer.selected_cluster_ids||[]);const topics=(answer.topics||[]).filter(t=>!selected.size||selected.has(t.cluster_id));
  return `<div class="map-answer rich-text">${renderMarkdown(cleanAssistantText(content))}</div><div class="topic-answer-cards">${topics.map(t=>`<button type="button" class="topic-card" data-open-topic="${esc(t.cluster_id)}" data-map-version="${esc(answer.map_version)}"><span class="project-kicker">主题 ${t.display_index}</span><strong>${esc(t.label)}</strong><span>查看 ${(t.paper_ids||t.member_paper_ids||[]).length} 篇论文 →</span></button>`).join('')}</div>`;
}
