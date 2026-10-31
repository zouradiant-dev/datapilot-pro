"""One pre-registered same-language rewrite per new Dev case, without Gold-based routing."""

import json

from dev import OUT, cases, environment, host_scope, pre_threshold
from v3_common import write_new

from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding


async def probe():
    values, settings = environment()
    bindings = json.loads((OUT / "bindings.json").read_bytes())["bindings"]
    embedding = LocalEmbedding()
    rows = []
    for case in cases():
        binding = bindings[case["id"]]
        rag, _ = host_scope(case, binding)
        query = case["rewrite"]
        async with rag_session(settings, rag, goal=case["question"]) as retrieval:
            result = await retrieval.search(query, 5)
        observed = {d.citation.document_id for d in result.documents}
        rows.append(
            {
                "case_id": case["id"],
                "strategy": "same_language_diagnostic",
                "calls": [
                    {
                        "query": query,
                        "result": result.model_dump(mode="json"),
                        "pre_threshold": pre_threshold(values, rag, embedding, query),
                    }
                ],
                "relevant_documents": sorted(
                    s["document_id"]
                    for s in binding["manifest"]["sources"]
                    if s["name"] in case["required"]
                ),
                "observed_documents": sorted(observed),
                "full_required": set(case["required"])
                <= {
                    s["name"]
                    for s in binding["manifest"]["sources"]
                    if s["document_id"] in observed
                },
            }
        )
    write_new(OUT / "same-language-trials.json", rows)
    print("12 pre-registered Chinese rewrites queried through real MCP; paid calls=0")


if __name__ == "__main__":
    run_async(probe())
