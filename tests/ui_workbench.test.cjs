const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function workbench() {
  const storage = new Map();
  const historyCalls = [];
  const stage = {scrollTop: 173};
  const c = vm.createContext({URL, URLSearchParams, AbortController, AbortSignal, DOMException, setInterval, clearInterval, clearTimeout,
    setTimeout(callback, delay) {if (delay === 750) {queueMicrotask(callback); return 0;} return setTimeout(callback, delay);},
    location: {search:'?run=r&view=methods', href:'http://localhost/?run=r&view=methods'},
    history: {pushState(value, title, url) {historyCalls.push(['push', value, String(url)]);},
      replaceState(value, title, url) {historyCalls.push(['replace', value, String(url)]);}},
    document: {getElementById: id => id === 'stage' ? stage : null,
      querySelector: () => null, querySelectorAll: () => [], activeElement: null},
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key,value) => storage.set(key,value)},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ui/static/workspace.js'),'utf8'), c);
  const app = fs.readFileSync(path.join(__dirname,'../src/ui/static/app.js'),'utf8');
  vm.runInContext(app.slice(0, app.lastIndexOf('boot().catch')), c);
  vm.runInContext(`state.runId='r';state.chatKey='run:r';state.workspaceId='workbench';state.view='methods';
    state.renderedPanelKey='run:r:methods';state.data={offline:true,papers:[
      {paper_id:'p1',title:'Study <one>',abstract:'A methods abstract',year:2024},
      {paper_id:'p2',title:'Study two',abstract:'Another research question',year:2023}],
      fulltext_audit:{documents:[{paper_id:'p1',status:'parsed',page_count:8}]}};
    state.composeDrafts[state.chatKey]='Unsent research question';
    rendered=0;painted=0;renderWorkspaceContext=()=>{rendered++};paint=()=>{painted++};
    setView=()=>{throw new Error('Object actions must not change the central task')};`, c);
  return {c, historyCalls, stage};
}

test('workspace helpers load before the application entry point', () => {
  const html = fs.readFileSync(path.join(__dirname,'../src/ui/static/index.html'),'utf8');
  const workspace = html.indexOf('/static/workspace.js');
  const app = html.indexOf('/static/app.js');
  assert.ok(workspace >= 0 && workspace < app, 'deferred workspace helpers must precede app.js');
});

test('paper and reader contexts preserve central task, position and unsent question', () => {
  const {c, historyCalls} = workbench();
  vm.runInContext(`openPaperContext('p1');openReaderContext('p1',3,'A quoted methods sentence');`, c);
  assert.equal(vm.runInContext('state.view',c), 'methods');
  assert.equal(vm.runInContext("state.composeDrafts['run:r']",c), 'Unsent research question');
  assert.equal(vm.runInContext("state.workspacePositions['run:r:methods']",c),173);
  assert.equal(vm.runInContext('painted',c),0);
  assert.equal(vm.runInContext('state.context.tab',c),'reader');
  assert.equal(vm.runInContext('state.context.page',c),3);
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('view'),'methods');
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('paper'),'p1');
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('tab'),'reader');
  vm.runInContext("switchPaperContextTab(state.context,'analysis')",c);
  assert.equal(historyCalls.at(-1)[0],'replace');
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('tab'),'analysis');
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('page'),null);
  vm.runInContext('closeWorkspaceContext()',c);
  assert.equal(vm.runInContext('state.context',c),null);
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('view'),'methods');
  assert.equal(new URL(historyCalls.at(-1)[2]).searchParams.get('panel'),null);
});

test('opening an analysis URL restores the scoped paper on a fresh load', async () => {
  const {c}=workbench();
  c.location.search='?run=r&view=funnel&panel=paper&paper=p1&tab=analysis';
  c.location.href='http://localhost/'+c.location.search;
  vm.runInContext(`savedData=state.data;state.data=null;
    api=async path=>path==='/api/run/r'?savedData:{};`,c);
  await vm.runInContext('boot()',c);
  assert.equal(vm.runInContext('state.view',c),'funnel');
  assert.equal(vm.runInContext('state.context.paperId',c),'p1');
  assert.match(vm.runInContext('contextPanelView()',c),/已处理 8 页.*分析方法与实验/);

  vm.runInContext(`savedData.offline=false;savedData.live={matched_paper_ids:['p2']};`,c);
  await vm.runInContext('boot()',c);
  assert.equal(vm.runInContext('state.context',c),null);
});

test('parsed papers appear before papers that still need a download', () => {
  const {c}=workbench();
  vm.runInContext('state.data.papers.reverse()',c);
  const html=vm.runInContext('funnelView()',c);
  assert.match(html,/data-open-paper-analysis="p1"[\s\S]*data-open-paper-text="p2"/);
  assert.equal(vm.runInContext('state.data.papers[0].paper_id',c),'p2');
});

test('unknown paper identifiers cannot replace the current research object', () => {
  const {c} = workbench();
  vm.runInContext("openPaperContext('p1');openReaderContext('foreign-paper',5);openFieldContext('foreign-paper','method')",c);
  assert.equal(vm.runInContext('state.context.paperId',c),'p1');
  assert.equal(vm.runInContext('state.context.tab',c),'overview');
});

test('reader renders a bounded three-page window and escapes original quote text', () => {
  const {c} = workbench();
  vm.runInContext("reader={paperId:'p1',tab:'reader',page:3,quote:'<unsafe> & original',zoom:1.15}",c);
  const html=vm.runInContext("readerContextView(state.data.papers[0],reader,paperDocument('p1'))",c);
  assert.equal((html.match(/class="reader-page-wrap"/g)||[]).length,3);
  assert.ok(html.includes('/api/pdf-page/r/p1/3')&&html.includes('/api/pdf-page/r/p1/5'));
  assert.ok(html.includes('data-reader-text-page="3"'));
  assert.ok(html.includes('&lt;unsafe&gt; &amp; original'));
  assert.ok(!html.includes('<unsafe>'));
  vm.runInContext('reader.page=8',c);
  assert.equal((vm.runInContext("readerContextView(state.data.papers[0],reader,paperDocument('p1'))",c).match(/class="reader-page-wrap"/g)||[]).length,1);
});

