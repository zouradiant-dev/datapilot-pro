"""Closed SaaS recipes. No user-supplied SQL template, expression, function or Python code."""

import re
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import sqlglot
from sqlglot import exp

from datapilot.contracts import AgentFailure, QueryResult
from datapilot.datasets.contracts import DatasetSchema
from datapilot.ingestion.common import digest
from datapilot.semantics.contracts import (
    MetricContext,
    MetricRequest,
    MetricValue,
    MetricVersion,
    MissingRequirement,
    SemanticVersion,
)
from datapilot.tools.sql import SQLPolicy, validate_sql

BLUEPRINTS = {
    "paid_invoice_revenue": ("invoices", ("record_id", "amount", "invoice_date", "payment_status")),
    "subscription_churn": (
        "subscriptions",
        ("record_id", "start_date", "end_date", "termination_kind"),
    ),
    "customer_churn": ("subscriptions", ("record_id", "customer_id", "start_date", "end_date")),
    "active_subscriptions": ("subscriptions", ("record_id", "start_date", "end_date")),
    "usage": ("usage_events", ("record_id", "event_date", "event_count")),
    "mrr": ("subscriptions", ("record_id", "start_date", "end_date")),
}
TITLES = {
    "paid_invoice_revenue": "已付账单收入",
    "subscription_churn": "期初订阅队列流失率",
    "customer_churn": "期初客户队列期末净流失率",
    "active_subscriptions": "时点活跃订阅数",
    "usage": "产品使用事件量",
    "mrr": "月度经常性收入",
}


def missing(code: str, message: str, *fields: str) -> MissingRequirement:
    return MissingRequirement(code=code, message=message, fields=list(fields))


def build_context(
    schema: DatasetSchema, semantic: SemanticVersion, metric: MetricVersion
) -> MetricContext:
    if (semantic.dataset_id, semantic.dataset_version, semantic.source_sha256) != (
        schema.dataset_id,
        schema.version,
        schema.source_sha256,
    ) or (
        metric.dataset_id,
        metric.dataset_version,
        metric.semantic_version,
        metric.semantic_sha256,
    ) != (schema.dataset_id, schema.version, semantic.semantic_version, semantic.definition_sha256):
        raise AgentFailure(
            "DEFINITION_VERSION_MISMATCH",
            "Definitions must bind the same source and semantic versions",
        )
    definition = metric.definition
    entity_name, required = BLUEPRINTS[definition.metric_id]
    roles = set(required)
    mapping = next(
        (m.model_copy(deep=True) for m in semantic.definition.entities if m.entity == entity_name),
        None,
    )
    table = next(
        (
            t.model_copy(deep=True)
            for t in schema.tables
            if mapping and t.table_id == mapping.table_id
        ),
        None,
    )
    problems = []
    if mapping is None or table is None:
        problems.append(missing("entity_missing", "缺少已确认的实体到数据表映射", entity_name))
    else:
        if definition.metric_id == "paid_invoice_revenue" and "currency" in mapping.fields:
            roles.add("currency")
        if definition.feature is not None:
            roles.add("feature")
        for role in sorted(roles - set(mapping.fields)):
            problems.append(
                missing("field_missing", "缺少指标所需的已确认字段", entity_name + "." + role)
            )
        if mapping.grain != [mapping.fields.get("record_id")]:
            problems.append(
                missing(
                    "grain_unconfirmed",
                    "本阶段需要已确认的单一记录 ID 粒度",
                    entity_name + ".record_id",
                )
            )
        if mapping.coverage_start is None:
            problems.append(
                missing(
                    "coverage_unconfirmed",
                    "未确认完整观测时间范围，不能把缺记录当作零",
                    entity_name,
                )
            )
        if entity_name == "subscriptions" and (
            not mapping.history_complete or mapping.subscription_identity != "contract"
        ):
            problems.append(
                missing(
                    "history_unconfirmed",
                    "需要完整有效区间和合同级订阅 ID；最终状态或套餐周期不能替代历史",
                    "subscriptions.history_complete",
                    "subscriptions.subscription_identity",
                )
            )
        if definition.metric_id == "paid_invoice_revenue":
            if mapping.amount_storage is None:
                problems.append(
                    missing(
                        "amount_unit_unconfirmed",
                        "需要确认金额按元还是整数分存储",
                        "invoices.amount_storage",
                    )
                )
            if "currency" not in mapping.fields and mapping.currency_constant is None:
                problems.append(
                    missing(
                        "currency_unconfirmed",
                        "缺少币种字段或用户明确确认的单一币种",
                        "invoices.currency",
                    )
                )
            if definition.currency != "CNY" or (
                mapping.currency_constant and mapping.currency_constant != definition.currency
            ):
                problems.append(
                    missing(
                        "currency_unsupported",
                        "首版仅计算明确的 CNY 单币种，不猜测汇率或最小货币单位",
                        "invoices.currency",
                    )
                )
        columns = {c.normalized_name: c for c in table.columns}
        for role in sorted(roles & set(mapping.fields)):
            col = columns.get(mapping.fields[role])
            allowed = (
                {"INTEGER", "NUMERIC"}
                if role == "amount"
                else {"INTEGER"}
                if role == "event_count"
                else {"DATE"}
                if role in {"invoice_date", "event_date", "start_date", "end_date"}
                else {"INTEGER", "TEXT"}
                if role in {"record_id", "customer_id"}
                else {"TEXT"}
            )
            if col is None or col.logical_type not in allowed:
                problems.append(
                    missing(
                        "field_type_invalid",
                        "字段类型不满足确定性指标规则；日期须先确认为 DATE",
                        entity_name + "." + role,
                    )
                )
        # Only the required entity/columns reach the worker/model context.
        mapping.fields = {k: v for k, v in mapping.fields.items() if k in roles}
        needed = set(mapping.fields.values()) | set(mapping.grain)
        table.columns = [c for c in table.columns if c.normalized_name in needed]
        table.primary_key = [c for c in table.primary_key if c in needed]
    if definition.metric_id == "mrr":
        problems.append(
            missing(
                "mrr_definition_missing",
                "账单收入不是 MRR；需要经常性合约金额、计费周期、折扣/退款及货币换算口径。"
                "本阶段没有已实现的 MRR 配方",
                "recurring_amount",
                "billing_period",
                "discount_refund_policy",
            )
        )
    context = MetricContext(
        dataset_id=schema.dataset_id,
        dataset_version=schema.version,
        source_sha256=schema.source_sha256,
        semantic_version=semantic.semantic_version,
        semantic_sha256=semantic.definition_sha256,
        metric_id=metric.metric_id,
        metric_version=metric.metric_version,
        metric_sha256=metric.definition_sha256,
        definition=definition,
        entity=mapping,
        table=table,
        missing=problems,
        context_sha256="0" * 64,
    )
    context.context_sha256 = digest(context.model_dump(mode="json", exclude={"context_sha256"}))
    return context


