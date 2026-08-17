"""Lifecycle management for the shared H2O-3 cluster."""

from __future__ import annotations

import importlib
import os
import threading
from dataclasses import dataclass
from typing import Any

from .errors import H2ONotAvailableError


@dataclass(frozen=True)
class H2ORuntimeConfig:
    """Connection settings for a local or separately hosted H2O-3 cluster.

    Attributes:
        url: Existing H2O endpoint. If empty, the Python client starts a local Java
            process.
        ip: Bind address used for a locally started cluster.
        port: Port used for a locally started cluster.
        max_mem_size: H2O JVM heap limit, for example ``"4G"``.
        nthreads: Worker threads made available to H2O. ``-1`` means all cores.
    """

    url: str = ""
    ip: str = "127.0.0.1"
    port: int = 54321
    max_mem_size: str = "4G"
    nthreads: int = -1

    @classmethod
    def from_env(cls) -> "H2ORuntimeConfig":
        """Build runtime settings from environment variables."""

        return cls(
            url=os.getenv("H2O_URL", "").strip(),
            ip=os.getenv("H2O_IP", "127.0.0.1").strip(),
            port=int(os.getenv("H2O_PORT", "54321")),
            max_mem_size=os.getenv("H2O_MAX_MEM_SIZE", "4G").strip(),
            nthreads=int(os.getenv("H2O_NTHREADS", "-1")),
        )


class H2ORuntime:
    """Thread-safe, lazy owner of one H2O connection.

    Importing the web application must not start Java.  The cluster is connected or
    started only when the first experiment is submitted or when ``health(connect=True)``
    is explicitly requested.
    """

    def __init__(self, config: H2ORuntimeConfig | None = None) -> None:
        self.config = config or H2ORuntimeConfig.from_env()
        self._lock = threading.RLock()
        self._h2o: Any | None = None

    def client(self) -> Any:
        """Return a live H2O module, creating its connection when necessary."""

        with self._lock:
            h2o = self._import_client()
            if self._connection_is_alive(h2o):
                self._h2o = h2o
                return h2o

            try:
                if self.config.url:
                    h2o.connect(url=self.config.url)
                else:
                    h2o.init(
                        ip=self.config.ip,
                        port=self.config.port,
                        max_mem_size=self.config.max_mem_size,
                        nthreads=self.config.nthreads,
                        start_h2o=True,
                    )
            except Exception as exc:  # H2O emits several client/HTTP/Java exception types.
                raise H2ONotAvailableError(
                    "Không thể kết nối hoặc khởi động H2O-3. Kiểm tra Java, H2O_URL "
                    f"và tài nguyên JVM. Chi tiết: {exc}"
                ) from exc

            self._h2o = h2o
            return h2o

    def health(self, *, connect: bool = False) -> dict[str, Any]:
        """Return install/connection state without starting Java by default."""

        try:
            h2o = self.client() if connect else self._import_client()
        except H2ONotAvailableError as exc:
            return {
                "installed": False,
                "connected": False,
                "ready": False,
                "error": str(exc),
            }

        connected = self._connection_is_alive(h2o)
        payload: dict[str, Any] = {
            "installed": True,
            "connected": connected,
            "ready": connected,
            "mode": "remote" if self.config.url else "local",
            "url": self.config.url or f"http://{self.config.ip}:{self.config.port}",
        }
        if connected:
            try:
                cluster = h2o.cluster()
                payload.update(
                    {
                        "version": str(getattr(cluster, "version", "")),
                        "cloud_name": str(getattr(cluster, "cloud_name", "")),
                    }
                )
            except Exception:
                pass
        return payload

    @staticmethod
    def _import_client() -> Any:
        try:
            return importlib.import_module("h2o")
        except Exception as exc:
            raise H2ONotAvailableError(
                "Chưa cài H2O Python client. Cài dependencies của backend rồi thử lại."
            ) from exc

    @staticmethod
    def _connection_is_alive(h2o: Any) -> bool:
        try:
            connection = h2o.connection()
            if connection is None:
                return False
            h2o.cluster().show_status(False)
            return True
        except Exception:
            return False