test('research questions separate the analysis scope from papers cited and distinguish source types', () => {
  const {c} = workbench();
  vm.runInContext(`agenda={overview_mode:'direct_answer',reading_scope:{paper_ids:['p1','p2','p3'],
    titles:['Study <one>','Study two','Scope only'],available_fulltext_paper_ids:['p1']},
    answer_audit:{ok:true,kind:'research_agenda',questions:[{question:'Transfer across tasks?',
      motivation:'The study settings differ.',analysis_plan:'Compare success by task.',scope:'cross_paper',sources:[
        {paper_id:'p1',source_kind:'fulltext',page:2,quote:'Held-out tasks'},
        {paper_id:'p2',source_kind:'abstract',quote:'<unseen> trial',page:8}]}]}};`,c);
  const html=vm.runInContext("chatMessage({role:'assistant',content:'Fallback content',response:agenda})",c);
  assert.match(html, /<summary>分析范围 3 篇 · 可读全文 1 篇 · 实际引用 2 篇<\/summary>/);
  assert.equal((html.match(/class="answer-scope-cited"/g)||[]).length,2);
  assert.match(html,/值得分析的研究问题[\s\S]*跨论文依据[\s\S]*Transfer across tasks\?/);
  assert.match(html,/为什么值得分析[\s\S]*The study settings differ/);
  assert.match(html,/怎么分析[\s\S]*Compare success by task/);
  assert.match(html,/data-context-source="p1" data-page="2" data-quote="Held-out tasks"/);
  assert.match(html,/<summary>摘要<\/summary><blockquote>&lt;unseen&gt; trial<\/blockquote>/);
  assert.doesNotMatch(html,/data-context-source="p2"|data-page="8"|Fallback content/);
  assert.match(html, /引用来源 · 2 篇论文/);
});

test('partial agendas distinguish an outline from structured proposals and show each source contribution', () => {
  const {c} = workbench();
  vm.runInContext(`agenda={answer_audit:{ok:true,kind:'research_agenda',answer_status:'partial',questions:[{
    question:'Which tasks can be compared?',analysis_plan:'Inventory existing tasks.',scope:'cross_paper',sources:[
      {paper_id:'p1',source_kind:'fulltext',page:2,quote:'<held-out> tasks',attribution:'Study <one> varies initial positions.'}
    ]}]}};`,c);
  const outline=vm.runInContext("readingAnswerView(agenda,'')",c);
  assert.match(outline,/data-agenda-status="partial"[\s\S]*研究问题提纲[\s\S]*data-agenda-card="outline"[\s\S]*比较提纲/);
  assert.doesNotMatch(outline,/跨论文依据|data-agenda-design/);

  vm.runInContext(`agenda.answer_audit.questions[0].design={comparison:'Prior experience on or off',
    control:'Use the same arm & budget',metrics:'Completion time and success'};
    agenda.answer_audit.questions[0].analysis_plan='Pair runs by task before comparing outcomes.';`,c);
  const proposal=vm.runInContext("readingAnswerView(agenda,'')",c);
  assert.match(proposal,/data-agenda-status="partial"[\s\S]*初步验证方案[\s\S]*data-agenda-card="proposal"/);
  assert.match(proposal,/<dl class="agenda-design" data-agenda-design><dt>对照<\/dt><dd>Prior experience on or off<\/dd><dt>控制条件<\/dt><dd>Use the same arm &amp; budget<\/dd><dt>评价指标<\/dt><dd>Completion time and success<\/dd><\/dl>/);
  assert.match(proposal,/data-agenda-source-attribution>Study &lt;one&gt; varies initial positions/);
  assert.match(proposal,/data-agenda-source-excerpt><summary>第 2 页<\/summary><blockquote>&lt;held-out&gt; tasks<\/blockquote>/);
  assert.match(proposal,/data-context-source="p1" data-page="2"/);
  assert.match(proposal,/<p data-agenda-procedure><strong>验证步骤<\/strong> Pair runs by task before comparing outcomes\.<\/p>/);
  vm.runInContext("agenda.answer_audit.questions[0].analysis_plan='Completion time and success.';",c);
  assert.doesNotMatch(vm.runInContext("readingAnswerView(agenda,'')",c),/data-agenda-procedure/);
  assert.equal(vm.runInContext("taskStageLabel('agenda_draft')",c),'拟定可验证的研究问题');
  assert.equal(vm.runInContext("taskStageLabel('agenda_repair')",c),'根据文献依据调整研究方案');

  vm.runInContext("agenda.answer_audit.questions=[];agenda.answer_audit.answer_status='insufficient_evidence';",c);
  const empty=vm.runInContext("readingAnswerView(agenda,'No usable excerpts.')",c);
  assert.match(empty,/data-agenda-status="insufficient_evidence"[\s\S]*暂无验证方案[\s\S]*No usable excerpts/);
  assert.doesNotMatch(empty,/data-agenda-card|data-agenda-design/);
});

test('repeated citations collapse by paper while separate quotes on the same page remain reachable', () => {
  const {c} = workbench();
  const html=vm.runInContext(`citationView({answer_audit:{ok:true,citations:[
    {paper_id:'p1',page:2,quote:'First quoted line'},
    {paper_id:'p1',page:2,quote:'First  quoted line'},
    {paper_id:'p1',page:2,quote:'Another quoted line'},
    {paper_id:'p1',page:3,quote:'Another page'}]}})`,c);
  assert.match(html,/引用来源 · 1 篇论文/);
  assert.equal((html.match(/Study &lt;one&gt;/g)||[]).length,1);
  assert.equal((html.match(/data-context-source="p1"/g)||[]).length,3);
  assert.match(html,/data-quote="First quoted line"[^<]*>[\s\S]*?第 2 页 · 摘录 1/);
  assert.match(html,/data-quote="Another quoted line"[^<]*>[\s\S]*?第 2 页 · 摘录 2/);
  assert.match(html,/data-page="3" data-quote="Another page"/);
});

test('field search binds each request to its paper and does not navigate the table', async () => {
  const {c} = workbench();
  vm.runInContext(`state.context={paperId:'p1',tab:'field',field:'baseline'};
    api=async(path,options)=>{sent={path,body:JSON.parse(options.body)};return{hits:[{paper_id:'p1',page:4,text:'Original baseline'}]}};`,c);
  await vm.runInContext("searchContextPassages('comparison baseline')",c);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(sent)',c)),
    {path:'/api/fulltext/search',body:{run_id:'r',query:'comparison baseline',paper_ids:['p1']}});
  assert.equal(vm.runInContext('state.context.hits[0].paper_id',c),'p1');
  assert.equal(vm.runInContext('state.context.searching',c),false);
  assert.equal(vm.runInContext('state.view',c),'methods');
});

