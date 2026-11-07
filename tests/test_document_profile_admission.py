"""A prior paid permit cannot silently adopt new retrieval/publication policies."""

import pytest
from test_source_goals import source_scope

from datapilot.reporting.contracts import finite_contract_hash
from datapilot.web.admission import AdmissionGate
from evaluation.p7_v3_current.partial_evidence_scope import confirm_document_evidence


@pytest.mark.parametrize("components", [False, True])
def test_extended_document_contract_is_bound_in_admission(components):
    scope, rag, _ = source_scope()
    if not components:
        scope.document_goal.source_goals = []
    scope = confirm_document_evidence(scope, rag, confirmation_ref="public-new-document-policy")
    payload = {
        "question": scope.question,
        "report_scope": scope.model_dump(mode="json"),
        "rag_scope": rag.model_dump(mode="json"),
    }
    gate = object.__new__(AdmissionGate)
    binding = gate._payload_binding(payload)
    assert binding["document_contract_sha256"] == finite_contract_hash(scope)
    assert gate._matches(binding, binding)
    old_permit = {k: v for k, v in binding.items() if k != "document_contract_sha256"}
    assert not gate._matches(old_permit, binding)
    changed = scope.model_copy(deep=True)
    if components:
        changed.document_goal.source_goals[0].question += "与交班责任"
    else:
        changed.document_explanation_policy = "legacy"
    changed = (
        confirm_document_evidence(changed, rag, confirmation_ref="public-other-review")
        if components
        else changed
    )
    payload["report_scope"] = changed.model_dump(mode="json")
    assert not gate._matches(binding, gate._payload_binding(payload))
