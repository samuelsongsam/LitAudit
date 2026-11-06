const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

function app() {
  const source = fs.readFileSync(path.join(__dirname, '../src/ui/static/workspace.js'), 'utf8')+'\n'+fs.readFileSync(path.join(__dirname, '../src/ui/static/app.js'), 'utf8');
  const context = vm.createContext({ URLSearchParams, URL, AbortController, setInterval, clearInterval,
    location: { search: '', href: 'http://localhost/' } });
  vm.runInContext(source.slice(0, source.lastIndexOf('boot().catch')), context);
  vm.runInContext(`state.data = {
    offline: false, live: {added_paper_ids: [], matched_paper_ids: ['hit'], retrieval: []},
    papers: [{paper_id: 'hit', title: 'Matched paper', decision: 'include'},
             {paper_id: 'old', title: 'Unrelated baseline', decision: 'exclude'}],
    stats: {paper_count: 2, decision_counts: {include: 1, exclude: 1}},
    screening: [{paper_id: 'old', reason: 'Unrelated screening'}],
    claims: [], evidence: [], falsification: [], retrieval_runs: [],
    eval: {paper_count: 1, verified_evidence_count: 0, delta_vs_no_retrieval: {}}
  }; state.selectedPaper = 'old';`, context);
  return context;
}

test('funnel and inspector show matched existing paper, never unrelated baseline', () => {
  const context = app();
  const html = vm.runInContext('funnelView()', context);
  assert.ok(html.includes('Matched paper'));
  assert.ok(!html.includes('Unrelated baseline'));
  assert.ok(!html.includes('Unrelated screening'));
  assert.equal(vm.runInContext('scopedAuditData().stats.paper_count', context), 1);
  assert.equal(vm.runInContext('scopedAuditData().stats.decision_counts.exclude', context), 0);
});

test('empty installation renders an editable research workspace instead of a boot dead end', async () => {
  const context = app();
  vm.runInContext(`api = async path => path === '/api/runs' ? {runs: [], default_run_id: null} : {conversations: []};
    paint = () => {}; state.runId = '';`, context);
  await vm.runInContext('boot()', context);
  assert.equal(vm.runInContext('state.chatNew', context), true);
  const html = vm.runInContext('chatView()', context);
  assert.ok(html.includes('id="search-form"'));
  assert.ok(html.includes('aria-label="研究问题"'));
  assert.ok(html.includes('data-example-query'));
});

test('a pending request keeps the replacement compose button disabled and rejects duplicate turns', async () => {
  const context = app();
  let resolve;
  let requests = 0;
  context.pending = new Promise(done => { resolve = done; });
  context.onRequest = () => { requests += 1; };
  vm.runInContext(`paint = () => {}; document = {querySelectorAll: () => []};
    api = async () => {onRequest(); return pending;}; state.chatKey = 'draft:test';
    firstTurn = chatTurn('first request');`, context);
  try {
    await vm.runInContext("chatTurn('duplicate request')", context);
    assert.equal(requests, 1);
    assert.equal(vm.runInContext('state.chat.messages.length', context), 1);
    const html = vm.runInContext('chatView()', context);
    assert.match(html, /<button class="solid" type="submit" disabled>处理中…<\/button>/);
    assert.match(html, /<input name="q"[^>]*disabled/);
  } finally {
    resolve({ status: 'needs_clarification', response: {overview: 'clarify', clarification_questions: []} });
    await vm.runInContext('firstTurn', context);
  }
  assert.equal(vm.runInContext('activeChatTask()', context), null);
});

