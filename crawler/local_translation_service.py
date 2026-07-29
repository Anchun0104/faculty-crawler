from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Protocol


class LocalTranslationServiceError(RuntimeError):
    """The bundled local translation service could not be made ready."""


class _Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float) -> int: ...


Launcher = Callable[[list[str]], _Process]
Healthcheck = Callable[[str, float], bool]


def bundled_translation_service_path(application_dir: Path | None = None) -> Path:
    """Return the expected path of the service shipped beside the desktop EXE."""
    if application_dir is None:
        application_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return Path(application_dir) / "translation-service" / "LibreTranslate.exe"


class LocalTranslationService:
    """Own the installed LibreTranslate child process for one desktop session.

    The service has no network-facing configuration: it is intentionally bound
    to a loopback address and exposes its generated endpoint only to the local
    application process.
    """

    def __init__(
        self,
        executable: str | Path,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        startup_timeout: float = 45.0,
        health_timeout: float = 1.0,
        shutdown_timeout: float = 3.0,
        launcher: Launcher | None = None,
        healthcheck: Healthcheck | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local translation service must use a loopback host")
        if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535):
            raise ValueError("local translation service port must be between 1 and 65535")
        if startup_timeout < 0 or health_timeout <= 0 or shutdown_timeout < 0:
            raise ValueError("local translation service timeouts are invalid")
        self.executable = Path(executable)
        self.host = host
        self.port = port
        self.startup_timeout = startup_timeout
        self.health_timeout = health_timeout
        self.shutdown_timeout = shutdown_timeout
        self._launcher = launcher or _launch_process
        self._healthcheck = healthcheck or _check_languages
        self._sleep = sleep
        self._process: _Process | None = None
        self._endpoint: str | None = None

    @property
    def endpoint(self) -> str | None:
        return self._endpoint

    def start(self) -> str:
        if self._process is not None and self._process.poll() is None and self._endpoint is not None:
            return self._endpoint
        self.stop()
        port = self.port or _find_free_port(self.host)
        endpoint = _endpoint_for(self.host, port)
        command = [str(self.executable), "--host", self.host, "--port", str(port)]
        try:
            self._process = self._launcher(command)
            self._wait_until_healthy(endpoint)
        except Exception as exc:
            self.stop()
            if isinstance(exc, LocalTranslationServiceError):
                raise
            raise LocalTranslationServiceError("could not start local translation service") from exc
        self._endpoint = endpoint
        return endpoint

    def stop(self) -> None:
        process, self._process = self._process, None
        self._endpoint = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=self.shutdown_timeout)
        except (subprocess.TimeoutExpired, TimeoutError):
            try:
                process.kill()
                process.wait(timeout=self.shutdown_timeout)
            except Exception:
                pass
        except Exception:
            pass

    def _wait_until_healthy(self, endpoint: str) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while True:
            if self._process is None or self._process.poll() is not None:
                raise LocalTranslationServiceError("local translation service exited during startup")
            if self._healthcheck(endpoint, self.health_timeout):
                return
            if time.monotonic() >= deadline:
                raise LocalTranslationServiceError("local translation service did not become healthy")
            self._sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def __enter__(self) -> "LocalTranslationService":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()


def _launch_process(command: list[str]) -> _Process:
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET6 if host == "::1" else socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _endpoint_for(host: str, port: int) -> str:
    display_host = f"[{host}]" if host == "::1" else host
    return f"http://{display_host}:{port}"


def _check_languages(endpoint: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint}/languages", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return isinstance(payload, list)
