const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function app(storage = new Map()) {
  const context=vm.createContext({URLSearchParams,URL,AbortController,setInterval,clearInterval,
    setTimeout:callback=>{queueMicrotask(callback);return 0;},
    location:{search:'',href:'http://localhost/'},history:{pushState(){},replaceState(){}},
    document:{getElementById(){return null;},querySelector(){return null;},querySelectorAll(){return[];}},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}});
  const source=fs.readFileSync(path.join(__dirname,'../src/ui/static/workspace.js'),'utf8')+'\n'+
    fs.readFileSync(path.join(__dirname,'../src/ui/static/app.js'),'utf8');
  vm.runInContext(source.slice(0,source.lastIndexOf('boot().catch')),context);
  vm.runInContext(`paint=()=>{};state.runId='r';state.workspaceId='workspace-A';state.chatKey='run:r';state.data={offline:true,
    papers:[{paper_id:'p1',title:'Study one'},{paper_id:'p2',title:'Study two'}],claims:[],evidence:[],screening:[],falsification:[],fulltext_audit:{documents:[{paper_id:'p1',status:'missing'},{paper_id:'p2',status:'parsed'}]}};`,context);
  return context;
}

test('agent is opt-in and carries a retry-stable request identity',async()=>{
  const c=app();
  vm.runInContext(`state.agentMode=true;state.readingMode=false;
    api=async(path,options)=>{captured=JSON.parse(options.body);return{status:'needs_clarification',response:{overview:''}};};`,c);
  await vm.runInContext("chatTurn('补充实验依据')",c);
  assert.equal(vm.runInContext('captured.agent_mode',c),true);
  assert.equal(vm.runInContext('captured.agent_request_id===captured.request_id',c),true);
  assert.ok(vm.runInContext('readingScopeControl()',c).includes('data-agent-mode'));
  await vm.runInContext("chatTurn('重新检索',{skipClarification:true})",c);
  assert.equal(vm.runInContext('captured.agent_mode',c),false);
});

test('missing materials offers PDF import while connection failures offer settings',()=>{
  const c=app();
  for(const error of ['no_fulltext','no_materials','answer_audit_rejected','missing_llm_api_key']){
    c.error=error;
    const html=vm.runInContext("chatMessage({role:'assistant',response:{overview_mode:'llm_error',error}})",c);
    assert.equal(html.includes('data-open-sources'),error==='missing_llm_api_key');
    assert.equal(html.includes('data-open-chat-tool="import"'),['no_fulltext','no_materials'].includes(error));
  }
});

test('reading selector is independent of an old fulltext filter and sends an explicit scope',async()=>{
  const c=app();vm.runInContext(`state.fulltext.paperId='p1';state.readingMode=true;state.readingPaperId='p2';
    api=async(path,options)=>{captured=JSON.parse(options.body);return{status:'needs_clarification',response:{overview:''}};};`,c);
  await vm.runInContext("chatTurn('实验设置是什么？')",c);
  assert.equal(vm.runInContext('captured.reading_paper_id',c),'p2');
  assert.equal(vm.runInContext('captured.reading_scope_mode',c),'selected');
  const html=vm.runInContext('readingScopeControl()',c);
  assert.ok(html.includes('data-reading-paper'));
  assert.ok(html.includes('<option value="p2" selected>'));
  assert.ok(!html.includes('<option value="p1"'));
});

test('answer source details retain coverage labels and counts without repeating status boilerplate',()=>{
  const c=app();c.audit={coverage_complete:false,rejected_section_count:1,question_coverage:[
    {label:'核心方法',status:'answered',reason:'Original methods'},
    {label:'数据集 <原文>',status:'insufficient_evidence',next_action:'搜索数据章节'}]};
  const original=JSON.stringify(c.audit);
  const html=vm.runInContext('answerCoverageView(audit)',c);
  assert.ok(html.includes('问题与原文 · 1/2'));
  assert.ok(html.includes('核心方法')&&html.includes('已关联原文'));
  assert.ok(html.includes('数据集 &lt;原文&gt;')&&!html.includes('数据集 <原文>'));
  assert.ok(!html.includes('<details class="answer-coverage" open'));
  assert.ok(!html.includes('搜索数据章节')&&!html.includes('不代表'));
  assert.equal(JSON.stringify(c.audit),original,'compact display must not rewrite evaluation or rejected-section data');
});

