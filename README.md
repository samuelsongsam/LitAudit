# 勘文 LitAudit

LitAudit 是面向科研人员的文献调研工作台。它围绕同一研究问题连接论文检索、全文阅读、方法比较、引用问答、人工证据、阅读笔记与成果导出。研究材料保存为可搬迁的独立记录，重要结果能回到原文和页码。

## 选择运行方式

推荐 Python 3.12，支持 Python 3.10 及以上版本。先在代码包根目录创建隔离环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**轻量阅读与整理**：安装基础、文档处理及测试依赖即可导入 PDF、提取正文、搜索片段、整理方法、保存笔记和导出引用，无需安装 PyTorch。

```powershell
python -m pip install -e ".[dev,documents]"
python -m src.cli ui
```

Windows 也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Lite
```

`-Lite` 显式使用可重复的轻量文本表示。默认配置下，正文重排优先使用 SPECTER2；模型不可用时记录实际回退后端。地图依赖尚未准备好时，论文、全文和人工记录仍可使用，地图显示准备说明与重试入口。

**完整语义检索与地图**：在上述环境中添加模型依赖并下载缓存。

```powershell
python -m pip install -e ".[dev,documents,map]"
python -m src.cli download-model
python -m src.cli doctor
python -m src.cli ui
```

浏览器访问 `http://127.0.0.1:8787/`。首次启动没有研究记录时，可直接输入问题或导入 PDF。随包案例可用 `scripts/start.ps1 -Demo` 回放。

## 配置在线服务

```powershell
Copy-Item .env.example .env
```

