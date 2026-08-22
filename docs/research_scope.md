# LitAudit 首期研究范围

## 范围版本
- scope_version: v0.1
- last_updated: 2026-08-22
- status: fixed for Phase 1; online metadata verification remains a documented limitation.

## 首期垂直领域
大模型智能体（LLM agents）与检索增强生成（RAG）在自动科研文献综述/研究问答中的应用。首期只研究文献检索、证据定位和基于文献的回答/综述这一条任务链，不扩展到实验机器人、代码智能体、通用搜索或临床决策。

## 主研究问题
> 在自动科研文献综述或研究问答任务中，相比不使用外部检索的 LLM 基线，检索增强的大模型智能体是否能提高回答的证据可追溯性与事实/任务质量？

“提高”必须由论文报告的可复核任务指标或人工评价支持；只有方法描述而没有比较或评价证据的论文不能单独支持因果性结论。

## 背景与边界
LLM agent 可以规划检索、调用搜索/数据库工具、读取论文并生成带引用的回答。RAG 可能减少知识过时和无依据生成，但检索噪声、引用错误、工具调用成本和评测泄漏仍是风险。本阶段只建立可回溯的候选集和筛选契约，不生成跨论文的确定性综述结论。

## 研究对象
论文必须把 LLM 作为生成或决策核心，并涉及外部文献/科学信息检索、检索增强、工具调用或多步 agent 流程；任务输出是文献综述、科学问答、证据汇总、引用支持的研究回答或相邻的自动科研信息整合。

## 纳入标准
1. 研究对象满足 LLM + agent/RAG/工具检索中的至少一项，且任务与科学文献或研究信息有关。
2. 论文给出可定位的实验、数据集、基线、人工评价或定量指标中的至少一类；仅概念提案进入 pending，不进入确定结论。
3. 能获得稳定标识（DOI、arXiv ID 或正式出版物 URL）并可记录来源。
4. 论文在 2019-01-01 至 2026-08-22 首期时间窗内公开。
5. 允许预印本、会议/期刊论文、系统论文和可公开核验的技术报告；必须保留其出版状态。

## 排除标准
1. 不是 LLM 驱动，或没有外部检索/科学信息任务。
2. 只讨论通用聊天、代码生成、游戏或非科研搜索，无法映射到主问题。
3. 只有营销/博客/新闻/幻觉摘要，没有可核验论文元数据。
4. 重复记录：优先 DOI，其次 arXiv ID，再次标准化标题 + 第一作者 + 年份。
5. 超出时间窗，或全文/摘要信息不足以判断范围且无法通过稳定来源补齐；此类记录可标为 pending 而非强行排除。

## 允许来源与论文类型
优先来源：arXiv API/页面、OpenAlex、Semantic Scholar；正式出版信息可用 DOI/Crossref 交叉核验。允许 preprint、conference、journal、technical report。没有实际访问记录的来源不得在日志中声称已验证。

## 词表
- 关键词：large language model, LLM, agent, LLM agent, retrieval-augmented generation, RAG, grounded generation, scientific literature, literature review, scientific question answering, research assistant
- 同义词：retrieval augmented / retrieval-augmented; literature synthesis / evidence synthesis; scientific QA / science question answering; tool-using agent / tool augmented agent
- 缩写：LLM, RAG, QA, IR, NLP, SciQA
- 相关任务名：automated literature review, citation-aware answer generation, evidence retrieval, multi-hop scientific QA, paper recommendation（仅当输出用于研究问答/综述时）
- 反向检索词：citation hallucination, unsupported claim, retrieval failure, irrelevant context, benchmark leakage, stale knowledge, negative result, limitations, faithfulness, attribution error

## 歧义词处理
- agent 单独出现可能指软件代理或强化学习 agent；必须与 LLM、language model、RAG 或科研文献任务词共现。
- retrieval 单独出现可能指数据库/视觉检索；必须与生成、问答、文献或科学任务词共现。
- scientific 单独出现可能只是领域标签；要求标题/摘要出现论文、文献、问答、证据或综述任务。
- autonomous scientist 可能包含实验执行；只有其文献检索/综述子任务纳入。

## 第一阶段不覆盖
不覆盖实验室机器人和真实实验执行、纯代码 agent、通用网页搜索、医学诊断结论、未公开内部报告、跨学科总体效果汇总、因果元分析以及未经原文定位的模型生成长段落。

## 研究范围变更规则
任何增加学科、改变主问题、放宽纳入标准或改变状态枚举的修改必须递增 scope_version，在 docs/agent_log.md 记录原因，并由 A 与 B 共同确认。