test('a reader question sends selected text, page and explicit current-paper scope', async () => {
  const {c} = workbench();
  vm.runInContext(`state.context={paperId:'p1',tab:'reader',page:4,selection:'The selected contiguous source text',questionDraft:''};
    api=async(path,options)=>{sent={path,body:JSON.parse(options.body)};return{status:'completed',run_id:'r',response:{overview:'中文解释'}}};
    adoptResearchRun=async()=>true;refreshConversations=async()=>{};`,c);
  await vm.runInContext("askFromContext('解释这段方法')",c);
  const sent=JSON.parse(vm.runInContext('JSON.stringify(sent)',c));
  assert.equal(sent.path,'/api/chat');
  assert.equal(sent.body.reading_mode,true);
  assert.equal(sent.body.reading_scope_mode,'selected');
  assert.equal(sent.body.reading_paper_id,'p1');
  assert.deepEqual(sent.body.reading_selection,{paper_id:'p1',page:4,quote:'The selected contiguous source text'});
  assert.equal(sent.body.message,'解释这段方法');
  assert.equal(vm.runInContext('state.view',c),'methods');
  assert.equal(vm.runInContext("state.composeDrafts['run:r']",c),'Unsent research question');
});

test('search results lead to whole-paper analysis and require PDF acquisition for abstract-only papers', async () => {
  const {c} = workbench();
  const parsed = vm.runInContext('paperResultRow(state.data.papers[0])',c);
  const missing = vm.runInContext('paperResultRow(state.data.papers[1])',c);
  assert.match(parsed,/data-open-paper-analysis="p1">全文分析/);
  assert.match(missing,/data-open-paper-text="p2">获取全文/);
  assert.doesNotMatch(missing,/data-open-paper-analysis/);
  vm.runInContext(`openPaperContext('p1','analysis');state.context.selection='Earlier reader selection';
    api=async(path,options)=>{sent=JSON.parse(options.body);return{status:'completed',run_id:'r',response:{overview:'Analysis'}};};
    adoptResearchRun=async()=>true;refreshConversations=async()=>{};`,c);
  const html = vm.runInContext('paperContextView(state.data.papers[0],state.context)',c);
  assert.match(html,/data-analyze-paper[^>]*>分析方法与实验/);
  await vm.runInContext("askFromContext('Describe the experiment')",c);
  assert.equal(vm.runInContext('sent.reading_paper_id',c),'p1');
  assert.equal(vm.runInContext('sent.reading_mode',c),true);
  assert.equal(vm.runInContext('sent.reading_selection',c),undefined);
});

test('the method preset preserves the draft and shows page-grounded results before history loads', async () => {
  const {c}=workbench();
  vm.runInContext(`openPaperContext('p1','analysis');state.context.questionDraft='A separate draft';
    api=async(path,options)=>{
      if(path!=='/api/chat'){historyLoading=true;return new Promise(()=>{});}
      sent=JSON.parse(options.body);
      return{status:'completed',run_id:'r',response:{overview_mode:'method_evidence',method_analysis:{paper_id:'p1',fields:[
        {label:'核心方法',candidate:{quote:'The test used a randomized protocol.',page:3}},
        {label:'基线',candidate:null}]}}};
    };`,c);
  await vm.runInContext("askFromContext('分析这篇论文的方法与实验',false,'methods_experiments')",c);
  assert.equal(vm.runInContext('sent.analysis_preset',c),'methods_experiments');
  assert.equal(vm.runInContext('historyLoading',c),true);
  assert.equal(vm.runInContext('state.context.questionDraft',c),'A separate draft');
  assert.equal(vm.runInContext('state.context.tab',c),'analysis');
  const html=vm.runInContext('contextPanelView()',c);
  assert.match(html,/The test used a randomized protocol/);
  assert.match(html,/data-context-source="p1" data-page="3"/);
  assert.match(html,/本次未定位到匹配的原文/);
  assert.doesNotMatch(html,/data-stop-context-question/);
});

test('paper questions keep progress on reopen and retry the original citation after a timeout', async () => {
  const {c}=workbench();
  c.setTimeout=(callback,delay)=>{assert.equal(delay,150_000);c.expire=callback;return 0;};
  vm.runInContext(`openReaderContext('p1',4,'Original page text');
    sent=[];api=async(path,options,onProgress)=>{
      if(path!=='/api/chat')return{messages:[]};
      sent.push(JSON.parse(options.body));
      if(sent.length===2)return{status:'completed',run_id:'r',response:{overview:'Retried answer'}};
      onProgress({stage:'semantic_review',task_id:'known-job',status:'running'});
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    pending=askFromContext('Explain the original passage');
    closeWorkspaceContext();openPaperContext('p1','analysis');`,c);
  const busy=vm.runInContext('contextPanelView()',c);
  assert.match(busy,/复核中文解读与原文/);
  assert.match(busy,/data-context-question-elapsed/);
  assert.match(busy,/data-stop-context-question/);
  assert.match(busy,/Explain the original passage/);
  c.expire();
  await vm.runInContext('pending',c);
  assert.match(vm.runInContext('contextPanelView()',c),/等待回答超时/);
  assert.match(vm.runInContext('contextPanelView()',c),/data-retry-context-question/);
  await vm.runInContext(`runContextQuestion(state.context,state.contextQuestions.get(contextQuestionKey(state.context)).retry)`,c);
  const requests=JSON.parse(vm.runInContext('JSON.stringify(sent)',c));
  assert.deepEqual(requests[1].reading_selection,{paper_id:'p1',page:4,quote:'Original page text'});
  assert.equal(requests[0].message,requests[1].message);
  assert.notEqual(requests[0].request_id,requests[1].request_id);
  assert.equal(vm.runInContext('state.context.tab',c),'analysis');
  assert.match(vm.runInContext('contextPanelView()',c),/Retried answer/);
});

test('stopping a paper question cancels its known server task and keeps the question draft', async () => {
  const {c}=workbench();
  vm.runInContext(`openPaperContext('p1','analysis');
    const response=(status,value)=>({status,ok:true,json:async()=>value});
    stopped=false;
    const polling=new Promise(resolve=>beginPoll=resolve);
    fetch=async(path,options)=>{
      if(path==='/api/chat')return response(202,{task_id:'analysis-job',status:'running'});
      if(path==='/api/tasks/analysis-job'&&options.method==='DELETE'){stopped=true;return response(200,{});}
      beginPoll();
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    pending=askFromContext('Keep this question');`,c);
  await vm.runInContext('polling',c);
  vm.runInContext('state.contextQuestions.get(contextQuestionKey(state.context)).task.controller.abort()',c);
  await vm.runInContext('pending',c);
  assert.equal(vm.runInContext('stopped',c),true);
  assert.match(vm.runInContext('contextPanelView()',c),/已停止等待/);
  assert.equal(vm.runInContext('state.context.questionDraft',c),'Keep this question');
});