在本地 `.env` 中填写 `LITAUDIT_LLM_API_KEY`、`LITAUDIT_LLM_BASE_URL`、`LITAUDIT_LLM_MODEL`。在线论文检索使用 arXiv 和 OpenAlex。OpenAlex 可配置 `OPENALEX_API_KEY`，保存后重启服务。真实密钥保存在本地，提交包提供 `.env.example`。[OpenAlex 配置](https://openalex.org/settings/api)

在工作台左下角打开「检索来源」，可查看来源状态并点击「测试连接」。检索、详情和引文查询复用来源请求队列、冷却状态和短期缓存。点击「测试连接」会向该来源发起探测。

未配置在线模型时，可以导入和阅读本地 PDF、搜索已保存全文、整理方法、保存人工记录与导出文件。在线对话、检索意图理解和模型复核使用所配置的服务。

## 研究工作流

1. **明确范围**：输入研究问题，查看并调整年份、对象、方法和文献类型等检索条件。
2. **发现论文**：多来源召回后按 DOI、arXiv 标识和标题去重，保存排序分量、来源状态和筛选理由。
3. **获取正文**：获取开放全文，或导入自己的 PDF；逐页记录文本、章节、表格候选、图像区域和 OCR 状态。
4. **全文分析**：在「文献」列表点击已解析论文的「全文分析」，可直接分析方法与实验，也可围绕本篇自由提问。点「阅读原文」可逐页阅读 PDF、缩放或选中文字提问。引用可回到论文原页。
5. **比较方法**：对照研究任务、方法、数据集、样本规模、实验设置、基线、指标、结果、资源和适用条件。字段保留连续原文摘录，用户可修订显示要点并人工确认。
6. **持续整理**：收藏论文、记录阅读状态、标签和笔记；保存正文证据、个人论断及复核历史。
7. **导出成果**：方法对比 CSV、文献 BibTeX/RIS、阅读清单 Markdown/CSV，以及带状态的审计报告。

语义地图提供论文阅读导航；引文探索提供上下游研究线索。有可读全文时，“基于当前研究正文回答”默认启用，保持启用可连续追问当前材料；关闭后可重新发现论文。引用问答保留本轮原文依据，并由第二次模型调用复核，论文报告的信息、研究解读和人工判断分别保存。

工作台主入口为研究、文献、地图、对比和笔记。论文详情、原文、字段修订、笔记和引文结果在右侧材料面板处理；关闭后返回原任务位置。手机端使用全屏材料面板。方法表默认六项核心字段，“显示全部对比项目”可展开十项。

地图主题名称根据成员论文的题名与摘要生成，保存稳定簇标识和内容版本。可直接问“各主题簇研究什么”“第二个呢”“比较这一簇的方法”。读取现有主题与本地术语命名可离线进行；“整理主题”或首次主题问答可使用已配置模型生成中文归纳，结果存入 `runs/.map-topics/`。搬迁时保留整个 `runs` 目录以便历史主题回放。

## 全文处理与证据记录

正文首先按页提取，再按章节和文本边界切片。检索结合 BM25、轻量候选召回与 SPECTER2 重排，中文问题扩展常见英文方法术语。命中保留论文、PDF 页序、文本指纹和邻页上下文。

表格单元格、图像区域和公式文本分别保存处理状态。OCR 是可选能力。安装系统 Tesseract 后可用 `LITAUDIT_TESSERACT_CMD` 指定路径。也可安装 `documents` 依赖，并将 `TESSDATA_PREFIX` 指向包含 `eng.traineddata` 等语言数据的目录，由 PyMuPDF 在本地识别。用 `LITAUDIT_OCR_LANG` 选择已安装语言，Windows 上可将 `TESSDATA_PREFIX` 设为相对于启动目录的 ASCII 路径。未处理页面会在覆盖信息中列出，便于补充阅读。

原文定位、语义支持与人工确认是独立状态。用户记录保存为人工来源，不自动改变原有 Claim 判决。对 `phase2-real` 或 `demo` 基准操作时创建研究副本，保留基准数据。

## 保存、恢复与搬迁

### 自动补充全文依据（试用）

已有研究的聊天框可开启「自动补充全文依据」，默认关闭。模型可在当前论文范围内选择读取摘要、获取开放全文、检索正文或结束；最多四次动作决策、一次全文获取（最多两篇），补证阶段总时限为 90 秒。普通聊天与新检索保持原流程。

补证完成后仍通过材料综述与引用复核回答。失败或达到预算时保留已有材料，回答旁显示执行状态。执行轨迹位于 `runs/.agent/`，聊天请求和后台任务使用独立标识；重试同一请求复用已完成结果，不自动重放状态不确定的写入。服务中断可能留下未完成研究副本，可查看其任务与清单状态。此版本不开放自主扩大检索、任意 URL、命令执行或修改人工判决。

设计、阶段计划与边界见 [有界执行层计划](docs/bounded_agent_plan.md)。

每项研究保存在 `runs/<run_id>/`：

```text
run_manifest.json       问题、条件、来源、阶段与状态
output/                 论文、全文索引、方法与人工记录
cache/                  来源响应、PDF与分页文本
```

新缓存使用运行目录相对路径，旧缓存可按当前运行目录重新定位。搬迁时完整复制运行目录。长任务按阶段保存；可选地图处理失败后保留研究材料，模型就绪后可单独重试：

```powershell
python -m src.cli retry-map <run_id>
```

使用 `LITAUDIT_HOME` 可将数据工作区放在独立位置，适合 wheel 安装或分离程序与研究数据。配置与部署步骤见 [运行指南](docs/workspace_guide.md)。

## 验证与开发

```powershell
$env:LITAUDIT_MAP_EMBEDDER='hash'
$env:LITAUDIT_RERANK_EMBEDDER='hash'
python -m pytest -q
node --test tests/ui_scope.test.cjs tests/ui_research.test.cjs tests/ui_quality.test.cjs tests/ui_workbench.test.cjs
git diff --check
```

回归验证程序流程、范围隔离、原文引用、并发记录和恢复行为；新主题的实际运行与效果评测单独记录。独立安装验证脚本为 `scripts/verify_clean_install.py`，实测报告保存在 `output/validation/v2/`。

工作台浏览器验收可运行 `python scripts/verify_workbench_ui.py`。该脚本在 `tmp/workbench/` 创建隔离副本，验证侧栏阅读、文字选择、字段保存、笔记和手机布局；模型问答及外部来源测试使用明确的模拟接口，原研究保持只读。

主要模块：`retrieve.py` 与 `research_query.py` 负责检索计划；`document_processing.py` 与 `fulltext_search.py` 负责全文；`research_workspace.py` 与 `paper_library.py` 负责方法和个人研究材料；`answer_audit.py` 负责引用约束；`pipeline.py`、`tasks.py` 和 `ui/` 负责执行、保存与交互。
