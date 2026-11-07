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
SOURCE_RELEVANCE_POLICY = "bge-host-source-goal-cosine-v1"
REQUIREMENT_POLICY = "host-goal-requirements-v4"


def requirement_class(question):
    """Bounded eligibility grammar, not authorization or corpus-completeness proof.

    Negation applies to its own collection action, never a later positive clause.
    Unresolved breadth is denied rather than silently narrowed to retrieved facts.
    """
    collection = (
        r"文档|文件|资料|来源|证据|语料|知识库|内容|\b(?:documents?|files?|sources?|"
        r"evidence|corpus|corpora|collection|knowledge\s+base)\b"
    )
    quantifier = (
        r"(?:所有(?!权|者)|全部|整个|完整(?!性)的?|"
        r"每(?!周|月|日|天|年|小时|分钟|秒|季度)[一个份篇]?|"
        r"\b(?:all|every|each|whole|entire|complete)\b"
        r"(?!\s+(?:days?|weeks?|months?|years?|hours?|minutes?|seconds?)\b)\s*)"
        r"(?!(?:已经|已)(?:确认|证实|验证|知)的?"
        r"(?:(?!文档|文件|来源|资料|语料)[^，。]){0,24}(?:事实|规则|条件|要求)|"
        r"\s*(?:confirmed|verified|known)\s+"
        r"(?:(?!documents?\b|files?\b|sources?\b)[a-z-]+\s+){0,6}"
        r"(?:facts?|rules?|requirements?|conditions?)\b)"
    )
    action = (
        r"(?:遍历|扫描|检查|审阅|核对|列出|检索|证明|确认|逐篇检查|"
        r"scan|inspect|review|list|claim|prove)"
    )
    has_collection = re.search(collection, question, re.IGNORECASE)
    classes = set()
    clauses = re.split(r"[，,。.!?！？；;\n]|但(?:是)?|而(?:是|要)|\bbut\b", question.lower())
    for clause in clauses:
        if not clause.strip():
            continue
        if re.search(
            r"不是说|尽量[^，。]{0,24}(?:完整|全面)|(?:所有|全部)(?:应该|应当)|"
            r"(?:全部|所有)相关内容|(?:不要|不得)漏掉关键来源|"
            r"everything\s+that\s+should|all\s+relevant\s+information|"
            r"try\s+to\s+be\s+comprehensive",
            clause,
        ):
            classes.add("ambiguous_unresolved")
            continue
        negated = re.search(
            r"(?:(?:不需要|无需|不必|不用|不要|不要求|禁止)(?:去|再)?\s*|"
            r"\b(?:do\s+not|don't|no\s+need\s+to|not\s+required\s+to)\s+)" + action,
            clause,
        )
        double_negative = re.search(r"不能不|不得不|并非不|不是不|not\s+unnecessary", clause)
        if negated and not double_negative and re.search(collection, clause[negated.end() :]):
            # Do not erase a second, positive requirement joined within this clause.
            if re.search(
                r"(?:并|且|还|而|却|必须|\band\b|\bwhile\b|\byet\b).{0,12}" + action,
                clause[negated.end() :],
            ):
                classes.add("ambiguous_unresolved")
            clause = clause[: negated.start()]
        omissions = re.search(
            r"(?:任何)?一[份篇个].{0,8}(?:不能|不得|不许|不)(?:再)?(?:漏|遗漏)|"
            r"不漏一[份篇]|(?:不允许|不能|不得|没有|无).{0,8}(?:遗漏|漏掉)|"
            r"\bno\b.{0,32}(?:source|document|file).{0,16}(?:missed|omitted)|"
            r"without\s+(?:exception|omissions)",
            clause,
        )
        enumerating = re.search(
            r"逐[篇份]|逐[个条](?:检查|审阅|核对|扫描|读取)?(?:文档|文件|资料|来源|语料)",
            clause,
        )
        if re.search(quantifier + r"[^，。！？；\n]{0,64}(?:" + collection + ")", clause) or (
            has_collection and (omissions or enumerating)
        ):
            classes.add("exhaustive_collection")
        elif re.search(
            quantifier
            + r".{0,32}(?:事实|规则|条件|要求|管理员|用户|客户|账号|账户|账单|发票|订单|订阅)",
            clause,
        ) and not re.search(r"已确认|已经确认|已验证|已证实|已知|确认的|指定|pinned", clause):
            classes.add("ambiguous_unresolved")
    return next(
        (c for c in ("exhaustive_collection", "ambiguous_unresolved") if c in classes),
        "bounded_facts",
    )


def enabled(retrieval):
    return getattr(retrieval, "completion_protocol", None) == PROTOCOL


