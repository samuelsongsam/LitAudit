"""Exercise research-quality fixes in disposable real-paper workspaces."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'tmp/quality-validation'
RUNS = OUT/'runs'
RUN = 'validation-v2-lora'


async def main(skip_model: bool):
    global RUNS
    RUNS = OUT/('runs-' + str(time.time_ns()))
    OUT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(exist_ok=True)
    for name in [RUN, 'validation-v2-segmentation']:
        if not (RUNS/name).exists():
            shutil.copytree(ROOT/'runs'/name, RUNS/name)
    tasks = RUNS/'.tasks';tasks.mkdir(exist_ok=True)
    fixture_id = 'interrupted-quality-check-' + str(time.time_ns())
    (tasks/(fixture_id+'.json')).write_text(json.dumps({
        'task_id':fixture_id,'operation':'/api/fulltext/search','status':'running','stage':'search_fulltext',
        'run_id':RUN,'created_at':datetime.now(timezone.utc).isoformat(),
        'retry_descriptor':{'path':'/api/fulltext/search','body':{'run_id':RUN,'query':'frozen low rank','paper_ids':['paper-015']}}}),encoding='utf-8')
    env={**os.environ,'LITAUDIT_RUNS_DIR':str(RUNS),'LITAUDIT_RERANK_EMBEDDER':'hash','LITAUDIT_MAP_EMBEDDER':'hash'}
    server=subprocess.Popen([sys.executable,'-m','src.cli','ui','--run-id',RUN,'--port','8792','--no-browser'],
        cwd=ROOT,env=env,stdout=(OUT/'server.log').open('w'),stderr=subprocess.STDOUT)
    base='http://127.0.0.1:8792'
    results={'checks':[],'model_turns':[],'page_errors':[],'representation':'explicit_hash_for_ui_workflow',
             'failure_fixture':'saved running task reclassified as interrupted on startup'}
    def check(name):
        results['checks'].append(name);print(name,flush=True)
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            page=await browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
            page.on('pageerror',lambda err:results['page_errors'].append(str(err)))
            for _ in range(50):
                try:
                    response=await page.request.get(base+'/api/health',timeout=1000)
                    if response.ok:break
                except Exception:pass
                await asyncio.sleep(.3)
            await page.goto(base+f'/?run={RUN}&view=library')
            form=page.locator('[data-library-form][data-paper-id=paper-008]');await form.wait_for()
            await form.locator('[name=notes]').fill('未保存草稿：继续核查NF4、基线与设备条件。')
            await page.locator('[data-workspace-view=methods]').click()
            await page.wait_for_selector('.comparison-table')
            await page.locator('[data-workspace-view=library]').click()
            await form.wait_for()
            assert '未保存草稿' in await form.locator('[name=notes]').input_value()
            await page.reload();await form.wait_for()
            assert '未保存草稿' in await form.locator('[name=notes]').input_value()
            check('unsaved_notes_survive_view_switch_and_reload')
            await form.locator('button[type=submit]').click()
            await page.wait_for_timeout(700)
            saved=await (await page.request.get(base+'/api/library/'+RUN)).json()
            assert '未保存草稿' in next(x for x in saved['items'] if x['paper_id']=='paper-008')['notes']
            assert not await form.locator('[data-discard-draft]').count()
            check('saved_note_clears_only_its_browser_draft')
            await page.locator('[data-workspace-view=methods]').click()
            await page.wait_for_selector('.comparison-table')
            await page.locator('.experiment-comparison>summary').click()
            assert '不自动拼接' in await page.locator('.experiment-comparison').inner_text()
            await page.screenshot(path=str(OUT/'experiment-conditions.png'),full_page=True)
            alternative=page.locator('form[data-review-form][data-paper-id=paper-008][data-field=method]').nth(1)
            await alternative.locator('xpath=ancestor::details[contains(@class,"alternative-candidates")]').locator('summary').first.click()
            await alternative.locator('..').locator('summary').click()
            quote=await alternative.get_attribute('data-quote')
            await alternative.locator('[name=status]').select_option('accepted')
            await alternative.locator('[name=note]').fill('隔离验收：选择另一处连续原文作为方法候选。')
            await alternative.locator('button[type=submit]').click()
            await page.wait_for_timeout(900)
            matrix=await (await page.request.get(base+'/api/methods/'+RUN)).json()
            method=next(x for x in matrix['papers'] if x['paper_id']=='paper-008')['fields']['method']
            assert method['candidate']['quote']==quote and method['status']=='accepted'
            check('alternative_method_candidate_is_saved_with_its_exact_quote')
            resource=page.locator('details').filter(has=page.locator('[data-guidance]'))
            await resource.locator('summary').click()
            await page.locator('[data-resource=time]').fill('两周')
            await page.locator('[data-resource=compute]').fill('7B模型，单张8GB显存GPU')
            await page.locator('[data-guidance]').click();await page.wait_for_selector('.resource-analysis')
            await page.screenshot(path=str(OUT/'resource-analysis.png'),full_page=True)
            check('resource_analysis_and_configuration_selection_are_visible')
            await page.locator('[data-workspace-view=chat]').click()
            await page.locator('.task-history>summary').click()
            await page.locator('[data-load-task-history]').click()
            button=page.locator(f'[data-retry-background-task="{fixture_id}"]');await button.wait_for()
            await button.click();await page.wait_for_timeout(1100)
            jobs=await (await page.request.get(base+'/api/tasks')).json()
            children=[j for j in jobs['tasks'] if j.get('retry_of')==fixture_id]
            assert len(children)==1 and children[0]['status']=='completed'
            assert not any('retry_descriptor' in j for j in jobs['tasks'])
            check('interrupted_task_retried_once_from_history_without_exposing_inputs')
            await page.locator('[data-workspace-view=funnel]').click()
            await page.locator('details').filter(has=page.locator('[data-search-more=more]')).locator('summary').first.click()
            assert await page.locator('[data-search-more=failed]').is_visible()
            check('supplementary_search_and_failed_source_retry_controls_visible')
            await page.set_viewport_size({'width':390,'height':844})
            await page.locator('[data-workspace-view=chat]').click()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.screenshot(path=str(OUT/'mobile-scope.png'),full_page=True)
            check('reading_scope_controls_fit_mobile_width')
            await page.set_viewport_size({'width':1440,'height':1000})
            if not skip_model:
                questions=[
                    ('QLoRA的核心方法、数据集、比较基线和适用条件分别是什么？请给出原文依据。',['paper-008']),
                    ('不要再看QLoRA，请解释LoRA的核心方法，并给出原文依据。',['paper-015']),
                    ('比较LoRA与QLoRA的资源要求和适用条件。',['paper-008','paper-015'])]
                for question,expected in questions:
                    await page.locator('[data-reading-mode]').check()
                    await page.locator('[data-reading-paper]').select_option('paper-008')
                    await page.locator('#search-form input[name=q]').fill(question)
                    started=time.monotonic()
                    async with page.expect_response(lambda r:r.url==base+'/api/chat') as received:
                        await page.locator('#search-form button[type=submit]').click()
                    submitted=await (await received.value).json()
                    assert 'task_id' in submitted,submitted
                    while True:
                        job=await (await page.request.get(base+'/api/tasks/'+submitted['task_id'])).json()
                        if job['status'] not in {'queued','running','cancel_requested'}:break
                        assert time.monotonic()-started<190
                        await asyncio.sleep(.6)
                    response=job.get('result',{}).get('response',{})
                    audit=response.get('answer_audit') or {}
                    row={'question':question,'seconds':round(time.monotonic()-started,2),'status':job['status'],
                         'scope':response.get('reading_scope'),'audit_kind':audit.get('kind'),
                         'question_coverage':audit.get('question_coverage'),'citation_papers':list({c.get('paper_id') for c in audit.get('citations',[])})}
                    results['model_turns'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
                    assert job['status']=='completed' and set(row['scope']['paper_ids'])==set(expected),row
                    assert audit.get('kind')=='grounded_reading' and audit.get('question_coverage'),row
                    assert set(row['citation_papers'])<=set(expected),row
                    await page.wait_for_selector('.answer-coverage',timeout=10000)
                    await page.wait_for_function('!document.querySelector("#search-form button[type=submit]").disabled')
                await page.screenshot(path=str(OUT/'compound-reading.png'),full_page=True)
                check('actual_model_compound_question_paper_switch_and_comparison')
            assert not results['page_errors'],results['page_errors']
            results['ok']=True
            await browser.close()
    finally:
        (OUT/('ui-only-result.json' if skip_model else 'result.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        server.terminate();server.wait(timeout=10)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--skip-model',action='store_true')
    asyncio.run(main(parser.parse_args().skip_model))