test('late result from an old draft never appends to the newly selected conversation', async () => {
  const context = app();
  let resolve;
  context.pending = new Promise(done => { resolve = done; });
  vm.runInContext(`paint = () => {}; document = {querySelectorAll: () => []};
    api = async path => path === '/api/chat' ? pending : {conversations: []};
    state.chatKey = 'draft:old'; oldTurn = chatTurn('old question');
    state.chatKey = 'run:new'; state.runId = 'new';
    state.chat = {messages: [{role: 'user', content: 'new question'}]};`, context);
  resolve({ status: 'completed', run_id: 'old-result', response: {overview: 'old answer'} });
  await vm.runInContext('oldTurn', context);
  assert.equal(vm.runInContext('state.runId', context), 'new');
  assert.equal(vm.runInContext('state.chat.messages.length', context), 1);
  assert.equal(vm.runInContext('state.chat.messages[0].content', context), 'new question');
  assert.equal(vm.runInContext('state.backgroundNotice.runId', context), 'old-result');
});

test('only the pending question offers compact choices with an explicit skip', () => {
  const context = app();
  vm.runInContext(`state.chat = {pendingTopic:'Astra 在具身智能中的研究', messages:[
    {role:'assistant',content:'',response:{overview_mode:'clarification',clarification_questions:[{question:'旧问题',options:['旧选项']}]}},
    {role:'assistant',content:'',response:{overview_mode:'clarification',clarification_questions:[
      {question:'你指的是哪个 Astra 项目？',options:['Project Astra', 'Astra & Robotics']},
      {question:'还要问时间范围？',options:['无关选项']}
    ]}}
  ]};`, context);
  const html = vm.runInContext('chatView()', context);
  assert.equal((html.match(/<fieldset class="clarification-question">/g) || []).length, 1);
  assert.match(html, /你指的是哪个 Astra 项目？/);
  assert.match(html, /Astra &amp; Robotics/);
  assert.match(html, /<button class="solid" type="submit" disabled>按此范围检索/);
  assert.match(html, /data-clarification-skip>按原问题检索/);
  assert.match(html, /当时的范围确认/);
  assert.doesNotMatch(html, /\bchecked\b|旧选项|还要问时间范围|无关选项/);
});

test('a free-text clarification and the skip action send independent search requests', async () => {
  const context = app();
  const submit = {disabled: false};
  const skip = {};
  const input = {value: ''};
  const form = {
    querySelector(selector) {
      return {'[data-clarification-skip]': skip, 'button[type=submit]': submit,
        '.clarification-other-input': input, '.clarification-other': {}}[selector];
    },
    querySelectorAll: () => []
  };
  context.stage = {querySelector: () => form};
  vm.runInContext(`paint = () => {}; document = {querySelectorAll: () => []};
    state.chat.pendingTopic = 'Astra 在具身智能中的研究';
    state.readingMode = true; state.readingPaperId = 'hit'; state.mapContext = {map_version:'old'};
    captured = []; api = async (path, options) => {
      captured.push(JSON.parse(options.body)); return {status:'completed',response:{overview:'结果'}};
    };
    bindClarification(stage);`, context);
  assert.equal(submit.disabled, true);
  await form.onsubmit({preventDefault() {}});
  assert.equal(vm.runInContext('captured.length', context), 0);
  input.value = '  Google DeepMind 的 Project Astra  ';
  input.oninput();
  assert.equal(submit.disabled, false);
  await form.onsubmit({preventDefault() {}});
  vm.runInContext("state.chat.pendingTopic = 'Astra 在具身智能中的研究'; bindClarification(stage);", context);
  await skip.onclick();
  const [answer, direct] = JSON.parse(vm.runInContext('JSON.stringify(captured)', context));
  assert.equal(answer.clarification_topic, 'Astra 在具身智能中的研究');
  assert.deepEqual(answer.clarification_context, ['Google DeepMind 的 Project Astra']);
  assert.equal(direct.message, 'Astra 在具身智能中的研究');
  assert.equal(direct.skip_clarification, true);
  assert.deepEqual(direct.clarification_context, []);
  for (const body of [answer, direct]) {
    assert.equal(body.reading_mode, false);
    assert.equal(body.reading_paper_id, undefined);
    assert.equal(body.map_context, undefined);
  }
  assert.equal(vm.runInContext('state.chat.pendingTopic', context), '');
});