def retrieval_goal(question, retrieval=None, report_scope=None):
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
    snapshot_unattested = not match and bool(
        re.search(
            r"(?:最新|同一时点|全局|跨来源一致)[^。！？\n]{0,128}快照"
            r"|(?:latest|global|consistent|point.in.time)[^.!?\n]{0,128}snapshot",
            question,
            re.IGNORECASE,
        )
    )
    breadth = "bounded_facts" if match else requirement_class(question)
    unsupported = snapshot_unattested or (
        not match
        and bool(
            re.search(r"至少(?:[6-9]|\d{2,}|[六七八九十])", question)
            or breadth != "bounded_facts"
            or (retrieval_only and re.search(r"最近|最新|\d{4}[-年]", question))
        )
    )
    goal = {
        "protocol": "retrieval-task-v1",
        "requirement_policy": REQUIREMENT_POLICY,
        "requirement_class": breadth,
        "relevance_policy": getattr(retrieval, "relevance_policy", RELEVANCE_POLICY),
        "minimum_goal_score": getattr(retrieval, "goal_threshold", RELEVANCE_THRESHOLD),
        "question_sha256": text_hash(question),
        "required_terms": [match[1]] if match else [],
        "minimum_sources": minimum,
        # A business analysis window is not automatically a date filter on background documents.
        "unsupported_requirements": unsupported,
        "business_conclusions_verified": False,
    }
    # Classification is not confirmation. Only a trusted review of the entire
    # host contract (or the exact, closed literal-locator grammar) grants eligibility.
    attestation = None
    if report_scope is not None and report_scope.goal_scope_attestation is not None:
        from datapilot.reporting.contracts import ReportScope, finite_contract_hash

        checked = ReportScope.model_validate_json(report_scope.model_dump_json())
        proof = checked.goal_scope_attestation
        if (
            checked.document_goal is None
            or checked.document_goal.question != question
            or retrieval is None
            or checked.owner != retrieval.scope.owner
            or checked.datasets != retrieval.scope.datasets
            or proof.contract_sha256 != finite_contract_hash(checked)
            or proof.rag_scope_sha256 != digest(retrieval.scope)
        ):
            raise AgentFailure("REPORT_SCOPE_INVALID", "Finite goal scope confirmation changed")
        attestation = proof.model_dump(mode="json")
        if checked.document_goal.source_goals:
            targets = [g.model_dump(mode="json") for g in checked.document_goal.source_goals]
            if hasattr(retrieval, "source_goals") and targets != [
                g.model_dump(mode="json") for g in retrieval.source_goals
            ]:
                raise AgentFailure(
                    "REPORT_SCOPE_INVALID", "MCP source goals differ from the reviewed contract"
                )
            goal["source_goals"] = targets
            goal["relevance_policy"] = SOURCE_RELEVANCE_POLICY
        if checked.citation_policy:
            # These are retrieval obligations as well as report classifications.
            # Extra relevant sources cannot replace an explicitly required source.
            goal["required_sources"] = [
                source.model_dump(mode="json")
                for source in checked.citation_policy.required_sources
            ]
    elif match and (report_scope is None or report_scope.question == question):
        attestation = {
            "basis": "literal-locator-grammar-v1",
            "question_sha256": text_hash(question),
        }
    goal["scope_attestation"] = attestation
    goal["completion_eligible"] = bool(not unsupported and attestation is not None)
    if snapshot_unattested:
        # Immutable per-source versions do not attest global freshness or a common cut-off.
        # This is a refusal reason, never a model-supplied snapshot ID or authorization.
        goal["unsupported_reason"] = "snapshot_not_attested"
    elif breadth != "bounded_facts":
        goal["unsupported_reason"] = (
            "exhaustiveness_not_attested"
            if breadth == "exhaustive_collection"
            else "goal_scope_unresolved"
        )
    return goal


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
    if (
        not documents
        or goal is None
        or goal["unsupported_requirements"]
        or goal.get("completion_eligible") is not True
    ):
        relevant = []
    elif goal["required_terms"]:
        relevant = [d for d in documents if all(t in d.text for t in goal["required_terms"])]
    else:
        relevant = retrieval.qualifying_documents(documents, goal)
    source_ids = {d.citation.source_id if d.citation else d.source for d in relevant}
    required_sources_met = True
    if goal and goal.get("required_sources"):
        from datapilot.reporting.contracts import CitationSource, source_identity

        observed = {source_identity(d.citation) for d in relevant if d.citation}
        required_sources_met = all(
            source_identity(CitationSource.model_validate(source)) in observed
            for source in goal["required_sources"]
        )
    if (
        not relevant
        or len(source_ids) < (goal["minimum_sources"] if goal else 1)
        or not required_sources_met
    ):
        raise AgentFailure(
            "EVIDENCE_INSUFFICIENT",
            "Host versions do not attest the requested latest/global snapshot; "
            "submit insufficient or unavailable."
            if goal and goal.get("unsupported_reason") == "snapshot_not_attested"
            else "Authorized relevant passages meeting the retrieval requirements are missing; "
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
