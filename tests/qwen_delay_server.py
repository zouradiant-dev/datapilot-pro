"""Test-only delayed model initialization in the real RAG MCP server, no vectors fabricated."""

import ctypes
import os
import time

from datapilot.config import Settings
from datapilot.rag import mcp
from datapilot.rag.contracts import RagScope
from datapilot.rag.models import create_embedding


def delayed_model(profile, *, observer=None):
    mode = os.environ.get("DATAPILOT_TEST_QWEN_FAULT", "encode_delay")
    if mode == "init_delay":
        time.sleep(30)
    model = create_embedding(profile, observer=observer)
    encode = model.encode

    def delayed_encode(texts, *, query=False):
        if query and texts == [os.environ["DATAPILOT_RAG_GOAL"]]:
            if mode == "encode_gil":
                if os.name == "nt":
                    ctypes.PyDLL("kernel32").Sleep(30000)
                else:
                    ctypes.PyDLL(None).sleep(30)
            else:
                time.sleep(30)
        return encode(texts, query=query)

    model.encode = delayed_encode
    return model


if __name__ == "__main__":
    mcp.create_embedding = delayed_model
    mcp.create_rag_server(
        Settings(llm_mode="fake", _env_file=None),
        RagScope.model_validate_json(os.environ["DATAPILOT_RAG_SCOPE"]),
        goal=os.environ["DATAPILOT_RAG_GOAL"],
    ).run(transport="stdio")