test('unsaved reading notes survive remounts and remain isolated by workspace and research',()=>{
  const storage=new Map();let c=app(storage);
  vm.runInContext("rememberFormDraft('library','p1','','',{notes:'unsaved <research>',tags:['tag'],reading_status:'reading',favorite:true})",c);
  c=app(storage);
  vm.runInContext("state.library.result={items:[{paper_id:'p1',title:'Study one',authors:[],notes:'saved note'}]}",c);
  const html=vm.runInContext('libraryView()',c);
  assert.ok(html.includes('unsaved &lt;research&gt;')&&html.includes('已恢复未保存草稿'));
  assert.equal(vm.runInContext('state.library.result.items[0].notes',c),'saved note');
  vm.runInContext("state.workspaceId='workspace-B'",c);
  assert.equal(vm.runInContext("getFormDraft('library','p1')",c),null);
  vm.runInContext("state.workspaceId='workspace-A';state.runId='another-research'",c);
  assert.equal(vm.runInContext("getFormDraft('library','p1')",c),null);
});

test('favorite saves only its flag and preserves unsaved notes and source drafts in a returned research copy',async()=>{
  const c=app();
  const button={dataset:{libraryFavorite:'p1'},disabled:false};
  c.stage={querySelectorAll:selector=>selector==='[data-library-favorite]'?[button]:[],querySelector:()=>null};
  vm.runInContext(`state.runId='phase2-real';state.chatKey='run:phase2-real';
    state.library.result={items:[{paper_id:'p1',title:'Study one',favorite:false,notes:'Saved note',reading_status:'unread'}]};
    rememberFormDraft('library','p1','','',{notes:'Unsaved <notes>',favorite:false,reading_status:'reading',tags:['draft tag']});
    rememberFormDraft('review','p2','p2:p4:c1','method',{display_value:'Unsaved method',source_text_sha256:'original-version',source_quote:'Original evidence'});
    originalData=state.data;captured=[];
    api=async(path,options)=>{
      if(path==='/api/library/save'){captured.push(JSON.parse(options.body));return{run_id:'research-copy',item:{paper_id:'p1',favorite:true,notes:'Saved note'}};}
      if(path==='/api/run/research-copy')return originalData;
      if(path==='/api/chat/research-copy')return{messages:[]};
      if(path==='/api/library/research-copy')return{items:[{paper_id:'p1',title:'Study one',favorite:true,notes:'Saved note',reading_status:'unread'}]};
      throw new Error('Unexpected request: '+path);
    };bindWorkbenchTools(stage);`,c);
  await button.onclick();
  const sent=JSON.parse(vm.runInContext('JSON.stringify(captured)',c));
  assert.deepEqual(sent,[{run_id:'phase2-real',paper_id:'p1',favorite:true}]);
  assert.equal(button.disabled,false);
  assert.equal(vm.runInContext('state.runId',c),'research-copy');
  assert.equal(vm.runInContext('state.library.result.items[0].notes',c),'Saved note');
  const draft=JSON.parse(vm.runInContext("JSON.stringify(getFormDraft('library','p1'))",c));
  assert.deepEqual(draft,{notes:'Unsaved <notes>',favorite:true,reading_status:'reading',tags:['draft tag']});
  assert.equal(vm.runInContext("getFormDraft('review','p2','p2:p4:c1','method').source_text_sha256",c),'original-version');
  assert.equal(vm.runInContext("getFormDraft('review','p2','p2:p4:c1','method').source_quote",c),'Original evidence');
  const html=vm.runInContext('libraryView()',c);
  assert.ok(html.includes('Unsaved &lt;notes&gt;'));
  assert.ok(html.includes('data-library-favorite="p1" aria-pressed="true"'));
  vm.runInContext("state.runId='phase2-real'",c);
  assert.equal(vm.runInContext("getFormDraft('library','p1').favorite",c),false);
  assert.equal(vm.runInContext("getFormDraft('library','p1').notes",c),'Unsaved <notes>');
});

