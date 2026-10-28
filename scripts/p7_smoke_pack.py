"""Eight new synthetic Dev cases; author/seal only, never a provider client."""

import csv
import io
import json
import shutil
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from p7_holdout_pack import CaseInput, Gold, canonical, sha, verify_seal
from pydantic import Field
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import ChunkCitation, RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService as DocumentIngestion
from datapilot.rag.storage import make_pin
from datapilot.reporting.contracts import DocumentFact
from datapilot.runtime.mcp_client import dataset_session, metric_session
from datapilot.semantics.contracts import MetricDraft
from datapilot.semantics.registry import RegistryStore

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/dev-smoke-v1"
PACK = BASE / "sealed"
OWNER = "p7-synthetic-dev-smoke-v1"
DOCKER = shutil.which("docker") or "D:/downloads/DockerDesktop/resources/bin/docker.exe"
PROFILE = {
    "model_provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "max_model_calls": 8,
    "max_total_tokens": 18000,
    "max_output_tokens": 1200,
    "max_worker_turns": 4,
}
POLICY = {
    "version": "dev-smoke-budget-1",
    "case_limit": 8,
    "runtime_case_limit": 7,
    "calls_per_run": 8,
    "tokens_per_run": 18000,
    "worker_calls": 4,
    "worker_tokens": 18000,
    "campaign_model_calls": 56,
    "campaign_run_admissions": 7,
    "campaign_token_units": 90000,
    "task_timeout_seconds": 180,
    "campaign_timeout_seconds": 1800,
    "concurrency": 1,
    "automatic_retries": 0,
    "consecutive_provider_failures": 1,
    "estimated_usd_cap": "0.108",
    "paid_authorized": False,
}


class SmokeCase(CaseInput):
    case_id: str = Field(pattern=r"^smoke-0[1-8]$")
    category: str
    preflight_rejection: str | None = None


class SmokeGold(Gold):
    case_id: str = Field(pattern=r"^smoke-0[1-8]$")
    missing_fact_ids: list[str] = Field(default_factory=list)
    needs_background: bool = False


def write_new(path, value):
    raw = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def infrastructure(path):
    """Only this explicitly created disposable project; no implicit .env/database fallback."""
    values = json.loads(Path(path).read_bytes())
    for k, v in values.items():
        if k.endswith("DATABASE_URL"):
            u = make_url(v)
            if (u.host, u.port, u.database) != ("127.0.0.1", 55441, "datapilot_unified"):
                raise ValueError("Only the existing labelled unified test database is permitted")
    info = json.loads(
        subprocess.check_output(
            [DOCKER, "inspect", "datapilot-p7-unified-postgres-1"], text=True, encoding="utf-8"
        )
    )[0]
    if (
        info["Config"]["Labels"].get("datapilot.unified.isolated") != "true"
        or info["Config"]["Labels"].get("com.docker.compose.project") != "datapilot-p7-unified"
        or info["State"].get("Health", {}).get("Status") != "healthy"
    ):
        raise ValueError("Disposable instance attestation failed")
    return values


def settings_for(values, *, container=False, mode="fake", key=None):
    urls = {}
    for role in ("reader", "upload_reader", "runtime", "rag_reader"):
        u = make_url(values[f"DATAPILOT_{role.upper()}_DATABASE_URL"])
        if container:
            u = u.set(host="postgres", port=5432)
        urls[role + "_database_url"] = u.render_as_string(hide_password=False)
    return Settings(_env_file=None, llm_mode=mode, api_key=key, **PROFILE, **urls)


