"""Public confirmation requirements are not source proofs or model approval."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from datapilot.web.contracts import DocumentQuery


def test_document_requirement_is_not_an_approved_fact():
    request = DocumentQuery(
        question="核对文档中的审计年限。",
        corpus_ids=[str(uuid4())],
        metric_goals=[],
        purpose="facts",
        required_facts=[{"fact_id": "retention", "description": "审计保留年限"}],
    )
    assert request.required_facts[0].description == "审计保留年限"
    with pytest.raises(ValidationError):
        DocumentQuery.model_validate(
            request.model_dump()
            | {
                "required_facts": [
                    {
                        "fact_id": "retention",
                        "description": "审计保留年限",
                        "confirmation_ref": "user-text-is-not-proof",
                    }
                ]
            }
        )


def test_document_purpose_is_explicit_and_legacy_projection_stays_unconfirmed():
    from datapilot.web.chat_contracts import ChatSelection

    assert not {"document_purpose", "required_facts"} & ChatSelection().model_dump().keys()
    body = {"question": "总结授权文档。", "corpus_ids": [str(uuid4())], "metric_goals": []}
    legacy = DocumentQuery(**body)
    assert legacy.purpose is None and legacy.model_dump() == body
    for purpose in ("locate", "summary", "conclusion"):
        assert DocumentQuery(**body, purpose=purpose).purpose == purpose
    with pytest.raises(ValidationError):
        DocumentQuery(**body, purpose="facts")


def test_ui_collects_requirements_without_creating_fact_proofs():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from datapilot.web.ui_components import document_requirements\n"
        "st.json(document_requirements('public-test'))\n"
    ).run()
    app.selectbox[0].select("facts").run()
    app.text_area[0].set_value("审计保留年限\n文档适用时间").run()
    assert not app.exception
    import json

    view = json.loads(app.json[0].value)
    assert view["purpose"] == "facts" and len(view["required_facts"]) == 2
    assert all(set(f) == {"fact_id", "description"} for f in view["required_facts"])
