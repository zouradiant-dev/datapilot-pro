"""Lifecycle/ownership contracts. Stub vectors here are NOT neural retrieval evidence."""

import asyncio
import contextlib
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import anyio
import numpy as np
import pytest

from datapilot.contracts import AgentFailure
from datapilot.rag.contracts import EmbeddingUsage
from datapilot.rag.lifecycle import ModelCache
from datapilot.rag.qwen import specification
from datapilot.runtime.owned_process import OwnedProcess, sha


class Connection:
    def execute(self, *args, **kwargs):
        return SimpleNamespace(scalar_one=lambda: True)

    def exec_driver_sql(self, *args):
        return None

    def commit(self):
        pass


class Model:
    spec = specification("qwen3-cpu-v1")

    def encode(self, texts, **kwargs):
        vector = np.zeros((len(texts), 1024), np.float32)
        vector[:, 0] = 1
        return vector, EmbeddingUsage(mode="local_torch", tokens=1, elapsed_ms=1, calls=1)


@pytest.fixture
def cache(monkeypatch):
    from datapilot.rag import lifecycle, qwen_runtime

    monkeypatch.setattr(qwen_runtime, "verify", lambda: {"manifest_sha256": "unit-only"})
    for key in list(os.environ):
        if key.endswith(("API_KEY", "DATABASE_URL")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(lifecycle, "available_ram", lambda: 8 * 1024**3)
    calls = []

    def factory(profile, **kwargs):
        calls.append(profile)
        return Model()

    repo = SimpleNamespace(
        manifests=lambda: {}, engine=SimpleNamespace(connect=lambda: Connection())
    )
    value = ModelCache(repo, "qwen3-cpu-v1", factory, exit_process=lambda code: calls.append(code))
    return value, calls


async def finish(cache):
    for task in [cache.loading, cache.heartbeat]:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def test_not_ready_search_never_lazy_loads_model(cache):
    value, calls = cache
    assert value.status()["state"] == "not_started"
    with pytest.raises(AgentFailure, match="explicit model readiness"):
        await value.search("question", 3)
    assert calls == []


async def test_explicit_startup_is_single_and_observable(cache):
    value, calls = cache
    first, second = await asyncio.gather(value.prepare(), value.prepare())
    assert first["state"] == second["state"] == "loading"
    await value.loading
    assert value.state == "ready" and value.loads == 1 and calls == ["qwen3-cpu-v1"]
    assert (await value.prepare())["loads"] == 1
    assert [e["phase"] for e in value.events][-3:] == [
        "warmup_started",
        "warmup_complete",
        "model_ready",
    ]
    await finish(value)


async def test_resource_pressure_fails_before_factory_without_retry(cache, monkeypatch):
    from datapilot.rag import lifecycle

    value, calls = cache
    monkeypatch.setattr(lifecycle, "available_ram", lambda: 1024**3)
    assert (await value.prepare())["state"] == "failed"
    assert value.error.code == "EMBEDDING_RESOURCE_LIMIT" and not calls
    assert (await value.prepare())["loads"] == 0


async def test_other_model_profile_cannot_become_ready(cache):
    value, _ = cache
    value.factory = lambda *args, **kwargs: SimpleNamespace(
        spec=specification("qwen3-cuda-fp16-v1")
    )
    await value.prepare()
    await value.loading
    assert value.state == "failed" and value.error.code == "EMBEDDING_VERSION"
    await finish(value)


async def test_busy_session_does_not_spawn_unbounded_work(cache):
    value, _ = cache
    await value.prepare()
    await value.loading
    value.active = True
    with pytest.raises(AgentFailure, match="bounded search"):
        await value.search("question", 3)
    assert value.loads == 1
    value.active = False
    await finish(value)


async def test_startup_quota_cancellation_arms_owner_without_receipt(monkeypatch):
    from datapilot.rag import lifecycle
    from datapilot.rag.contracts import RagScope
    from datapilot.rag.mcp import MCPRetrievalTools

    monkeypatch.setattr(lifecycle, "STARTUP_SECONDS", 0.02)
    tools = MCPRetrievalTools(None, 10, scope=RagScope(embedding_profile="qwen3-cpu-v1"))
    calls = []
    tools.process_owner = SimpleNamespace(arm=lambda: calls.append("armed"))

    async def pending(*args):
        return {"embedding": {"state": "loading"}}

    tools.call = pending
    with pytest.raises(AgentFailure, match="startup timed out"):
        await tools.prepare()
    assert calls == ["armed"] and tools.startup_trace is None


@pytest.mark.parametrize("pid", [0, 1, -1, os.getpid()])
def test_process_metadata_cannot_target_current_or_system_process(pid):
    with pytest.raises(AgentFailure):
        OwnedProcess(pid, time.time(), {"0" * 64})


def sleeper():
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    return subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(30)"], env=env)


def test_real_os_child_hard_cleanup_deadline():
    process = sleeper()
    try:
        # venv redirectors are verified against both pinned interpreter binaries.
        owner = OwnedProcess(
            process.pid, time.time() - 1, {sha(sys.executable), sha(sys._base_executable)}
        )
        start = time.monotonic()
        owner.arm()
        process.wait(timeout=5)
        assert time.monotonic() - start < 5
        assert owner.events[-1]["phase"] == "cleanup_deadline_terminated"
        owner.close()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def test_wrong_binary_identity_is_rejected_without_killing_child():
    process = sleeper()
    try:
        with pytest.raises(AgentFailure):
            OwnedProcess(process.pid, time.time() - 1, {"0" * 64})
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=3)


