"""Real browser acceptance in disposable copies of new-topic records."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/validation/v2/ui'
RUNS = ROOT / 'tmp/research-v2/ui-runs'


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    for name in ['validation-v2-lora', 'validation-v2-segmentation']:
        target = RUNS / name
        if not target.exists():
            shutil.copytree(ROOT / 'runs' / name, target)
    env = {**os.environ, 'LITAUDIT_RUNS_DIR': str(RUNS),
           'LITAUDIT_RERANK_EMBEDDER': 'hash', 'LITAUDIT_MAP_EMBEDDER': 'hash'}
    server = subprocess.Popen([sys.executable, '-m', 'src.cli', 'ui', '--run-id', 'validation-v2-lora',
                               '--port', '8796', '--no-browser'], cwd=ROOT, env=env,
                              stdout=(OUT/'server.log').open('w'), stderr=subprocess.STDOUT)
    base = 'http://127.0.0.1:8796'
    results = {'representation': 'explicit_hash_for_ui_only', 'checks': [], 'page_errors': []}
    def check(name):
        results['checks'].append(name)
        print(name, flush=True)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base+'/api/health', timeout=1)
                break
            except Exception:
                await asyncio.sleep(.3)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            page.on('pageerror', lambda e: results['page_errors'].append(str(e)))
            await page.goto(base+'/?run=validation-v2-lora')
            await page.wait_for_selector('#search-form input[name=q]')
            await page.locator('#search-form input[name=q]').fill('比较 LoRA 和 QLoRA 的低显存微调方法')
            details = page.locator('details').filter(has=page.locator('[data-preview-plan]'))
            await details.locator('summary').click()
            await page.locator('[data-constraint=year_from]').fill('2021')
            await page.locator('[data-constraint=year_to]').fill('2024')
            await page.locator('[data-preview-plan]').click()
            await page.wait_for_selector('.query-plan li')
            check('editable_constraints_and_query_plan')
            await page.screenshot(path=str(OUT/'research-plan.png'), full_page=True)
            await page.locator('[data-workspace-view=fulltext]').click()
            await page.locator('#fulltext-search input[name=query]').fill('quantization memory frozen low rank')
            await page.locator('#fulltext-search button[type=submit]').click()
            await page.wait_for_selector('.passage-card [data-read-pdf]', timeout=90000)
            await page.locator('[data-read-pdf]').first.click()
            await page.wait_for_selector('.reader-overlay img')
            await page.wait_for_function('document.querySelector(".reader-page")?.naturalWidth > 100')
            src = await page.locator('.reader-overlay a').get_attribute('href')
            response = await page.request.get(base+src.split('#')[0])
            assert response.ok and (await response.body()).startswith(b'%PDF')
            await page.screenshot(path=str(OUT/'source-reader.png'))
            await page.locator('[data-reader-next]').click()
            await page.wait_for_function('document.querySelector(".reader-page")?.complete && document.querySelector(".reader-page").naturalWidth>100')
            await page.locator('[data-close-reader]').click()
            check('fulltext_search_and_local_pdf_reader')
            await page.locator('[data-workspace-view=methods]').click()
            await page.wait_for_selector('.comparison-table', timeout=30000)
            assert await page.locator('.comparison-table tbody tr').count() == 10
            form = page.locator('form[data-review-form][data-field=method]').first
            await form.locator('..').locator('summary').click()
            await form.locator('[name=status]').select_option('accepted')
            await form.locator('[name=display_value]').fill('人工核对：采用低秩适配；以所附原文为依据。')
            await form.locator('[name=note]').fill('验收笔记：先复查量化配置，再开展小规模试验。')
            await form.locator('button[type=submit]').click()
            await page.get_by_text('人工核对：采用低秩适配；以所附原文为依据。', exact=True).first.wait_for()
            check('ten_fields_source_bound_human_edit_saved')
            await page.screenshot(path=str(OUT/'methods.png'), full_page=True)
            async with page.expect_download() as item:
                await page.locator('[data-method-export]').click()
            await (await item.value).save_as(str(OUT/'methods.csv'))
            assert '人工核对' in (OUT/'methods.csv').read_text(encoding='utf-8-sig')
            await page.reload()
            await page.get_by_text('人工核对：采用低秩适配；以所附原文为依据。', exact=True).first.wait_for()
            check('human_edit_survives_reload_and_csv')
            resource = page.locator('details').filter(has=page.locator('[data-guidance]'))
            await resource.locator('summary').click()
            await page.locator('[data-resource=compute]').fill('单张8GB显存GPU')
            await page.locator('[data-resource=time]').fill('两周')
            await page.locator('[data-guidance]').click()
            await page.wait_for_selector('.guidance-list')
            await page.reload()
            assert await page.locator('[data-resource=compute]').input_value() == '单张8GB显存GPU'
            check('resource_guidance_and_saved_conditions')
            await page.locator('[data-workspace-view=library]').click()
            await page.wait_for_selector('[data-library-form]')
            form = page.locator('[data-library-form]').first
            await form.locator('[name=favorite]').check()
            await form.locator('[name=reading_status]').select_option('reading')
            await form.locator('[name=tags]').fill('低显存, 待复现')
            await form.locator('[name=notes]').fill('已核对方法原文，继续检查实验设置。')
            await form.locator('button[type=submit]').click()
            await page.wait_for_timeout(700)
            await page.reload()
            form = page.locator('[data-library-form]').first
            await form.wait_for()
            assert await form.locator('[name=favorite]').is_checked()
            assert await form.locator('[name=reading_status]').input_value() == 'reading'
            assert '已核对方法原文' in await form.locator('[name=notes]').input_value()
            for fmt in ['bibtex', 'ris', 'markdown', 'csv']:
                async with page.expect_download() as item:
                    await page.locator(f'[data-library-export={fmt}]').click()
                await (await item.value).save_as(str(OUT/f'library.{fmt}'))
            check('reading_library_persistence_and_four_exports')
            await page.screenshot(path=str(OUT/'library.png'), full_page=True)
            await page.locator('[data-workspace-view=report]').click()
            async with page.expect_download() as item:
                await page.locator('[data-audit-export]').click()
            await (await item.value).save_as(str(OUT/'audit.md'))
            assert '人工核对' in (OUT/'audit.md').read_text(encoding='utf-8')
            check('markdown_contains_human_revision_and_original_quote')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.locator('[data-workspace-view=library]').click()
            await page.wait_for_selector('[data-library-form]')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            await page.screenshot(path=str(OUT/'mobile.png'), full_page=True)
            check('mobile_reading_library_no_horizontal_overflow')
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            await page.goto(base+'/?run=validation-v2-segmentation&view=methods')
            await page.wait_for_selector('.comparison-table')
            assert 'U-Net' in await page.locator('.comparison-table').inner_text()
            assert '人工核对：采用低秩适配' not in await page.locator('body').inner_text()
            await page.screenshot(path=str(OUT/'segmentation.png'), full_page=True)
            check('english_task_and_run_isolation')
            await page.get_by_role('button', name='新建对话', exact=False).click()
            pdf_form = page.locator('[data-import-pdf]')
            await pdf_form.locator('..').locator('summary').click()
            await pdf_form.locator('[name=pdf]').set_input_files(str(ROOT/'output/validation/v2/sources/1404.1100.pdf'))
            await pdf_form.locator('[name=title]').fill('A Tutorial on Principal Component Analysis')
            await pdf_form.locator('[name=question]').fill('PCA为什么先中心化数据？')
            await pdf_form.locator('button[type=submit]').click()
            await page.wait_for_selector('#fulltext-search', timeout=90000)
            imported = page.url.split('run=')[1].split('&')[0]
            result = await (await page.request.get(base+'/api/run/'+imported)).json()
            assert result['stats']['error_count'] == 0, result['stats']
            await page.locator('#fulltext-search input[name=query]').fill('mean centering covariance')
            await page.locator('#fulltext-search button[type=submit]').click()
            await page.wait_for_selector('.passage-card [data-read-pdf]', timeout=30000)
            check('new_research_from_real_local_pdf_zero_validation_errors')
            await page.locator('[data-workspace-view=chat]').click()
            pdf_form=page.locator('[data-import-pdf]')
            await pdf_form.locator('..').locator('summary').click()
            await pdf_form.locator('[name=pdf]').set_input_files(str(ROOT/'output/validation/v2/sources/1505.04597.pdf'))
            await pdf_form.locator('[name=title]').fill('U-Net: Convolutional Networks for Biomedical Image Segmentation')
            await pdf_form.locator('[name=authors]').fill('Olaf Ronneberger; Philipp Fischer; Thomas Brox')
            await pdf_form.locator('[name=year]').fill('2015')
            await pdf_form.locator('button[type=submit]').click()
            await page.wait_for_selector('#fulltext-search',timeout=90000)
            appended=page.url.split('run=')[1].split('&')[0]
            assert appended != imported
            payload=await (await page.request.get(base+'/api/run/'+appended)).json()
            assert len(payload['papers'])==2 and payload['stats']['error_count']==0
            assert payload['manifest']['parent_run_id']==imported
            assert payload['papers'][1]['year']==2015
            check('append_second_pdf_in_independent_copy_preserves_first_and_metadata')
            await page.screenshot(path=str(OUT/'pca-import.png'), full_page=True)
            assert not results['page_errors'], results['page_errors']
            await browser.close()
        results['ok'] = True
    finally:
        (OUT/'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    asyncio.run(main())
