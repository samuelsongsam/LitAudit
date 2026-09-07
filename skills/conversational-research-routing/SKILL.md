---
name: conversational-research-routing
description: Route LitAudit conversational research turns into new retrieval, current-run follow-up, paper exploration, branch deepening, or scope clarification.
metadata:
  short-description: Route multi-turn research questions safely
---

# Conversational Research Routing

Use this skill for a LitAudit conversation after the user submits a research question or follows up on an existing result.

Classify each turn before acting:

- `new_topic`: a new research question or unrelated topic; create a new online run.
- `follow_up`: asks about the current result, claims, evidence status, counts, limitations, or screening; reuse the current run.
- `paper_explore`: names or clearly points to a paper; reuse the current run and focus the answer on that paper.
- `branch_deepen`: asks to continue a research direction, method, risk, or contradiction; create a new run only when new literature is needed, otherwise reuse the current run.
- `requery`: explicitly asks to search again, refresh, broaden, narrow, or use a different source; create a new online run.
- `scope_clarify`: asks to explain or refine the research scope without requesting retrieval; reuse the current run.

Return a structured intent with `kind`, `confidence`, `reason`, `needs_retrieval`, `needs_clarification`, `direct_answer`, and optional `target_paper_id`, `branch`, `clarification_questions`, `expanded_query`, or `answer`. Do not infer a paper ID from an ambiguous title. Search only when the turn needs new literature and the research request is sufficiently specified. Factual questions about a loaded run stay local.

## LLM-first understanding

For every new topic or expanded keyword, send the user's wording and the relevant conversation context to the configured LLM before choosing an action. The LLM must decide among:

- `direct_answer`: the current run already has papers/claims/evidence that can answer the follow-up; answer through the LLM and do not search. Never use this when the run is empty, this is a new conversation, or `available_papers` is empty.
- `clarify`: the topic needs scope decisions; return exactly three questions, each with exactly three topic-specific options.
- `retrieve`: the brief is sufficiently specified, or the user asked a research topic with no loaded literature; return an expanded query that includes the original topic and the user's choices. Do not tell the user to retrieve first — retrieve.

The local Skill supplies the routing rules and output contract; it must not replace LLM-generated answers or questions with a fixed topic list. If the LLM is unavailable, return an AI-service error with no answer, questions, options, or retrieval. Never search merely because the LLM call failed.

## Clarify before retrieval

Do not immediately search after a short, broad, or ambiguous user message. First ask focused follow-up questions to establish enough of the research brief:

- research object or population/domain;
- method, intervention, phenomenon, or comparison;
- task and intended output;
- time range, language, source databases, or inclusion boundaries;
- whether the user wants a broad survey, a branch investigation, or a specific paper.

Set `needs_clarification=true` and `needs_retrieval=false` when these details are missing. A direct request such as “请检索……” may proceed only when its topic is still concrete enough to form a defensible query. Do not treat a generic “帮我看看”“找些论文” or a one-line topic as sufficient. Once the user answers the clarification, combine the accumulated details into an expanded query and then retrieve.

The clarification response must contain only the LLM-generated questions and options. Do not show a total overview, related-paper list, research map, fixed example questions, fabricated papers, results, or citations during clarification.

All generated overviews must distinguish abstract-level screening from page-verified evidence. Preserve pending claims and retrieval failures. Never convert citation proximity, keyword overlap, or a paper being included into proof of a claim.

## Tool decision contract

For every post-retrieval message, infer one concrete operation before producing content:

- `follow_up`: answer from the current run without retrieving and preserve its run ID.
- `paper_explore`: resolve the mentioned title to `target_paper_id`, then answer only from that paper's current metadata, abstract, claims, and evidence. Retrieve only when the requested detail is absent.
- `branch_deepen`: set `branch`, expand that branch with the current research scope, and create a new live run.
- `requery`: honor an explicit request to search again, broaden, narrow, compare, or refresh, and create a new live run.
- `new_topic`: detach from the current run; if the run is empty, retrieve (or clarify if underspecified). Never answer that there is no data instead of searching.

Return both the coarse `action` (`direct_answer`, `clarify`, or `retrieve`) and the operation `kind`. A completed `direct_answer` may legitimately reuse the current run and must never trigger a request for a null run. A completed retrieval must always return a non-empty replayable run ID. Do not mechanically ask questions when the current run already contains enough information to answer.
