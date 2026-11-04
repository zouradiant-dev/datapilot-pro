"""Formal 50-case CLI: manifest -> host preflight -> Runtime -> Collector -> Scorer."""

import argparse
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_v3"))
import current_binding
from container_adapter import run as container_run
from current_worker import permit_valid as worker_permit_valid
from p7_business_scoring import sign_collection
from scorer import score
from v3_common import Answer, Case
from v3_gate import ordinary_failure_may_continue
from v3_probe import ProbeAnswer as ProbeAnswer
from v3_probe import ProbeCase as ProbeCase

from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.rag.contracts import IndexManifest  # noqa: E402
from datapilot.reporting.contracts import RagScope, ReportScope  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_manifest(manifest, configs, *, case_count=None):
    cases = manifest.get("preflight") or manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != (case_count or manifest.get("planned", 50)):
        raise ValueError("manifest case count mismatch")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    cfg = {c["case_id"]: c for c in configs}
    if set(cfg) != set(ids):
        raise ValueError("config/case identity mismatch")
    return cases, cfg


def run_dev(dev, out):
    current_binding.verify_current()
    case = ProbeCase.model_validate_json(__import__("json").dumps(dev["case"]))
    gold = ProbeAnswer.model_validate_json(__import__("json").dumps(dev["gold"]))
    cfg = dev["config"]
    pins = dev["pins"]
    key = secrets.token_bytes(32)
    out.mkdir(parents=True, exist_ok=False)
    folder = out / "case"
    folder.mkdir()
    cfg = dict(cfg)
    cfg["run_id"] = cfg.get("run_id") or "formal-dev-" + secrets.token_hex(8)
    (folder / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    values = load(ROOT / "artifacts/p7/current-pg/private/environment.json")
    product = {
        "docker": {"image_id": "datapilot-current:local"},
        "source_snapshot": str(
            (ROOT / "artifacts/p7/final-evaluation-v1/current-source-snapshot").resolve()
        ),
    }
    deadline = time.monotonic() + 300
    actions = []
    for action in ["probe", "start", "approve", "collect"]:
        payload = container_run(cfg, folder, "fake", action, values, product, deadline)
        actions.append(action)
        if action == "collect":
            collection = payload
    signed = sign_collection(collection, key)
    (folder / "signed-collection.json").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = score(case, gold, signed, key, pins)
    (folder / "score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "schema": "formal-runner-dev-summary/v1",
        "mode": "fake_toy",
        "case_id": case.case_id,
        "actions": actions,
        "run_id": cfg["run_id"],
        "strict_correct": result.get("strict_correct"),
        "status": result.get("status"),
        "paid_calls": 0,
        "image": "datapilot-current:local",
        "network": "datapilot-p7-current-v1_default",
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def validate_permit(permit, manifest, mode):
    if mode != "live":
        raise ValueError("formal permit requires live mode")
    if permit.get("authorized") is not True:
        raise ValueError("permit not authorized")
    if permit.get("provider") != "deepseek" or permit.get("model") != "deepseek-flash":
        raise ValueError("permit provider mismatch")
    if permit.get("thinking") != "disabled":
        raise ValueError("permit thinking mismatch")
    limits = {"case_count": 50, "runtime_runs": 13, "provider_attempts": 104, "token_units": 234000}
    if permit.get("campaign_id") != "p7-final-50-v7":
        raise ValueError("wrong continuation campaign")
    if any(type(permit.get(k)) is not int or permit[k] != v for k, v in limits.items()):
        raise ValueError("permit budget mismatch")
    excluded = {
        row["case_id"]
        for row in manifest.get("preflight", [])
        if row.get("status")
        in {
            "HISTORICAL_UNKNOWN",
            "PREVIOUSLY_COLLECTED",
            "PREVIOUSLY_PREFLIGHTED",
            "SCOPE_MISMATCH",
        }
    }
    if len(excluded) != 37 or set(permit.get("excluded_case_ids") or []) != excluded:
        raise ValueError("permit continuation exclusion mismatch")
    if permit.get("manifest_sha256") != digest(manifest):
        raise ValueError("permit manifest mismatch")
    if permit.get("evaluation_sha256") != digest(current_binding.load_manifest()):
        raise ValueError("permit evaluation identity mismatch")
    if permit.get("approved_by_role") != "project_owner" or not permit.get("approval_ref"):
        raise ValueError("owner approval required")
    return permit


def actual_preflight(cfg):
    rag_scope = None
    try:
        ReportScope.model_validate_json(json.dumps(cfg["report_scope"]))
        if cfg.get("rag_scope"):
            rag_scope = RagScope.model_validate_json(json.dumps(cfg["rag_scope"]))
    except Exception:
        return "REPORT_SCOPE_INVALID"
    material = load(ROOT / "artifacts/p7/final-evaluation-v1/total-50/materialization.json")
    allowed = {(d.get("id"), d.get("version")) for d in material.get("datasets", {}).values()}
    for m in cfg["report_scope"].get("metrics") or []:
        if (m.get("dataset_id"), m.get("dataset_version")) not in allowed:
            return "VERSION_NOT_AUTHORIZED"
    corpus_rows = material.get("corpora", {})
    corpus_details = current_binding.BASE / "materialized-v3/private/materialization"
    for pin in (cfg.get("rag_scope") or {}).get("corpora") or []:
        row = next(
            (
                (name, row)
                for name, row in corpus_rows.items()
                if row.get("id") == pin.get("corpus_id")
                and row.get("index_version") == pin.get("index_version")
            ),
            None,
        )
        if row is None:
            return "DOCUMENT_NOT_AUTHORIZED"
        name, row = row
        detail = load(corpus_details / f"corpus-{name}.json")
        manifest = detail["manifest"]
        if (
            detail["index_version"] != row["index_version"]
            or manifest["target"]["corpus_id"] != row["id"]
        ):
            raise ValueError("materialized corpus identity mismatch")
        parsed = IndexManifest.model_validate_json(json.dumps(manifest))
        source_ids = {source.document_id for source in parsed.sources}
        if not rag_scope.permits(parsed.target) or set(pin.get("document_ids") or []) != source_ids:
            return "DOCUMENT_NOT_AUTHORIZED"
    return None


def input_hashes():
    base = current_binding.BASE
    sealed = ROOT / "artifacts/p7/independent-holdout-v3/sealed"
    paths = [
        base / "total-50/materialization.json",
        base / "live-final-50-v3/summary.json",
        base / "live-final-50-v3/017-offline-rescore.json",
        base / "live-final-50-v4/stop-audit.json",
        base / "live-final-50-v5/stop-audit.json",
        base / "live-final-50-v5/summary.json",
        base / "live-final-50-v6/summary.json",
        base / "live-final-50-v6/064-offline-stop-diagnosis.json",
        ROOT / "docs/research/p7-final-50-remaining-scope-audit.md",
        *sorted((base / "materialized-v3/private/materialization").glob("corpus-*.json")),
        *(sealed / name for name in ("inputs.jsonl", "gold.jsonl", "pins.json", "SEALED.json")),
        *(
            base / "supplement-19" / name
            for name in ("inputs.jsonl", "private/gold.jsonl", "pins.json", "SEAL.json")
        ),
    ]
    return {
        path.name if path.parent == sealed else path.as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def verify_scoring_scope(task, config):
    scope = ReportScope(
        owner=task.owner,
        question=task.question,
        datasets=task.datasets,
        metrics=task.metrics,
        document_goal=task.document_goal,
        causal_requested=task.causal_requested,
    )
    rag = task.rag_scope.model_dump(mode="json") if task.rag_scope else None
    if digest(scope) != digest(config["report_scope"]) or rag != config["rag_scope"]:
        raise ValueError(f"launch differs from frozen scoring scope: {task.case_id}")


def load_cases():
    paths = (
        ROOT / "artifacts/p7/independent-holdout-v3/sealed/inputs.jsonl",
        current_binding.BASE / "supplement-19/inputs.jsonl",
    )
    rows = [
        json.loads(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["case_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate sealed case ID")
    return by_id


def load_gold(case_id):
    v3 = Path("artifacts/p7/independent-holdout-v3/sealed/gold.jsonl")
    sup = Path("artifacts/p7/final-evaluation-v1/supplement-19/private/gold.jsonl")
    for path in (v3, sup):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                if g["case_id"] == case_id:
                    return g
    raise ValueError("Gold missing for " + case_id)


def load_pins(case_id):
    if case_id.startswith("p7-holdout-v3-0") and int(case_id[-3:]) >= 61:
        return load("artifacts/p7/final-evaluation-v1/supplement-19/pins.json")
    return load("artifacts/p7/independent-holdout-v3/sealed/pins.json")


def collected_provider_503(collection):
    snapshot = collection.get("snapshot") or {}
    state = snapshot.get("state") or {}
    root = state.get("error") or {}
    calls = collection.get("calls") or []
    uncertain = [call for call in calls if call.get("status") != "complete"]
    errors = [
        result["error"] for result in state.get("results", {}).values() if result.get("error")
    ]
    return (
        snapshot.get("unknown") is True
        and not snapshot.get("report")
        and not collection.get("unresolved_dispatch")
        and root.get("code") == "MODEL_ERROR"
        and root.get("message") == "Async model provider failed (OpenAIAPIError, HTTP 503)"
        and len(uncertain) == 1
        and uncertain[0].get("kind") == "model"
        and uncertain[0].get("status") == "uncertain"
        and all(
            (error.get("code"), error.get("message")) == (root["code"], root["message"])
            or error.get("code") == "RECOVERY_UNCERTAIN"
            for error in errors
        )
    )


def run_batch(
    manifest,
    configs,
    permit,
    out,
    *,
    mode="live",
    runner=container_run,
    scorer=score,
    dev=False,
    max_calls=None,
    max_tokens=None,
):
    current_binding.verify_current()
    cases, cfgs = verify_manifest(manifest, configs)
    if mode == "live":
        validate_permit(permit, manifest, mode)
        if max_calls is not None or max_tokens is not None:
            raise ValueError("live budgets come from the permit")
        max_calls, max_tokens = permit["provider_attempts"], permit["token_units"]
        for cid, cfg in cfgs.items():
            binding = cfg["authorization_binding"]
            if (
                binding["case_id"] != cid
                or binding["source_manifest_lf"]
                != current_binding.load_manifest()["source_manifest_lf"]
            ):
                raise ValueError("worker identity mismatch")
            if (
                digest(
                    {
                        k: v
                        for k, v in cfg.items()
                        if k not in {"authorization_binding", "config_sha256"}
                    }
                )
                != binding["config_sha256"]
            ):
                raise ValueError("worker launch hash mismatch")
            worker_permit_valid(permit, binding)
        if permit.get("input_hashes") != input_hashes():
            raise ValueError("permit input hash mismatch")
        preflight = {
            row["case_id"]: actual_preflight(cfgs[row["case_id"]])
            for row in cases
            if row["case_id"] not in permit["excluded_case_ids"]
        }
        for row in cases:
            cid = row["case_id"]
            if cid not in preflight:
                continue
            expected = row.get("reason") if row.get("status") == "EXPECTED_HOST_REJECTION" else None
            if preflight[cid] != expected:
                raise ValueError(f"host preflight mismatch: {cid}: {preflight[cid]}")
        inputs = load_cases()
        scoring_inputs = {
            row["case_id"]: (
                Case.model_validate_json(json.dumps(inputs[row["case_id"]])),
                Answer.model_validate_json(json.dumps(load_gold(row["case_id"]))),
                load_pins(row["case_id"]),
            )
            for row in cases
            if row.get("status") == "READY" and row["case_id"] not in permit["excluded_case_ids"]
        }
        for cid, (task, _, _) in scoring_inputs.items():
            verify_scoring_scope(task, cfgs[cid])
        if len(scoring_inputs) != permit["runtime_runs"]:
            raise ValueError("ready runtime count mismatch")
    values = load(ROOT / "artifacts/p7/current-pg/private/environment.json")
    product = {
        "docker": {"image_id": "datapilot-current:local"},
        "source_snapshot": str(
            (ROOT / "artifacts/p7/final-evaluation-v1/current-source-snapshot").resolve()
        ),
    }
    out.mkdir(parents=True, exist_ok=mode != "live")
    if mode == "live":
        claims = current_binding.BASE / "dispatch-claims"
        claims.mkdir(exist_ok=True)
        with (claims / (digest(permit["campaign_id"]) + ".json")).open(
            "x", encoding="utf-8"
        ) as claim:
            json.dump({"campaign_id": permit["campaign_id"], "output": str(out.resolve())}, claim)
    key = secrets.token_bytes(32)
    if mode == "live":
        key_path = claims / (digest(permit["campaign_id"]) + ".collector-key")
        with key_path.open("xb") as key_file:
            key_file.write(key)
    campaign_deadline = time.monotonic() + 10800
    state_path = out / "state.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    state = previous.get("cases", previous) if isinstance(previous, dict) else {}
    stop = previous.get("stop") if isinstance(previous, dict) else None
    total_calls = sum(int(v.get("calls", 0)) for v in state.values())
    total_tokens = sum(int(v.get("tokens", 0)) for v in state.values())
    max_calls = len(cases) * 8 if max_calls is None else max_calls
    max_tokens = len(cases) * 18000 if max_tokens is None else max_tokens
    for case in cases:
        cid = case["case_id"]
        cfg = cfgs[cid]
        folder = out / cid
        if cid in state:
            continue
        if stop:
            state.setdefault(cid, {"status": "not_run", "reason": "stopped_after:" + str(stop)})
            continue
        if mode == "live" and cid in permit["excluded_case_ids"]:
            state[cid] = {
                "status": "not_run",
                "reason": "historical_unknown"
                if case["status"] == "HISTORICAL_UNKNOWN"
                else case["status"].lower(),
                "calls": 0,
                "tokens": 0,
            }
            continue
        folder.mkdir(exist_ok=True)
        (folder / "config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if case.get("status") == "EXPECTED_HOST_REJECTION":
            code = actual_preflight(cfg)
            if not code:
                state[cid] = {"status": "blocked", "reason": "expected rejection did not occur"}
                stop = "infrastructure"
                break
            state[cid] = {
                "status": "expected_host_rejection",
                "code": code,
                "model_calls": 0,
                "calls": 0,
                "tokens": 0,
            }
            if mode == "live":
                gold = Answer.model_validate_json(json.dumps(load_gold(cid)))
                state[cid]["strict_correct"] = gold.host_code == code
            state_path.write_text(
                json.dumps({"cases": state, "stop": stop}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            continue
        code = actual_preflight(cfg)
        if code and mode == "live":
            state[cid] = {"status": "blocked", "reason": code}
            stop = "infrastructure"
            break
        if code:
            state[cid] = {
                "status": "expected_host_rejection",
                "code": code,
                "model_calls": 0,
                "calls": 0,
                "tokens": 0,
            }
            state_path.write_text(
                json.dumps({"cases": state, "stop": stop}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            continue
        if (
            total_calls + (8 if mode == "live" else 1) > max_calls
            or total_tokens + (18000 if mode == "live" else 1) > max_tokens
        ):
            state[cid] = {
                "status": "not_run",
                "reason": "BUDGET_EXHAUSTED",
                "calls": 0,
                "tokens": 0,
            }
            continue
        if mode == "live" and cfg.get("synthetic_probe"):
            raise ValueError("probe config cannot enter live")
        deadline = min(campaign_deadline, time.monotonic() + 180)
        if mode == "live" and (out.joinpath("STOP").exists() or time.monotonic() >= deadline):
            stop = "campaign_stopped"
            break
        state[cid] = {"status": "dispatching", "run_id": cfg.get("run_id")}
        state_path.write_text(json.dumps({"cases": state, "stop": stop}), encoding="utf-8")
        usage = {}
        accounted = False
        continue_after_503 = False
        try:
            actions = []
            for action in ["probe", "start", "approve", "collect"]:
                payload = runner(
                    cfg,
                    folder,
                    mode,
                    action,
                    values,
                    product,
                    deadline,
                    Path(permit["_path"]) if mode == "live" else None,
                )
                actions.append(action)
                if action == "collect":
                    collection = payload
            usage = (collection.get("snapshot") or {}).get("usage") or {}
            calls = int(usage.get("calls", 0))
            tokens = int(usage.get("total_tokens", 0))
            total_calls += calls
            total_tokens += tokens
            accounted = True
            if (collection.get("snapshot") or {}).get("unknown"):
                continue_after_503 = (
                    mode == "live"
                    and total_calls <= max_calls
                    and total_tokens <= max_tokens
                    and collected_provider_503(collection)
                )
                if continue_after_503:
                    (folder / "signed-collection.json").write_text(
                        json.dumps(sign_collection(collection, key), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                raise RuntimeError("unknown outcome")
            signed = sign_collection(collection, key)
            if mode == "live":
                task, gold, pins = scoring_inputs[cid]
            else:
                task = Case.model_validate_json(json.dumps(case))
                gold = Answer.model_validate_json(json.dumps(load_gold(cid)))
                pins = load_pins(cid)
            result = scorer(task, gold, signed, key, pins)
            if mode == "live" and (
                not usage.get("usage_complete")
                or not ordinary_failure_may_continue(result, collection)
            ):
                raise RuntimeError("unknown or unsafe collected outcome")
            if total_calls > max_calls or total_tokens > max_tokens:
                raise RuntimeError("BUDGET_EXCEEDED")
            (folder / "signed-collection.json").write_text(
                json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (folder / "score.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            state[cid] = {
                "status": result.get("status", "collected"),
                "strict_correct": result.get("strict_correct"),
                "actions": actions,
                "run_id": cfg.get("run_id"),
                "calls": calls,
                "tokens": tokens,
            }
        except Exception as exc:
            text = str(exc)
            unknown = "unknown" in text.lower() or "uncertain" in text.lower()
            infra = (
                isinstance(
                    exc, (KeyError, TypeError, ValueError, FileNotFoundError, PermissionError)
                )
                or "Candidate process failed" in text
                or "BUDGET_EXCEEDED" in text
            )
            if unknown:
                if mode == "live" and not accounted:
                    total_calls += 8
                    total_tokens += 18000
                state[cid] = {
                    "status": "unknown",
                    "error": type(exc).__name__,
                    "calls": int(usage.get("calls", 0))
                    if accounted
                    else (8 if mode == "live" else 0),
                    "tokens": int(usage.get("total_tokens", 0))
                    if accounted
                    else (18000 if mode == "live" else 0),
                    "usage_complete": False,
                    "usage_basis": "journal" if accounted else "uncollected_reservation",
                }
                if continue_after_503:
                    state[cid].update(reason="provider_http_503", run_id=cfg["run_id"])
                else:
                    stop = "unknown"
            elif infra:
                state[cid] = {"status": "blocked", "error": type(exc).__name__ + ": " + text[:200]}
                stop = "infrastructure"
            else:
                state[cid] = {
                    "status": "failed",
                    "error": type(exc).__name__ + ": " + text[:200],
                }
            state_path.write_text(
                json.dumps({"cases": state, "stop": stop}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if stop:
                break
            continue
        state_path.write_text(
            json.dumps({"cases": state, "stop": stop}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    state_path.write_text(json.dumps({"cases": state, "stop": stop}), encoding="utf-8")
    # fixed denominator: any unvisited case is not_run
    for case in cases:
        state.setdefault(case["case_id"], {"status": "not_run", "calls": 0, "tokens": 0})
    summary = {
        "schema": "formal-runner-summary/v1",
        "planned": len(cases),
        "states": state,
        "stop": stop,
        "calls": total_calls,
        "tokens": total_tokens,
        "paid_calls": 0 if mode == "fake" else None,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path)
    p.add_argument("--configs", type=Path)
    p.add_argument("--materialization", type=Path)
    p.add_argument("--permit", type=Path)
    p.add_argument("--dev", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mode", choices=["fake", "live"], default="fake")
    a = p.parse_args()
    if a.dev:
        print(json.dumps(run_dev(load(a.dev), a.out), ensure_ascii=False, indent=2))
        return
    if not (a.manifest and a.configs):
        raise SystemExit("formal live requires --manifest and --configs")
    current_binding.verify_current()
    if a.mode == "live" and (
        not a.materialization
        or a.materialization.resolve()
        != (ROOT / "artifacts/p7/final-evaluation-v1/total-50/materialization.json").resolve()
    ):
        raise SystemExit("use the bound materialization file")
    m = load(a.manifest)
    c = load(a.configs)
    cases, cfgs = verify_manifest(m, c)
    if a.mode == "live" and not a.permit:
        raise SystemExit("live mode requires permit")
    permit = load(a.permit) if a.permit else None
    if permit is not None:
        permit = dict(permit)
        permit["_path"] = str(a.permit)
    summary = run_batch(m, c, permit, a.out, mode=a.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
