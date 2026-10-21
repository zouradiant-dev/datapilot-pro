"""Developer-only synthetic context experiment. No database, supplier API or billable tokens."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from langchain_core.messages import messages_to_dict

from datapilot.config import Settings


async def measure() -> dict:
    # This explicit test helper path also works with precise src editable installations.
    # These fixtures never substitute for a real model benchmark or production RAG.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_context_engineering import history, make_context

    settings = Settings(
        llm_mode="fake",
        api_key=None,
        reader_database_url=None,
        upload_reader_database_url=None,
        _env_file=None,
    )
    scenarios = [
        ("L1_L2", 20000, 12, 1600, 0),
        ("L3", 13000, 12, 900, 1800),
        ("L4", 7100, 4, 900, 1800),
    ]
    cases = []
    for name, limit, turns, body, ai_body in scenarios:
        _, manager, gateway, registry, prefix = make_context(settings, max_chars=limit)
        messages = history(manager, prefix, count=turns, body=body, ai_body=ai_body)
        before = messages_to_dict(messages)
        started = time.perf_counter()
        await gateway.invoke(messages, registry.schemas(), "1:r")
        report = manager.stats[-1].model_dump()
        cases.append(
            {
                "scenario": name,
                **report,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "logical_model_calls": gateway.ledger.snapshot().calls,
                "synthetic_reported_tokens": gateway.ledger.snapshot().reported_tokens,
                "canonical_history_unchanged": before == messages_to_dict(messages),
            }
        )
    return {
        "mode": "synthetic_component_only",
        "paid_api_calls": 0,
        "real_model_tokens": 0,
        "measured_supplier_cost": None,
        "cost_note": "Fixture usage is synthetic, not a supplier cost/quality benchmark.",
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    artifacts = (Path(__file__).resolve().parents[1] / "artifacts").resolve()
    if not output.is_relative_to(artifacts):
        parser.error("Output must stay inside this repository's artifacts/")
    result = asyncio.run(measure())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