test('retry after a lost response resumes the same request identifier', async () => {
  const {c}=workbench();
  vm.runInContext(`openPaperContext('p1','analysis');sent=[];
    api=async(path,options)=>{
      if(path!=='/api/chat')return{messages:[]};
      sent.push(JSON.parse(options.body));
      if(sent.length===1)throw new TypeError('connection reset');
      return{status:'completed',run_id:'r',response:{overview:'Recovered answer'}};
    };`,c);
  await vm.runInContext("askFromContext('Explain the controls')",c);
  assert.match(vm.runInContext('contextPanelView()',c),/与服务的连接中断/);
  await vm.runInContext('runContextQuestion(state.context,state.contextQuestions.get(contextQuestionKey(state.context)).retry)',c);
  assert.equal(vm.runInContext('sent[0].request_id===sent[1].request_id',c),true);
  assert.match(vm.runInContext('contextPanelView()',c),/Recovered answer/);
});

test('citation results are visible before the saved study finishes opening', async () => {
  const {c}=workbench();
  vm.runInContext(`openPaperContext('p1','citations');
    const loading=new Promise(resolve=>beginLoad=resolve);
    const gate=new Promise(resolve=>finishLoad=resolve);
    api=async()=>({run_id:'with-references',related:{status:'completed',added_count:1,
      papers:[{paper_id:'p3',title:'Source <paper>',year:2020,url:'https://example.invalid/p3'}]}});
    adoptResearchRun=async()=>{beginLoad();await gate;return false};
    pending=exploreContextCitations('references');`,c);
  await vm.runInContext('loading',c);
  const html=vm.runInContext('contextPanelView()',c);
  assert.match(html,/data-citation-results/);
  assert.match(html,/Source &lt;paper&gt;/);
  assert.match(html,/已新增 1 篇论文/);
  assert.match(html,/data-open-citation-run href="\/\?run=with-references/);
  assert.doesNotMatch(html,/data-stop-citations/);
  vm.runInContext('finishLoad()',c);
  await vm.runInContext('pending',c);
  assert.equal(vm.runInContext('state.context.tab',c),'citations');
  assert.match(vm.runInContext('contextPanelView()',c),/打开已保存研究/);
});

test('stopping an active citation task cancels it and retries its original direction and filters', async () => {
  const {c}=workbench();
  vm.runInContext(`openPaperContext('p1','citations');state.constraints.year_from=2020;
    const response=(status,value)=>({status,ok:true,json:async()=>value});
    sent=[];stopped=false;
    const polling=new Promise(resolve=>beginPoll=resolve);
    fetch=async(path,options)=>{
      if(path==='/api/research/related'){
        sent.push(JSON.parse(options.body));
        if(sent.length>1)return response(200,{run_id:'r',related:{status:'already_present',papers:[]}});
        return response(202,{task_id:'citation-job',status:'running'});
      }
      if(path==='/api/tasks/citation-job'&&options.method==='DELETE'){stopped=true;return response(200,{});}
      beginPoll();
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    pending=exploreContextCitations('citations');`,c);
  await vm.runInContext('polling',c);
  vm.runInContext(`closeWorkspaceContext();openPaperContext('p1','citations')`,c);
  assert.match(vm.runInContext('contextPanelView()',c),/data-citation-elapsed/);
  vm.runInContext('state.contextCitations.get(contextCitationKey(state.context)).task.controller.abort()',c);
  await vm.runInContext('pending',c);
  assert.equal(vm.runInContext('stopped',c),true);
  assert.match(vm.runInContext('contextPanelView()',c),/重试后续引用/);
  await vm.runInContext('runContextCitation(state.context,state.contextCitations.get(contextCitationKey(state.context)).retry)',c);
  const requests=JSON.parse(vm.runInContext('JSON.stringify(sent)',c));
  assert.equal(requests[1].direction,'citations');
  assert.equal(requests[1].constraints.year_from,2020);
  assert.notEqual(requests[1].request_id,requests[0].request_id);
  assert.match(vm.runInContext('contextPanelView()',c),/已在当前研究中/);
});

test('citation deadline and source failure return distinct retryable states', async () => {
  const {c}=workbench();
  c.setTimeout=(callback,delay)=>{assert.equal(delay,60_000);c.expire=callback;return 0;};
  vm.runInContext(`openPaperContext('p1','citations');attempt=0;
    api=async(path,options,onProgress)=>{
      if(attempt++>0)return{run_id:'r',related:{status:'unavailable',source_status:'rate_limited'}};
      onProgress({stage:'citation_fetch',task_id:'known-citation',status:'running'});
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    pending=exploreContextCitations('references');`,c);
  assert.match(vm.runInContext('contextPanelView()',c),/从 OpenAlex 获取引文/);
  c.expire();
  await vm.runInContext('pending',c);
  assert.match(vm.runInContext('contextPanelView()',c),/等待引文结果超时/);
  await vm.runInContext('runContextCitation(state.context,state.contextCitations.get(contextCitationKey(state.context)).retry)',c);
  assert.match(vm.runInContext('contextPanelView()',c),/引文来源暂时限流/);
  assert.match(vm.runInContext('contextPanelView()',c),/重试参考文献/);
});

test('an intentionally deferred citation map offers generation without a setup error', () => {
  const {c}=workbench();
  const html=vm.runInContext(`mapView({status:'pending',algorithm:'unavailable',embedding:{reason:'引文结果已保存'}})`,c);
  assert.match(html,/生成研究地图/);
  assert.match(html,/data-map-retry[^>]*>生成地图/);
  assert.match(html,/引文结果已保存/);
  assert.doesNotMatch(html,/download-model/);
});

test('a withdrawn PDF keeps the active research and explains the issue in the sidebar', async () => {
  const {c} = workbench();
  vm.runInContext(`openPaperContext('p2','reader');
    api=async()=>({run_id:'failed-copy',acquisition:{documents:[{paper_id:'p2',status:'missing',error_code:'arxiv_withdrawn',pdf_saved:false}]}});
    adoptResearchRun=async()=>{throw new Error('An unsuccessful download must not switch research');};`,c);
  await vm.runInContext('acquireContextPaper()',c);
  assert.equal(vm.runInContext('state.runId',c),'r');
  assert.equal(vm.runInContext('state.context.error',c),'');
  assert.match(vm.runInContext('paperContextView(state.data.papers[1],state.context)',c),/当前版本已撤回/);
});

test('an unavailable PDF explains what the source lacks and keeps the result when reopening the paper', async () => {
  const {c} = workbench();
  vm.runInContext(`state.data.papers[1].url='https://doi.org/10.1000/example';
    openPaperContext('p2','reader');
    api=async()=>({run_id:'failed-copy',acquisition:{documents:[{paper_id:'p2',status:'missing',error_code:'fulltext_not_available',pdf_saved:false}]}});
    adoptResearchRun=async()=>{throw new Error('An unavailable PDF must not switch research');};`,c);
  const view='paperContextView(state.data.papers[1],state.context)';
  assert.match(vm.runInContext(view,c),/正文处理完成后会打开「全文分析」/);
  await vm.runInContext('acquireContextPaper()',c);
  vm.runInContext("closeWorkspaceContext();openPaperContext('p2','analysis');",c);
  const html=vm.runInContext(view,c);
  assert.match(html,/当前来源未提供可自动下载的公开 PDF/);
  assert.match(html,/href="https:\/\/doi.org\/10.1000\/example"/);
  assert.match(html,/data-panel-import/);
  assert.doesNotMatch(html,/data-analyze-paper/);
});

test('a parsed PDF opens analysis for the same paper after acquisition', async () => {
  const {c} = workbench();
  vm.runInContext(`openPaperContext('p2','reader');
    api=async()=>({run_id:'with-pdf',acquisition:{documents:[{paper_id:'p2',status:'parsed',pdf_saved:true}]}});
    adoptResearchRun=async id=>{state.runId=id;state.data.fulltext_audit.documents.push({paper_id:'p2',status:'parsed',page_count:12});return true;};`,c);
  await vm.runInContext('acquireContextPaper()',c);
  assert.equal(vm.runInContext('state.runId',c),'with-pdf');
  assert.equal(vm.runInContext('state.context.tab',c),'analysis');
  assert.match(vm.runInContext('paperContextView(state.data.papers[1],state.context)',c),/已处理 12 页.*分析方法与实验/);
});

test('opening a saved research result loads the run and its conversation concurrently', async () => {
  const {c} = workbench();
  const calls = [];
  let sendRun;
  c.fetch = path => {
    calls.push(path);
    if (path === '/api/run/saved') return new Promise(resolve => {sendRun = resolve;});
    assert.equal(path, '/api/chat/saved');
    return Promise.resolve({ok:true,json:async () => ({messages:[{content:'Saved research question'}]})});
  };
  const loading = vm.runInContext("state.view='funnel';loadRun('saved',false);",c);
  assert.deepEqual(calls, ['/api/run/saved','/api/chat/saved']);
  sendRun({ok:true,json:async () => ({offline:true,papers:[]})});
  assert.equal(await loading,true);
  assert.equal(vm.runInContext('state.chat.messages[0].content',c),'Saved research question');
});

test('rapidly reopening a PDF page shares the in-flight text layer request', async () => {
  const {c} = workbench();
  const calls = [];
  let sendText;
  c.fetch = path => {
    calls.push(path);
    return new Promise(resolve => {sendText = resolve;});
  };
  const layer = () => ({dataset:{readerTextPage:'3'},isConnected:true,closest:() => ({style:{}})});
  const old = layer();
  const current = layer();
  c.oldReader = {querySelectorAll:() => [old]};
  c.currentReader = {querySelectorAll:() => [current]};
  const renders = vm.runInContext(`state.context={paperId:'p1'};
    Promise.all([hydrateReaderText(oldReader,state.context,'r'),hydrateReaderText(currentReader,state.context,'r')]);`,c);
  assert.deepEqual(calls, ['/api/pdf-text/r/p1/3']);
  old.isConnected = false;
  sendText({ok:true,json:async () => ({width:612,height:792,words:[{text:'Shared text',x:0,y:0,width:.2,height:.1}]})});
  await renders;
  assert.equal(old.innerHTML,undefined);
  assert.match(current.innerHTML,/Shared text/);
});

test('acquisition progress stays with the paper and stopping it unlocks retry and import', async () => {
  const {c} = workbench();
  const requests = [];
  const stage = {textContent: ''};
  c.document.querySelector = selector => selector === '[data-fulltext-stage]' ? stage : null;
  let pollStarted;
  const polling = new Promise(resolve => {pollStarted = resolve;});
  let polls = 0;
  c.fetch = async (path, options) => {
    requests.push([path, options.method]);
    if (options.method === 'POST') {
      assert.equal(options.headers.Prefer, 'respond-async');
      assert.deepEqual(JSON.parse(options.body).paper_ids, ['p2']);
      return {ok: true, status: 202, json: async () => ({task_id:'paper-job'})};
    }
    if (options.method === 'DELETE') return {ok: true};
    if (polls++ === 0) return {ok: true, json: async () => ({stage:'fulltext_download',status:'running'})};
    pollStarted();
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason)));
  };
  const acquisition = vm.runInContext("openPaperContext('p2','reader');acquireContextPaper();",c);
  await polling;
  assert.equal(stage.textContent,'连接来源并下载 PDF');
  vm.runInContext("closeWorkspaceContext();openPaperContext('p2','analysis');",c);
  const active = vm.runInContext('contextPanelView()',c);
  assert.match(active,/连接来源并下载 PDF.*data-stop-fulltext/);
  assert.doesNotMatch(active,/data-panel-acquire|data-panel-import/);
  await vm.runInContext('acquireContextPaper()',c);
  vm.runInContext("state.acquisitionTasks.get('r:p2').controller.abort();",c);
  await acquisition;
  assert.equal(requests.filter(([,method]) => method === 'POST').length,1);
  assert.deepEqual(requests.at(-1),['/api/tasks/paper-job','DELETE']);
  const stopped = vm.runInContext('contextPanelView()',c);
  assert.match(stopped,/已停止等待.*data-panel-acquire.*data-panel-import/);
  assert.doesNotMatch(stopped,/data-stop-fulltext/);
});