def request_missing(context: MetricContext, request: MetricRequest) -> list[MissingRequirement]:
    identity = (
        request.dataset_id,
        request.dataset_version,
        request.semantic_version,
        request.metric_id,
        request.metric_version,
    )
    if identity != (
        context.dataset_id,
        context.dataset_version,
        context.semantic_version,
        context.metric_id,
        context.metric_version,
    ):
        raise AgentFailure(
            "DEFINITION_VERSION_MISMATCH", "Request and context identify different versions"
        )
    problems = list(context.missing)
    if request.intent == "explain_cause":
        problems.append(
            missing(
                "causal_evidence_missing",
                "描述性指标不能识别原因；缺少实验或可信准实验/因果识别证据",
                "causal_design",
            )
        )
    mapping = context.entity
    if mapping and mapping.coverage_start:
        start = request.window.start if request.window else request.as_of
        end = request.window.end_exclusive if request.window else request.as_of
        if start < mapping.coverage_start or (
            end > mapping.coverage_end_exclusive
            if request.window
            else end >= mapping.coverage_end_exclusive
        ):
            problems.append(
                missing(
                    "outside_coverage", "请求时间超出用户确认的完整观测范围", "observation_coverage"
                )
            )
    return problems


def quote(name: str) -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect="postgres")


def literal(value) -> str:
    return exp.Literal.string(value.isoformat() if hasattr(value, "isoformat") else str(value)).sql(
        dialect="postgres"
    )


