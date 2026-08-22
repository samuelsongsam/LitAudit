# A -> B 交接：研究范围与数据契约

## 1. 本阶段完成内容
已固定首期研究范围 v0.1，建立 4 条可复用检索式、5 条候选论文记录、5 条筛选日志、PaperCard/Claim/Evidence/ScreeningLog/FalsificationHit 契约、fixture、操作日志和本交接文档。在线 arXiv API 请求已实际尝试但因套接字权限失败，相关论文未被伪装成已核验结论。

## 2. 研究范围
- 垂直领域：LLM agents 与 RAG 在自动科研文献综述/科学研究问答中的应用。
- 主问题：相比无外部检索 LLM 基线，检索增强大模型智能体是否提高自动科研回答的证据可追溯性与事实/任务质量？
- 范围版本：v0.1（2026-08-22）。

## 3. 交付文件
- docs/research_scope.md：范围、主问题、纳排标准、词表、歧义处理和不覆盖项；状态 fixed。
- data/search_queries.json：4 条查询（主、扩展、任务限定、风险反向）；状态可复用，实际 API 执行仅 arXiv q-001 的尝试失败。
- data/papers.jsonl：5 条候选；状态 0 include、2 exclude、3 pending。
- data/screening_log.jsonl：每篇 1 条 title_abstract 记录；状态完整覆盖 papers.jsonl。
- docs/data_contract.md：字段契约和虚构 fixture；状态可供实现校验。
- docs/prompts/role_a_phase1.md：角色 A 职责副本。
- docs/agent_log.md：可审计操作日志。

## 4. 数据字段和语义
- 关键字段：paper_id、dedup_key、decision、reason、claim_id、evidence_id、snippet、locator、verdict、confidence、extraction_status。
- 必填字段：PaperCard 至少 paper_id/title/source/retrieved_at/dedup_key/decision/reason；ScreeningLog 的全部基础字段；Claim 的 claim_id/text/source/status/decision_reason；Evidence 的 evidence_id/claim_id/paper_id/snippet/locator/verdict/confidence/extraction_status。
- 状态枚举：论文/筛选为 include|exclude|pending；Claim 为 supported|partial|unsupported|pending；Evidence verdict 为 supports|partially_supports|contradicts|context_only。
- 关联关系：Claim -> Evidence（claim_id）-> PaperCard（paper_id）；ScreeningLog -> PaperCard（paper_id）。

## 5. B 可以立即执行的操作
- 可复制的读取或校验命令（PowerShell）：
  Get-Content data/papers.jsonl | ForEach-Object { $_ | ConvertFrom-Json }
  Get-Content data/screening_log.jsonl | ForEach-Object { $_ | ConvertFrom-Json }
  Get-Content data/search_queries.json -Raw | ConvertFrom-Json | Measure-Object
- 预期输出：前两条逐行无解析错误；查询数组计数为 4；论文计数为 5，筛选记录计数为 5。
- fixture 或样例位置：docs/data_contract.md 的“Fixture（虚构，不是真实论文）”小节；不得计入真实统计。

## 6. B 不得擅自改变的内容
- 研究问题：不能扩展为多学科或通用搜索。
- 纳入/排除标准：必须由 A 更新 research_scope.md 并递增 scope_version。
- 字段语义：尤其是 paper_id、snippet、locator、decision、status，不得为方便 UI 改名或改含义。
- 状态判决规则：缺 Evidence、缺 locator、规则与模型冲突时必须 pending；exclude 记录不可删除。

## 7. 已知限制
- API 或网络限制：export.arxiv.org:443 请求返回套接字权限错误；OpenAlex/Semantic Scholar 查询式已保存但尚未执行。
- 数据缺失：5 条记录的 authors/abstract 均为 null 或未核验；没有全文页码和证据摘录。
- 尚未完成的筛选：paper-001、paper-002、paper-003 需重新获取摘要/全文后再做 title_abstract/full_text 判断。
- 需要后续人工核验的论文：全部 3 条 pending；即使标题高度相关，也不能直接当 include。

## 8. 需要 B 确认的问题
1. B 的读取器是否接受 null 元数据并保留 pending，而不是填充默认作者/摘要？
2. B 是否能在 UI/流水线中同时展示 exclude 与 pending 及 reason/reason_code？
3. B 是否同意以 docs/data_contract.md 的 locator 对象支持 page/section/paragraph/url_anchor 多种定位？

## 9. 验收建议
- B 应检查 docs/research_scope.md、data/search_queries.json、data/papers.jsonl、data/screening_log.jsonl、docs/data_contract.md 和 docs/agent_log.md。
- B 应验证 ID 唯一、decision/status 枚举、paper_id 外键、每篇论文都有筛选日志和非空 reason。
- B 可先运行本交接第 5 节的三条命令确认 JSON/JSONL 可读取，再用 fixture 构建离线 schema 测试；fixture 不应进入真实论文统计。
