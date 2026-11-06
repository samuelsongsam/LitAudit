# LitAudit 研究工作区运行说明

本说明面向运行、部署与验收人员。系统围绕同一研究记录组织检索条件、论文、全文、方法、阅读清单、证据和报告。可先导入自己的 PDF 熟悉阅读流程，再配置在线服务开展新主题检索。

## 安装选择

推荐 Python 3.12。首次安装需要网络以获取 Python 包；语义模型首次下载另需网络。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

| 用途 | 安装命令 | 模型准备 |
| --- | --- | --- |
| 本地 PDF 阅读、全文检索、方法与笔记 | `python -m pip install -e ".[dev,documents]"` | 可直接开始，实际检索后端会标注 |
| 完整语义排序与地图 | `python -m pip install -e ".[dev,documents,map]"` | 再运行 `python -m src.cli download-model` |
| 仅运行基础源码 | `python -m pip install -e .` | pypdf 文本路径可用，文档版面能力按已安装依赖提供 |

如果提交包附有 `requirements-verified-py312.txt`，可在上述命令末尾添加 `-c requirements-verified-py312.txt`，使用该包记录的已验证 Python 3.12 版本约束。

核心依赖包含 NumPy，用于确定性轻量地图的真实 MDS 投影；`documents` 安装 PyMuPDF、Pillow 与 pytesseract，不包含 PyTorch。轻量安装已在独立虚拟环境中验证真实 PCA 论文的导入、全文检索、方法字段、人工记录、阅读笔记与四种引用导出。地图模型依赖不在环境内时显示可恢复状态，正文与研究记录保持可用。实际依赖版本和结果见 `output/validation/v2/clean_install_wheel.json`。

## 启动与配置

```powershell
Copy-Item .env.example .env
python -m src.cli ui
```

浏览器访问 `http://127.0.0.1:8787/`。Windows 可使用启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Lite
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Demo
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -RunId <run_id> -Port 8790
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Lite -Workspace C:/research/LitAudit-workspace
```

`-Lite` 使用显式轻量文本表示；`-Demo` 打开随包研究案例并使用相同确定性配置。已有真实语义地图仍按保存的表示信息显示。完整语义模式可省略这两个参数，并先安装 `map`、下载模型。

在线服务使用本地 `.env`：

```dotenv
LITAUDIT_LLM_API_KEY=填写自己的密钥
LITAUDIT_LLM_BASE_URL=填写兼容接口地址
LITAUDIT_LLM_MODEL=填写模型名称
```

在线论文检索使用 arXiv 和 OpenAlex。OpenAlex 可在 `.env` 配置 `OPENALEX_API_KEY` 或 `OPENALEX_MAILTO`。保存后重启服务，并在工作台的「检索来源」中测试连接。[OpenAlex 配置](https://openalex.org/settings/api)

未配置在线模型时，仍可导入 PDF、阅读研究记录、搜索已有正文、保存人工材料和导出。`doctor` 检查配置存在性、模型缓存、依赖、存储及随包基准数据，不会联网或打印密钥。

## 独立数据目录与 wheel 部署

源代码运行默认把项目目录作为工作区。设置 `LITAUDIT_HOME` 后，配置、数据和运行目录都相对指定位置解析：

```powershell
New-Item -ItemType Directory -Force workspace | Out-Null
$env:LITAUDIT_HOME=(Resolve-Path workspace).Path
python -m src.cli ui --no-browser
```

全新工作区可以从 PDF 导入开始。需要回放已有记录时，将完整的 `runs/` 复制到工作区；需要使用随包基准数据时，同时复制 `data/` 与相关说明文件。

源码可构建 wheel：

```powershell
python -m pip install build
python -m build --wheel
python -m pip install "dist/litaudit-0.3.0-py3-none-any.whl[documents]"
```

部署后先设置 `LITAUDIT_HOME`，再运行 `litaudit ui --no-browser`。已实测 wheel 包含 HTML、JavaScript、CSS 与 SVG 静态资源，并从源码目录外导入安装包完成真实 PDF 工作流。验证结果见 `output/validation/v2/clean_install_wheel.json`。

## PDF、版面和 OCR

可获取开放全文，也可导入自己的 PDF。每个文件逐页保存文本来源、章节和覆盖状态：原生文本与 OCR 文本分别标记，表格为已提取候选，图像与公式区域保留定位信息。

OCR 需另行安装系统 Tesseract 及所用语言数据。pytesseract Python 包本身不包含识别引擎。可在 `.env` 设置：

```dotenv
LITAUDIT_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
LITAUDIT_OCR_LANG=eng
```

处理过程有 OCR 页数、超时与图像尺寸上限，待处理页面会列在文档覆盖信息中。当前独立部署实测环境没有系统 Tesseract，因此报告明确记录 `ocr_engine_available=false`。

## 日常操作与验收

1. 输入研究问题，预览查询计划，调整年份、研究对象、方法及文献类型等条件。
2. 在论文列表检查来源和筛选理由，收藏目标论文，标记阅读进度并记录标签。
3. 获取或导入全文，检查哪些页已提取、哪些页还需处理。
4. 在全文页查找问题或术语，按论文和章节筛选。原文阅读器以真实PDF原页图显示内容，支持上一页、下一页，并保留打开原PDF入口；可同时阅读命中的原文和邻页上下文。原页图渲染需 documents 组件中的 PyMuPDF，未安装时仍可打开原PDF。
5. 在方法页比较十类字段。字段要点与原文摘录同时保留，可修订显示值、确认或排除候选，填写个人论断与备注。
6. 围绕当前原文继续追问。有可读全文时，“基于当前研究正文回答”默认启用；保持启用可继续阅读当前材料，需要重新发现论文时关闭。历史帮助理解指代，每轮事实仍需当前正文依据和模型复核。正文摘录、模型解释和人工判断按来源区分，重要信息附可回查依据。
7. 导出方法 CSV、BibTeX/RIS、阅读清单 Markdown/CSV 与审计报告，重新打开研究检查记录持久化。

基准记录编辑时自动创建研究副本。人工确认按原文指纹检查版本，保存原文、页码、时间和历史，不自动改写已有 Claim 判决。

## 保存与恢复

`runs/<run_id>/run_manifest.json` 保存研究问题、条件、阶段与状态；`output/` 保存结构化成果；`cache/` 保存 PDF、来源响应与分页文本。搬迁时完整复制该运行目录，新记录采用相对路径，历史路径可在当前运行内重新定位。

长任务可查看状态，重复请求按请求编号处理。地图等可选阶段未完成时仍保留已有材料，准备模型后可在界面重试，或执行：

```powershell
python -m src.cli retry-map <run_id>
```

## 验证

```powershell
$env:LITAUDIT_MAP_EMBEDDER='hash'
$env:LITAUDIT_RERANK_EMBEDDER='hash'
python -m pytest -q
node --test tests/ui_scope.test.cjs
```

独立安装的真实 PDF 工作流可重复执行：

```powershell
python scripts/verify_clean_install.py --pdf <真实PDF路径> --output <验证报告路径> --installation editable --expect-no-map
```

该命令适用于没有安装地图模型依赖的隔离环境，使用独立工作区，不读取项目真实密钥，也不调用在线模型。回归、真实运行与效果评测分别记录，报告中的测试对象和实际后端保持明确。

浏览器自动验收脚本另需 Playwright 与 Chromium，仅在运行界面验收时安装，日常使用无需这些组件：

```powershell
python -m pip install playwright
python -m playwright install chromium
```

先按对应验收脚本的说明启动本地界面，再执行脚本。浏览器验收记录与真实模型问答的来源复核记录分别保存。
