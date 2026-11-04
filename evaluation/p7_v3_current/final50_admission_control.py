"""Execute the three Final 50 follow-ups under a separate admission binding."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from final50_admission import CASE_IDS, isolated_reader, load_drafts, preflight, score_admission
from p7_business_runtime import collect
from p7_business_scoring import sign_collection
from report_recovery_probe import ReportDecisions

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.parsing import decode
from datapilot.reporting.contracts import DocumentFact, ReportScope, confirm_finite_scope

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = "p7-final50-admission-017-064-077-v1"
DIAGNOSTIC_CAMPAIGN = "p7-final50-admission-064-diagnostic-v1"
FOLLOWUP_CAMPAIGN = "p7-final50-admission-077-followup-v1"
PROFILE = {
    "model_provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "max_model_calls": 8,
    "max_total_tokens": 18000,
    "max_output_tokens": 1200,
    "max_worker_turns": 4,
    "max_parallel_workers": 1,
}


def authorize(permit, binding):
    if (
        permit.get("authorized") is not True
        or permit.get("campaign_id") != binding["campaign_id"]
        or permit.get("binding_sha256") != digest(binding)
        or permit.get("approved_by_role") != "project_owner"
        or not isinstance(permit.get("approval_ref"), str)
        or not permit["approval_ref"].strip()
    ):
        raise ValueError("Owner permit must authorize this exact admission binding")
    expiry = datetime.fromisoformat(permit["expires_at"])
    if expiry.tzinfo is None or expiry <= datetime.now(UTC):
        raise ValueError("Permit expired or has no timezone")


def write(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def confirm_document(draft, scope, case, bindings, sources):
    proof = draft["document_pin_evidence"]
    corpus = bindings["corpora"]["operations"]["manifest"]
    (source,) = (s for s in corpus["sources"] if s["document_id"] == proof["document_id"])
    original = ROOT / draft["original_input_path"]
    (raw,) = (
        line
        for line in original.read_bytes().splitlines()
        if hashlib.sha256(line).hexdigest() == draft["original_input_sha256"]
    )
    original_case = json.loads(raw)
    if original_case["case_id"] != draft["original_case_id"]:
        raise ValueError("Wrong original contract")
    (previous,) = original_case["document_goal"]["required_facts"]
    (current,) = scope.document_goal.required_facts
    text = decode((sources / "operations" / source["name"]).read_bytes())
    quotation = previous["quotation"]
    chunk = proof["chunk"]
    if (
        previous["fact_id"] != current.fact_id
        or previous["description"] != current.description
        or hashlib.sha256(text.encode()).hexdigest() != previous["citation"]["source_sha256"]
        or text.count(quotation) != 1
        or quotation not in text[chunk["start"] : chunk["end"]]
    ):
        raise ValueError("Original fact proof cannot be reproduced")
    ref = "codex-host-review-final50-admit-077-20261104"
    if draft.get("revision"):
        ref += "-" + digest(scope)[:12]
    fact = DocumentFact.model_validate(
        {
            **current.model_dump(),
            "quotation": quotation,
            "confirmation_ref": ref,
            "citation": {
                **chunk,
                "corpus_id": proof["corpus_id"],
                "index_version": proof["index_version"],
                "document_id": source["document_id"],
                "source_id": source["source_id"],
                "version": source["version"],
                "source_sha256": source["text_sha256"],
                "model_revision": corpus["model"]["revision"],
                "chunker_sha256": digest(corpus["chunker"]),
                "score": 0.0,
            },
        }
    )
    data = scope.model_dump(mode="json")
    data["document_goal"]["required_facts"] = [fact.model_dump(mode="json")]
    reviewed = ReportScope.model_validate_json(json.dumps(data))
    return confirm_finite_scope(reviewed, case.rag_scope, confirmation_ref=ref)


def worker(config, bound_sha, settings, scope, rag, action, *, live=False, loop_runner=None):
    if (
        settings.llm_mode != ("live" if live else "fake")
        or bool(settings.api_key) != live
        or digest(config) != bound_sha
        or config["report_scope"] != scope.model_dump(mode="json")
        or config["rag_scope"] != (rag.model_dump(mode="json") if rag else None)
    ):
        raise ValueError("Worker execution binding mismatch")
    execute_async = loop_runner.run if loop_runner is not None else run_async
    if action == "collect":
        return execute_async(collect(config, settings, scope, rag))
    return execute_async(
        run_durable(
            settings,
            config["run_id"],
            scope.question,
            owner=scope.owner,
            resume=action == "approve",
            approve=True if action == "approve" else None,
            require_review=True,
            report_scope=scope,
            rag_scope=rag,
            transport=None
            if live
            else ReportDecisions(scope.document_goal.question if rag else ""),
        )
    )


def run(
    pack,
    base,
    out,
    collected_from=None,
    case_id=None,
    *,
    prepare=False,
    permit=None,
    diagnostic_064=False,
    followup_077=False,
):
    import current_binding
    import p7_business_evaluator
    import p7_business_scoring
    from v3_oracle import answer as source_answer

    formal = prepare or permit is not None
    if diagnostic_064 and followup_077:
        raise ValueError("Select only one single-case campaign")
    single_case = diagnostic_064 or followup_077
    if single_case:
        if case_id or collected_from:
            raise ValueError("Single-case admission requires its new execution identity")
        case_id = "p7-final50-admit-064" if diagnostic_064 else "p7-final50-admit-077"
    if formal and (collected_from or (case_id and not single_case)):
        raise ValueError("Select the fixed three-case or explicit single-case campaign")
    campaign = CAMPAIGN
    if diagnostic_064:
        campaign = DIAGNOSTIC_CAMPAIGN
    elif followup_077:
        campaign = FOLLOWUP_CAMPAIGN
    env = json.loads((base / "private/pg/environment.json").read_text(encoding="utf-8"))
    checks = preflight(pack, env, case_id=case_id)
    database_settings = {
        f"{role.lower()}_database_url": isolated_reader(env, role)
        for role in ("READER", "UPLOAD_READER", "RAG_READER", "RUNTIME")
    }
    settings = Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        max_parallel_workers=1,
        **database_settings,
    )
    os.environ["DATAPILOT_REGISTRY_DATABASE_URL"] = isolated_reader(env, "REGISTRY")
    bindings = json.loads((base / "bindings.json").read_text(encoding="utf-8"))
    prepared = []
    for draft, scope, case, gold, evidence in load_drafts(pack):
        cid = case.case_id
        if case_id and cid != case_id:
            continue
        alias = "future" if cid.endswith("017") else "master"
        period = "march" if cid.endswith("064") else "feb"
        for req, row in zip(scope.metrics, evidence, strict=True):
            expected = source_answer(alias, req.metric_id, req.metric_version, period)
            if expected != row["decimal_oracle"]:
                raise ValueError("Gold differs from independent Decimal oracle")
        if case.rag_scope:
            scope = confirm_document(draft, scope, case, bindings, base / "sources")
            case = case.model_copy(update={"document_goal": scope.document_goal})
            proof = draft["document_pin_evidence"]
            gold = gold.model_copy(
                update={
                    "retrieval": {
                        "relevant_document_ids": [proof["document_id"]],
                        "relevant_chunk_ids": [proof["chunk"]["chunk_id"]],
                    }
                }
            )
        config = {
            "case_id": cid,
            "run_id": str(uuid5(NAMESPACE_URL, campaign + "/" + cid) if formal else uuid4()),
            "owner": scope.owner,
            "question_sha256": digest(scope.question),
            "report_scope": scope.model_dump(mode="json"),
            "rag_scope": case.rag_scope.model_dump(mode="json") if case.rag_scope else None,
        }
        pins = {
            "datasets": {
                alias: {
                    "schema": {
                        "dataset_id": scope.metrics[0].dataset_id,
                        "version": scope.metrics[0].dataset_version,
                        "source_sha256": evidence[0]["source_sha256"],
                    },
                    "semantics": {"definition_sha256": evidence[0]["semantic_sha256"]},
                    "metrics": [
                        {
                            "metric_id": req.metric_id,
                            "metric_version": req.metric_version,
                            "definition_sha256": row["metric_sha256"],
                        }
                        for req, row in zip(scope.metrics, evidence, strict=True)
                    ],
                }
            }
        }
        if collected_from:
            prior = json.loads((collected_from / cid / "config.json").read_bytes())
            config["run_id"] = prior["run_id"]
            if config != prior:
                raise ValueError("Offline replay requires the identical Worker contract")
        prepared.append((config, scope, case, gold, pins))
    hashes = {cfg["case_id"]: digest(cfg) for cfg, *_ in prepared}
    binding = {
        "mode": "live" if formal else "fake",
        "preflight": checks,
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": [
            {
                "case_id": cfg["case_id"],
                "config_sha256": hashes[cfg["case_id"]],
                "gold_sha256": digest(gold),
                "pins_sha256": digest(pins),
            }
            for cfg, _, _, gold, pins in prepared
        ],
    }
    if formal:
        closure = current_binding.load_manifest()
        evaluation_files = {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                ROOT / "evaluation/p7_v3_current/final50_admission.py",
                *(ROOT / path for path in closure["evaluation_files"]),
                ROOT / "scripts/p7_business_evaluator.py",
                ROOT / "scripts/p7_business_scoring.py",
                ROOT / "evaluation/p7_v3/v3_score.py",
            )
        }
        source_files = closure["files"]
        if single_case:
            # Preserve the historical freeze. The new native-process binding records
            # current raw and LF bytes and permits only the authorized diagnostic edit.
            source_files = {}
            for name, previous in closure["files"].items():
                raw = (ROOT / name).read_bytes()
                lf_sha256 = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
                if (
                    lf_sha256 != previous["lf_sha256"]
                    and name != "src/datapilot/orchestration/model.py"
                ):
                    raise ValueError("Unexpected source change: " + name)
                source_files[name] = {
                    "lf_sha256": lf_sha256,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                }
        else:
            current_binding.verify_manifest(
                ROOT,
                ROOT / closure["source_snapshot"],
                {**closure, "evaluation_files": evaluation_files},
            )
        binding.update(
            campaign_id=campaign,
            profile=PROFILE,
            provider_attempts=8 * len(prepared),
            token_units=18000 * len(prepared),
            source_manifest_sha256=digest(source_files),
            source_files=source_files,
            evaluation_files=evaluation_files,
        )
    if permit is not None:
        authorize(permit, binding)
        if (pack / "STOP").exists():
            raise ValueError("Campaign STOP is present")
        settings = Settings(_env_file=None, llm_mode="live", **PROFILE, **database_settings)
        if out.exists():
            raise ValueError("Execution output already exists")
        claims = base / "dispatch-claims"
        claims.mkdir(exist_ok=True)
        (claims / (campaign + ".claimed")).mkdir()
    out.mkdir()
    write(out / "binding.json", binding)
    if prepare:
        write(out / "launch-configs.json", [config for config, *_ in prepared])
        write(
            out / "permit-template.json",
            {
                "authorized": False,
                "campaign_id": campaign,
                "binding_sha256": digest(binding),
                "approved_by_role": "project_owner",
                "approval_ref": None,
                "expires_at": None,
            },
        )
        return
    # SDK HTTP clients are cached by endpoint, so all native async calls in this
    # process must share the loop that owns their pooled connections.
    with asyncio.Runner(
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
    ) as loop_runner:
        results = []
        paid_calls = 0
        for config, scope, case, gold, pins in prepared:
            path = out / case.case_id
            path.mkdir()
            write(path / "config.json", config)
            write(path / "reviewed-gold.json", gold.model_dump(mode="json"))
            bound = hashes[case.case_id]
            if not collected_from:
                if permit is not None:
                    authorize(permit, binding)
                    if (pack / "STOP").exists():
                        raise ValueError("Campaign STOP is present")
                worker(
                    config,
                    bound,
                    settings,
                    scope,
                    case.rag_scope,
                    "start",
                    live=permit is not None,
                    loop_runner=loop_runner,
                )
                if permit is not None:
                    authorize(permit, binding)
                    if (pack / "STOP").exists():
                        raise ValueError("Campaign STOP is present")
                worker(
                    config,
                    bound,
                    settings,
                    scope,
                    case.rag_scope,
                    "approve",
                    live=permit is not None,
                    loop_runner=loop_runner,
                )
            collected = worker(
                config,
                bound,
                settings,
                scope,
                case.rag_scope,
                "collect",
                live=permit is not None,
                loop_runner=loop_runner,
            )
            write(path / "collection.json", collected)
            snapshot = collected["snapshot"]
            if permit is not None and (
                snapshot["unknown"] or not snapshot["usage"]["usage_complete"]
            ):
                raise ValueError("Uncertain outcome or incomplete usage. Campaign stopped")
            if permit is not None:
                paid_calls += snapshot["usage"]["calls"]
            key = secrets.token_bytes(32)
            recorded_scope = collected["manifest"]["cross_source_report"]["scope"]
            if digest(recorded_scope) != digest(scope):
                raise ValueError("Collection differs from the complete admission scope")

            # The existing scorer reconstructs a legacy scope without policy or attestation.
            # Supply the complete bound scope for its identity check on this control only.
            def bound_goal(question, scope=scope, rag_scope=case.rag_scope):
                if not rag_scope or question != scope.document_goal.question:
                    raise ValueError("Unexpected retrieval goal in admission score")
                return retrieval_goal(question, SimpleNamespace(scope=rag_scope), scope)

            with (
                patch.object(p7_business_scoring, "ReportScope", return_value=scope),
                patch.object(p7_business_evaluator, "retrieval_goal", bound_goal),
            ):
                scored = score_admission(case, gold, sign_collection(collected, key), key, pins)
            write(path / "score.json", scored)
            results.append(
                {
                    "case_id": case.case_id,
                    "run_id": config["run_id"],
                    "strict_correct": scored["strict_correct"],
                    "failure_class": scored.get("failure_class"),
                }
            )
            print(results[-1], flush=True)
        write(
            out / "summary.json",
            {
                "mode": "live" if permit is not None else "fake",
                "paid_calls": paid_calls,
                "results": results,
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--collected-from", type=Path)
    parser.add_argument("--case-id", choices=sorted(CASE_IDS))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-live", action="store_true")
    mode.add_argument("--permit", type=Path)
    single = parser.add_mutually_exclusive_group()
    single.add_argument("--diagnostic-064", action="store_true")
    single.add_argument("--followup-077", action="store_true")
    args = parser.parse_args()
    run(
        args.pack,
        args.base,
        args.out,
        args.collected_from,
        args.case_id,
        prepare=args.prepare_live,
        permit=json.loads(args.permit.read_bytes()) if args.permit else None,
        diagnostic_064=args.diagnostic_064,
        followup_077=args.followup_077,
    )