test('a stalled submission stops waiting even before the server returns a task id', async () => {
  const {c} = workbench();
  let deadline;
  c.setTimeout = (callback, delay) => {assert.equal(delay,180_000);deadline = callback;return 0;};
  c.fetch = (path, options) => {
    assert.equal(path,'/api/audit/upgrade');
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason)));
  };
  const acquisition = vm.runInContext("openPaperContext('p2','reader');acquireContextPaper();",c);
  deadline();
  await acquisition;
  const html = vm.runInContext('contextPanelView()',c);
  assert.match(html,/等待全文获取超时.*data-panel-acquire.*data-panel-import/);
  assert.doesNotMatch(html,/data-stop-fulltext/);
});

test('a stalled result load has a deadline and keeps a direct link to the saved analysis', async () => {
  const {c} = workbench();
  let deadline;
  c.setTimeout = (callback, delay) => {assert.equal(delay,180_000);deadline = callback;return 0;};
  let loading;
  const resultLoading = new Promise(resolve => {loading = resolve;});
  c.fetch = async (path, {signal}) => {
    if (path === '/api/audit/upgrade') return {ok:true,status:200,json:async () => ({run_id:'saved',acquisition:{documents:[{paper_id:'p2',status:'parsed',pdf_saved:true}]}})};
    if (path === '/api/chat/saved') return {ok:true,json:async () => ({messages:[]})};
    assert.equal(path,'/api/run/saved');
    loading();
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  };
  const acquisition = vm.runInContext("openPaperContext('p2','reader');acquireContextPaper();",c);
  await resultLoading;
  deadline();
  await acquisition;
  assert.equal(vm.runInContext('state.chatKey',c),'run:r');
  const html = vm.runInContext('contextPanelView()',c);
  assert.match(html,/打开结果时连接中断/);
  assert.match(html,/href="\/\?run=saved&amp;panel=paper&amp;paper=p2&amp;tab=analysis"/);
  assert.doesNotMatch(html,/data-stop-fulltext/);
});