async def test_broken_sdk_stream_arms_cleanup_and_never_returns_success():
    from datapilot.runtime.mcp_client import MCPDatabaseTools

    async def broken(*args):
        raise anyio.BrokenResourceError

    armed = []
    tools = MCPDatabaseTools(SimpleNamespace(call_tool=broken), 10)
    tools.process_owner = SimpleNamespace(arm=lambda: armed.append(True))
    with pytest.raises(AgentFailure) as failed:
        await tools.call("health", {})
    assert failed.value.error.code == "TOOL_ERROR" and armed == [True]


def test_fixed_interpreter_is_not_selected_from_environment(monkeypatch):
    from datapilot.rag import qwen_runtime
    from datapilot.rag.qwen import interpreter

    monkeypatch.setenv("DATAPILOT_QWEN_PYTHON", "../../untrusted/python")
    monkeypatch.setenv("PYTHONHOME", "untrusted")
    monkeypatch.setattr(qwen_runtime, "expected", lambda: ({}, "unit-only"))
    assert interpreter() == str(qwen_runtime.executable())


def test_readiness_control_is_not_a_worker_capability():
    from datapilot.orchestration.tools import CAPABILITIES

    assert all("prepare_embedding" not in tools for tools in CAPABILITIES.values())


@pytest.mark.parametrize("damage", ["absent", "symlink", "hash", "lock", "packages"])
def test_deployment_manifest_drift_fails_closed(tmp_path, monkeypatch, damage):
    from datapilot.rag import qwen_runtime as rt

    prefix = tmp_path / "qwen"
    prefix.mkdir()
    binary = prefix / "python"
    binary.write_bytes(b"public test executable identity")
    cfg = prefix / "pyvenv.cfg"
    cfg.write_text("public test venv identity")
    lock = tmp_path / "lock"
    lock.write_text("test==1")
    manifest = prefix / "runtime.json"
    monkeypatch.setattr(rt, "PREFIX", prefix)
    monkeypatch.setattr(rt, "MANIFEST", manifest)
    monkeypatch.setattr(rt, "executable", lambda: binary)
    monkeypatch.setattr(rt, "lock_file", lambda: lock)
    monkeypatch.setattr(rt, "pinned_packages", lambda: {"test": "1"})
    value = {
        "schema_version": "qwen-runtime-1",
        "platform": sys.platform,
        "python": rt.PYTHON[sys.platform],
        "packages": {"test": "1"},
        "executable_sha256": sha(binary),
        "pyvenv_sha256": sha(cfg),
        "lock_sha256": sha(lock),
    }
    import json

    if damage == "hash":
        value["executable_sha256"] = "0" * 64
    elif damage == "lock":
        value["lock_sha256"] = "0" * 64
    elif damage == "packages":
        value["packages"] = {"test": "2"}
    if damage != "absent":
        manifest.write_text(json.dumps(value))
    if damage == "symlink":
        # No Windows symlink privilege is required for this deterministic unit negative.
        original = type(manifest).is_symlink
        monkeypatch.setattr(type(manifest), "is_symlink", lambda p: p == manifest or original(p))
    with pytest.raises(AgentFailure) as failed:
        rt.expected()
    assert failed.value.error.code == "EMBEDDING_NOT_READY"
