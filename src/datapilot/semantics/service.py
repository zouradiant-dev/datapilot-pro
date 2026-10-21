"""Trusted host orchestration of one metric worker; no new scheduler or agent framework."""

from datapilot.agents.sql import SQLAgent
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.harness.metric_verification import equal_value, make_evidence, verify_execution
from datapilot.ingestion.common import digest
from datapilot.llm.client import ModelClient
from datapilot.runtime.mcp_client import metric_session
from datapilot.semantics.contracts import MetricOutcome, MetricReport, MetricRequest, ReportClaim
from datapilot.semantics.recipes import TITLES
from datapilot.semantics.registry import RegistryStore


def validate_claims(requests, claims, evidence_lookup, verification_lookup):
    goals = {r.goal_id: r for r in requests}
    if (
        len(goals) != len(requests)
        or len(claims) != len(goals)
        or {c.goal_id for c in claims} != set(goals)
    ):
        raise AgentFailure("REPORT_COVERAGE", "Every requested goal must appear exactly once")
    for claim in claims:
        evidence = evidence_lookup(claim.evidence_id)
        verification = verification_lookup(claim.verification_id)
        request = goals[claim.goal_id]
        if (
            evidence.evidence_id != claim.evidence_id
            or verification.verification_id != claim.verification_id
            or evidence.request != request
            or verification.evidence_id != evidence.evidence_id
            or verification.request_sha256 != digest(request)
            or (verification.dataset_id, verification.dataset_version)
            != (request.dataset_id, request.dataset_version)
        ):
            raise AgentFailure(
                "REPORT_REFERENCE", "Claim references another goal or source version"
            )
        if claim.kind == "causal":
            raise AgentFailure(
                "CAUSAL_OVERCLAIM", "Descriptive evidence cannot establish causality"
            )
        if claim.kind == "metric":
            if verification.verdict != "verified" or not equal_value(claim.value, evidence.value):
                raise AgentFailure(
                    "REPORT_VALUE", "Only verified, exactly evidenced numbers can be reported"
                )
        elif claim.value is not None or verification.verdict == "verified":
            raise AgentFailure("REPORT_VALUE", "Unavailable claims must contain no number")


def render_report(outcomes: list[MetricOutcome]) -> str:
    lines = [
        "# SaaS 经营指标报告",
        "",
        "口径：已确认字段映射与版本化指标。账单收入不代表 MRR；描述性结果不证明因果。",
        "",
    ]
    for outcome in outcomes:
        ref = (
            f"[Evidence {outcome.evidence_id}; Verification {outcome.verification.verification_id}]"
        )
        if outcome.verification.verdict == "verified":
            value = outcome.value
            components = (
                f"（{value.numerator}/{value.denominator}）"
                if value.denominator is not None
                else ""
            )
            lines.append(
                f"- {TITLES[outcome.request.metric_id]}：{value.value} "
                f"{value.unit}{components}。{ref}"
            )
        else:
            reasons = (
                "；".join(m.message for m in outcome.missing) or "六层校验拒绝结果；请检查验证记录"
            )
            lines.append(f"- {TITLES[outcome.request.metric_id]}：不能计算/验证。{reasons}。{ref}")
        r = outcome.request
        period = f"[{r.window.start}, {r.window.end_exclusive})" if r.window else f"as_of={r.as_of}"
        lines.append(
            f"  数据源 `{r.dataset_id}` v{r.dataset_version}，语义 v{r.semantic_version}，"
            f"指标 v{r.metric_version}，{period}。{ref}"
        )
    lines.extend(
        ["", "限制：只验证已确认的数据口径和受限快照，不能证明源文件真实、业务完整或因果关系。"]
    )
    return "\n".join(lines)


async def analyze(
    settings: Settings,
    store: RegistryStore,
    requests: list[MetricRequest],
    *,
    client: ModelClient | None = None,
) -> MetricReport:
    if not 1 <= len(requests) <= 10 or len({r.goal_id for r in requests}) != len(requests):
        raise ValueError("Use one to ten unique metric goals")
    outcomes, claims = [], []
    for request in requests:
        scope = DatasetScope(
            bindings=[
                DatasetBinding(dataset_id=request.dataset_id, version=request.dataset_version)
            ]
        )
        async with metric_session(settings, scope) as tools:
            execution = await SQLAgent(
                client, tools, max_attempts=settings.max_sql_attempts
            ).run_metric(request)
            evidence = make_evidence(execution)
            store.append_evidence(evidence)  # Raw artifact; it has no 'verified' flag.
            referenced = await tools.evidence(request.dataset_id, evidence.evidence_id)
            verification = verify_execution(execution, evidence, referenced)
            store.append_verification(verification)
        value = evidence.value if verification.verdict == "verified" else None
        outcomes.append(
            MetricOutcome(
                request=request,
                evidence_id=evidence.evidence_id,
                verification=verification,
                value=value,
                missing=evidence.missing,
            )
        )
        claims.append(
            ReportClaim(
                goal_id=request.goal_id,
                kind="metric" if value else "unavailable",
                evidence_id=evidence.evidence_id,
                verification_id=verification.verification_id,
                value=value,
            )
        )
    validate_claims(requests, claims, store.get_evidence, store.get_verification)
    return MetricReport(
        execution_mode="model_assisted" if client else "deterministic",
        outcomes=outcomes,
        claims=claims,
        markdown=render_report(outcomes),
    )
