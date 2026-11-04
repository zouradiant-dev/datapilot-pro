"""Keep-alive HTTP exercises the pooled connections MockTransport does not use."""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import final50_admission_control as admission
from langchain_core.messages import HumanMessage

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.orchestration.model import live_transport
from datapilot.reporting.contracts import ReportScope


def test_two_workers_share_the_loop_owning_sdk_connections(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(self.path)
            body = json.dumps(
                {
                    "id": "local-loop-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    async def runtime(settings, run_id, question, **kwargs):
        if kwargs["approve"]:
            response = await live_transport(settings).respond([HumanMessage(content=question)], [])
            return {"status": "completed", "usage": response.usage_metadata}
        return {"status": "awaiting_review"}

    monkeypatch.setattr(admission, "run_durable", runtime)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = Settings(
        _env_file=None,
        llm_mode="live",
        model_provider="deepseek",
        model="deepseek-flash",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="local-test-only",
        model_timeout_seconds=3,
    )
    scope = ReportScope.model_validate_json(
        json.dumps(
            {
                "question": "Local synthetic metric question",
                "datasets": {
                    "bindings": [
                        {
                            "dataset_id": "00000000-0000-4000-8000-000000000001",
                            "version": 1,
                        }
                    ]
                },
                "metrics": [
                    {
                        "goal_id": "metric_1",
                        "dataset_id": "00000000-0000-4000-8000-000000000001",
                        "dataset_version": 1,
                        "semantic_version": 1,
                        "metric_id": "usage",
                        "metric_version": 1,
                        "window": {"start": "2032-02-01", "end_exclusive": "2032-03-01"},
                    }
                ],
            }
        )
    )
    try:
        with asyncio.Runner(
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
        ) as loop_runner:
            for suffix in ("017", "064"):
                config = {
                    "case_id": "local-" + suffix,
                    "run_id": "local-" + suffix,
                    "report_scope": scope.model_dump(mode="json"),
                    "rag_scope": None,
                }
                for action in ("start", "approve"):
                    result = admission.worker(
                        config,
                        digest(config),
                        settings,
                        scope,
                        None,
                        action,
                        live=True,
                        loop_runner=loop_runner,
                    )
                assert result["status"] == "completed"
                assert result["usage"]["total_tokens"] == 30
        assert requests == ["/v1/chat/completions"] * 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
