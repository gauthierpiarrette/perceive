"""Local HTTP server for serving conformance pages."""

from __future__ import annotations

import contextlib
import http.server
import socket
import socketserver
import threading
from pathlib import Path


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        # Silence the default access log.
        pass


class PagesServer:
    """Serves the bench/pages directory on a local port. Context-manager friendly."""

    def __init__(self, pages_dir: Path, port: int | None = None):
        self.pages_dir = pages_dir.resolve()
        self.port = port or _find_free_port()
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url_for(self, file_name: str) -> str:
        return f"{self.base_url}/{file_name}"

    def __enter__(self) -> "PagesServer":
        pages_dir = self.pages_dir

        class _Boundhandler(_Handler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(pages_dir), **kwargs)

        self._server = socketserver.TCPServer(("127.0.0.1", self.port), _Boundhandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None