def compile_sql(context: MetricContext, request: MetricRequest) -> str:
    if request_missing(context, request):
        raise AgentFailure(
            "METRIC_UNAVAILABLE", "Required business semantics or observation data are missing"
        )
    fields = context.entity.fields
    table = "uploads." + quote(context.table.physical_name)

    def col(role, alias="s"):
        return alias + "." + quote(fields[role])

    def when(value):
        return "DATE " + literal(value)

    def cohort(alias):
        return (
            f"{col('start_date', alias)} < {when(request.window.start)} "
            f"AND ({col('end_date', alias)} IS NULL "
            f"OR {col('end_date', alias)} >= {when(request.window.start)})"
        )

    kind = request.metric_id
    if kind == "paid_invoice_revenue":
        paid = ",".join(literal(v) for v in context.definition.paid_values)
        currency = (
            f" AND {col('currency')}={literal(context.definition.currency)}"
            if "currency" in fields
            else ""
        )
        divisor = "100" if context.entity.amount_storage == "minor" else "1"
        sql = (
            f"SELECT COALESCE(SUM(CAST({col('amount')} AS DECIMAL)),0)/{divisor} AS value "
            f"FROM {table} s WHERE {col('payment_status')} IN ({paid}) "
            f"AND {col('invoice_date')} >= {when(request.window.start)} "
            f"AND {col('invoice_date')} < {when(request.window.end_exclusive)}{currency}"
        )
    elif kind == "usage":
        feature = (
            f" AND {col('feature')}={literal(context.definition.feature)}"
            if context.definition.feature is not None
            else ""
        )
        sql = (
            f"SELECT COALESCE(SUM({col('event_count')}),0) AS value FROM {table} s "
            f"WHERE {col('event_date')} >= {when(request.window.start)} "
            f"AND {col('event_date')} < {when(request.window.end_exclusive)}{feature}"
        )
    elif kind == "active_subscriptions":
        sql = (
            f"SELECT COUNT(*) AS value FROM {table} s "
            f"WHERE {col('start_date')} <= {when(request.as_of)} "
            f"AND ({col('end_date')} IS NULL OR {col('end_date')} > {when(request.as_of)})"
        )
    elif kind == "subscription_churn":
        events = ",".join(literal(v) for v in context.definition.churn_values)
        sql = (
            f"SELECT COUNT(*) FILTER (WHERE {cohort('s')} "
            f"AND {col('end_date')} >= {when(request.window.start)} "
            f"AND {col('end_date')} < {when(request.window.end_exclusive)} "
            f"AND {col('termination_kind')} IN ({events})) AS numerator, "
            f"COUNT(*) FILTER (WHERE {cohort('s')}) AS denominator FROM {table} s"
        )
    elif kind == "customer_churn":
        retained = (
            f"{col('customer_id', 't')}={col('customer_id')} "
            f"AND {col('start_date', 't')} < {when(request.window.end_exclusive)} "
            f"AND ({col('end_date', 't')} IS NULL "
            f"OR {col('end_date', 't')} >= {when(request.window.end_exclusive)})"
        )
        sql = (
            f"SELECT COUNT(DISTINCT {col('customer_id')}) "
            f"- COUNT(DISTINCT {col('customer_id', 't')}) AS numerator, "
            f"COUNT(DISTINCT {col('customer_id')}) AS denominator "
            f"FROM {table} s LEFT JOIN {table} t ON {retained} WHERE {cohort('s')}"
        )
    else:
        raise AgentFailure("METRIC_UNAVAILABLE", "No executable recipe for this metric")
    return validate_sql(sql, SQLPolicy("uploads", frozenset({context.table.physical_name})))


def semantics_match(sql: str, context: MetricContext, request: MetricRequest) -> bool:
    policy = SQLPolicy("uploads", frozenset({context.table.physical_name}))
    checked = validate_sql(sql, policy)
    expected = compile_sql(context, request)
    return sqlglot.parse_one(checked, read="postgres").sql(
        dialect="postgres", normalize=True
    ) == sqlglot.parse_one(expected, read="postgres").sql(dialect="postgres", normalize=True)


def unit(context: MetricContext) -> str:
    return (
        context.definition.currency
        if context.metric_id == "paid_invoice_revenue"
        else "ratio"
        if context.metric_id in {"customer_churn", "subscription_churn"}
        else "subscriptions"
        if context.metric_id == "active_subscriptions"
        else "events"
        if context.metric_id == "usage"
        else "CNY/month"
    )


def scalar(value) -> Decimal:
    if type(value) not in (int, str):
        raise ValueError("Exact integer/NUMERIC text required, never floating-point arithmetic")
    text = str(value)
    if len(text) > 80 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", text) is None:
        raise ValueError("Bounded fixed-point numeric text required")
    result = Decimal(text)
    if not result.is_finite():
        raise ValueError("Nonfinite result")
    return result


def metric_value(
    context: MetricContext, request: MetricRequest, result: QueryResult
) -> MetricValue:
    if result.truncated or result.row_count != 1:
        raise ValueError("Metric result must be one complete scalar/components row")
    days = (request.window.end_exclusive - request.window.start).days if request.window else None
    if context.metric_id in {"customer_churn", "subscription_churn"}:
        if result.columns != ["numerator", "denominator"]:
            raise ValueError("Expected numerator and denominator")
        n, d = (scalar(v) for v in result.rows[0])
        if n != n.to_integral_value() or d != d.to_integral_value() or not 0 <= n <= d <= 100_000:
            raise ValueError("Invalid cohort counts")
        with localcontext() as arithmetic:
            arithmetic.prec = 50
            ratio = (
                (n / d).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN) if d else None
            )
        return MetricValue(
            value=format(ratio, "f") if ratio is not None else None,
            unit="ratio",
            numerator=int(n),
            denominator=int(d),
            window_days=days,
        )
    if result.columns != ["value"]:
        raise ValueError("Expected value column")
    number = scalar(result.rows[0][0])
    if number < 0 or (
        context.metric_id != "paid_invoice_revenue" and number != number.to_integral_value()
    ):
        raise ValueError("Invalid nonnegative metric value")
    return MetricValue(value=format(number, "f"), unit=unit(context), window_days=days)
