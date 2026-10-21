"""P4.1 measurements and bounded L0 views; no history rewriting or model summarizer."""

import json

from langchain_core.messages import messages_to_dict

from datapilot.orchestration.contracts import ContextUsage


def measure_context(messages, tools, output_tokens):
    message_text = json.dumps(messages_to_dict(messages), ensure_ascii=False)
    schema_text = json.dumps(tools, ensure_ascii=False)
    text = json.dumps({"messages": messages_to_dict(messages), "tools": tools}, ensure_ascii=False)
    usage = ContextUsage(
        messages=len(messages),
        message_chars=len(message_text),
        tool_schema_chars=len(schema_text),
        input_bytes=len(text.encode("utf-8")),
        estimated_input_tokens=len(text.encode("utf-8")) + 128,
        output_reserved_tokens=output_tokens,
        tool_result_chars=sum(len(m.content) for m in messages if m.type == "tool"),
    )
    return text, usage


def tool_view(artifact, ref, max_chars):
    """Called ONLY after full validated artifact storage. No authoritative content is rewritten."""
    payload = {"artifact_refs": [ref.model_dump()], "model_view": "L0"}
    if artifact.query:
        q = artifact.query
        payload.update(
            row_count=q.row_count,
            columns=q.columns[:16],
            columns_omitted=max(0, len(q.columns) - 16),
            truncated=q.truncated,
        )
    elif artifact.documents:
        result = artifact.documents
        payload.update(
            document_count=len(result.documents),
            fixture=result.fixture,
            documents=[
                {
                    "document_id": d.document_id,
                    "source": d.source,
                    "version": d.version,
                    "sha256": d.sha256,
                    "text": d.text[:256],
                    "text_omitted_chars": max(0, len(d.text) - 256),
                }
                for d in result.documents
            ],
        )
    # Even adversarial identifiers cannot make a model view unbounded. Complete metadata
    # remains in the artifact; this is not a change to source evidence or authorization.
    if len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        payload.pop("documents", None)
        payload.pop("columns", None)
        payload["details_omitted"] = True
    return payload
