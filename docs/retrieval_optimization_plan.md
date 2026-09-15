# 文献检索优化调研与实施记录

## 明确目标、执行步骤与状态

### 方向一：SPECTER2 统一重排（已完成）

目标：把 arXiv、OpenAlex、Semantic Scholar 的合并候选按用户问题统一排序，同时保留可解释的分数组成。

执行步骤：

1. 使用 `allenai/specter2_adhoc_query` 编码短查询。
2. 使用 `allenai/specter2` proximity adapter 编码论文标题和摘要。
3. 计算余弦相似度，并与词项覆盖率、对数归一化被引数按 0.75/0.20/0.05 合成。
4. 将三个分数写入 PaperCard；本地模型不可用时记录哈希降级原因，严格模式直接失败。

验收：相关专项测试通过；三个官方模型仓库均已缓存；真实模型冒烟测试中检索论文排在无关哲学论文之前。

### 方向二：全文分段混合检索（已完成）

目标：将已取得的 PDF 转换为可定位、可复核的检索片段，避免整篇全文直接参与回答。

执行步骤：

1. 按 PDF 页码抽取文本，再切为最多 1200 字符、160 字符重叠的片段。
2. 识别常见章节标题并保存论文 ID、页码、片段 ID 和 SHA-256。
3. 用 BM25 召回前 40 个片段，再用 SPECTER2 查询/候选适配器重排。
4. 按 BM25 0.55、SPECTER2 0.45 生成最终结果，写入 `output/fulltext_index.json`。

验收：相关片段排名、页码、哈希、空全文降级均有自动测试；扫描件仍明确进入 OCR 待办，不生成虚假命中。

### 方向三：一跳引文网络扩展（已完成）

目标：围绕最相关论文发现其方法来源与后续施引论文，同时保留引用语境，且不与语义相似边混淆。

执行步骤：

1. 选择综合排名最高且具有 Semantic Scholar ID 的最多 3 篇论文。
2. 每篇分别请求最多 20 条 references 与 20 条 citations。
3. 保存引用方向、上下文、意图、influential 标志和关联论文元数据。
4. 保存原始响应与请求状态，输出独立 `output/citation_graph.json`；429 和解析失败不记为零结果。

验收：引用方向、上下文、意图、影响标记、缓存文件和限流状态均有自动测试。语义图和引文图保持独立数据层。

## 先前已实施的基础能力

1. OpenAlex 检索结果保存 `best_oa_location.pdf_url`、主题、文献类型、被引数和参考文献数。
2. Semantic Scholar 请求并保存 `openAccessPdf`、学科、文献类型、引用/参考文献数和 TLDR。
3. arXiv、OpenAlex、Semantic Scholar 的重复命中按 DOI、arXiv ID 和规范化标题合并；保留更完整的摘要、开放全文入口和较丰富的计量元数据。
4. 已存在于运行数据中的论文再次被命中时，也会补充上述元数据，而不改写 `data/` 与 `runs/phase2-real/`。
5. 全文获取从仅支持 arXiv 扩展到检索提供商声明的 HTTPS 开放 PDF。下载仍受单批 5 篇、25 MiB、300 页限制；PDF 被保存、哈希并逐页抽取，扫描件明确标记为需要 OCR。

## 调研结论

当前检索不应把“增加全文”理解成把整篇 PDF 直接塞给 SPECTER2。SPECTER2 的论文表示适合标题与摘要；全文更适合按章节和段落切分后，做关键词与稠密向量的混合检索，并把命中段落保留到页码级证据中。

建议按以下顺序继续：

### P1：提升召回与排序

- 保留用户问题中的专名、英文缩写、引号短语和布尔约束，避免只取少量通用词。
- 对三个来源的候选集统一重排：关键词分数负责精确术语，SPECTER2 adhoc-query/proximity adapter 负责语义相关性，再加入年代、文献类型和被引数等可解释特征。
- 增加检索评测集，记录 Recall@10、nDCG@10、无关文献比例及各来源新增贡献，禁止只凭地图观感调阈值。

### P2：全文段落检索

- 开放全文按摘要、引言、方法、结果、讨论和结论切分；保留 PDF 页码、章节、文本哈希及版本。
- 建立 BM25 与段落向量双索引，先召回段落再重排；回答只引用实际命中的段落。
- 为扫描 PDF 增加 OCR 回退，并记录 OCR 引擎、语言、置信度与页码映射。
- 继续补充 Unpaywall、PubMed Central 和 Crossref `link` 中许可允许的全文入口，并保存许可和版本信息。

### P3：引文网络扩展

- 使用 Semantic Scholar/OpenAlex 的 references 与 citations 做一跳扩展，优先发现奠基论文和直接反证。
- 保存 Semantic Scholar citation context、intent 与 influential 标志，用于区分背景引用、方法沿用和结果争议。
- 图谱中将语义相似、引用关系和共同主题分层展示，避免把不同含义的边混成一种粗细线。

## 验收指标

- 每条全文记录可追溯到提供商 URL、获取日期、文件哈希和解析状态。
- 同一论文跨来源命中后只生成一个候选，且丰富元数据不丢失。
- 没有全文时仍可做摘要筛选，但不能升级为页码级已核验证据。
- 检索质量改动需要固定问题集上的 Recall@10/nDCG@10 对比，并报告 API 失败与限流率。

## 参考资料

- SPECTER2 模型说明：https://huggingface.co/allenai/specter2
- Semantic Scholar Academic Graph API：https://api.semanticscholar.org/api-docs/snippets
- Crossref REST API：https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- Crossref 全文链接与文本数据挖掘：https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/
- OpenAlex 论文与开放索引介绍：https://arxiv.org/abs/2205.01833