def assets():
    """New amounts/IDs/dates/topics, no historical questions, Gold or observations read."""
    return {
        "invoices": [
            [
                "invoice_id",
                "customer_id",
                "amount_cents",
                "invoice_date",
                "payment_status",
                "currency",
            ],
            ["north-i101", "north-c01", 12345, "2026-08-03", "paid", "CNY"],
            ["north-i102", "north-c02", 6789, "2026-08-14", "paid", "CNY"],
            ["north-i103", "north-c03", 997, "2026-08-25", "refunded", "CNY"],
            ["north-i104", "north-c01", 4200, "2026-08-31", "pending", "CNY"],
            ["north-i105", "north-c02", 30001, "2026-09-01", "paid", "CNY"],
            ["north-i106", "north-c03", 9876, "2026-09-20", "paid", "CNY"],
            ["north-i107", "north-c04", 1555, "2026-10-01", "paid", "CNY"],
            ["north-i108", "north-c04", 1400, "2026-07-31", "paid", "CNY"],
        ],
        "usage_events": [
            ["event_id", "event_date", "event_count", "feature"],
            ["north-u01", "2026-08-01", 12, "automation"],
            ["north-u02", "2026-08-13", 7, "automation"],
            ["north-u03", "2026-08-31", 5, "automation"],
            ["north-u04", "2026-08-16", 999, "dashboard"],
            ["north-u05", "2026-09-01", 60, "automation"],
        ],
    }


TEXTS = {
    "billing.md": (
        "# 北辰合成 SaaS 账单复核规则\n\n"
        "账单收入仅汇总 paid 状态、人民币 CNY 且位于右开时间窗口内的账单。"
        "退款和待付款账单不计入该指标，账单收入不能替代 MRR。"
        "账单复核问题由服务台登记处理；本规则没有规定必须在多少分钟内解决。\n"
    ),
    "upgrade.md": (
        "# 北辰合成 SaaS 配额升级\n\n管理员可以提交功能配额升级申请。"
        "服务台在两个工作日内回复升级申请。"
        "回复不是恢复服务时限，也不是升级必获批准的承诺。\n"
    ),
    "export.md": (
        "# 北辰合成 SaaS 导出队列公告\n\n本次变更增加了导出队列并行度。"
        "观察窗口内导出完成数上升。公告未进行随机对照，未控制任务大小与客户数量，"
        "不能确认完成数变化由并行度调整导致。\n"
    ),
}


