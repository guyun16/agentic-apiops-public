"""Serve the deterministic Stage21 timeout target as a standalone child process.

The unified Stage21 runtime-world launcher owns this process.  The target only
serves HTTP; Java Runner remains the authority for timeout facts and reports.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import sleep
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 18082
TIMEOUT_DELAY_SECONDS = 10


class Stage21TimeoutTargetHandler(BaseHTTPRequestHandler):
    """Expose health and a genuinely slow HTTP endpoint."""

    def _send_body(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A Runner timeout may close the client socket before the target wakes.
            pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        if path == "/healthz":
            body = json.dumps(
                {"service": "stage21-timeout-target", "status": "READY"},
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_body(200, "application/json", body)
            return
        if path != "/timeout":
            self.send_error(404)
            return

        sleep(TIMEOUT_DELAY_SECONDS)
        self._send_body(200, "text/plain; charset=utf-8", b"timeout target completed")

    def log_message(self, format: str, *args: object) -> None:
        del format, args
        return None


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Stage21TimeoutTargetHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
