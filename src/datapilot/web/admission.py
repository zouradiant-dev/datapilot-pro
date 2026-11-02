"""Opt-in one-shot Web smoke admission.

The permit is loaded only from the private host policy file by the trusted process.
It is HMAC-signed with an operator-held key from the environment; browser arguments,
model output and arbitrary request paths cannot grant authority. Case rows live in
the existing Web database so restart/retry cannot reset consumption.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from datapilot.ingestion.common import digest
from datapilot.web.config import HostPolicy
from datapilot.web.store import deny, execute

KIND = "datapilot-web-smoke-admission-1"
MAX_BYTES = 64 * 1024


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def signed_payload(permit: dict) -> bytes:
    body = {k: v for k, v in permit.items() if k != "signature"}
    return canonical(body)


def permit_digest(permit: dict) -> str:
    return hashlib.sha256(canonical(permit)).hexdigest()


def _hex(value) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


class AdmissionGate:
    def __init__(self, policy: HostPolicy, store, settings):
        self.policy = policy
        self.store = store
        self.settings = settings
        self.enabled = policy.smoke_admission_file is not None

    def update_settings(self, settings):
        self.settings = settings

    def validate(self):
        self._load()

    def _load(self):
        if not self.enabled:
            return None, None
        path = Path(self.policy.smoke_admission_file)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            deny("SMOKE_ADMISSION_MISSING", "Smoke admission permit is unavailable")
        try:
            permit = json.loads(path.read_bytes())
        except (ValueError, OSError):
            deny("SMOKE_ADMISSION_INVALID", "Smoke admission permit is invalid")
        if not isinstance(permit, dict) or not _hex(permit.get("signature")):
            deny("SMOKE_ADMISSION_SIGNATURE", "Smoke admission permit is not signed")
        key = os.environ.get(self.policy.smoke_admission_key_env, "")
        if len(key) < 32:
            deny("SMOKE_ADMISSION_KEY", "Smoke admission key is unavailable")
        expected = hmac.new(key.encode(), signed_payload(permit), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(permit["signature"], expected):
            deny("SMOKE_ADMISSION_SIGNATURE", "Smoke admission signature is invalid")
        self._validate(permit)
        return permit, permit_digest(permit)

    def _validate(self, permit):
        if (
            permit.get("kind") != KIND
            or permit.get("authorized") is not True
            or permit.get("approved_by_role") != "project_owner"
            or not isinstance(permit.get("source_user_authorization_ref"), str)
            or not permit["source_user_authorization_ref"].strip()
            or permit.get("revoked") is True
        ):
            deny("SMOKE_ADMISSION_INVALID", "Smoke admission is not an owner-approved permit")
        if permit.get("owner") != self.policy.owner:
            deny("SMOKE_ADMISSION_OWNER", "Smoke admission belongs to another owner")
        if permit.get("host_settings_hash") != self.store.host_settings_hash(self.settings):
            deny("SMOKE_ADMISSION_CONFIG", "Smoke admission host configuration changed")
        if self.policy.max_workers != 1 or self.settings.max_parallel_workers != 1:
            deny(
                "SMOKE_ADMISSION_CONCURRENCY",
                "Smoke admission requires serial Run and Worker execution",
            )
        if (permit.get("provider"), permit.get("model"), permit.get("thinking")) != (
            "deepseek",
            "deepseek-flash",
            "disabled",
        ):
            deny("SMOKE_ADMISSION_MODEL", "Smoke admission model is not the approved profile")
        if not _hex(permit.get("freeze_sha256")):
            deny("SMOKE_ADMISSION_FREEZE", "Smoke admission freeze is missing")
        try:
            approved = datetime.fromisoformat(permit["approved_at"])
            expires = datetime.fromisoformat(permit["expires_at"])
        except (KeyError, TypeError, ValueError):
            deny("SMOKE_ADMISSION_TIME", "Smoke admission validity is missing")
        if approved.tzinfo is None or expires.tzinfo is None or expires <= datetime.now(UTC):
            deny("SMOKE_ADMISSION_EXPIRED", "Smoke admission has expired")
        if approved > datetime.now(UTC):
            deny("SMOKE_ADMISSION_TIME", "Smoke admission approval is from the future")
        if expires <= approved:
            deny("SMOKE_ADMISSION_TIME", "Smoke admission validity is invalid")
        stop = permit.get("stop_file")
        if stop and Path(stop).exists():
            deny("SMOKE_STOPPED", "Smoke admission stop file exists")
        if (
            permit.get("max_runs") != 3
            or permit.get("calls_per_run") != 8
            or permit.get("tokens_per_run") != 18000
            or permit.get("campaign_calls") != 24
            or permit.get("campaign_token_units") != 54000
            or permit.get("concurrency") != 1
            or permit.get("automatic_retries") != 0
            or permit.get("max_output_tokens") != 1200
            or permit.get("task_timeout_seconds") != 180
            or permit.get("campaign_timeout_seconds") != 1800
        ):
            deny("SMOKE_ADMISSION_BUDGET", "Smoke admission budget is not the approved budget")
        cases = permit.get("cases")
        if not isinstance(cases, list) or len(cases) != 3:
            deny("SMOKE_ADMISSION_CASES", "Smoke admission must bind exactly three cases")
        if len({c.get("case_id") for c in cases if isinstance(c, dict)}) != 3:
            deny("SMOKE_ADMISSION_CASES", "Smoke admission cases are not unique")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
                deny("SMOKE_ADMISSION_CASES", "Smoke admission case is malformed")
            if not _hex(case.get("question_sha256")):
                deny("SMOKE_ADMISSION_CASES", "Smoke admission case question is malformed")

    def _payload_binding(self, payload):
        report = payload.get("report_scope") or {}
        rag = payload.get("rag_scope") or {}
        docs = report.get("document_goal")
        metrics = report.get("metrics") or []
        corpora = rag.get("corpora") or []
        return {
            "question_sha256": digest(payload["question"]),
            "metrics": [
                {
                    k: m.get(k)
                    for k in (
                        "goal_id",
                        "dataset_id",
                        "dataset_version",
                        "semantic_version",
                        "metric_id",
                        "metric_version",
                        "window",
                    )
                }
                for m in metrics
            ],
            "corpora": [
                {
                    "corpus_id": c.get("corpus_id"),
                    "index_version": c.get("index_version"),
                    "document_ids": sorted(c.get("document_ids") or []),
                }
                for c in corpora
            ],
            "document_goal": None
            if not docs
            else {
                "question": docs.get("question"),
                "purpose": docs.get("purpose"),
                "required_facts": [
                    {"fact_id": f["fact_id"], "description": f["description"]}
                    for f in docs.get("required_facts") or []
                ],
            },
            "causal_requested": report.get("causal_requested", False),
            "partial_evidence_policy": report.get("partial_evidence_policy", "legacy"),
            "citation_policy": report.get("citation_policy"),
            "rag_query_policy": report.get("rag_query_policy", "legacy"),
            "rag_policy": {
                "min_score": rag.get("min_score"),
                "allow_saas": rag.get("allow_saas", False),
                "embedding_profile": rag.get("embedding_profile"),
            },
        }

    def _matches(self, case, binding):
        expected = case
        if expected.get("question_sha256") != binding["question_sha256"]:
            return False
        if len(expected.get("metrics") or []) != len(binding["metrics"]):
            return False
        for left, right in zip(expected.get("metrics") or [], binding["metrics"], strict=True):
            if {k: left.get(k) for k in right} != right:
                return False
        if len(expected.get("corpora") or []) != len(binding["corpora"]):
            return False
        for left, right in zip(expected.get("corpora") or [], binding["corpora"], strict=True):
            if {
                "corpus_id": left.get("corpus_id"),
                "index_version": left.get("index_version"),
                "document_ids": sorted(left.get("document_ids") or []),
            } != right:
                return False
        if expected.get("document_goal") != binding["document_goal"]:
            return False
        for key in (
            "causal_requested",
            "partial_evidence_policy",
            "citation_policy",
            "rag_query_policy",
            "rag_policy",
        ):
            if expected.get(key) != binding[key]:
                return False
        return True

    def match_case(self, payload):
        permit, sha = self._load()
        if permit is None:
            return None, None, None
        binding = self._payload_binding(payload)
        for case in permit["cases"]:
            if self._matches(case, binding):
                return case, permit, sha
        deny("SMOKE_NOT_ADMITTED", "This Web request is not one of the admitted smoke cases")
        return None, None, None

    def reserve(self, conn, payload, message_id, goal_contract_sha256=None):
        """Reserve one case inside the caller's transaction; return existing run on retry."""
        if not self.enabled:
            return None, None, None
        case, permit, sha = self.match_case(payload)
        execute(
            conn,
            "SELECT pg_advisory_xact_lock(hashtextextended(:k,6170))",
            k=self.policy.owner + ":smoke:" + case["case_id"],
        )
        request_sha = digest(payload)
        row = (
            execute(
                conn,
                "SELECT * FROM execution.web_smoke_admissions "
                "WHERE owner=:o AND case_id=:c FOR UPDATE",
                o=self.policy.owner,
                c=case["case_id"],
            )
            .mappings()
            .one_or_none()
        )
        if row:
            if row["run_id"] is None:
                deny("SMOKE_CASE_IN_FLIGHT", "Smoke case admission is already in progress")
            if row["request_sha256"] == request_sha and row["message_id"] == message_id:
                return row["run_id"], case, sha
            deny("SMOKE_CASE_CONSUMED", "This admitted smoke case already has a Run")
        execute(
            conn,
            "INSERT INTO execution.web_smoke_admissions "
            "(owner,case_id,permit_sha256,freeze_sha256,request_sha256,message_id,"
            "goal_contract_sha256,binding,expires_at) "
            "VALUES (:o,:c,:p,:f,:r,:m,:g,CAST(:b AS jsonb),:e)",
            o=self.policy.owner,
            c=case["case_id"],
            p=sha,
            f=permit["freeze_sha256"],
            r=request_sha,
            m=message_id,
            g=goal_contract_sha256,
            b=json.dumps(case, ensure_ascii=False),
            e=datetime.fromisoformat(permit["expires_at"]),
        )
        return None, case, sha

    def attach(self, conn, case_id, run_id):
        if not self.enabled:
            return
        changed = execute(
            conn,
            "UPDATE execution.web_smoke_admissions SET run_id=:r "
            "WHERE owner=:o AND case_id=:c AND run_id IS NULL",
            r=run_id,
            o=self.policy.owner,
            c=case_id,
        ).rowcount
        if changed != 1:
            deny("SMOKE_ADMISSION_RACE", "Smoke admission Run binding is not unique")

    def check_run(self, run_id):
        if not self.enabled:
            return
        permit, sha = self._load()
        with self.store.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_smoke_admissions WHERE owner=:o AND run_id=:r",
                    o=self.policy.owner,
                    r=run_id,
                )
                .mappings()
                .one_or_none()
            )
            campaign_start = execute(
                conn,
                "SELECT min(admitted_at) FROM execution.web_smoke_admissions "
                "WHERE owner=:o AND permit_sha256=:p",
                o=self.policy.owner,
                p=sha,
            ).scalar_one_or_none()
        if not row:
            deny("SMOKE_NOT_ADMITTED", "This Run has no smoke admission")
        if row["permit_sha256"] != sha:
            deny("SMOKE_AUTHORIZATION_CHANGED", "Smoke admission was replaced or revoked")
        if row["freeze_sha256"] != permit["freeze_sha256"]:
            deny("SMOKE_AUTHORIZATION_CHANGED", "Smoke admission freeze changed")
        admitted = campaign_start or row["admitted_at"]
        if admitted.tzinfo is None:
            deny("SMOKE_CAMPAIGN_TIMEOUT", "Smoke admission time is invalid")
        if (datetime.now(UTC) - admitted).total_seconds() > permit["campaign_timeout_seconds"]:
            deny("SMOKE_CAMPAIGN_TIMEOUT", "Smoke campaign time bound is exhausted")
