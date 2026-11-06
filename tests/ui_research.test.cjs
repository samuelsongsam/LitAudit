const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

function app(extra = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src/ui/static/workspace.js'), 'utf8')+'\n'+fs.readFileSync(path.join(__dirname, '../src/ui/static/app.js'), 'utf8');
  const context = vm.createContext({
    URLSearchParams, URL, AbortController, setInterval, clearInterval,
    setTimeout: callback => { queueMicrotask(callback); return 0; },
    document: {getElementById: () => null, querySelectorAll: () => [], querySelector: () => null},
    history: {pushState: () => {}, replaceState: () => {}},
    location: {search: '', href: 'http://localhost/'}, ...extra,
  });
  vm.runInContext(source.slice(0, source.lastIndexOf('boot().catch')), context);
  vm.runInContext(`paint=()=>{};state.runId='r';state.chatKey='run:r';state.data={offline:true,
    papers:[{paper_id:'p',title:'Study'}],claims:[],evidence:[],screening:[],falsification:[]};`, context);
  return context;
}

const response = (status, body) => ({status, ok: status >= 200 && status < 300, json: async () => body});

test('method comparison starts with six core fields and exposes all ten with sourced human edits', () => {
  const context = app();
  vm.runInContext(`state.methods.result={papers:[{paper_id:'p',title:'Study',has_fulltext:true,fields:{
    sample_size:{status:'accepted',review:{display_value:'人工核对120名参与者',note:'需核查排除条件'},
      candidate:{paper_id:'p',passage_id:'p:p3:c1',page:3,text:'Full methods paragraph',
        quote:'We included 120 participants <carefully>.',value:'120 participants',text_sha256:'current-hash'}}}}]};`, context);
  const compact = vm.runInContext('methodsView()', context);
  const coreLabels = ['研究问题', '核心方法', '数据集', '评价指标', '主要结果', '适用条件'];
  const advancedLabels = ['样本规模', '实验设置', '比较基线', '资源要求'];
  assert.equal((compact.match(/<th scope="row">/g) || []).length, 6);
  for (const label of coreLabels) assert.ok(compact.includes(`<th scope="row">${label}</th>`), label);
  for (const label of advancedLabels) assert.ok(!compact.includes(`<th scope="row">${label}</th>`), label);
  assert.match(compact, /<details\b[^>]*class="paper-selection"[^>]*>/);
  assert.ok(compact.includes('data-method-fields-toggle'));
  const toggle = {checked: true};
  context.stage = {querySelectorAll: selector => selector === '[data-method-fields-toggle]' ? [toggle] : [], querySelector: () => null};
  vm.runInContext('bindResearchControls(stage)', context);
  toggle.onchange();
  assert.equal(vm.runInContext('state.methodFieldsExpanded', context), true);
  const html = vm.runInContext('methodsView()', context);
  assert.equal((html.match(/<th scope="row">/g) || []).length, 10);
  for (const label of ['研究问题', '核心方法', '数据集', '样本规模', '实验设置', '比较基线', '评价指标', '主要结果', '资源要求', '适用条件']) {
    assert.ok(html.includes(`<th scope="row">${label}</th>`), label);
  }
  assert.ok(html.includes('人工核对120名参与者'));
  assert.ok(html.includes('We included 120 participants &lt;carefully&gt;.'));
  assert.ok(html.includes('data-context-source="p" data-page="3"'));
  assert.ok(html.includes('data-field="sample_size"'));
  for (const label of ['实验设置', '比较基线', '资源要求']) assert.ok(html.includes(`data-field-query="${label}"`), label);
  const cell = vm.runInContext("methodFieldCell(state.methods.result.papers[0],'sample_size')", context);
  assert.equal((cell.match(/data-context-source=/g) || []).length, 1);
  assert.ok(cell.includes('data-edit-method-field="p" data-field="sample_size"'));
  assert.ok(cell.includes('人工已确认'));
  assert.ok(!cell.includes('data-review-form'),'method table should open its editor in the material panel');
  vm.runInContext(`state.context={kind:'paper',paperId:'p',tab:'field',field:'sample_size',
    reviewHit:state.methods.result.papers[0].fields.sample_size.candidate,
    review:state.methods.result.papers[0].fields.sample_size.review}`,context);
  const panel=vm.runInContext('contextPanelView()',context);
  assert.ok(panel.includes('data-text-hash="current-hash"'));
  assert.ok(panel.includes('We included 120 participants &lt;carefully&gt;.'));
  assert.ok(!panel.includes('We included 120 participants <carefully>.'));
  assert.ok(panel.includes('人工核对120名参与者'));
  for (const field of ['display_value', 'note', 'claim']) assert.ok(panel.includes(`name="${field}"`), field);
  assert.ok(!html.includes('We included 120 participants <carefully>.'));
  toggle.checked = false;
  toggle.onchange();
  assert.equal((vm.runInContext('methodsView()', context).match(/<th scope="row">/g) || []).length, 6);
});

