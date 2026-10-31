"""One-shot test process: hard exit during a known delayed MCP encode, no provider."""

import asyncio
import json
import os
import secrets
import sys
from functools import partial
from pathlib import Path

from datapilot.config import Settings
from datapilot.persistence.session import run_async
from datapilot.rag.cli import read_scope
from datapilot.rag.mcp import MCPRetrievalTools
from datapilot.rag.qwen import interpreter
from datapilot.runtime import mcp_client


async def main():
    scope_path, signal_path = map(Path, sys.argv[1:])
    settings = Settings(_env_file=None, llm_mode="fake", api_key=None)
    scope = read_scope(scope_path)
    goal = "How does maintenance freeze affect new and running workflows?"
    token = secrets.token_hex(16)
    root = Path(__file__).resolve().parents[1]
    env = mcp_client.server_environment(settings)
    env.update(
        DATAPILOT_RAG_READER_DATABASE_URL=settings.rag_reader_database_url.get_secret_value(),
        DATAPILOT_RAG_SCOPE=scope.model_dump_json(),
        DATAPILOT_RAG_GOAL=goal,
        DATAPILOT_MCP_SESSION_TOKEN=token,
        DATAPILOT_TEST_QWEN_FAULT="encode_gil",
        PYTHONPATH=str(root / "src"),
    )
    parameters = mcp_client.StdioServerParameters

    def fixed(**kwargs):
        args = list(kwargs["args"])
        assert args[:2] == ["-I", "-c"]
        args[2] = args[2].replace(
            "runpy.run_module('datapilot.runtime.mcp_server',run_name='__main__')",
            "runpy.run_path(sys.argv[2],run_name='__main__')",
        )
        args.append(str(root / "tests/qwen_delay_server.py"))
        return parameters(**{**kwargs, "command": interpreter(), "args": args})

    mcp_client.StdioServerParameters = fixed
    async with mcp_client._connection(
        settings,
        env,
        partial(MCPRetrievalTools, scope=scope, goal=goal, session_token=token),
        executable=interpreter(),
        isolated=True,
    ) as tools:
        await tools.preflight()
        await tools.prepare()
        asyncio.create_task(tools.search(goal, 3))
        await asyncio.sleep(0.5)
        signal_path.write_text(json.dumps({"pid": tools.process_owner.pid}))
        while not signal_path.with_suffix(".ack").exists():
            await asyncio.sleep(0.05)
        os._exit(91)


if __name__ == "__main__":
    run_async(main())