test('topic follow-ups retain the exact version and update the selected cluster from the response', async () => {
  const {c} = workbench();
  const version='a'.repeat(64);
  vm.runInContext(`graph={map_version:'${version}',tracks:[
    {cluster_id:'topic-11111111111111111111',display_index:1,label:'第一组研究',paper_ids:['p1']},
    {cluster_id:'topic-22222222222222222222',display_index:2,label:'第二组研究',paper_ids:['p2']}]};
    openTopicContext('topic-22222222222222222222',graph);
    api=async(path,options)=>{sent=JSON.parse(options.body);return{status:'completed',run_id:'r',response:{overview:'第二组研究方法',
      map_answer:{map_version:'${version}',selected_cluster_ids:['topic-22222222222222222222']}}}};
    adoptResearchRun=async()=>true;refreshConversations=async()=>{};`,c);
  await vm.runInContext("askFromContext('详细解释这个主题',true)",c);
  const sent=JSON.parse(vm.runInContext('JSON.stringify(sent)',c));
  assert.deepEqual(sent.map_context,{map_version:version,cluster_ids:['topic-22222222222222222222']});
  assert.equal(sent.reading_mode,false);
  assert.equal(sent.reading_paper_id,undefined);
  assert.equal(vm.runInContext('state.mapContext.cluster_ids[0]',c),'topic-22222222222222222222');
});

test('topic panel separates the shared direction from each paper and its own source', () => {
  const {c} = workbench();
  const html = vm.runInContext(`topicContextView({topic:{label:'相近研究', paper_ids:['p1','p2'],
    common_direction:'两篇共同方向', common_sources:[{paper_id:'p1',field:'title',quote:'共享依据一'}],
    paper_tasks:[{paper_id:'p2',task:'第二篇的专属任务',source:{paper_id:'p2',field:'abstract',quote:'本篇原句'}}]}})`, c);
  const shared = html.split('<h4>各篇论文</h4>')[0];
  assert.match(shared, /共同方向[\s\S]*两篇共同方向[\s\S]*共同方向来源[\s\S]*共享依据一/);
  assert.doesNotMatch(shared, /第二篇的专属任务|本篇原句/);
  assert.match(html, /data-inspect-paper="p2"[\s\S]*Study two[\s\S]*第二篇的专属任务/);
  assert.match(html, /逐篇任务来源[\s\S]*Study two[\s\S]*本篇原句/);
});