test('unsubmitted research text survives shell redraws and stays within its conversation',async()=>{
  const c=app();
  const shell={innerHTML:''};
  const input={value:''};
  const form={q:input};
  const historyButton={};
  const collapseButton={};
  c.document={
    getElementById:id=>id==='app'?shell:id==='search-form'?form:null,
    querySelector:selector=>selector==='[data-toggle-history]'?historyButton:selector==='[data-collapse-history]'?collapseButton:null,
    querySelectorAll:()=>[],
  };
  vm.runInContext('renderView=()=>{};bindConversationControls=()=>{};renderShell()',c);
  input.value='尚未发送的 <研究问题> "draft"';
  input.oninput();
  vm.runInContext('renderShell()',c);
  const original=vm.runInContext('chatView()',c);
  assert.ok(original.includes('value="尚未发送的 &lt;研究问题&gt; &quot;draft&quot;"'));
  assert.equal((original.match(/id="search-form"/g)||[]).length,1);
  vm.runInContext("state.chatKey='run:other'",c);
  assert.ok(!vm.runInContext('chatView()',c).includes('尚未发送的'));
  vm.runInContext("state.chatKey='run:r'",c);
  assert.ok(vm.runInContext('chatView()',c).includes('尚未发送的'));
  vm.runInContext('chatTurn=async question=>{submittedQuestion=question;}',c);
  await form.onsubmit({preventDefault(){},target:form});
  assert.equal(vm.runInContext('submittedQuestion',c),'尚未发送的 <研究问题> "draft"');
  assert.equal(vm.runInContext("state.composeDrafts['run:r']",c),undefined);
});

test('method drafts tied to an older source version are not applied to a new quote',()=>{
  const c=app();vm.runInContext(`rememberFormDraft('review','p1','s1','method',{status:'accepted',display_value:'Old conclusion',source_text_sha256:'old',source_quote:'Original old quote'});
    passage={paper_id:'p1',passage_id:'s1',page:2,text_sha256:'new',value:'Current value',quote:'Current original quote'};`,c);
  const html=vm.runInContext("reviewEditor(passage,'method')",c);
  assert.ok(html.includes('原文版本已变化'));
  assert.ok(html.includes('Current value'));
  assert.ok(!html.includes('<option value="accepted" selected>'));
  vm.runInContext("clearFormDraft('review','p1','s1','method')",c);
  assert.equal(vm.runInContext("getFormDraft('review','p1','s1','method')",c),null);
});

test('experimental comparison shows incompatible conditions with original configuration evidence',()=>{
  const c=app();vm.runInContext(`papers=[{paper_id:'p1',title:'Study one',experiment_contexts:[{
    source:{page:3,quote:'We evaluated Dataset A with a batch of 16.'},condition_mentions:{datasets:['Dataset A'],metrics:[],settings:{batch_size:['16']}}}]},
    {paper_id:'p2',title:'Study two',experiment_contexts:[]}];result={comparability:{notice:'配置必须核对',pairs:[{left_paper_id:'p1',right_paper_id:'p2',notice:'条件不同，不能按数值排名',checks:[{label:'数据集',status:'different',left_values:['A'],right_values:['B']}]}]}};`,c);
  const html=vm.runInContext('experimentComparisonView(papers,result)',c);
  assert.ok(html.includes('条件不同，不能按数值排名'));
  assert.ok(html.includes('We evaluated Dataset A with a batch of 16.'));
  assert.ok(html.includes('data-read-pdf="p1"'));
});

test('additional search stays opt-in and exports the explicit extra-request budget',()=>{
  const c=app();assert.equal(vm.runInContext('searchSupplementOptions()',c),undefined);
  vm.runInContext('state.searchSupplement=true',c);
  assert.equal(vm.runInContext('searchSupplementOptions().max_requests',c),4);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(searchSupplementOptions().sources)',c)),['arxiv','openalex']);
  assert.ok(vm.runInContext('researchConditionsView()',c).includes('data-search-supplement checked'));
});

test('old provider coverage remains readable without an unavailable retry action',()=>{
  const c=app();
  vm.runInContext(`state.data.live={coverage:{semantic_scholar:{status:'failed'}}};`,c);
  const historical=vm.runInContext('searchCoverageView()',c);
  assert.ok(historical.includes('Semantic Scholar'));
  assert.ok(!historical.includes('data-search-more="failed"'));
  vm.runInContext(`state.data.live.coverage.openalex={status:'failed'};`,c);
  assert.ok(vm.runInContext('searchCoverageView()',c).includes('data-search-more="failed"'));
});

test('task history offers retry only for an eligible saved task and escapes service errors',()=>{
  const c=app();vm.runInContext(`state.taskHistory=[{task_id:'failed',operation:'/api/chat',status:'failed',can_retry:true,error:'<bad>'},
    {task_id:'done',operation:'/api/search',status:'completed',can_retry:false}];`,c);
  const html=vm.runInContext('taskHistoryView()',c);
  assert.ok(html.includes('data-retry-background-task="failed"'));
  assert.ok(!html.includes('data-retry-background-task="done"'));
  assert.ok(html.includes('&lt;bad&gt;'));
});
