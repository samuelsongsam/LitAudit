"""Verify the simplified UI using disposable copies of real-paper research.

Run from the project root with ``python scripts/verify_ui_v2.py``.  The script
starts its own local server, never writes to the original research, and does
not submit model requests.  Screenshots and machine-readable results stay in
``tmp/ui-v2`` so they are not confused with research-effect measurements.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp/ui-v2"
RUN = "acceptance_20261104_lora"
PORT = 8793


def research_fingerprints() -> dict[str, str]:
    """Include all source-run bytes, not only the records we intend to edit."""
    return {
        str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "runs" / RUN).rglob("*"))
        if path.is_file()
    }


async def open_details(locator) -> None:
    if not await locator.evaluate("node => node.open"):
        await locator.locator(":scope > summary").click()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    screenshots = OUT / "after"
    screenshots.mkdir(exist_ok=True)
    runs = OUT / ("runs-" + str(time.time_ns()))
    runs.mkdir()
    shutil.copytree(ROOT / "runs" / RUN, runs / RUN)
    original = research_fingerprints()
    env = {
        **os.environ,
        "LITAUDIT_RUNS_DIR": str(runs),
        "LITAUDIT_RERANK_EMBEDDER": "hash",
        "LITAUDIT_MAP_EMBEDDER": "hash",
    }
    results = {
        "checks": [],
        "page_errors": [],
        "research_run": RUN,
        "isolated_runs": str(runs),
        "model_requests": 0,
        "simulated_failures": ["PDF import HTTP 400 intercepted in the browser; no import reaches the server"],
        "purpose": "UI workflow verification; not a research-quality score",
    }

    def check(name: str) -> None:
        results["checks"].append(name)
        print(name, flush=True)

    log = (OUT / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "src.cli", "ui", "--run-id", RUN,
         "--port", str(PORT), "--no-browser"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{PORT}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True,
            )
            page = await context.new_page()
            page.set_default_timeout(15000)
            page.on("pageerror", lambda error: results["page_errors"].append(str(error)))

            def requested(request):
                if request.method == "POST" and request.url.endswith("/api/chat"):
                    results["model_requests"] += 1

            page.on("request", requested)
            for _ in range(60):
                try:
                    response = await page.request.get(base + "/api/health", timeout=1000)
                    if response.ok:
                        break
                except Exception:
                    pass
                assert server.poll() is None, "Isolated UI server exited; inspect server.log"
                await asyncio.sleep(.25)
            else:
                raise AssertionError("Isolated UI server did not become healthy")

            await page.goto(base + f"/?run={RUN}")
            await page.wait_for_selector("#search-form")
            await page.locator("#sidebar-new-conversation").click()
            await expect(page.locator(".chat-page.is-empty")).to_be_visible()
            await expect(page.locator("#search-form input[name=q]")).to_be_visible()
            await expect(page.locator("[data-constraint=research_object]")).to_be_hidden()
            await expect(page.locator("form[data-import-pdf] [name=title]")).to_be_hidden()
            assert await page.locator(".workspace-nav > button").count() == 5
            await page.screenshot(path=str(screenshots / "new-research-desktop.png"), full_page=True)
            check("new_research_starts_with_one_question_and_five_primary_destinations")

            question = "如何比较小样本医学图像分割方法？"
            await page.locator("#search-form input[name=q]").fill(question)
            await page.locator("[data-open-chat-tool=search]").click()
            await expect(page.locator("[data-constraint=year_from]")).to_be_visible()
            await expect(page.locator("[data-constraint=research_object]")).to_be_hidden()
            advanced = page.locator("details.advanced-search-options")
            await open_details(advanced)
            await page.locator("[data-constraint=research_object]").fill("医学影像")
            await page.locator("[data-constraint=year_from]").fill("2020")
            assert await page.locator("#search-form input[name=q]").input_value() == question
            await page.locator("[data-preview-plan]").click()
            await expect(page.locator(".query-plan-details")).to_be_visible()
            assert await page.locator("#search-form input[name=q]").input_value() == question
            check("advanced_search_is_discoverable_and_query_preview_preserves_typed_question")

            await page.locator("[data-open-chat-tool=import]").click()
            await expect(page.locator("form[data-import-pdf] [name=pdf]")).to_be_visible()
            await expect(page.locator("form[data-import-pdf] [name=title]")).to_be_hidden()
            await open_details(page.locator("details.import-metadata"))
            await expect(page.locator("form[data-import-pdf] [name=title]")).to_be_visible()
            assert await page.locator("#search-form input[name=q]").input_value() == question
            check("pdf_import_starts_with_file_and_question_and_keeps_optional_metadata_accessible")

            pdf_form = page.locator("form[data-import-pdf]")
            await pdf_form.locator("[name=pdf]").set_input_files(
                str(ROOT / "output/validation/v2/sources/2106.09685.pdf")
            )
            import_values = {
                "question": "解释LoRA方法及实验设置",
                "title": "隔离验收：LoRA导入失败保留信息",
                "authors": "Edward Hu; Yelong Shen",
                "year": "2021",
                "identifier": "2106.09685",
                "source_url": "https://arxiv.org/abs/2106.09685",
            }
            for name, value in import_values.items():
                await pdf_form.locator(f"[name={name}]").fill(value)

            async def reject_import(route):
                await route.fulfill(status=400, content_type="application/json",
                                    body=json.dumps({"error": "隔离验收模拟：服务暂时不可用"}))

            await page.route("**/api/import/pdf", reject_import)
            try:
                await pdf_form.locator("button[type=submit]").click()
                await expect(pdf_form.locator("[data-import-error]")).to_contain_text("隔离验收模拟")
                assert await pdf_form.locator("[name=pdf]").evaluate("node => node.files[0]?.name") == "2106.09685.pdf"
                for name, value in import_values.items():
                    await expect(pdf_form.locator(f"[name={name}]")).to_have_value(value)
                await expect(pdf_form.locator("button[type=submit]")).to_be_enabled()
                await expect(pdf_form.locator("button[type=submit]")).to_have_text("导入并开始阅读")
            finally:
                await page.unroute("**/api/import/pdf", reject_import)
            check("failed_pdf_import_preserves_selected_file_question_metadata_and_retry_button")

            await open_details(page.locator(".task-history"))
            async with page.expect_response(
                lambda r: r.url.endswith("/api/tasks") and r.request.method == "GET"
            ) as received:
                await page.locator("[data-load-task-history]").click()
            assert (await received.value).ok
            await expect(page.locator("[data-load-task-history]")).to_be_enabled()
            assert await page.locator(".chat-toolbox").evaluate("node => node.open")
            assert await page.locator(".task-history").evaluate("node => node.open")
            check("task_refresh_keeps_task_history_and_its_parent_toolbox_expanded")

            await page.goto(base + f"/?run={RUN}&view=methods")
            await page.wait_for_selector(".comparison-table")
            assert await page.locator(".comparison-table tbody > tr").count() == 6
            await expect(page.locator(".comparison-picker [data-compare-paper]").first).to_be_hidden()
            await page.locator("[data-method-fields-toggle]").click()
            assert await page.locator(".comparison-table tbody > tr").count() == 10
            await page.locator("[data-method-fields-toggle]").click()
            assert await page.locator(".comparison-table tbody > tr").count() == 6
            await open_details(page.locator("details.paper-selection"))
            await expect(page.locator(".comparison-picker [data-compare-paper]").first).to_be_visible()
            extra_id = await page.locator("[data-compare-paper]:not(:checked)").first.input_value()
            extra = page.locator(f'[data-compare-paper][value="{extra_id}"]')
            await extra.check()
            await expect(extra).to_be_checked()
            assert await page.locator("details.paper-selection").evaluate("node => node.open")
            await extra.uncheck()
            await expect(extra).not_to_be_checked()
            assert await page.locator("details.paper-selection").evaluate("node => node.open")
            check("comparison_paper_selection_stays_open_after_checking_and_unchecking_a_paper")
            await page.locator("details.paper-selection > summary").click()
            await page.screenshot(path=str(screenshots / "methods-desktop.png"), full_page=True)
            check("method_comparison_defaults_to_six_fields_and_keeps_all_ten_and_paper_selection_available")

            original_button = page.locator(".comparison-table [data-read-pdf]").first
            await original_button.click()
            await page.wait_for_selector(".reader-page")
            await page.wait_for_function(
                "document.querySelector('.reader-page')?.complete && "
                "document.querySelector('.reader-page')?.naturalWidth > 300"
            )
            first_page = await page.locator("[data-reader-page]").inner_text()
            await page.locator("[data-reader-next]").click()
            await page.wait_for_function(
                "document.querySelector('.reader-page')?.complete && "
                "document.querySelector('.reader-page')?.naturalWidth > 300"
            )
            assert await page.locator("[data-reader-page]").inner_text() != first_page
            await page.screenshot(path=str(screenshots / "original-paper-page.png"), full_page=True)
            await page.locator("[data-close-reader]").click()
            check("method_source_opens_a_rendered_original_pdf_and_supports_next_page")

            review = page.locator(
                'form[data-review-form][data-paper-id="paper-008"][data-field="method"]'
            ).first
            source = review.locator('xpath=ancestor::details[contains(@class,"method-source")]')
            await open_details(source)
            # Accommodate the standalone review editor retained for full-text pages.
            parent = review.locator('xpath=parent::details[contains(@class,"review-editor")]')
            if await parent.count():
                await open_details(parent)
            quote = await review.get_attribute("data-quote")
            await review.locator("[name=status]").select_option("accepted")
            await review.locator("[name=display_value]").fill("隔离UI验收：QLoRA核心方法（人工核对）")
            await review.locator("[name=note]").fill("保留原文与页码，需结合基线条件阅读。")
            async with page.expect_response(
                lambda r: r.url.endswith("/api/workspace/review") and r.request.method == "POST"
            ) as received:
                await review.locator("button[type=submit]").click()
            assert (await received.value).ok
            await page.wait_for_function(
                "document.querySelector('.comparison-table')?.textContent.includes('隔离UI验收：QLoRA核心方法')"
            )
            await page.reload()
            await page.wait_for_selector(".comparison-table")
            assert "隔离UI验收：QLoRA核心方法" in await page.locator(".comparison-table").inner_text()
            method_data = await (await page.request.get(base + "/api/methods/" + RUN)).json()
            field = next(p for p in method_data["papers"] if p["paper_id"] == "paper-008")["fields"]["method"]
            assert field["status"] == "accepted" and field["candidate"]["quote"] == quote
            check("method_human_value_and_exact_source_survive_save_and_reload")
            async with page.expect_download() as received:
                await page.locator("[data-method-export]").click()
            downloaded = await received.value
            path = OUT / ("export-" + downloaded.suggested_filename)
            await downloaded.save_as(path)
            assert "隔离UI验收：QLoRA核心方法" in path.read_text(encoding="utf-8-sig")
            check("method_csv_contains_the_saved_human_revision")

            await page.locator("[data-workspace-view=library]").click()
            form = page.locator('form[data-library-form][data-paper-id="paper-008"]')
            await form.wait_for(state="attached")
            card = form.locator('xpath=ancestor::article[contains(@class,"library-card")]')
            await expect(form.locator("[name=notes]")).to_be_hidden()
            assert await page.locator("[data-library-export]").count() == 1
            await page.screenshot(path=str(screenshots / "library-desktop.png"), full_page=True)
            check("reading_list_uses_compact_cards_and_one_format_export_control")

            await page.locator('[data-open-paper-text="paper-001"]').click()
            await expect(page).to_have_url(base + f"/?run={RUN}&view=evidence")
            await page.locator("[data-workspace-view=library]").click()
            await page.locator('[data-open-paper-text="paper-008"]').click()
            await expect(page).to_have_url(base + f"/?run={RUN}&view=fulltext")
            await expect(page.locator('#fulltext-search [name="paper_id"]')).to_have_value("paper-008")
            hit_papers = await page.locator(".passage-list .passage-card [data-read-pdf]").evaluate_all(
                "nodes => nodes.map(node => node.dataset.readPdf)"
            )
            assert hit_papers and set(hit_papers) == {"paper-008"}, hit_papers
            check("library_distinguishes_fulltext_acquisition_from_paper_scoped_reading_and_saved_hits")
            await page.locator("[data-workspace-view=library]").click()

            await open_details(card.locator("details.library-editor"))
            note = "UI验收草稿：核查NF4、比较基线与设备条件。"
            await form.locator("[name=notes]").fill(note)
            await page.locator("[data-workspace-view=methods]").click()
            await page.wait_for_selector(".comparison-table")
            await page.locator("[data-workspace-view=library]").click()
            await expect(form.locator("[name=notes]")).to_have_value(note)
            await page.reload()
            await expect(form.locator("[name=notes]")).to_have_value(note)
            await open_details(card.locator("details.library-editor"))
            check("library_draft_survives_navigation_and_reload_after_editor_simplification")

            favorite = card.locator('[data-library-favorite="paper-008"]')
            was_favorite = await favorite.get_attribute("aria-pressed") == "true"
            async with page.expect_response(
                lambda r: r.url.endswith("/api/library/save") and r.request.method == "POST"
            ) as received:
                await favorite.click()
            assert (await received.value).ok
            await expect(favorite).to_have_attribute("aria-pressed", "false" if was_favorite else "true")
            await expect(form.locator("[name=notes]")).to_have_value(note)
            saved = await (await page.request.get(base + "/api/library/" + RUN)).json()
            saved_item = next(p for p in saved["items"] if p["paper_id"] == "paper-008")
            assert saved_item["favorite"] is not was_favorite
            assert saved_item["notes"] != note, "Favorite must not implicitly commit an unsaved note"
            check("one_click_favorite_updates_saved_state_without_discarding_or_committing_note_draft")

            await open_details(card.locator("details.library-editor"))
            await form.locator("[name=reading_status]").select_option("done")
            async with page.expect_response(
                lambda r: r.url.endswith("/api/library/save") and r.request.method == "POST"
            ) as received:
                await form.locator("button[type=submit]").click()
            assert (await received.value).ok
            await page.wait_for_function(
                "!document.querySelector('form[data-library-form][data-paper-id=\"paper-008\"] [data-discard-draft]')"
            )
            await page.reload()
            await form.wait_for(state="attached")
            await open_details(card.locator("details.library-editor"))
            await expect(form.locator("[name=notes]")).to_have_value(note)
            await expect(form.locator("[name=reading_status]")).to_have_value("done")
            saved = await (await page.request.get(base + "/api/library/" + RUN)).json()
            saved_item = next(p for p in saved["items"] if p["paper_id"] == "paper-008")
            assert saved_item["notes"] == note and saved_item["reading_status"] == "done"
            check("reading_note_and_status_save_and_replay_from_persistent_research_record")

            for fmt, expected in [("bibtex", "@"), ("ris", "TY  -"), ("markdown", "QLoRA"), ("csv", "QLoRA")]:
                await page.locator('[name="export_format"]').select_option(fmt)
                async with page.expect_download() as received:
                    await page.locator("[data-library-export]").click()
                downloaded = await received.value
                path = OUT / ("export-" + downloaded.suggested_filename)
                await downloaded.save_as(path)
                assert expected in path.read_text(encoding="utf-8-sig")
            check("all_four_bibliography_formats_download_from_the_consolidated_control")

            await page.locator(".nav-more > summary").click()
            await expect(page.locator("[data-workspace-view=evidence]")).to_be_visible()
            await page.locator("[data-workspace-view=evidence]").click()
            await expect(page.locator(".nav-more > summary")).to_be_visible()
            await page.locator("[data-workspace-view=report]").click()
            await expect(page.locator("[data-audit-export]")).to_be_visible()
            async with page.expect_download() as received:
                await page.locator("[data-audit-export]").click()
            downloaded = await received.value
            path = OUT / ("export-" + downloaded.suggested_filename)
            await downloaded.save_as(path)
            assert "QLoRA" in path.read_text(encoding="utf-8-sig")
            check("advanced_evidence_and_research_exports_remain_accessible")

            await page.set_viewport_size({"width": 390, "height": 844})
            await page.locator("[data-workspace-view=chat]").click()
            await expect(page.locator(".rail")).to_be_hidden()
            await page.locator("[data-toggle-history]").click()
            await expect(page.locator(".rail")).to_be_visible()
            await page.screenshot(path=str(screenshots / "mobile-history-drawer.png"), full_page=True)
            await page.locator(".sidebar-backdrop").click(position={"x": 370, "y": 600}, force=True)
            await expect(page.locator(".rail")).to_be_hidden()
            await page.locator("[data-toggle-history]").click()
            await page.locator("[data-conversation-run]").first.click()
            await expect(page.locator(".rail")).to_be_hidden()
            check("mobile_history_drawer_opens_closes_and_dismisses_after_selecting_research")

            for view in ["chat", "library", "methods", "fulltext"]:
                await page.locator(f"[data-workspace-view={view}]").click()
                ready = {
                    "chat": "#search-form",
                    "library": "form[data-library-form]",
                    "methods": ".comparison-table",
                    "fulltext": "#fulltext-search",
                }[view]
                await page.locator(ready).first.wait_for(state="attached")
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), view
                if view == "chat":
                    await expect(page.locator("#search-form input[name=q]")).to_be_visible()
                if view == "methods":
                    if await page.locator(".comparison-scroll").evaluate("node => node.scrollWidth > node.clientWidth + 1"):
                        await expect(page.locator(".comparison-scroll-hint")).to_be_visible()
                        await expect(page.locator(".comparison-scroll-hint")).to_contain_text("左右滑动")
                        await expect(page.locator(".comparison-scroll")).to_have_attribute("tabindex", "0")
                        check("mobile_comparison_explains_horizontal_swipe_and_supports_keyboard_focus")
                await page.screenshot(path=str(screenshots / f"mobile-{view}.png"), full_page=True)
            check("mobile_chat_reading_list_comparison_and_fulltext_fit_without_page_overflow")
            assert not results["page_errors"], results["page_errors"]
            assert results["model_requests"] == 0
            assert original == research_fingerprints(), "Original research was modified during isolated verification"
            check("no_browser_exceptions_no_model_calls_and_original_research_bytes_unchanged")
            results["ok"] = True
            await browser.close()
    except Exception as error:
        results["error"] = repr(error)
        if "page" in locals():
            try:
                await page.screenshot(path=str(screenshots / "failure.png"), full_page=True)
            except Exception:
                pass
        raise
    finally:
        results["source_research_unchanged"] = original == research_fingerprints()
        (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        server.terminate()
        server.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    asyncio.run(main())
