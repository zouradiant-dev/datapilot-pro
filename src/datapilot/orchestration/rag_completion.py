"""Deterministic RAG completion checks; not an evaluator of arbitrary business claims."""

import re

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.runtime import text_hash

SUBMIT = "submit_rag_result"
PROTOCOL = "rag-submit-v1"
CORRECTION = "rag_completion_correction"
RELEVANCE_POLICY = "bge-host-goal-cosine-v1"
RELEVANCE_THRESHOLD = 0.55


def enabled(retrieval):
    return getattr(retrieval, "completion_protocol", None) == PROTOCOL


def retrieval_goal(question):
    # Requirements come from the original host goal, never model search keywords.
    match = re.fullmatch(
        r'(?:仅)?(?:检索|查找|定位)包含[“"]([^”"\n]{1,64})[”"]的文档片段'
        r"(?:[，,]保留(?:实际)?来源引用)?[。？?]?",
        question,
    )
    if not question:
        return None
    sources = re.search(r"至少([二两三四五2-5])(?:份|篇|个)文档", question)
    minimum = (
        int(sources[1])
        if sources and sources[1].isdigit()
        else ({"二": 2, "两": 2, "三": 3, "四": 4, "五": 5}.get(sources[1], 1) if sources else 1)
    )
    retrieval_only = bool(re.match(r"(?:仅)?(?:检索|查找|定位|搜索|寻找)", question)) or not bool(
        re.search(r"分析|解释|因果|计算|统计", question)
    )
    unsupported = not match and bool(
        re.search(r"至少(?:[6-9]|\d{2,}|[六七八九十])|(?:全部|所有|完整的?)(?:文档|资料)", question)
        or (retrieval_only and re.search(r"全部|所有|完整|最近|最新|\d{4}[-年]", question))
    )
    return {
        "protocol": "retrieval-task-v1",
        "relevance_policy": RELEVANCE_POLICY,
        "minimum_goal_score": RELEVANCE_THRESHOLD,
        "question_sha256": text_hash(question),
        "required_terms": [match[1]] if match else [],
        "minimum_sources": minimum,
        # A business analysis window is not automatically a date filter on background documents.
        "unsupported_requirements": unsupported,
        "business_conclusions_verified": False,
    }


def validate_submission(envelope, store, granted, submission, retrieval, goal):
    ids = submission.artifact_ids
    allowed = {r.artifact_id: r for r in granted}
    if len(set(ids)) != len(ids) or any(i not in allowed for i in ids):
        raise AgentFailure(
            "EVIDENCE_INVALID", "Only unique, actually obtained task artifacts may be cited"
        )
    documents = []
    for id_ in ids:
        item = store.get(allowed[id_])
        if (item.run_id, item.task_id, item.plan_version, item.kind) != (
            envelope.run_id,
            envelope.task.task_id,
            envelope.plan_version,
            "documents",
        ) or item.parents:
            raise AgentFailure(
                "EVIDENCE_INVALID", "Completion evidence belongs to another task/version"
            )
        if any(text_hash(d.text) != d.sha256 for d in item.documents.documents):
            raise AgentFailure("EVIDENCE_INVALID", "Document hash changed")
        retrieval.validate_result(item.documents)
        documents.extend(item.documents.documents)
    if submission.outcome == "unavailable":
        if documents:
            raise AgentFailure(
                "RAG_OUTCOME_INVALID", "Nonempty retrieval requires insufficient, not unavailable"
            )
        return "empty"
    if submission.outcome == "insufficient":
        if not documents:
            raise AgentFailure("RAG_OUTCOME_INVALID", "Use unavailable for actual empty retrieval")
        return "insufficient"
    if not documents or goal is None or goal["unsupported_requirements"]:
        relevant = []
    elif goal["required_terms"]:
        relevant = [d for d in documents if all(t in d.text for t in goal["required_terms"])]
    else:
        relevant = retrieval.qualifying_documents(documents, goal)
    source_ids = {d.citation.source_id if d.citation else d.source for d in relevant}
    if not relevant or len(source_ids) < (goal["minimum_sources"] if goal else 1):
        raise AgentFailure(
            "EVIDENCE_INSUFFICIENT",
            "Authorized relevant passages meeting the retrieval requirements are missing; "
            "submit insufficient or unavailable. Business conclusions are a separate check.",
        )
    return "literal_locator" if goal["required_terms"] else "semantic_retrieval"


def relevant_ids(store, refs, retrieval, goal):
    documents = [d for ref in refs for d in store.get(ref).documents.documents]
    relevant = (
        [d for d in documents if all(t in d.text for t in goal["required_terms"])]
        if goal["required_terms"]
        else retrieval.qualifying_documents(documents, goal)
    )
    return sorted({d.document_id for d in relevant})


def goal_hash(goal):
    return digest(goal) if goal is not None else None


def assistant_calls(message):
    return [*message.tool_calls, *message.invalid_tool_calls] if message.type == "ai" else []