test('topic refresh shows progress and clickable results above both active graphs without reloading the run', async () => {
  const {c} = workbench();
  vm.runInContext(`state.view='map';
    track={track_id:'semantic-1',cluster_id:'topic-1',label:'旧名称',paper_ids:['p1']};
    state.data.map={run_id:'r',map_version:'v1',nodes:[{paper_id:'p1',title:'Study one',track_id:track.track_id}],tracks:[track],edges:[]};
    originalNodes=state.data.map.nodes;originalChat=state.chat;state.selectedPaper='p1';
    openTopicContext('topic-1');originalPanel=state.context;
    loadRun=()=>{throw new Error('Topic refresh must not reload the entire run');};
    paint=({preserveGraphLayout}={})=>{if(!preserveGraphLayout)throw new Error('Preserve graph layout during topic refresh');};
    sends=[];
    gate=new Promise(resolve=>release=resolve);
    api=async(path,options,progress)=>{
      sends.push([path,JSON.parse(options.body)]);
      progress({stage:'map_topics_generate',status:'running',task_id:'topics-test'});
      await gate;
      return {run_id:'r',map_version:'v1',topics:[{...track,label:'证据问答方法',member_count:1},
        {cluster_id:'single',label:'其他研究',paper_ids:['p2'],member_count:1}],naming_status:'model',
        refresh_status:sends.length===1?'generated':'cached'};
    };
    refreshed=refreshMapTopics();`,c);
  let html=vm.runInContext('mapView()',c);
  assert.match(html,/data-refresh-map-topics disabled>整理中/);
  assert.match(html,/data-map-topic-stage>根据论文整理主题/);
  assert.match(html,/data-map-topic-elapsed/);
  assert.match(html,/data-stop-map-topics/);
  vm.runInContext('release()',c);
  await vm.runInContext('refreshed',c);
  html=vm.runInContext('mapView()',c);
  assert.match(html,/已整理 2 个主题/);
  assert.match(html,/data-map-topic-results[\s\S]*data-open-topic="topic-1"[\s\S]*证据问答方法[\s\S]*class="graph-wrap/);
  assert.match(vm.runInContext("mapView(state.data.map,{embed:true,graphId:'chat-map-0'})",c),/data-refresh-map-topics[\s\S]*data-map-topic-results/);
  assert.doesNotMatch(vm.runInContext("mapView({...state.data.map,run_id:'old',map_version:'v0'},{embed:true,graphId:'chat-map-1'})",c),/data-refresh-map-topics/);
  assert.equal(vm.runInContext("state.data.map.nodes===originalNodes && state.chat===originalChat && state.context===originalPanel && state.selectedPaper==='p1'",c),true);
  assert.equal(vm.runInContext('state.context.topic.label',c),'证据问答方法');
  vm.runInContext("openTopicContext('single')",c);
  assert.equal(vm.runInContext('state.context.topic.label',c),'其他研究');
  await vm.runInContext('refreshMapTopics()',c);
  assert.match(vm.runInContext('mapView()',c),/已显示上次整理的 2 个主题/);
  const requests=JSON.parse(vm.runInContext('JSON.stringify(sends)',c));
  assert.equal(requests.length,2);
  assert.ok(requests.every(([url,body])=>url==='/api/map-topics/refresh' && body.run_id==='r' && body.force===undefined));
  assert.notEqual(requests[0][1].request_id,requests[1][1].request_id);
});

test('topic refresh can be stopped with no loss of the previous labels', async () => {
  const {c}=workbench();
  vm.runInContext(`state.view='map';
    state.data.map={run_id:'r',map_version:'v1',nodes:[{paper_id:'p1',title:'Study one'}],
      tracks:[{track_id:'semantic-1',label:'已有主题',paper_ids:['p1']}],edges:[]};
    api=async(path,options,progress)=>{
      progress({stage:'map_topics_generate',status:'running',task_id:'topic-id'});
      await new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    refreshed=refreshMapTopics();
    mapTopicRefreshEntry(state.data.map).task.controller.abort();`,c);
  await vm.runInContext('refreshed',c);
  const html=vm.runInContext('mapView()',c);
  assert.match(html,/已停止等待/);
  assert.match(html,/重试整理主题/);
  assert.match(html,/已有主题/);
  assert.doesNotMatch(html,/data-stop-map-topics/);
});

test('source configuration shows active providers and key presence without secret values', () => {
  const {c} = workbench();
  vm.runInContext(`state.sources={result:{sources:[{id:'semantic_scholar',label:'Semantic Scholar',
    configuration:{environment_variable:'SEMANTIC_SCHOLAR_API_KEY'}},
    {id:'arxiv',label:'arXiv'},
    {id:'openalex',label:'OpenAlex',key_configured:true,api_key:'SECRET-MUST-NOT-RENDER',
    connection:{status:'failed',http_status:503,message:'检索暂不可用 <debug>'},
    configuration:{environment_variable:'OPENALEX_API_KEY',apply_url:'https://openalex.org/settings/api'}}]}}`,c);
  const html=vm.runInContext('sourceSettingsView()',c);
  assert.ok(html.includes('API Key 已配置'));
  assert.ok(html.includes('data-test-source="arxiv"'));
  assert.ok(html.includes('data-test-source="openalex"'));
  assert.ok(!html.includes('Semantic Scholar')&&!html.includes('SEMANTIC_SCHOLAR_API_KEY'));
  assert.ok(html.includes('OPENALEX_API_KEY=你的密钥'));
  assert.ok(html.includes('503')&&html.includes('检索暂不可用 &lt;debug&gt;'));
  assert.ok(!html.includes('SECRET-MUST-NOT-RENDER'));
});

test('source probe transmits only the selected registry identifier and restores its button state', async () => {
  const {c} = workbench();
  vm.runInContext(`state.context={kind:'sources'};state.sources={result:{sources:[{id:'openalex'}]}};
    api=async(path,options)=>{sent={path,body:JSON.parse(options.body)};return{source:{id:'openalex',connection:{status:'connected'}}}}`,c);
  await vm.runInContext("testSource('openalex')",c);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(sent)',c)),{path:'/api/sources/test',body:{source:'openalex'}});
  assert.equal(vm.runInContext('state.sources.testing',c),'');
  assert.equal(vm.runInContext('state.sources.result.sources[0].connection.status',c),'connected');
});

test('a research refresh cannot reopen a closed panel or replace a newer paper selection', async () => {
  for (const next of ['closed','new-paper']) {
    const {c}=workbench();
    vm.runInContext(`state.context={kind:'paper',paperId:'p1',tab:'reader',page:2};
      loadRun=async()=>{${next==='closed'?'closeWorkspaceContext()':"openPaperContext('p2')"};return true};`,c);
    await vm.runInContext("adoptResearchRun('r')",c);
    if(next==='closed') assert.equal(vm.runInContext('state.context',c),null);
    else assert.equal(vm.runInContext('state.context.paperId',c),'p2');
  }
});

test('history restores a historical topic after visiting a paper without changing map membership', () => {
  const {c,historyCalls}=workbench();
  const oldVersion='a'.repeat(64),currentVersion='b'.repeat(64);
  vm.runInContext(`oldTopic={cluster_id:'topic-11111111111111111111',display_index:1,label:'旧地图主题',summary:'旧地图成员共同研究的问题',paper_ids:['p1']};
    oldGraph={map_version:'${oldVersion}',tracks:[oldTopic]};
    state.data.map={map_version:'${currentVersion}',tracks:[{cluster_id:'topic-22222222222222222222',label:'当前主题',paper_ids:['p2']}]};
    state.chat.messages=[{role:'assistant',response:{map_answer:{map_version:'${oldVersion}',topics:[oldTopic]}}}];
    openTopicContext(oldTopic.cluster_id,oldGraph);`,c);
  const descriptor=historyCalls.at(-1)[1].workspaceContext;
  assert.equal(descriptor.mapVersion,oldVersion);
  assert.equal(descriptor.topic.label,'旧地图主题');
  c.descriptor=descriptor;
  vm.runInContext("openPaperContext('p2')",c);
  const count=historyCalls.length;
  vm.runInContext('restoreWorkspaceContext(descriptor)',c);
  assert.equal(historyCalls.length,count,'history replay must not create another history entry');
  assert.equal(vm.runInContext('state.context.kind',c),'topic');
  assert.equal(vm.runInContext('state.context.topic.label',c),'旧地图主题');
  assert.equal(vm.runInContext('state.mapContext.map_version',c),oldVersion);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(state.context.topic.paper_ids)',c)),['p1']);
  assert.ok(vm.runInContext('contextPanelView()',c).includes('旧地图主题'));
  assert.equal(vm.runInContext('state.view',c),'methods');
});

test('field history restores the field, source version and manual value and rejects an unknown paper', () => {
  const {c,historyCalls}=workbench();
  vm.runInContext(`state.methods.result={papers:[{paper_id:'p1',fields:{baseline:{candidate:{paper_id:'p1',passage_id:'p1:p4:c1',page:4,quote:'Exact original baseline',text_sha256:'original-hash'},review:{display_value:'人工基线'}}}}]};
    openFieldContext('p1','baseline','baseline comparison');`,c);
  c.descriptor=historyCalls.at(-1)[1].workspaceContext;
  vm.runInContext("openPaperContext('p2');restoreWorkspaceContext(descriptor)",c);
  assert.equal(vm.runInContext('state.context.tab',c),'field');
  assert.equal(vm.runInContext('state.context.field',c),'baseline');
  assert.equal(vm.runInContext('state.context.query',c),'baseline comparison');
  assert.equal(vm.runInContext('state.context.reviewHit.text_sha256',c),'original-hash');
  assert.equal(vm.runInContext('state.context.review.display_value',c),'人工基线');
  const html=vm.runInContext('contextPanelView()',c);
  assert.ok(html.includes('data-text-hash="original-hash"')&&html.includes('人工基线'));
  vm.runInContext("restoreWorkspaceContext({kind:'paper',paperId:'foreign',tab:'field',field:'baseline'})",c);
  assert.equal(vm.runInContext('state.context',c),null);
});

test('an awaited research copy retains the topic comparison and reading scope most recently chosen by the user', async () => {
  const {c}=workbench();
  vm.runInContext(`state.view='chat';state.context={kind:'paper',paperId:'p1',tab:'reader'};
    state.data.fulltext_audit.documents.push({paper_id:'p2',status:'parsed',page_count:5});
    state.methods.selected=['p1'];state.readingPaperId='p1';state.readingMode=false;
    state.mapContext={map_version:'${'a'.repeat(64)}',cluster_ids:['topic-11111111111111111111']};
    originalData=state.data;gate=new Promise(resolve=>releaseRun=resolve);
    api=async path=>{if(path==='/api/run/copy'){await gate;return originalData}if(path==='/api/chat/copy')return{messages:[]};throw new Error(path)};
    adoption=adoptResearchRun('copy');
    state.mapContext={map_version:'${'b'.repeat(64)}',cluster_ids:['topic-22222222222222222222']};
    state.methods.selected=['p2'];state.readingPaperId='p2';state.readingMode=true;state.methodFieldsExpanded=true;
    openPaperContext('p2');newPane=state.context;releaseRun();`,c);
  await vm.runInContext('adoption',c);
  assert.equal(vm.runInContext('state.runId',c),'copy');
  assert.equal(vm.runInContext('state.context===newPane',c),true);
  assert.equal(vm.runInContext('state.mapContext.map_version',c),'b'.repeat(64));
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(state.methods.selected)',c)),['p2']);
  assert.equal(vm.runInContext('state.readingPaperId',c),'p2');
  assert.equal(vm.runInContext('state.readingMode',c),true);
  assert.equal(vm.runInContext('state.methodFieldsExpanded',c),true);
});

test('a new source page clears a previous selection and question before its follow-up request', async () => {
  const {c}=workbench();
  vm.runInContext(`state.context={kind:'paper',paperId:'p1',tab:'reader',page:2,quote:'Old page quote',selection:'Old selected text',questionDraft:'Old question'};
    openReaderContext('p1',5,'New page original quote');
    api=async(path,options)=>{sent=JSON.parse(options.body);return{status:'completed',run_id:'r',response:{overview:'New source answer'}}};
    adoptResearchRun=async()=>true;refreshConversations=async()=>{};`,c);
  assert.equal(vm.runInContext('state.context.selection',c),'');
  assert.equal(vm.runInContext('state.context.questionDraft',c),'');
  await vm.runInContext("askFromContext('Explain this page')",c);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(sent.reading_selection)',c)),
    {paper_id:'p1',page:5,quote:'New page original quote'});
});

