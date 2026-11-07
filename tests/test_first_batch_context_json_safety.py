"""Ambiguous JSON in public first-batch feedback must fail before model dispatch."""

import json

import pytest
from langchain_core.messages import messages_to_dict
from test_first_batch_context_budget import first_batch

from datapilot.contracts import AgentFailure


async def assert_rejected_without_effects(gateway, registry, messages, content):
    messages[-1] = messages[-1].model_copy(update={"content": content})
    canonical = messages_to_dict(messages)
    artifacts = {
        key: artifact.model_dump(mode="json") for key, artifact in registry.store.export().items()
    }
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)

    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "EVIDENCE_INVALID"
    assert not gateway.transport.requests
    assert gateway.ledger.dump_state() == ledger
    assert messages_to_dict(messages) == canonical
    assert registry.context_refs == archives
    assert {
        key: artifact.model_dump(mode="json") for key, artifact in registry.store.export().items()
    } == artifacts


@pytest.mark.parametrize("location", ["payload", "document"])
async def test_duplicate_json_keys_cannot_enter_first_batch_projection(settings, location):
    _, gateway, registry, messages, _ = first_batch(settings)
    content = messages[-1].content
    if location == "payload":
        field = '"fixture": true'
        assert content.count(field) == 1
    else:
        payload = json.loads(content)
        document = payload["documents"][0]
        field = '"document_id": ' + json.dumps(document["document_id"])
        assert content.count(field) == 1
    duplicated = content.replace(field, field + ", " + field, 1)
    # A permissive parser would produce the unchanged valid feedback. The
    # projection must reject the duplicate syntax, including nested fields.
    assert json.loads(duplicated) == json.loads(content)

    await assert_rejected_without_effects(gateway, registry, messages, duplicated)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_json_cannot_enter_first_batch_projection(settings, number):
    _, gateway, registry, messages, _ = first_batch(settings)
    payload = json.loads(messages[-1].content)
    # Keep every artifact-bound preview field intact, so rejection exercises
    # the JSON boundary rather than a mismatching document or reference.
    payload["untrusted_numeric_hint"] = number
    nonfinite = json.dumps(payload, ensure_ascii=False, allow_nan=True)

    await assert_rejected_without_effects(gateway, registry, messages, nonfinite)


@pytest.mark.parametrize("field", ["fixture", "document_count", "start", "line_start"])
async def test_json_type_aliases_do_not_match_artifact_proof_fields(settings, field):
    _, gateway, registry, messages, _ = first_batch(settings)
    original = json.loads(messages[-1].content)
    payload = json.loads(messages[-1].content)
    if field == "fixture":
        payload[field] = 1
    elif field == "document_count":
        payload[field] = float(payload[field])
    else:
        payload["documents"][0]["citation"][field] = bool(
            payload["documents"][0]["citation"][field]
        )
    # Python equality aliases bool/int and int/float, but their JSON types
    # have different meanings and cannot replace an artifact-bound proof.
    assert payload == original
    assert json.dumps(payload, sort_keys=True) != json.dumps(original, sort_keys=True)
    await assert_rejected_without_effects(
        gateway, registry, messages, json.dumps(payload, ensure_ascii=False)
    )
