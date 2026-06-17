from __future__ import annotations

from functools import partial
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .model_client import ModelCallError, ModelConfigError, generate_chat_reply, load_env_file, runtime_status


def web_root() -> Path:
    return Path(str(files("wechat_skill_distill").joinpath("web")))


class ChatUIHandler(SimpleHTTPRequestHandler):
    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/runtime":
            self._write_json(200, runtime_status())
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._write_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._write_json(400, {"error": "request body is required"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"error": "request body must be valid JSON"})
            return
        try:
            reply = generate_chat_reply(payload)
        except ModelConfigError as exc:
            self._write_json(400, {"error": str(exc), "kind": "config"})
            return
        except ModelCallError as exc:
            self._write_json(502, {"error": str(exc), "kind": "provider"})
            return
        self._write_json(200, reply)


def serve_chat_ui(host: str, port: int, *, env_file: Path | None = None) -> None:
    load_env_file(env_file)
    root = web_root()
    if not (root / "index.html").exists():
        raise RuntimeError(f"chat UI assets not found: {root}")
    handler = partial(ChatUIHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address
    print(f"chat UI: http://{actual_host}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("chat UI stopped")
