"""Exercise the research workbench against isolated real-paper copies.

No remote provider is called: reader answers, source probes and citation
discovery use explicit browser fixtures; map follow-ups use the real local
backend with all model credentials disabled.  Research-quality improvements
are not inferred from these UI checks or interaction counts.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "tmp/workbench"
RUN = "acceptance_20261104_lora"
PORT = 8794
FIXTURE_SOURCE_KEY = "workbench-ui-secret-must-not-render"


def fingerprints() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "runs" / RUN).rglob("*")) if p.is_file()}


async def open_details(node) -> None:
    if not await node.evaluate("node => node.open"):
        await node.locator(":scope > summary").click()


async def close_context(page) -> None:
    button = page.locator("#context-panel [data-close-context]")
    if await button.is_visible():
        await button.click()


async def go_view(page, view: str) -> None:
    await close_context(page)
    button = page.locator(f'[data-workspace-view="{view}"]')
    if not await button.is_visible():
        await open_details(page.locator(".nav-more"))
    await button.click()
    selectors = {"chat": "#search-form", "funnel": "[data-inspect-paper]",
                 "map": "[data-open-topic]", "methods": ".comparison-table",
                 "library": ".library-card", "fulltext": "#fulltext-search"}
    if view in selectors:
        await page.locator("#stage " + selectors[view]).first.wait_for(state="attached")


async def current_view(page) -> str:
    return await page.evaluate("new URL(location.href).searchParams.get('view') || 'chat'")


async def mark_center(page) -> None:
    await page.evaluate("""() => {
      window.__centerStage = document.getElementById('stage');
      window.__centerChild = __centerStage.firstElementChild;
      window.__centerScroll = __centerStage.scrollTop;
    }""")


async def assert_center_unchanged(page, view: str, identity: bool = True, pixel_scroll: bool = True) -> None:
    assert await current_view(page) == view
    position = await page.evaluate("({before:window.__centerScroll,after:document.getElementById('stage').scrollTop})")
    if pixel_scroll and abs(position["before"] - position["after"]) >= 3:
        await page.screenshot(path=str(OUT / "screenshots/position-failure.png"), full_page=True)
        raise AssertionError(f"Central task scroll changed: {position}")
    if identity:
        assert await page.evaluate("document.getElementById('stage') === __centerStage && __centerStage.firstElementChild === __centerChild")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shots = OUT / "screenshots"
    shots.mkdir(exist_ok=True)
    runs = OUT / ("runs-" + str(time.time_ns()))
    runs.mkdir()
    shutil.copytree(ROOT / "runs" / RUN, runs / RUN)
    original = fingerprints()
    env = {**os.environ, "LITAUDIT_RUNS_DIR": str(runs),
           "LITAUDIT_RERANK_EMBEDDER": "hash", "LITAUDIT_MAP_EMBEDDER": "hash",
           "LITAUDIT_LLM_API_KEY": "", "OPENAI_API_KEY": "",
           "OPENALEX_API_KEY": FIXTURE_SOURCE_KEY}
    results = {"checks": [], "page_errors": [], "external_requests": [],
               "mocked_reading_questions": [], "backend_map_questions": [],
               "source_probes": [], "interaction_measurements": {},
               "fixtures": ["reader answer HTTP fixture", "source connection HTTP fixture",
                            "citation result HTTP fixture", "missing baseline candidate UI fixture"],
               "measurement_scope": "UI task continuity and input actions; not research-effect evaluation",
               "runs_dir": str(runs)}

    def check(name: str) -> None:
        results["checks"].append(name)
        print(name, flush=True)

    fixture = {"related_added": False, "missing_baseline": True}
    log = (OUT / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "src.cli", "ui", "--run-id", RUN,
                               "--port", str(PORT), "--no-browser"], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{PORT}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            await context.add_init_script("""(() => {
              window.__wbMetrics={mainViewChanges:0, inputEvents:0, history:[]};
              const view=()=>new URL(location.href).searchParams.get('view')||'chat';
              for(const key of ['pushState','replaceState']) {
                const original=history[key].bind(history);
                history[key]=(...args)=>{const before=view();original(...args);const after=view();
                  if(before!==after)__wbMetrics.mainViewChanges++;
                  __wbMetrics.history.push({before,after,kind:key});};
              }
              document.addEventListener('input',e=>{if(e.isTrusted && e.target.matches('input:not([type=checkbox]),textarea'))__wbMetrics.inputEvents++;});
            })()""")
            page = await context.new_page()
            page.set_default_timeout(18000)
            page.on("pageerror", lambda e: results["page_errors"].append(str(e)))

            async def routes(route):
                request = route.request
                path = urlparse(request.url).path
                if not request.url.startswith(base):
                    if request.url.startswith(("http://", "https://")):
                        results["external_requests"].append(request.url)
                    await route.abort()
                    return
                if path == "/api/chat" and request.method == "POST":
                    body = request.post_data_json
                    if body.get("map_context") or any(t in body.get("message", "") for t in ["地图", "主题簇", "第二个"]):
                        results["backend_map_questions"].append(body)
                        await route.continue_()
                    else:
                        results["mocked_reading_questions"].append(body)
                        selected = body.get("reading_selection") or {}
                        response = {"status": "completed", "run_id": RUN, "response": {
                            "overview": "选中原文说明了模型量化和低秩适配的组合方式。",
                            "overview_mode": "direct_answer", "reading_scope": {
                                "paper_ids": [body.get("reading_paper_id")], "titles": ["QLoRA"], "source": "selected"},
                            "answer_audit": {"ok": True, "kind": "grounded_reading", "citations": [],
                                "sections": [{"kind": "explanation", "text": "选中原文说明了模型量化和低秩适配的组合方式。",
                                              "sources": [selected]}]}}}
                        await route.fulfill(status=200, content_type="application/json", body=json.dumps(response, ensure_ascii=False))
                    return
                if path == "/api/sources/test":
                    body = request.post_data_json
                    results["source_probes"].append(body)
                    source = next(s for s in results["sources_payload"]["sources"] if s["id"] == body["source"])
                    source = deepcopy(source)
                    source["connection"] = {"status": "connected", "checked_at": "2026-11-05T00:00:00Z"}
                    await route.fulfill(status=200, content_type="application/json", body=json.dumps({"source": source}))
                    return
                if path == "/api/research/related":
                    fixture["related_added"] = True
                    await route.fulfill(status=200, content_type="application/json", body=json.dumps({"run_id": RUN}))
                    return
                if path == "/api/workspace/review" and request.method == "POST":
                    fixture["missing_baseline"] = False
                if path == "/api/run/" + RUN and fixture["related_added"]:
                    response = await route.fetch()
                    payload = await response.json()
                    row = deepcopy(next(p for p in payload["papers"] if p["paper_id"] == "paper-015"))
                    row["paper_id"] = "paper-workbench-fixture"
                    row["title"] = "引文交互验收样本 · " + row["title"]
                    payload["papers"].append(row)
                    payload.setdefault("workspace", {})["visible_paper_count"] = len(payload["papers"])
                    if payload.get("live"):
                        for key in ["matched_paper_ids", "added_paper_ids"]:
                            if key in payload["live"]:
                                payload["live"][key].append(row["paper_id"])
                    await route.fulfill(response=response, json=payload)
                    return
                if path == "/api/methods/" + RUN and fixture["missing_baseline"]:
                    response = await route.fetch()
                    payload = await response.json()
                    row = next(p for p in payload["papers"] if p["paper_id"] == "paper-008")
                    row["fields"]["baseline"] = {"candidate": None, "candidates": [], "status": "pending"}
                    await route.fulfill(response=response, json=payload)
                    return
                await route.continue_()

            await context.route("**/*", routes)
            for _ in range(60):
                try:
                    response = await page.request.get(base + "/api/health", timeout=1000)
                    if response.ok:
                        health = await response.json()
                        assert not health["capabilities"]["llm_configured"], "Provider credentials must be disabled for UI checks"
                        break
                except AssertionError:
                    raise
                except Exception:
                    pass
                assert server.poll() is None
                await asyncio.sleep(.25)
            else:
                raise AssertionError("Isolated workbench server did not become healthy")

            await page.goto(base + f"/?run={RUN}")
            await page.locator("#search-form").wait_for()
            assert await page.locator(".workspace-nav > button").evaluate_all("nodes => nodes.map(n=>n.dataset.workspaceView)") == ["chat", "funnel", "map", "methods", "library"]
            draft = "尚未发送：比较QLoRA和LoRA的实验条件"
            await page.locator("#search-form input[name=q]").fill(draft)
            reading_text = await page.locator("#stage .reading-answer").all_inner_texts()
            forbidden = ["本条仅列出待核验内容", "引用完整性检查已通过", "定位核验不代表"]
            assert not any(template in text for text in reading_text for template in forbidden)
            await mark_center(page)
            source = page.locator("#stage [data-context-source]").first
            await source.click()
            panel = page.locator("#context-panel")
            await expect(panel).to_be_visible()
            await assert_center_unchanged(page, "chat")
            await expect(page.locator("#search-form input[name=q]")).to_have_value(draft)
            check("answer_source_opens_beside_the_same_dom_task_scroll_and_unsent_question")

            await expect(panel.locator(".reader-page-wrap")).to_have_count(3)
            await page.wait_for_function("document.querySelector('#context-panel .reader-page')?.naturalWidth > 300")
            await panel.locator(".reader-text-layer span").first.wait_for(state="attached")
            await page.wait_for_function("document.querySelectorAll('#context-panel .quote-highlight').length > 0")
            center_box = await page.locator("#stage").bounding_box()
            side_box = await panel.bounding_box()
            assert center_box["x"] + center_box["width"] <= side_box["x"] + 2
            original_page = await panel.locator("[data-reader-jump]").input_value()
            await panel.locator("[data-reader-next]").click()
            assert await panel.locator("[data-reader-jump]").input_value() != original_page
            await panel.locator("[data-reader-zoom='+']").click()
            await expect(panel.locator("[data-reader-zoom-label]")).to_have_text("115%")
            await page.wait_for_function("document.querySelector('#context-panel .reader-page')?.complete && document.querySelector('#context-panel .reader-page')?.naturalWidth > 300")
            await panel.locator(".reader-text-layer span").first.wait_for(state="attached")
            await page.screenshot(path=str(shots / "desktop-reading-context.png"), full_page=True)
            await assert_center_unchanged(page, "chat")
            check("three_original_pages_text_layer_exact_quote_highlight_paging_and_zoom_work_beside_task")

            await panel.locator(".reader-text-layer span").first.wait_for(state="attached")
            selection = await page.evaluate("""() => {
              const words=[...document.querySelectorAll('#context-panel .reader-text-layer')][0].querySelectorAll('span');
              const range=document.createRange();range.setStart(words[0].firstChild,0);range.setEnd(words[Math.min(14,words.length-1)].firstChild,words[Math.min(14,words.length-1)].textContent.length);
              const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);return selected.toString().trim();
            }""")
            await panel.locator("[data-ask-reader]").click()
            question = "请解释这段方法与适用条件"
            before = await page.evaluate("({...__wbMetrics})")
            await panel.locator("[data-context-question] textarea").fill(question)
            await panel.locator("[data-context-question] button[type=submit]").click()
            await expect(panel.locator(".context-answer")).to_contain_text("模型量化和低秩适配")
            sent = results["mocked_reading_questions"][-1]
            assert sent["reading_paper_id"] == "paper-008" and sent["reading_scope_mode"] == "selected"
            assert sent["reading_selection"]["quote"] == selection
            assert sent["reading_selection"]["paper_id"] == "paper-008"
            from src.reading_selection import resolve_reader_selection
            resolved = resolve_reader_selection(runs, RUN, sent["reading_selection"])
            assert resolved["source"] == "stored_original_page" and resolved["quote"]
            assert resolved["page"] == sent["reading_selection"]["page"]
            assert await current_view(page) == "chat"
            await expect(page.locator("#search-form input[name=q]")).to_have_value(draft)
            after = await page.evaluate("({...__wbMetrics})")
            results["interaction_measurements"]["context_reader_followup"] = {"main_view_changes": after["mainViewChanges"] - before["mainViewChanges"], "manual_question_entries": 1, "manual_search_entries": 0, "trusted_input_events": after["inputEvents"] - before["inputEvents"]}
            check("selected_text_followup_sends_exact_paper_page_quote_without_reentering_main_question")

            await panel.locator('.context-tabs [data-context-tab="notes"]').click()
            notes = panel.locator('form[data-library-form][data-paper-id="paper-008"]')
            await notes.wait_for(state="visible")
            unsaved = "工作台草稿：继续核对设备条件和量化误差。"
            await notes.locator("[name=notes]").fill(unsaved)
            saved_before = await (await page.request.get(base + "/api/library/" + RUN)).json()
            saved_note = next(p for p in saved_before["items"] if p["paper_id"] == "paper-008")["notes"]
            await panel.locator('[data-library-favorite="paper-008"]').click()
            await expect(notes.locator("[name=notes]")).to_have_value(unsaved)
            saved_after = await (await page.request.get(base + "/api/library/" + RUN)).json()
            assert next(p for p in saved_after["items"] if p["paper_id"] == "paper-008")["notes"] == saved_note
            await notes.locator("button[type=submit]").click()
            await page.wait_for_function("!document.querySelector('#context-panel [data-discard-draft=library]')")
            await panel.locator('.context-tabs [data-context-tab="overview"]').click()
            await panel.locator('.context-tabs [data-context-tab="notes"]').click()
            await expect(notes.locator("[name=notes]")).to_have_value(unsaved)
            assert await current_view(page) == "chat"
            check("side_notes_save_and_reappear_and_favorite_never_commits_the_note_draft")

            await panel.locator('.context-tabs [data-context-tab="citations"]').click()
            await panel.locator('[data-panel-related="references"]').click()
            await expect(panel).to_contain_text("本次新增 1 篇")
            assert await current_view(page) == "chat"
            await expect(page.locator("#search-form input[name=q]")).to_have_value(draft)
            check("citation_discovery_fixture_joins_the_research_without_leaving_the_central_task")

            await go_view(page, "funnel")
            inspect = page.locator('#stage [data-inspect-paper="paper-008"]').first
            await inspect.scroll_into_view_if_needed()
            await mark_center(page)
            await inspect.click()
            await expect(panel.locator(".context-paper")).to_be_visible()
            await assert_center_unchanged(page, "funnel", pixel_scroll=False)
            assert await page.evaluate("state.composeDrafts[state.chatKey]") == draft
            await panel.locator("[data-context-read]").click()
            await expect(panel.locator(".context-reader")).to_be_visible()
            await assert_center_unchanged(page, "funnel", pixel_scroll=False)
            check("paper_overview_and_reader_open_without_navigating_or_remounting_the_paper_list")

            await go_view(page, "methods")
            await page.locator("[data-method-fields-toggle]").check()
            missing = page.locator('[data-method-search="paper-008"][data-field-query="比较基线"]')
            await missing.wait_for()
            await missing.scroll_into_view_if_needed()
            await mark_center(page)
            await missing.click()
            await expect(panel.locator("[data-context-search]")).to_be_visible()
            await expect(panel.locator(".context-hits [data-select-field-hit]").first).to_be_visible()
            await assert_center_unchanged(page, "methods", pixel_scroll=False)
            await expect(missing).to_be_in_viewport()
            await panel.locator(".context-hits [data-select-field-hit]").first.click()
            review = panel.locator("form[data-review-form]")
            visible_source = await panel.locator(".passage-card blockquote").first.text_content()
            source_hash = await review.get_attribute("data-text-hash")
            passage_id = await review.get_attribute("data-passage-id")
            await review.locator("[name=status]").select_option("accepted")
            await review.locator("[name=display_value]").fill("工作台验收：人工选择的比较基线")
            async with page.expect_response(lambda r: r.url.endswith("/api/workspace/review") and r.request.method == "POST") as received:
                await review.locator("button[type=submit]").click()
            assert (await received.value).ok
            saved_review = (await (await received.value).json())["review"]
            assert saved_review["text_sha256"] == source_hash
            assert saved_review["quote"] and saved_review["quote"] in visible_source
            assert saved_review["quote_sha256"] == sha256(saved_review["quote"].encode()).hexdigest()
            fixture["missing_baseline"] = False
            await expect(page.locator("#stage .comparison-table")).to_contain_text("工作台验收：人工选择的比较基线")
            await assert_center_unchanged(page, "methods", identity=False, pixel_scroll=False)
            await expect(page.locator(".comparison-table tbody > tr").filter(has=page.get_by_role("rowheader", name="比较基线", exact=True))).to_be_in_viewport()
            matrix = await (await page.request.get(base + "/api/methods/" + RUN)).json()
            baseline = next(p for p in matrix["papers"] if p["paper_id"] == "paper-008")["fields"]["baseline"]
            assert baseline["status"] == "accepted" and baseline["candidate"]["quote"] == saved_review["quote"]
            assert baseline["candidate"]["passage_id"] == passage_id
            await page.locator('[data-edit-method-field="paper-008"][data-field="baseline"]').click()
            await expect(panel.locator("form[data-review-form] [name=display_value]")).to_have_value("工作台验收：人工选择的比较基线")
            assert await current_view(page) == "methods"
            await panel.locator("[data-context-source]").first.click()
            await expect(panel.locator(".context-reader")).to_be_visible()
            await page.go_back()
            await expect(panel.locator('form[data-review-form][data-field="baseline"] [name=display_value]')).to_have_value("工作台验收：人工选择的比较基线")
            assert await current_view(page) == "methods"
            check("browser_back_from_original_page_restores_the_same_method_field_and_saved_value")
            await page.screenshot(path=str(shots / "desktop-field-context.png"), full_page=True)
            check("missing_field_search_selection_and_human_save_keep_comparison_in_place")

            await go_view(page, "map")
            topics = page.locator("#stage [data-open-topic]")
            assert await topics.count() >= 2
            second_id = await topics.nth(1).get_attribute("data-open-topic")
            await topics.nth(1).click()
            topic_label = await panel.locator(".topic-heading h3").inner_text()
            await panel.locator(".topic-paper-list [data-inspect-paper]").first.click()
            await expect(panel.locator(".context-paper")).to_be_visible()
            await page.go_back()
            await expect(panel.locator(".topic-heading h3")).to_have_text(topic_label)
            assert await page.evaluate("state.context.clusterId") == second_id
            assert await current_view(page) == "map"
            check("browser_back_from_member_paper_restores_the_topic_descriptor_and_membership")
            await panel.locator("[data-topic-ask]").click()
            await page.wait_for_function("state.mapContext?.cluster_ids?.length > 0 && !state.context?.answerBusy")
            assert results["backend_map_questions"][-1]["map_context"]["cluster_ids"] == [second_id]
            assert await current_view(page) == "map"
            conversation_path = runs / RUN / "output/conversation.json"
            history_before_label = json.loads(conversation_path.read_text(encoding="utf-8"))
            conversation_before_label = conversation_path.read_bytes()
            graph_path = runs / RUN / "output/map.json"
            graph_before_label = graph_path.read_bytes()
            membership_before = await page.evaluate("({version:state.data.map.map_version,members:state.context.topic.paper_ids})")
            manual_name = "量化适配 · 我的研究主题"
            await open_details(panel.locator(".topic-name-editor"))
            await panel.locator("[data-topic-label] [name=label]").fill(manual_name)
            async with page.expect_response(lambda r: r.url.endswith("/api/map-topics/label") and r.request.method == "POST") as received:
                await panel.locator("[data-topic-label] button[type=submit]").click()
            assert (await received.value).ok
            await expect(panel.locator(".topic-heading h3")).to_have_text(manual_name)
            legend = page.locator(f'#stage .legend-group[data-open-topic="{second_id}"]')
            await expect(legend).to_contain_text(manual_name)
            refreshed = await page.request.post(base + "/api/map-topics/refresh", data={"run_id": RUN, "force": True})
            assert refreshed.ok
            refreshed_topics = (await refreshed.json())["topics"]
            assert next(t for t in refreshed_topics if t["cluster_id"] == second_id)["label"] == manual_name
            await page.reload()
            await expect(legend).to_contain_text(manual_name)
            await legend.click()
            await expect(panel.locator(".topic-heading h3")).to_have_text(manual_name)
            assert await page.evaluate("state.context.topic.label_source") == "human"
            membership_after = await page.evaluate("({version:state.data.map.map_version,members:state.context.topic.paper_ids})")
            assert membership_after == membership_before
            assert conversation_path.read_bytes() == conversation_before_label
            assert graph_path.read_bytes() == graph_before_label
            await page.screenshot(path=str(shots / "desktop-manual-topic-name.png"), full_page=True)
            check("manual_topic_name_survives_local_refresh_and_reload_without_changing_membership_or_saved_history")
            await close_context(page)
            await go_view(page, "chat")
            await page.locator("#search-form input[name=q]").fill("第二个主题簇具体研究什么？")
            await page.locator("#search-form button[type=submit]").click()
            await page.wait_for_function("!document.querySelector('#search-form button[type=submit]')?.disabled")
            await expect(page.locator("#stage .map-answer").last).to_be_visible()
            map_response = await page.evaluate("state.chat.messages.filter(m=>m.response?.map_answer).at(-1).response")
            assert map_response["overview_mode"] == "map_answer"
            assert map_response["map_answer"]["selected_cluster_ids"] == [second_id]
            assert next(t for t in map_response["map_answer"]["topics"] if t["cluster_id"] == second_id)["label"] == manual_name
            history_after_label = json.loads(conversation_path.read_text(encoding="utf-8"))
            assert history_after_label["messages"][:len(history_before_label["messages"])] == history_before_label["messages"]
            for text in ["引用完整性检查已通过", "本条仅列出待核验内容", "定位核验不代表"]:
                assert text not in await page.locator("#stage .map-answer").last.inner_text()
            await page.locator("#stage .map-answer").last.scroll_into_view_if_needed()
            await page.screenshot(path=str(shots / "desktop-map-followup.png"), full_page=True)
            check("map_topic_click_and_second_cluster_followup_use_versioned_local_backend_membership")

            results["sources_payload"] = await (await page.request.get(base + "/api/sources")).json()
            assert FIXTURE_SOURCE_KEY not in json.dumps(results["sources_payload"])
            sources_by_id = {s["id"]: s for s in results["sources_payload"]["sources"]}
            assert set(sources_by_id) == {"arxiv", "openalex"}
            assert sources_by_id["openalex"]["key_configured"]
            await page.locator("[data-open-sources]").first.click()
            await expect(panel.locator("[data-test-source]")).to_have_count(2)
            sources_text = await panel.inner_text()
            assert FIXTURE_SOURCE_KEY not in sources_text
            assert not any(template in sources_text for template in forbidden)
            if secret := os.environ.get("OPENALEX_API_KEY"):
                assert secret not in sources_text
            assert "Authorization" not in sources_text and "Bearer " not in sources_text
            probe = page.locator('[data-test-source="openalex"]')
            await panel.locator('[data-test-source="openalex"]').click()
            await expect(panel.locator(".source-card").filter(has=probe)).to_contain_text("连接正常")
            assert results["source_probes"] == [{"source": "openalex"}]
            await page.screenshot(path=str(shots / "desktop-source-settings.png"), full_page=True)
            check("source_metadata_and_mock_probe_show_status_without_keys_or_external_calls")

            # The retained main-page route is a reference path, not an old-version benchmark.
            await go_view(page, "chat")
            start = await page.evaluate("({...__wbMetrics})")
            await go_view(page, "fulltext")
            await page.locator('#fulltext-search [name="query"]').fill("4-bit NormalFloat")
            await page.locator('#fulltext-search [name="paper_id"]').select_option("paper-008")
            await page.locator("#fulltext-search button[type=submit]").click()
            await page.wait_for_function("!state.fulltext.loading && state.fulltext.result?.query === '4-bit NormalFloat'")
            await page.locator("#stage [data-ask-passage]").first.wait_for()
            await page.locator("#stage [data-ask-passage]").first.click()
            await panel.locator("[data-context-question] textarea").fill(question)
            end = await page.evaluate("({...__wbMetrics})")
            results["interaction_measurements"]["retained_cross_page_route"] = {
                "main_view_changes": end["mainViewChanges"] - start["mainViewChanges"],
                "manual_question_entries": 1, "manual_search_entries": 1,
                "trusted_input_events": end["inputEvents"] - start["inputEvents"],
                "description": "Measured in current UI using the fulltext main page; not a historical release benchmark"}
            check("interaction_counts_record_actual_view_changes_and_manual_query_entries")

            await go_view(page, "chat")
            await page.locator("#search-form input[name=q]").fill(question)
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.locator("#stage [data-context-source]").first.scroll_into_view_if_needed()
            await mark_center(page)
            await page.locator("#stage [data-context-source]").first.click()
            await expect(panel).to_be_visible()
            await page.wait_for_function("document.querySelector('#context-panel .reader-page')?.complete && document.querySelector('#context-panel .reader-page')?.naturalWidth > 300")
            await page.screenshot(path=str(shots / "mobile-context-sheet.png"), full_page=True)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            await panel.locator("[data-close-context]").click()
            await assert_center_unchanged(page, "chat")
            await expect(page.locator("#search-form input[name=q]")).to_have_value(question)
            await page.locator("#stage [data-context-source]").first.click()
            await page.go_back()
            await expect(panel).to_be_hidden()
            assert await current_view(page) == "chat"
            await page.screenshot(path=str(shots / "mobile-returned-task.png"), full_page=True)
            check("mobile_material_sheet_closes_and_browser_back_restores_the_same_task_position")

            assert not results["page_errors"], results["page_errors"]
            assert not results["external_requests"], results["external_requests"]
            assert original == fingerprints()
            results.pop("sources_payload", None)
            results["ok"] = True
            check("no_browser_exceptions_no_remote_requests_and_original_research_bytes_unchanged")
            await browser.close()
    except Exception as error:
        results["error"] = repr(error)
        if "page" in locals():
            try:
                await page.screenshot(path=str(shots / "failure.png"), full_page=True)
            except Exception:
                pass
        raise
    finally:
        results.pop("sources_payload", None)
        results["source_research_unchanged"] = original == fingerprints()
        (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        server.terminate()
        server.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    asyncio.run(main())
