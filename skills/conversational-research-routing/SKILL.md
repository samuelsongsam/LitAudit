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

Send new topics and expanded keywords to the configured LLM before choosing an action. An explicit request to proceed with the original wording goes straight to retrieval. The LLM must decide among:

- `direct_answer`: the current run already has papers/claims/evidence that can answer the follow-up; answer through the LLM and do not search. Never use this when the run is empty, this is a new conversation, or `available_papers` is empty.
- `clarify`: a consequential ambiguity about the subject or research focus blocks a useful query. Return one question. Supply two or three distinct answers only when they answer that question directly. Use an empty option list for a free-text answer.
- `retrieve`: the brief is sufficiently specified, or the user asked a research topic with no loaded literature; return an expanded query that includes the original topic and the user's choices. Do not tell the user to retrieve first — retrieve.

The local Skill supplies the routing rules and output contract; it must not replace LLM-generated answers or questions with a fixed topic list. If the LLM is unavailable, return an AI-service error with no answer, questions, options, or retrieval. Never search merely because the LLM call failed.

## Scope clarification

Retrieve when the wording supports a useful query, even when it is short or leaves dates and publication preferences open. Ask one focused question when the answer would materially change the search, such as which work an ambiguous name refers to. Options must resolve that specific ambiguity. Leave options empty when no distinct choices can be stated without guessing.

Set `needs_clarification=true` and `needs_retrieval=false` for that turn. The user can answer the question or start with the original wording. On the next turn retrieve using the original topic and any supplied answer. A malformed clarification should continue using the available query without generic questions or option padding.

The clarification response presents the question and any valid options. It contains no literature results before retrieval.

All generated overviews must distinguish abstract-level screening from page-verified evidence. Preserve pending claims and retrieval failures. Never convert citation proximity, keyword overlap, or a paper being included into proof of a claim.

## Tool decision contract

For every post-retrieval message, infer one concrete operation before producing content:

- `follow_up`: answer from the current run without retrieving and preserve its run ID.
- `paper_explore`: resolve the mentioned title to `target_paper_id`, then answer only from that paper's current metadata, abstract, claims, and evidence. Retrieve only when the requested detail is absent.
- `branch_deepen`: set `branch`, expand that branch with the current research scope, and create a new live run.
- `requery`: honor an explicit request to search again, broaden, narrow, compare, or refresh, and create a new live run.
- `new_topic`: detach from the current run; if the run is empty, retrieve (or clarify if underspecified). Never answer that there is no data instead of searching.

Return both the coarse `action` (`direct_answer`, `clarify`, or `retrieve`) and the operation `kind`. A completed `direct_answer` may legitimately reuse the current run and must never trigger a request for a null run. A completed retrieval must always return a non-empty replayable run ID. Do not mechanically ask questions when the current run already contains enough information to answer.
