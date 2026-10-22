"""Replaceable HTTP client; deliberately imports no business/runtime/database modules."""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx


class ClientError(Exception):
    def __init__(self, error):
        self.error = error
        super().__init__(error.get("message", "API request failed"))


class APIClient:
    def __init__(self, policy_path=None):
        path = Path(
            policy_path
            or os.environ.get(
                "DATAPILOT_WEB_HOST_FILE",
                Path(__file__).resolve().parents[3] / "artifacts/web/host.json",
            )
        )
        config = json.loads(path.read_text(encoding="utf-8"))
        base = os.environ.get("DATAPILOT_WEB_API_URL", "http://" + config["api_host"])
        self.http = httpx.Client(
            base_url=base,
            timeout=120,
            follow_redirects=False,
            trust_env=False,
            headers={"Origin": config["ui_origin"], "Host": config["api_host"]},
        )
        result = self.http.post(
            "/api/v1/session", headers={"X-DataPilot-Host-Key": config["secret"]}
        )
        data = self._read(result)
        self.http.headers["X-CSRF-Token"] = data["csrf_token"]

    def _read(self, response):
        try:
            result = response.json()
        except ValueError:
            raise ClientError(
                {"code": "HTTP_UNAVAILABLE", "message": "API 返回无法识别的响应"}
            ) from None
        if response.is_error:
            raise ClientError(result.get("error", {"code": "HTTP_ERROR", "message": "请求未完成"}))
        return result

    def get(self, path):
        return self._read(self.http.get("/api/v1" + path))

    def post(self, path, body=None, *, files=None, data=None, key=None):
        return self._read(
            self.http.post(
                "/api/v1" + path,
                json=body if files is None else None,
                files=files,
                data=data,
                headers={"Idempotency-Key": key or uuid4().hex},
            )
        )

    def close(self):
        self.http.close()