test('fulltext and method views expose original pages, manual confirmation and escaped source text', () => {
  const context = app();
  vm.runInContext(`state.runId = 'current'; state.fulltext.result = {indexed_paper_count: 1, passage_count: 4,
    hits: [{passage_id:'hit:p7:c1',paper_id:'hit',title:'Matched paper',page:7,text:'A method <script>',text_sha256:'abc'}]};
    state.methods.result = {papers:[{paper_id:'hit',title:'Matched paper',has_fulltext:true,
      fields:{method:{candidate:{passage_id:'hit:p7:c1',paper_id:'hit',page:7,text:'A method <script>',text_sha256:'abc'},status:'pending'}}}]};`, context);
  const fulltext = vm.runInContext('fulltextView()', context);
  const methods = vm.runInContext('methodsView()', context);
  vm.runInContext(`state.context={kind:'paper',paperId:'hit',tab:'field',field:'method',
    reviewHit:state.methods.result.papers[0].fields.method.candidate}`,context);
  const panel=vm.runInContext('contextPanelView()',context);
  assert.ok(fulltext.includes('data-read-pdf="hit" data-page="7"'));
  assert.ok(methods.includes('data-context-source="hit" data-page="7"'));
  for (const html of [fulltext, methods, panel]) {
    assert.ok(html.includes('A method &lt;script&gt;'));
    assert.ok(!html.includes('A method <script>'));
  }
  for (const html of [fulltext,panel]) {
    assert.ok(html.includes('data-review-form'));
    assert.ok(html.includes('data-text-hash="abc"'));
  }
  assert.ok(fulltext.includes('/api/fulltext/current/hit#page=7'));
  const methodCell = vm.runInContext("methodFieldCell(state.methods.result.papers[0],'method')", context);
  assert.equal((methodCell.match(/data-context-source=/g) || []).length, 1);
  assert.ok(methodCell.includes('data-edit-method-field="hit" data-field="method"'));
  assert.ok(!methodCell.includes('data-review-form'));
  assert.ok(methods.includes('data-method-export'));
  assert.ok(methods.includes('待人工确认'));
  assert.ok(fulltext.includes('正文检索线索'));
});

test('saved manual research records appear separately from original claim audit', () => {
  const context = app();
  vm.runInContext(`state.data.research_workspace = {reviews: [{status:'accepted',paper_id:'hit',page:7,
    passage_id:'hit:p7:c1',text:'Source excerpt',claim:'My reading note',note:'Check the baseline'}]};`, context);
  const html = vm.runInContext('researchReviewView()', context);
  assert.ok(html.includes('人工已确认'));
  assert.ok(html.includes('Source excerpt'));
  assert.ok(html.includes('My reading note'));
  assert.ok(html.includes('原有论断判决保留'));
  assert.ok(!html.includes('已有证据支持的论断'));
});

test('unavailable map preserves candidate count and offers explicit model repair without a fake empty graph', () => {
  const context = app();
  vm.runInContext(`state.runId='current'; state.data.map={status:'unavailable',algorithm:'unavailable',embedding:{reason:'Missing model cache'},nodes:[],edges:[]};`, context);
  const html = vm.runInContext('mapView()', context);
  assert.ok(html.includes('保留了 1 篇候选论文'));
  assert.ok(html.includes('python -m src.cli download-model'));
  assert.ok(html.includes('data-map-retry'));
  assert.ok(html.includes('Missing model cache'));
  assert.ok(!html.includes('0 篇论文'));
  assert.ok(!html.includes('余弦距离的二维投影'));
  assert.ok(!html.includes('<svg'));
});

test('empty current scope and legacy added-only manifests remain isolated', () => {
  const context = app();
  vm.runInContext('state.data.live.matched_paper_ids = []', context);
  assert.equal(vm.runInContext('scopedAuditData().papers.length', context), 0);
  vm.runInContext("delete state.data.live.matched_paper_ids; state.data.live.added_paper_ids = ['hit']", context);
  assert.equal(vm.runInContext('scopedAuditData().papers.length', context), 1);
  const html = vm.runInContext('evalView()', context);
  assert.ok(html.includes('当前论文'));
  assert.ok(!html.includes('相对「不检索'));
});
