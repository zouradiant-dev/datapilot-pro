"""Bounded cleanup of an OS-verified child of this MCP client; never accepts shell commands."""

import ctypes
import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from datapilot.contracts import AgentFailure


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class OwnedProcess:
    def __init__(self, pid, started, binary_hashes):
        if type(pid) is not int or pid <= 1 or pid == os.getpid():
            raise AgentFailure("EMBEDDING_VERSION", "Invalid MCP process ownership")
        self.pid, self.handles, self.timer = pid, [], None
        self.events, self.mutex = [], threading.Lock()
        try:
            if sys.platform == "win32":
                self._windows(pid, started, binary_hashes)
            else:
                # pidfd prevents PID reuse between verification and eventual termination.
                fd = os.pidfd_open(pid)
                self.handles.append(fd)
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[1]) != os.getpid() or sha(f"/proc/{pid}/exe") not in binary_hashes:
                    raise ValueError("Not this client's interpreter child")
        except Exception:
            self.close()
            raise AgentFailure(
                "EMBEDDING_VERSION", "MCP child identity could not be verified"
            ) from None

    def _windows(self, pid, started, hashes):
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.QueryFullProcessImageNameW.argtypes = [
            w.HANDLE,
            w.DWORD,
            w.LPWSTR,
            ctypes.POINTER(w.DWORD),
        ]
        kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
        kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self.kernel = kernel

        class Entry(ctypes.Structure):
            _fields_ = [
                ("size", w.DWORD),
                ("usage", w.DWORD),
                ("pid", w.DWORD),
                ("heap", ctypes.c_size_t),
                ("module", w.DWORD),
                ("threads", w.DWORD),
                ("parent", w.DWORD),
                ("priority", w.LONG),
                ("flags", w.DWORD),
                ("name", w.WCHAR * 260),
            ]

        kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError("Cannot verify child ancestry")
        parents = {}
        try:
            entry = Entry()
            entry.size = ctypes.sizeof(entry)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                parents[entry.pid] = entry.parent
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        # A Windows venv redirector may be between the interpreter and SDK owner.
        for _ in range(3):
            if pid == os.getpid():
                return
            handle = kernel.OpenProcess(0x100001 | 0x1000, False, pid)
            if not handle:
                raise OSError("Cannot bind process handle")
            self.handles.append(handle)
            buf = ctypes.create_unicode_buffer(32768)
            length = w.DWORD(len(buf))
            if not kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
                raise OSError("Cannot verify interpreter binary")
            times = [w.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                raise OSError("Cannot verify process start")
            created = (
                (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            ) / 10**7 - 11644473600
            if created < started - 2 or sha(buf.value) not in hashes:
                raise ValueError("Child start/binary differs")
            pid = parents.get(pid)
            if pid is None:
                raise ValueError("Child ancestry unavailable")
        raise ValueError("Unrelated process tree")

    def emit(self, phase):
        event = {"phase": phase, "pid": self.pid, "wall_time": time.time()}
        self.events.append(event)
        print(json.dumps({"component": "qwen_lifecycle", **event}), file=sys.stderr, flush=True)

    def arm(self):
        with self.mutex:
            if self.timer is not None:
                return
            self.emit("cleanup_armed_2s")
            self.timer = threading.Timer(2, self.kill)
            self.timer.daemon = True
            self.timer.start()

    def kill(self):
        with self.mutex:
            for handle in self.handles:
                try:
                    if sys.platform == "win32":
                        code = ctypes.c_ulong()
                        if (
                            self.kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                            and code.value == 259
                        ):
                            self.kernel.TerminateProcess(handle, 119)
                    else:
                        signal.pidfd_send_signal(handle, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            self.emit("cleanup_deadline_terminated")

    def close(self):
        with self.mutex:
            if self.timer:
                self.timer.cancel()
            for handle in self.handles:
                if sys.platform == "win32":
                    self.kernel.CloseHandle(handle)
                else:
                    os.close(handle)
            self.handles = []
