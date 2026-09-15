const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

function app() {
  const source = fs.readFileSync(path.join(__dirname, '../src/ui/static/app.js'), 'utf8');
  const context = vm.createContext({ URLSearchParams, location: { search: '' } });
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
