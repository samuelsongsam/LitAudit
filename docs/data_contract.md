# LitAudit 数据契约（A -> B）

版本：v0.1；对应研究范围：scope_version=v0.1；更新时间：2026-08-22。

## 总体约束
所有对象以 UTF-8 JSON/JSONL 存储。paper_id 是跨文件主键，必须稳定且唯一；缺失 paper_id 的引用不得进入最终输出。研究结论必须能沿 Claim -> Evidence -> PaperCard 回溯。没有 Evidence 的 Claim 不得判定为 supported 或其他确定支持状态。排除论文保留在候选集和筛选日志中，供反证据模块重新召回。

规则判断与模型判断冲突时，状态必须为 pending，并保留两路结果；不得由 UI 覆盖研究状态。B 可以提出字段修改建议，但不能自行改变字段含义或枚举。

## PaperCard
当前阶段 papers.jsonl 是最小 PaperCard 输入；完整卡片可在后续 paper_cards.jsonl 扩展。

| 字段 | 类型 | 必填 | 语义/约束 |
|---|---|---|---|
| paper_id | string | 是 | 稳定唯一主键，如 paper-001；不得复用。 |
| title | string/null | 是 | 原始标题；未知时显式 null，不猜测。 |
| authors | string[]/null | 否 | 可核验作者列表。 |
| year | integer/null | 否 | 公开年份；未知时 null。 |
| venue | string/null | 否 | 期刊、会议或 preprint 状态。 |
| doi_or_arxiv | string/null | 否 | DOI 或 arXiv ID；至少应有 doi_or_arxiv 或 url 之一。 |
| url | string/null | 否 | 可回溯来源 URL。 |
| source | enum/string | 是 | arxiv、openalex、semantic_scholar、crossref 或其他明确来源。 |
| abstract | string/null | 否 | 原文摘要；未核验必须 null。 |
| retrieved_at | date | 是 | 获取/检查日期，ISO YYYY-MM-DD。 |
| dedup_key | string | 是 | 去重依据：DOI > arXiv ID > 标准化标题+作者+年份。 |
| decision | enum | 是 | include、exclude、pending。 |
| reason | string | 是 | 人工可复核筛选理由，不能是模糊文本。 |

可选完整字段 fields：task、method、data、metrics、claims、limitations；每项都必须带来源或显式 null。解析失败使用 parse_status=failed 和 parse_error，不能补造页码。

本轮新增的 data/paper_cards.jsonl 使用同一 paper_id 和基础 PaperCard 标识，并填充 fields、parse_status、parse_error。多数内容来自已核验的 arXiv 摘要：parse_status=abstract_verified 不等于全文已核验；当前 paper-001 仍保留该卡片级摘要状态，而其少量 Evidence 已单独升级为 PDF 页码级 verified。fields 中没有数值或定位时不得由流水线补写。

## Claim
字段：claim_id:string（必填且唯一）；text:string（原子、可证伪论断）；source: user_idea|paper|derived；paper_id:string/null（source=paper 时必填）；status: supported|partial|unsupported|pending；decision_reason:string（必填）。supported 只允许在至少一条有效 Evidence 且没有未解决冲突时使用；缺 Evidence 或规则/模型冲突必须降级为 pending。

## Evidence
字段：evidence_id:string（必填且唯一）；claim_id:string（必填外键）；paper_id:string（必填外键）；snippet:string（原文逐字摘录或明确摘要摘录）；locator:object（至少 page、section、paragraph、char_range、url_anchor 之一）；verdict: supports|partially_supports|contradicts|context_only；confidence: high|medium|low|unverified；extraction_status: verified|abstract_only|unverified|failed。缺失定位、来源或原文摘录时，只能为 unverified/failed，不能支撑确定结论。

## ScreeningLog
字段：screening_id:string（必填且唯一）；paper_id:string（必填）；stage: title_abstract|full_text|deduplication；decision: include|exclude|pending；reason_code:string；reason:string；checked_fields:string[]；reviewer:string；reviewed_at:date；scope_version:string。每个 paper_id 至少有一条记录，后续变更必须新增阶段记录。

## FalsificationHit（后续）
字段：hit_id、target_claim、paper_id、threat、threat_level、snippet、locator、reason、status。threat 为 fatal|overlap|distinguishable；threat_level 为 high|medium|low；status 为 verified|pending|rejected。必须关联目标 Claim 和 PaperCard，保留反向检索词与原文证据。

## ClaimDecision 与检索运行记录

data/claim_decisions.jsonl 是 Claim 判决审计账本。字段为 claim_id、status、evidence_ids、reason、reviewer、reviewed_at、scope_version；它不能替代 claims.jsonl，且 status 必须与 Claim.status 一致。

data/retrieval_runs.jsonl 记录实际检索调用。字段为 retrieval_id、query_id、source、request、retrieved_at、http_status、status、result_count、response_path、notes。HTTP 429、连接失败或解析失败必须保留记录，不能写成零结果成功。

## 关联与无效数据处理
读取时先校验 ID、枚举、日期和外键，再构建地图/界面。未知枚举、重复 ID、孤立 Claim/Evidence、缺少 paper_id、空 snippet 或无 locator 的 Evidence 应报错或降级为 pending，不能静默丢弃。UI 必须展示 exclude 与 pending 及失败原因。

## Fixture（虚构，不是真实论文）
{"paper_id":"fixture-paper-001","title":"Fixture: Retrieval for Science QA","authors":["Fixture Author"],"year":2026,"venue":"fixture","doi_or_arxiv":null,"url":"https://example.invalid/fixture","source":"fixture","abstract":"Fixture abstract only.","retrieved_at":"2026-08-22","dedup_key":"fixture:title|fixture author|2026","decision":"include","reason":"fixture only; demonstrates schema and is not research evidence."}
{"claim_id":"fixture-claim-001","text":"Fixture retriever improves citation traceability.","source":"derived","paper_id":null,"status":"pending","decision_reason":"No real evidence; fixture must not support a conclusion."}
{"evidence_id":"fixture-evidence-001","claim_id":"fixture-claim-001","paper_id":"fixture-paper-001","snippet":"Fixture abstract only.","locator":{"section":"abstract","page":null},"verdict":"context_only","confidence":"unverified","extraction_status":"abstract_only"}

Fixture 中的 example.invalid 和 fixture 状态不得出现在真实研究结论或线上统计中。