test('review submission carries the visible original version and keeps human value independent', async () => {
  const button = {disabled: false};
  const form = {dataset: {passageId:'p:p3:c1',paperId:'p',field:'sample_size',textHash:'visible-version',quote:'We included 120 participants.'},
    querySelector: () => button};
  const context = app({FormData: class {get(key) {return {status:'accepted',claim:'Sample composition requires checking',
    note:'Reviewed today',display_value:'120名参与者'}[key];}}});
  context.stage = {querySelectorAll: selector => selector === '[data-review-form]' ? [form] : [], querySelector: () => null};
  vm.runInContext(`captured=null;api=async(path,options)=>{captured=JSON.parse(options.body);return {run_id:'r'};};
    loadRun=async()=>true;state.view='fulltext';bindResearchControls(stage);`, context);
  await form.onsubmit({preventDefault() {}});
  const sent = JSON.parse(vm.runInContext('JSON.stringify(captured)', context));
  assert.equal(sent.expected_text_sha256, 'visible-version');
  assert.equal(sent.quote, 'We included 120 participants.');
  assert.equal(sent.display_value, '120名参与者');
  assert.equal(sent.status, 'accepted');
});

test('reading list retains status and escapes notes, titles and tag attributes', () => {
  const context = app();
  vm.runInContext(`state.library.result={items:[{paper_id:'p',title:'Study <script>',authors:['A & B'],
    year:2024,favorite:true,reading_status:'reading',tags:['x" autofocus'],notes:'</textarea><script>alert(1)</script>'}]};`, context);
  const html = vm.runInContext('libraryView()', context);
  assert.ok(html.includes('<option value="reading" selected>'));
  assert.ok(html.includes('type="hidden" name="favorite" value="on"'));
  assert.ok(html.includes('data-library-favorite="p" aria-pressed="true"'));
  assert.ok(html.includes('Study &lt;script&gt;'));
  assert.ok(html.includes('x&quot; autofocus'));
  assert.ok(html.includes('&lt;/textarea&gt;&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('name="export_format"'));
  assert.equal((html.match(/data-library-export/g) || []).length, 1);
  for (const format of ['bibtex','ris','markdown','csv']) assert.ok(html.includes(`<option value="${format}"`));
});

test('reading list saves checked fields, Chinese tags and free-form notes into a returned fork', async () => {
  const button = {disabled:false};
  const form = {dataset:{paperId:'p'},querySelector:()=>button};
  const context = app({FormData: class {get(key) {return {favorite:'on',reading_status:'done',tags:'重点， 复现, 方法',notes:'My research note'}[key];}}});
  context.stage = {querySelectorAll: selector => selector === '[data-library-form]' ? [form] : [], querySelector: () => null};
  vm.runInContext(`rememberFormDraft('library','p','','',{notes:'My research note'});
    rememberFormDraft('review','other','other:p2:c1','method',{note:'Other unsaved evidence',source_text_sha256:'other-version',source_quote:'Other original'});
    captured=null;reloaded=[];api=async(path,options)=>{captured=JSON.parse(options.body);return {run_id:'fork'};};
    loadRun=async id=>{reloaded.push(id);state.runId=id;};loadLibrary=async()=>{};bindWorkbenchTools(stage);`, context);
  await form.onsubmit({preventDefault() {}});
  const sent = JSON.parse(vm.runInContext('JSON.stringify(captured)', context));
  assert.equal(sent.run_id, 'r');
  assert.equal(sent.favorite, true);
  assert.equal(sent.reading_status, 'done');
  assert.deepEqual(sent.tags, ['重点','复现','方法']);
  assert.equal(sent.notes, 'My research note');
  assert.equal(vm.runInContext('state.runId', context), 'fork');
  assert.equal(vm.runInContext("getFormDraft('library','p')", context), null);
  assert.equal(vm.runInContext("getFormDraft('review','other','other:p2:c1','method').note", context), 'Other unsaved evidence');
  assert.equal(vm.runInContext("getFormDraft('review','other','other:p2:c1','method').source_text_sha256", context), 'other-version');
});

test('editable research conditions and resources travel with a new question', async () => {
  const context = app();
  vm.runInContext(`state.constraints={year_from:'2020',year_to:'2024',research_object:'中文影像',method:'LoRA',publication_type:'journal'};
    state.resources={data:'120张影像',compute:'8GB显存',time:'两周'};
    state.queryPlan={queries:[{source:'arxiv',purpose:'Supplement',query:'method <test>'}]};
    captured=null;api=async(path,options)=>{captured=JSON.parse(options.body);return {status:'needs_clarification',response:{overview:'请细化研究对象'}};};`, context);
  const html = vm.runInContext('researchConditionsView()', context);
  assert.ok(html.includes('data-constraint="year_from" value="2020"'));
  assert.ok(html.includes('<option value="journal" selected>'));
  assert.ok(html.includes('method &lt;test&gt;'));
  await vm.runInContext("chatTurn('什么方法适合我的研究？')", context);
  const body = JSON.parse(vm.runInContext('JSON.stringify(captured)', context));
  assert.equal(body.constraints.research_object, '中文影像');
  assert.equal(body.constraints.year_to, '2024');
  assert.equal(body.user_resources.compute, '8GB显存');
  assert.ok(body.request_id);
});

test('async research protocol polls progress and clears task state on completion', async () => {
  const calls = [];
  const progress = {textContent:''};
  const context = app({fetch: async (url, config) => {
    calls.push([url, config]);
    if (url === '/api/search') return response(202, {task_id:'task-1'});
    return calls.length === 2 ? response(200, {status:'running',stage:'retrieval'}) :
      response(200, {status:'completed',stage:'finished',result:{run_id:'new'}});
  }, document:{querySelectorAll: () => [progress],querySelector:()=>null}});
  const result = await vm.runInContext("api('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})", context);
  assert.equal(result.run_id, 'new');
  assert.equal(calls[0][1].headers.Prefer, 'respond-async');
  assert.equal(calls[1][0], '/api/tasks/task-1');
  assert.equal(progress.textContent, '处理完成');
  assert.equal(vm.runInContext('Object.keys(state.pendingTasks).length', context), 0);
});

test('stopping a queued research task sends cancellation and removes pending UI state', async () => {
  const controller = new AbortController();
  const methods = [];
  const context = app({controller,
    setTimeout: callback => {controller.abort();queueMicrotask(callback);return 0;},
    fetch: async (url, config) => {
      methods.push(config?.method || 'GET');
      if (config?.method === 'POST') return response(202, {task_id:'task-cancel'});
      if (config?.method === 'DELETE') return response(200, {status:'cancel_requested'});
      if (config?.signal?.aborted) throw Object.assign(new Error('aborted'), {name:'AbortError'});
      throw new Error('Unexpected poll');
    }});
  await assert.rejects(vm.runInContext("api('/api/chat',{method:'POST',signal:controller.signal})", context), {name:'AbortError'});
  assert.deepEqual(methods, ['POST','DELETE','GET']);
  assert.equal(vm.runInContext('Object.keys(state.pendingTasks).length', context), 0);
});

test('changing to a research record without context resets previous search constraints', async () => {
  const context = app();
  vm.runInContext(`state.constraints.year_from='2024';state.constraints.method='Old method';
    state.resources.compute='old GPU';state.queryPlan={queries:[{query:'old topic'}]};
    api=async path=>path.startsWith('/api/run/')?{papers:[],claims:[],offline:true}:{messages:[]};`, context);
  await vm.runInContext("loadRun('fresh-import',false)", context);
  assert.equal(vm.runInContext('state.constraints.year_from', context), '');
  assert.equal(vm.runInContext('state.constraints.method', context), '');
  assert.equal(vm.runInContext('state.resources.compute', context), '');
  assert.equal(vm.runInContext('state.queryPlan', context), null);
});

test('starting a new research topic clears saved topic tools and search conditions', () => {
  const context = app();
  vm.runInContext(`state.constraints.year_to='2021';state.resources.compute='old GPU';
    state.queryPlan={queries:[{query:'old topic'}]};state.guidance={suggestions:[{title:'Old suggestion'}]};
    state.fulltext.result={hits:[{paper_id:'p'}]};state.methods.result={papers:[{paper_id:'p'}]};
    state.library.result={items:[{paper_id:'p'}]};startNewConversation();`, context);
  assert.equal(vm.runInContext('state.constraints.year_to', context), '');
  assert.equal(vm.runInContext('state.resources.compute', context), '');
  for (const expression of ['state.queryPlan','state.guidance','state.fulltext.result','state.methods.result','state.library.result']) {
    assert.equal(vm.runInContext(expression, context), null, expression);
  }
});

test('source reading toggle reaches chat and resets when changing research scope', async () => {
  const toggle = {checked:true};
  const context = app();
  context.stage = {querySelectorAll:()=>[],querySelector: selector=>selector==='[data-reading-mode]'?toggle:null};
  vm.runInContext(`bindWorkbenchTools(stage);state.readingMode=false;`, context);
  toggle.onchange();
  vm.runInContext(`captured=null;api=async(path,options)=>{captured=JSON.parse(options.body);
    return {status:'needs_clarification',response:{overview:'test'}};};`, context);
  await vm.runInContext("chatTurn('继续解释这个方法')", context);
  assert.equal(vm.runInContext('captured.reading_mode', context), true);
  vm.runInContext(`api=async path=>path.startsWith('/api/run/')?{papers:[],claims:[],offline:true}:{messages:[]};`, context);
  await vm.runInContext("loadRun('new-topic',false)", context);
  assert.equal(vm.runInContext('state.readingMode', context), false);
});