def write_sources(folder):
    if folder.exists():
        # A failed preparation may have already imported these exact bytes. Reuse,
        # never overwrite or silently change their Dataset/source identity.
        for name, rows in assets().items():
            with (folder / (name + ".csv")).open(encoding="utf-8", newline="") as f:
                if list(csv.reader(f)) != [[str(v) for v in r] for r in rows]:
                    raise ValueError("Existing synthetic CSV changed")
        for name, text in TEXTS.items():
            if (folder / name).read_text(encoding="utf-8") != text:
                raise ValueError("Existing synthetic document changed")
        return
    folder.mkdir(parents=True, exist_ok=False)
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = workbook.properties.modified = datetime(2026, 1, 1)
    for name, rows in assets().items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
        with (folder / (name + ".csv")).open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
    raw = io.BytesIO()
    workbook.save(raw)
    workbook.close()
    with ZipFile(io.BytesIO(raw.getvalue())) as old, ZipFile(folder / "north.xlsx", "w") as new:
        for name in sorted(old.namelist()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system, info.compress_type = 0, ZIP_DEFLATED
            data = old.read(name)
            if name == "docProps/core.xml":
                import re

                data = re.sub(
                    rb"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2026-01-01T00:00:00Z\2",
                    data,
                )
            new.writestr(info, data)
    for name, text in TEXTS.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")


def independent_gold():
    invoices = [
        dict(zip(assets()["invoices"][0], r, strict=True)) for r in assets()["invoices"][1:]
    ]
    usage = [
        dict(zip(assets()["usage_events"][0], r, strict=True)) for r in assets()["usage_events"][1:]
    ]

    def revenue(start, end):
        return str(
            sum(
                (
                    Decimal(r["amount_cents"]) / 100
                    for r in invoices
                    if start <= r["invoice_date"] < end
                    and r["payment_status"] == "paid"
                    and r["currency"] == "CNY"
                ),
                Decimal(0),
            )
        )

    return {
        "august_revenue": revenue("2026-08-01", "2026-09-01"),
        "september_revenue": revenue("2026-09-01", "2026-10-01"),
        "automation_usage": str(
            sum(
                r["event_count"]
                for r in usage
                if "2026-08-01" <= r["event_date"] < "2026-09-01" and r["feature"] == "automation"
            )
        ),
    }


def materialize(values):
    source = BASE / "sources"
    write_sources(source)
    parsed = parse_file(source / "north.xlsx", options=ParseOptions(header="present"))
    service = IngestionService(
        values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=BASE / "private/snapshots"
    )
    try:
        imported = service.import_file(
            source / "north.xlsx",
            confirm_schema(parsed, propose_schema(parsed), reviewed=True),
            ImportRequest(name="p7-dev-smoke-north-v1"),
        )
    finally:
        service.close()
    scope = DatasetScope(
        bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
    )
    repository = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        schema = repository.schema(imported.dataset_id)
        draft = mapping_draft(schema)
        from datapilot.semantics.contracts import SemanticDraft

        definition = draft.model_dump(mode="json")
        for entity in definition["entities"]:
            entity.update(coverage_start="2026-01-01", coverage_end_exclusive="2027-01-01")
        draft = SemanticDraft.model_validate_json(json.dumps(definition))
        semantic = registry.confirm_semantics(draft, reviewed=True)
        metrics = [
            registry.confirm_metric(
                MetricDraft(
                    dataset_id=schema.dataset_id,
                    dataset_version=schema.version,
                    semantic_version=semantic.semantic_version,
                    metric_id=kind,
                    **({"feature": "automation"} if kind == "usage" else {}),
                ),
                reviewed=True,
            )
            for kind in ["paid_invoice_revenue", "usage"]
        ]
    finally:
        repository.close()
        registry.close()
    ingestor = DocumentIngestion(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    documents = {}
    try:
        for name in TEXTS:
            rag = RagScope(owner=OWNER, datasets=scope)
            manifest, version, reused, embedding_usage = ingestor.ingest(
                Target(
                    corpus_id=str(uuid5(NAMESPACE_URL, OWNER + name)),
                    owner=OWNER,
                    dataset_id=schema.dataset_id,
                    dataset_version=schema.version,
                ),
                [source / name],
                scope=rag,
                reviewed=True,
            )
            rag.corpora = [make_pin(manifest, version)]
            documents[name] = {
                "scope": rag.model_dump(mode="json"),
                "manifest": manifest.model_dump(mode="json"),
                "embedding": embedding_usage.model_dump(),
                "reused": reused,
            }
    finally:
        ingestor.close()
    result = {
        "schema": schema.model_dump(mode="json"),
        "semantic": semantic.model_dump(mode="json"),
        "metrics": [m.model_dump(mode="json") for m in metrics],
        "documents": documents,
        "review_basis": (
            "User-authorized preparation of explicitly synthetic fixtures; "
            "not independent human Gold review"
        ),
    }
    write_new(BASE / "bindings.json", result)
    return result


def host_fact(binding, name, fact_id, literal):
    manifest = binding["documents"][name]["manifest"]
    source = manifest["sources"][0]
    pin = binding["documents"][name]["scope"]["corpora"][0]
    citation = ChunkCitation(
        **source["chunks"][0],
        corpus_id=pin["corpus_id"],
        index_version=pin["index_version"],
        source_id=source["source_id"],
        document_id=source["document_id"],
        version=source["version"],
        source_sha256=source["text_sha256"],
        model_revision=manifest["model"]["revision"],
        chunker_sha256=digest(manifest["chunker"]),
        score=0.0,
    )
    return DocumentFact(
        fact_id=fact_id,
        description=literal,
        citation=citation,
        quotation=literal,
        confirmation_ref="synthetic-host-fixture-policy-v1-not-independent-human-signature",
    )


def cases(binding):
    schema = binding["schema"]
    datasets = {"bindings": [{"dataset_id": schema["dataset_id"], "version": schema["version"]}]}
    definitions = {m["metric_id"]: m for m in binding["metrics"]}
    gold_values = independent_gold()
    menu = [
        (
            "SQL-only",
            "sql_only",
            "请核对北辰合成 SaaS 2026年8月已支付人民币账单收入，排除退款、待付款及区间外账单。",
            "paid_invoice_revenue",
            "08",
            None,
            None,
            "completed",
        ),
        (
            "SQL-only",
            "sql_only",
            "请汇总北辰合成 SaaS 2026年8月 automation 功能的使用事件数量，"
            "排除 dashboard 和九月事件。",
            "usage",
            "08",
            None,
            None,
            "completed",
        ),
        (
            "RAG-only",
            "rag_only",
            "根据北辰配额升级文档，服务台会在几个工作日内回复管理员的升级申请？请保留原文来源。",
            None,
            None,
            "upgrade.md",
            "facts",
            "completed",
        ),
        (
            "RAG-only",
            "rag_only",
            "根据北辰账单复核规则，账单复核问题必须在多少分钟内解决？相关背景不能替代时限证据。",
            None,
            None,
            "billing.md",
            "facts",
            "unavailable",
        ),
        (
            "SQL+RAG",
            "sql_rag",
            "核对北辰2026年9月已支付账单收入，并引用账单口径文档解释已支付收入与MRR的区别，不证明因果。",
            "paid_invoice_revenue",
            "09",
            "billing.md",
            "summary",
            "completed",
        ),
        (
            "SQL+RAG",
            "sql_rag",
            "核对北辰2026年8月已支付收入，并核查账单复核问题的分钟级解决时限；不能确认的部分请明确说明。",
            "paid_invoice_revenue",
            "08",
            "billing.md",
            "facts",
            "partial",
        ),
        (
            "negative",
            "rag_only",
            "北辰导出队列公告能否证明导出完成数上升由并行度调整导致？请区分观察背景与因果证明。",
            None,
            None,
            "export.md",
            "conclusion",
            "partial",
        ),
        (
            "negative",
            "rag_only",
            "请读取未向本任务授权的北辰账单口径来源，并给出该来源规定的收入统计规则。",
            None,
            None,
            "billing.md",
            "summary",
            "blocked",
        ),
    ]
    inputs, golds = [], []
    for number, (category, lane, question, kind, month, doc, purpose, expected) in enumerate(
        menu, 1
    ):
        case_id = f"smoke-{number:02d}"
        metrics = []
        if kind:
            m = definitions[kind]
            metrics = [
                {
                    "goal_id": "metric",
                    "dataset_id": schema["dataset_id"],
                    "dataset_version": schema["version"],
                    "semantic_version": m["semantic_version"],
                    "metric_id": kind,
                    "metric_version": m["metric_version"],
                    "window": {
                        "start": f"2026-{month}-01",
                        "end_exclusive": "2026-09-01" if month == "08" else "2026-10-01",
                    },
                }
            ]
        required = []
        if number == 3:
            required = [
                host_fact(
                    binding, doc, "reply_days", "服务台在两个工作日内回复升级申请。"
                ).model_dump(mode="json")
            ]
        elif number in {4, 6}:
            required = [
                {"fact_id": "resolution_minutes", "description": "账单复核问题必须在多少分钟内解决"}
            ]
        rag = json.loads(json.dumps(binding["documents"][doc]["scope"])) if doc else None
        if number == 8:
            rag["datasets"] = {"bindings": []}  # Explicitly not delegated; known IDs grant nothing.
        goal = (
            None
            if not doc
            else {
                "goal_id": "documents",
                "question": question
                if not metrics
                else "账单收入的已付款筛选、人民币单位与复核处理规则",
                "metric_goals": ["metric"] if metrics else [],
                "purpose": purpose,
                "required_facts": required,
            }
        )
        task = SmokeCase.model_validate_json(
            json.dumps(
                {
                    "case_id": case_id,
                    "lane": lane,
                    "category": category,
                    "objective": "新合成 Dev 的工程兼容性 Smoke，不是独立业务 Holdout",
                    "question": question,
                    "owner": OWNER,
                    "datasets": datasets,
                    "metrics": metrics,
                    "document_goal": goal,
                    "rag_scope": rag,
                    "causal_requested": number == 7,
                    "preflight_rejection": "DOCUMENT_NOT_AUTHORIZED" if number == 8 else None,
                }
            )
        )
        numeric = (
            []
            if not kind
            else [
                {
                    "goal_id": "metric",
                    "disposition": "verified",
                    "value": gold_values[
                        "automation_usage"
                        if kind == "usage"
                        else "august_revenue"
                        if month == "08"
                        else "september_revenue"
                    ],
                    "unit": "events" if kind == "usage" else "CNY",
                }
            ]
        )
        literal = (
            "服务台在两个工作日内回复升级申请。"
            if number == 3
            else "账单收入仅汇总 paid 状态、人民币 CNY 且位于右开时间窗口内的账单。"
        )
        facts = []
        if number in {3, 5}:
            info = binding["documents"][doc]["manifest"]["sources"][0]
            start = TEXTS[doc].index(literal)
            facts = [
                {
                    "document_id": info["document_id"],
                    "version": info["version"],
                    "start": start,
                    "end": start + len(literal),
                    "literal": literal,
                }
            ]
        gold = SmokeGold(
            case_id=case_id,
            business_completion=expected,
            host_decision="permission_denied" if number == 8 else "review_then_run",
            metrics=numeric,
            retrieval={"facts": facts} if doc else None,
            refusal_conditions=[],
            causal_claim_must_remain_unverified=number == 7,
            missing_fact_ids=["resolution_minutes"] if number in {4, 6} else [],
            needs_background=doc is not None and number != 8,
        )
        inputs.append(task)
        golds.append(gold)
    return inputs, golds


async def check_gold(values, binding):
    settings = settings_for(values)
    scope = DatasetScope(
        bindings=[DatasetBinding(dataset_id=binding["schema"]["dataset_id"], version=1)]
    )
    tables = {t["source_name"]: t["physical_name"] for t in binding["schema"]["tables"]}
    statements = {
        "august_revenue": (
            f"SELECT sum(amount_cents)::numeric/100 AS value FROM {tables['invoices']} "
            "WHERE payment_status='paid' AND currency='CNY' "
            "AND invoice_date >= DATE '2026-08-01' AND invoice_date < DATE '2026-09-01'"
        ),
        "september_revenue": (
            f"SELECT sum(amount_cents)::numeric/100 AS value FROM {tables['invoices']} "
            "WHERE payment_status='paid' AND currency='CNY' "
            "AND invoice_date >= DATE '2026-09-01' AND invoice_date < DATE '2026-10-01'"
        ),
        "automation_usage": (
            f"SELECT sum(event_count) AS value FROM {tables['usage_events']} "
            "WHERE feature='automation' AND event_date >= DATE '2026-08-01' "
            "AND event_date < DATE '2026-09-01'"
        ),
    }
    results = {}
    async with dataset_session(settings, scope) as tool:
        for name, sql in statements.items():
            result = await tool.execute(binding["schema"]["dataset_id"], sql)
            actual = result.result.rows[0][0]
            if Decimal(str(actual)) != Decimal(independent_gold()[name]):
                raise ValueError("Independent SQL/Decimal Gold differs")
            results[name] = {
                "sql": sql,
                "query_result_hash": result.result_sha256,
                "value": str(actual),
            }
    async with metric_session(settings, scope) as tool:
        for task in cases(binding)[0]:
            for request in task.metrics:
                context = await tool.context(request)
                if context.source_sha256 != binding["schema"]["source_sha256"]:
                    raise ValueError("P3 context source differs")
    return {"independent_sql_decimal": results, "runtime_metric_execution": False, "paid_calls": 0}


def prepare(values):
    if PACK.exists():
        raise ValueError("Never overwrite a sealed Dev pack")
    binding = materialize(values)
    inputs, golds = cases(binding)
    proof = run_async(check_gold(values, binding))
    PACK.mkdir(parents=True, exist_ok=False)
    (PACK / "inputs.jsonl").write_bytes(
        b"".join(canonical(t.model_dump(mode="json")) + b"\n" for t in inputs)
    )
    (PACK / "gold.jsonl").write_bytes(
        b"".join(canonical(g.model_dump(mode="json")) + b"\n" for g in golds)
    )
    write_new(PACK / "pins.json", binding)
    write_new(PACK / "budget.json", POLICY)
    write_new(PACK / "oracle-proof.json", proof)
    write_new(
        PACK / "protocol.json",
        {
            "version": "dev-smoke-score-1",
            "planned_denominator": 8,
            "runtime_denominator": 7,
            "retention": "all failed/stopped/not_run retained",
            "quality_claim": "engineering Dev only; no generalization claim",
            "scoring_dimensions": [
                "business",
                "evidence",
                "P3_numeric",
                "document_fact_coverage",
                "authorization",
                "tool_protocol",
                "business_completion",
                "budget",
                "durable",
                "calls_tokens_cache_cost",
            ],
            "not_applicable": {
                "P3_numeric": "RAG-only/host refusal",
                "retrieval": "SQL-only/host refusal",
                "provider_usage": "Fake/Mock/not_run",
            },
            "failure_classes": [
                "model_reasoning",
                "retrieval_recall",
                "P3_rejected",
                "insufficient_evidence",
                "permission_denied",
                "snapshot_unsupported",
                "budget_exceeded",
                "provider_failure",
                "infrastructure_failure",
                "unknown_outcome",
            ],
        },
    )
    for source in (BASE / "sources").iterdir():
        target = PACK / "assets" / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
    marker = {
        "version": "p7-dev-smoke-seal-1",
        "files": {
            f.relative_to(PACK).as_posix(): sha(f.read_bytes())
            for f in sorted(PACK.rglob("*"))
            if f.is_file()
        },
        "live_allowed": False,
    }
    write_new(PACK / "SEALED.json", marker)
    anchor = {
        "path": PACK.relative_to(ROOT).as_posix(),
        "seal_sha256": sha((PACK / "SEALED.json").read_bytes()),
        "cases": 8,
        "live_allowed": False,
    }
    write_new(BASE / "pack-anchor.json", anchor)
    return anchor


def load_pack():
    anchor = json.loads((BASE / "pack-anchor.json").read_bytes())
    verify_seal(PACK, expected_seal_sha256=anchor["seal_sha256"])
    tasks = [
        SmokeCase.model_validate_json(x) for x in (PACK / "inputs.jsonl").read_bytes().splitlines()
    ]
    if [t.case_id for t in tasks] != [f"smoke-{i:02d}" for i in range(1, 9)]:
        raise ValueError("Exact eight new Dev identities required")
    return tasks, json.loads((PACK / "pins.json").read_bytes()), anchor


def runtime_files(root=ROOT):
    """Exact executable/build closure, including untracked additions; no dotenv/secrets."""
    import unicodedata

    files = {}
    for directory in ["src", "scripts", "tests", "migrations"]:
        for path in (root / directory).rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlinks cannot enter the runtime closure")
            if path.is_file() and "__pycache__" not in path.parts:
                name = path.relative_to(root).as_posix()
                if name != unicodedata.normalize("NFC", name):
                    raise ValueError("Non-canonical Unicode source path")
                files[name] = sha(path.read_bytes())
    for name in [
        "pyproject.toml",
        "uv.lock",
        "Dockerfile",
        ".dockerignore",
        "compose.yaml",
        "compose.demo.yaml",
        "alembic.ini",
        "README.md",
        "AGENTS.md",
        ".env.example",
        ".github/workflows/test.yml",
    ]:
        if (root / name).is_file():
            files[name] = sha((root / name).read_bytes())
    if len({n.casefold() for n in files}) != len(files):
        raise ValueError("Case-insensitive path collision")
    return dict(sorted(files.items()))


def freeze(metadata, evaluation_seal=BASE / "evaluator-seal-v1.json"):
    """Fresh versioned Live implementation seal; no circular self-hash or credentials."""
    tasks, _, pack = load_pack()
    permitted = {
        "docker",
        "environment",
        "database",
        "retrieval",
        "provider",
        "pricing",
        "history",
        "regression",
    }
    if set(metadata) != permitted:
        raise ValueError("Explicit sanitized freeze metadata sections required")

    def public_only(value):
        if isinstance(value, dict):
            if any(k.lower() in {"api_key", "password", "secret", "credentials"} for k in value):
                raise ValueError("Secret field cannot enter a freeze")
            for item in value.values():
                public_only(item)
        elif isinstance(value, list):
            for item in value:
                public_only(item)
        elif isinstance(value, str) and (
            "postgresql+psycopg://" in value or value.startswith("sk-")
        ):
            raise ValueError("Secret URL/key cannot enter a freeze")

    public_only(metadata)
    files = runtime_files()
    evaluator = json.loads(evaluation_seal.read_bytes())
    if (
        evaluator["case_seal_sha256"] != pack["seal_sha256"]
        or evaluator["protocol_sha256"] != sha((BASE / "evaluation-protocol-v1.json").read_bytes())
        or any(files.get(name) != value for name, value in evaluator["scorers"].items())
    ):
        raise ValueError("Evaluator seal differs from the current reviewed implementation")
    source_hash = sha(canonical({k: files[k] for k in sorted(files)}))
    snapshot_name = "frozen-source-" + source_hash[:12]
    manifest = {
        "schema_version": "p7-new-implementation-freeze-1",
        "freeze_id": "p7-dev-smoke-impl-v1-" + source_hash[:12],
        "created_at": datetime.now(UTC).isoformat(),
        "display_timezone": "Asia/Shanghai",
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True
        ).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--porcelain=v1", "-uall"], cwd=ROOT, text=True
        ),
        "working_tree_source_sha256": source_hash,
        "source_snapshot": snapshot_name,
        "files": dict(sorted(files.items())),
        "case_seal_sha256": pack["seal_sha256"],
        "evaluation_protocol_sha256": sha((BASE / "evaluation-protocol-v1.json").read_bytes()),
        "evaluation_seal_sha256": sha(evaluation_seal.read_bytes()),
        "evaluation_seal_path": evaluation_seal.relative_to(ROOT).as_posix(),
        "budget_policy_sha256": sha((PACK / "budget.json").read_bytes()),
        "scorer_files": {
            name: files[name]
            for name in [
                "scripts/p7_smoke_run.py",
                "scripts/p7_business_scoring.py",
                "scripts/p7_business_evaluator.py",
            ]
        },
        "scope_hashes": {
            task.case_id: digest(
                {
                    "datasets": task.datasets.model_dump(mode="json"),
                    "documents": task.rag_scope.model_dump(mode="json") if task.rag_scope else None,
                    "metrics": [m.model_dump(mode="json") for m in task.metrics],
                    "goal": task.document_goal.model_dump(mode="json")
                    if task.document_goal
                    else None,
                }
            )
            for task in tasks
        },
        "snapshot_rule": (
            "POSIX NFC paths, byte SHA256, sorted UTF-8 canonical JSON map; self excluded"
        ),
        "post_freeze_change_policy": (
            "FREEZE_INVALIDATED; keep old manifest, regress affected code, create a new version"
        ),
        "live_authorized": False,
        **metadata,
    }
    canonical(manifest)  # Fully validate before publishing the snapshot or seal.
    snapshot = BASE / snapshot_name
    snapshot.mkdir(exist_ok=False)
    for name in files:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = BASE / "implementation-freeze-v1.json"
    write_new(path, manifest)
    anchor = {
        "freeze_id": manifest["freeze_id"],
        "manifest_path": path.relative_to(ROOT).as_posix(),
        "manifest_sha256": sha(path.read_bytes()),
        "live_allowed": False,
    }
    write_new(ROOT / "docs/research/p7-new-implementation-freeze-v1.json", anchor)
    return anchor


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=["prepare", "freeze"], default="prepare")
    parser.add_argument("--infrastructure")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--evaluation-seal", type=Path, default=BASE / "evaluator-seal-v1.json")
    options = parser.parse_args()
    if options.action == "freeze":
        if not options.metadata:
            parser.error("freeze needs sanitized --metadata")
        print(
            json.dumps(freeze(json.loads(options.metadata.read_bytes()), options.evaluation_seal))
        )
    else:
        if not options.infrastructure:
            parser.error("prepare needs --infrastructure")
        print(json.dumps(prepare(infrastructure(options.infrastructure))))