test('acquire import and citation completion cannot modify a newer material panel during adoption', async () => {
  for(const operation of ['acquire','import','citations']) {
    const {c}=workbench();
    c.FileReader=class {
      readAsDataURL(){this.result='data:application/pdf;base64,JVBERi0=';queueMicrotask(()=>this.onload());}
    };
    vm.runInContext(`state.context={kind:'paper',paperId:'p1',tab:'reader'};
    api=async(path,options)=>{sent=JSON.parse(options.body);return{run_id:'r',paper_id:'p1'}};
      adoptResearchRun=async()=>{openPaperContext('p2');state.context.notice='Latest paper remains selected';newPane=state.context;return true};`,c);
    if(operation==='acquire') await vm.runInContext('acquireContextPaper()',c);
    if(operation==='import') {
      await vm.runInContext("importContextPaper({target:{files:[{name:'paper.pdf',size:100}]}})",c);
      assert.equal(vm.runInContext('sent.paper_id',c),'p1');
    }
    if(operation==='citations') await vm.runInContext("exploreContextCitations('references')",c);
    assert.equal(vm.runInContext('state.context===newPane',c),true,operation);
    assert.equal(vm.runInContext('state.context.paperId',c),'p2',operation);
    assert.equal(vm.runInContext('state.context.tab',c),'overview',operation);
    assert.equal(vm.runInContext('state.context.notice',c),'Latest paper remains selected',operation);
    assert.equal(vm.runInContext('state.context.error',c),undefined,operation);
  }
});

test('manual topic naming sends its exact map identity escapes the label and ignores a stale panel', async () => {
  const name='Edited <topic> "name"';
  for(const stale of [false,true]) {
    const {c}=workbench();
    const button={disabled:false};
    c.form={querySelector:()=>button};
    c.FormData=class {get(){return '  '+name+'  '}};
    vm.runInContext(`topic={cluster_id:'topic-11111111111111111111',label:'Original topic',paper_ids:['p1'],map_version:'${'a'.repeat(64)}'};
      state.data.map={tracks:[topic,{cluster_id:'topic-22222222222222222222',label:'Other topic',paper_ids:['p2']}]};
      state.context={kind:'topic',clusterId:topic.cluster_id,topic,map:{map_version:topic.map_version}};
      api=async(path,options)=>{sent={path,body:JSON.parse(options.body)};${stale?"openPaperContext('p2');":''}
        return{topic:{...topic,label:sent.body.label,label_source:'human'}}};`,c);
    await vm.runInContext('saveContextTopicLabel({preventDefault(){},target:form})',c);
    const sent=JSON.parse(vm.runInContext('JSON.stringify(sent)',c));
    assert.deepEqual(sent,{path:'/api/map-topics/label',body:{run_id:'r',cluster_id:'topic-11111111111111111111',map_version:'a'.repeat(64),label:name}});
    assert.equal(button.disabled,false);
    assert.equal(vm.runInContext('state.data.map.tracks[1].label',c),'Other topic');
    if(stale) {
      assert.equal(vm.runInContext('state.context.paperId',c),'p2');
      assert.equal(vm.runInContext('state.data.map.tracks[0].label',c),'Original topic');
    } else {
      assert.equal(vm.runInContext('state.context.topic.label_source',c),'human');
      assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(state.context.topic.paper_ids)',c)),['p1']);
      const html=vm.runInContext('contextPanelView()',c);
      assert.ok(html.includes('Edited &lt;topic&gt; &quot;name&quot;'));
      assert.ok(!html.includes('Edited <topic>'));
      assert.ok(html.includes('maxlength="80"')&&html.includes('data-topic-label'));
    }
  }
});

test('natural reading answers keep substantive limitations while removing repeated status boilerplate', () => {
  const {c} = workbench();
  c.text='模型在小样本上更稳定。\n论文报告该方法只在英语数据上测试。\n引用完整性检查已通过（不代表语义已人工复核）\n本条仅列出待核验内容';
  const text=vm.runInContext('cleanAssistantText(text)',c);
  assert.ok(text.includes('论文报告该方法只在英语数据上测试。'));
  assert.ok(text.includes('模型在小样本上更稳定。'));
  assert.ok(!text.includes('引用完整性检查')&&!text.includes('本条仅列出'));
});
